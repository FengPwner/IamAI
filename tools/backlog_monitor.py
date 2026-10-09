#!/usr/bin/env python3
"""backlog_monitor.py — detect sustained uncommitted file accumulation.

The batch committer runs every 10 minutes. When it fails silently
(lock file, merge conflict, credential expiry), uncommitted files
accumulate until the next caretaker visit. This monitor provides
an early warning: it tracks the uncommitted file count, compares
it against a threshold, and exits non-zero when the count has
exceeded the threshold for longer than a configurable grace period.

Designed to run inside the batch committer's cycle or as a
standalone watchdog invoked by the caretaker.

Usage:
    python3 tools/backlog_monitor.py
    python3 tools/backlog_monitor.py --threshold 5 --grace 1200
    python3 tools/backlog_monitor.py --json

Exit codes:
    0  — backlog within limits
    1  — backlog exceeds threshold past grace period
    2  — git error (repo unreadable)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
STATE_FILE = REPO / "data" / "backlog_monitor_state.json"


@dataclass
class BacklogSnapshot:
    """A single point-in-time measurement of uncommitted files."""
    count: int
    at: float
    files: list[str]

    @property
    def at_iso(self) -> str:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(self.at, tz=timezone.utc).isoformat()


@dataclass
class BacklogState:
    """Persistent state across invocations."""
    first_exceeded: float | None  # epoch when count first crossed threshold
    last_count: int
    last_check: float
    consecutive_exceeded: int

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> BacklogState:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__})

    @classmethod
    def empty(cls) -> BacklogState:
        return cls(first_exceeded=None, last_count=0,
                   last_check=0.0, consecutive_exceeded=0)


def count_uncommitted(repo: Path) -> BacklogSnapshot:
    """Run `git status --porcelain` and return the file count + names."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(repo), timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("git status timed out")
    except (FileNotFoundError, OSError) as e:
        raise RuntimeError(f"git status failed: {e}")
    if result.returncode != 0:
        raise RuntimeError(f"git status failed: {result.stderr.strip()}")

    lines = [l for l in result.stdout.splitlines() if l.strip()]
    files = [l[3:] for l in lines]  # strip the 2-char status + space
    return BacklogSnapshot(count=len(files), at=time.time(), files=files)


def load_state() -> BacklogState:
    """Load persistent state, or return a fresh one."""
    if not STATE_FILE.exists():
        return BacklogState.empty()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return BacklogState.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError):
        return BacklogState.empty()


def save_state(state: BacklogState) -> None:
    """Persist state to disk."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state.to_dict(), indent=2),
                          encoding="utf-8")


def evaluate(snapshot: BacklogSnapshot, state: BacklogState,
             threshold: int, grace: float) -> dict:
    """Determine if the backlog is critical.

    Returns a dict with keys:
        - healthy (bool): True if backlog is within limits
        - count (int): current uncommitted file count
        - threshold (int): the configured threshold
        - exceeded_duration (float): seconds since first_exceeded, or 0
        - grace (float): configured grace period
        - grace_remaining (float): seconds of grace remaining (negative = expired)
        - message (str): human-readable status
    """
    now = snapshot.at
    exceeded = snapshot.count >= threshold

    if exceeded:
        if state.first_exceeded is None:
            state.first_exceeded = now
            state.consecutive_exceeded = 1
        else:
            state.consecutive_exceeded += 1
        duration = now - state.first_exceeded
        grace_remaining = grace - duration
        healthy = grace_remaining > 0
        if healthy:
            msg = (f"backlog {snapshot.count} >= {threshold}, "
                   f"grace {grace_remaining:.0f}s remaining")
        else:
            msg = (f"backlog {snapshot.count} >= {threshold} "
                   f"for {duration:.0f}s (grace {grace:.0f}s expired)")
    else:
        state.first_exceeded = None
        state.consecutive_exceeded = 0
        duration = 0.0
        grace_remaining = grace
        healthy = True
        msg = f"backlog {snapshot.count} < {threshold}, healthy"

    state.last_count = snapshot.count
    state.last_check = now

    return {
        "healthy": healthy,
        "count": snapshot.count,
        "threshold": threshold,
        "exceeded_duration": round(duration, 1),
        "grace": grace,
        "grace_remaining": round(grace_remaining, 1),
        "consecutive_exceeded": state.consecutive_exceeded,
        "message": msg,
        "files": snapshot.files,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threshold", type=int, default=5,
                    help="uncommitted file count that triggers alert (default 5)")
    ap.add_argument("--grace", type=float, default=1800,
                    help="seconds to allow backlog above threshold (default 1800)")
    ap.add_argument("--json", action="store_true", help="emit JSON output")
    ap.add_argument("--repo", type=str, default=str(REPO),
                    help="path to git repository")
    args = ap.parse_args()

    repo = Path(args.repo)
    try:
        snapshot = count_uncommitted(repo)
    except RuntimeError as e:
        if args.json:
            print(json.dumps({"healthy": False, "error": str(e)}))
        else:
            print(f"ERROR: {e}", file=sys.stderr)
        return 2

    state = load_state()
    result = evaluate(snapshot, state, args.threshold, args.grace)
    save_state(state)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"  backlog: {result['message']}")
        if result.get("files"):
            for f in result["files"][:10]:
                print(f"    {f}")
            if len(result["files"]) > 10:
                print(f"    ... and {len(result['files']) - 10} more")

    return 0 if result["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
