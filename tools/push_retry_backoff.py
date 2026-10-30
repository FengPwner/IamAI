#!/usr/bin/env python3
"""push_retry_backoff.py — schedule push retries with exponential backoff.

When git push fails (deploy key unregistered, SSH error, network timeout),
blindly retrying every cycle wastes resources and logs. This tool tracks
push failure history and computes the next retry time using exponential
backoff with jitter.

Core model:
  - base_interval: 10 minutes (matches batch commit cadence)
  - max_interval: 4 hours (never wait longer than this)
  - jitter: random 0–25% of computed interval (prevents thundering herd)
  - backoff factor: 2x on each consecutive failure

State is persisted to a JSON file so it survives container recycles.

Failure categories and their base intervals:
  - auth_failure (deploy key, SSH): 1h base — won't fix itself, slow retry
  - network_error (timeout, DNS):   5min base — likely transient
  - conflict (non-fast-forward):    10min base — needs human or rebase
  - unknown:                        15min base — conservative default

Usage:
    python3 tools/push_retry_backoff.py              # show current state
    python3 tools/push_retry_backoff.py --record auth_failure   # record a failure
    python3 tools/push_retry_backoff.py --record network_error
    python3 tools/push_retry_backoff.py --check      # is it time to retry?
    python3 tools/push_retry_backoff.py --reset      # clear state after success
    python3 tools/push_retry_backoff.py --json       # machine-readable output

Exit codes:
    0 — ready to retry (or no failures recorded)
    1 — not yet time to retry
    2 — error
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List


# --- Constants ---

DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "push_retry_state.json"

CATEGORY_BASE_INTERVALS = {
    "auth_failure": 3600,      # 1 hour
    "network_error": 300,      # 5 minutes
    "conflict": 600,           # 10 minutes
    "unknown": 900,            # 15 minutes
}

BACKOFF_FACTOR = 2.0
MAX_INTERVAL = 14400          # 4 hours
JITTER_FRACTION = 0.25        # 0–25% random jitter


@dataclass
class RetryState:
    consecutive_failures: int = 0
    last_failure_category: str = "unknown"
    last_failure_at: Optional[str] = None
    next_retry_at: Optional[float] = None  # unix timestamp
    total_failures: int = 0
    total_retries: int = 0
    total_successes: int = 0
    history: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RetryState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def load_state(path: Path = DEFAULT_STATE_PATH) -> RetryState:
    if path.exists():
        try:
            return RetryState.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, TypeError):
            return RetryState()
    return RetryState()


def save_state(state: RetryState, path: Path = DEFAULT_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2))


def compute_next_retry(
    consecutive_failures: int,
    category: str,
    now: float,
) -> float:
    """Compute the next retry timestamp using exponential backoff with jitter."""
    base = CATEGORY_BASE_INTERVALS.get(category, CATEGORY_BASE_INTERVALS["unknown"])
    interval = min(base * (BACKOFF_FACTOR ** (consecutive_failures - 1)), MAX_INTERVAL)
    jitter = random.uniform(0, interval * JITTER_FRACTION)
    return now + interval + jitter


def record_failure(
    state: RetryState,
    category: str,
    now: Optional[float] = None,
) -> RetryState:
    """Record a push failure and compute next retry time."""
    t = now or time.time()
    state.consecutive_failures += 1
    state.total_failures += 1
    state.last_failure_category = category
    state.last_failure_at = datetime.fromtimestamp(t, tz=timezone.utc).isoformat()
    state.next_retry_at = compute_next_retry(state.consecutive_failures, category, t)

    # Keep history bounded
    state.history.append({
        "at": state.last_failure_at,
        "category": category,
        "consecutive": state.consecutive_failures,
        "next_retry_at": state.next_retry_at,
    })
    if len(state.history) > 100:
        state.history = state.history[-100:]

    return state


def record_success(state: RetryState) -> RetryState:
    """Record a successful push — resets consecutive counter."""
    state.consecutive_failures = 0
    state.next_retry_at = None
    state.total_successes += 1
    return state


def check_ready(state: RetryState, now: Optional[float] = None) -> tuple[bool, float]:
    """Check if it's time to retry. Returns (ready, seconds_remaining)."""
    t = now or time.time()
    if state.consecutive_failures == 0:
        return True, 0.0
    if state.next_retry_at is None:
        return True, 0.0
    remaining = state.next_retry_at - t
    if remaining <= 0:
        return True, 0.0
    return False, remaining


def classify_failure(stderr: str) -> str:
    """Classify a push failure from git stderr output."""
    stderr_lower = stderr.lower()
    if any(kw in stderr_lower for kw in [
        "permission denied", "publickey", "deploy key",
        "not found", "could not read from remote",
        "identity file", "no such file",
    ]):
        return "auth_failure"
    if any(kw in stderr_lower for kw in [
        "non-fast-forward", "rejected", "conflict",
        "fetch first", "updates were rejected",
    ]):
        return "conflict"
    if any(kw in stderr_lower for kw in [
        "timeout", "timed out", "connection refused",
        "could not resolve", "network", "broken pipe",
        "connection reset",
    ]):
        return "network_error"
    return "unknown"


def format_human(state: RetryState) -> str:
    """Format state for human-readable display."""
    lines = []
    lines.append(f"Consecutive failures: {state.consecutive_failures}")
    lines.append(f"Total failures: {state.total_failures}")
    lines.append(f"Total successes: {state.total_successes}")
    lines.append(f"Last failure category: {state.last_failure_category}")
    if state.last_failure_at:
        lines.append(f"Last failure at: {state.last_failure_at}")
    if state.next_retry_at:
        remaining = state.next_retry_at - time.time()
        if remaining > 0:
            mins = remaining / 60
            lines.append(f"Next retry in: {mins:.1f} minutes")
        else:
            lines.append("Next retry: NOW (overdue)")
    else:
        lines.append("Next retry: immediate (no failures)")
    base = CATEGORY_BASE_INTERVALS.get(state.last_failure_category, 900)
    raw_interval = min(base * (BACKOFF_FACTOR ** max(0, state.consecutive_failures - 1)), MAX_INTERVAL)
    lines.append(f"Current backoff interval: {raw_interval/60:.0f} minutes")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Push retry backoff scheduler")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--record", type=str, help="Record a failure: auth_failure|network_error|conflict|unknown")
    parser.add_argument("--classify", type=str, help="Classify failure from stderr string")
    parser.add_argument("--success", action="store_true", help="Record a successful push")
    parser.add_argument("--check", action="store_true", help="Check if it's time to retry")
    parser.add_argument("--reset", action="store_true", help="Reset all state")
    parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    args = parser.parse_args()

    state = load_state(args.state)

    if args.reset:
        state = RetryState()
        save_state(state, args.state)
        print("State reset.")
        return 0

    if args.classify:
        cat = classify_failure(args.classify)
        print(cat)
        return 0

    if args.record:
        if args.record not in CATEGORY_BASE_INTERVALS:
            print(f"Unknown category: {args.record}", file=sys.stderr)
            print(f"Valid: {', '.join(CATEGORY_BASE_INTERVALS.keys())}", file=sys.stderr)
            return 2
        state = record_failure(state, args.record)
        save_state(state, args.state)
        if args.json_output:
            print(json.dumps(state.to_dict(), indent=2))
        else:
            print(format_human(state))
        return 1  # not ready yet

    if args.success:
        state = record_success(state)
        save_state(state, args.state)
        print("Success recorded. Backoff reset.")
        return 0

    if args.check:
        ready, remaining = check_ready(state)
        if args.json_output:
            print(json.dumps({"ready": ready, "seconds_remaining": round(remaining, 1)}))
        else:
            if ready:
                print("Ready to retry push.")
            else:
                print(f"Not yet. {remaining/60:.1f} minutes remaining.")
        return 0 if ready else 1

    # Default: show state
    if args.json_output:
        print(json.dumps(state.to_dict(), indent=2))
    else:
        print(format_human(state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
