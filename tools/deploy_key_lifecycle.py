#!/usr/bin/env python3
"""deploy_key_lifecycle.py — track ssh deploy key state transitions over time.

the push pipeline has four possible states for the deploy key:

  MISSING       key file does not exist on disk
  UNREGISTERED  key file exists but github rejects it (not added as deploy key)
  REGISTERED    key file exists and github accepts it (push works)
  REVOKED       key was registered before but github now rejects it

each transition is logged to data/deploy_key_lifecycle.jsonl with
timestamp, old_state, new_state, and a short reason string.

the lifecycle tracker answers three questions the caretaker needs:

  1. how long has the key been in its current state?
  2. what is the mean time to recovery (MTTR) for key issues?
  3. how many state transitions have happened today?

design principle: the tracker observes state; it never auto-fixes.
fixes belong in push_recovery_orchestrator. the tracker's job is to
produce an honest, append-only record that makes patterns visible.

usage:
    python3 tools/deploy_key_lifecycle.py              # one-shot state check
    python3 tools/deploy_key_lifecycle.py --json        # machine-readable output
    python3 tools/deploy_key_lifecycle.py --history 10  # last 10 transitions
    python3 tools/deploy_key_lifecycle.py --stats       # MTTR and uptime stats

exit codes:
    0 — key is REGISTERED (healthy)
    1 — key is UNREGISTERED or REVOKED (actionable)
    2 — key is MISSING (actionable: restore or generate key)
    3 — error
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
LIFECYCLE_LOG = DATA_DIR / "deploy_key_lifecycle.jsonl"
STATE_CACHE = DATA_DIR / "deploy_key_state.json"

KEY_PATHS = [
    Path.home() / ".ssh" / "id_ed25519",
    Path("/root/.ssh/id_ed25519"),
]

GITHUB_SSH_PROBE_TIMEOUT = 10  # seconds


class KeyState(str, Enum):
    MISSING = "MISSING"
    UNREGISTERED = "UNREGISTERED"
    REGISTERED = "REGISTERED"
    REVOKED = "REVOKED"


@dataclass
class Transition:
    timestamp: str
    old_state: str
    new_state: str
    reason: str
    key_path: str = ""
    fingerprint: str = ""


@dataclass
class LifecycleStats:
    total_transitions: int = 0
    transitions_today: int = 0
    current_state: str = "MISSING"
    current_state_since: str = ""
    mttr_seconds: float = 0.0
    uptime_ratio: float = 0.0
    time_in_state: dict = field(default_factory=dict)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def today_str() -> str:
    return time.strftime("%Y-%m-%d")


def find_key_path() -> Optional[Path]:
    """Return the first existing key path, or None."""
    for p in KEY_PATHS:
        if p.exists():
            return p
    return None


def get_fingerprint(key_path: Path) -> str:
    """Extract ssh key fingerprint using ssh-keygen."""
    try:
        result = subprocess.run(
            ["ssh-keygen", "-lf", str(key_path)],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split()
            return parts[1] if len(parts) >= 2 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, IndexError):
        pass
    return ""


def probe_github_ssh(key_path: Path) -> bool:
    """Test if the key is accepted by github's ssh endpoint.

    Returns True if github says 'successfully authenticated' or
    'Hi <user>! You've successfully authenticated'.
    Returns False for permission denied or connection errors.
    """
    try:
        result = subprocess.run(
            [
                "ssh", "-T", "-i", str(key_path),
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
                "-o", "BatchMode=yes",
                "git@github.com",
            ],
            capture_output=True, text=True,
            timeout=GITHUB_SSH_PROBE_TIMEOUT,
        )
        combined = (result.stdout + result.stderr).lower()
        return "successfully authenticated" in combined or "hi " in combined
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def detect_current_state() -> tuple[KeyState, str, Path | None]:
    """Detect the current deploy key state.

    Returns (state, reason, key_path_or_None).
    """
    key_path = find_key_path()

    if key_path is None:
        return KeyState.MISSING, "no key file found in known paths", None

    fingerprint = get_fingerprint(key_path)
    reason = f"key at {key_path}"
    if fingerprint:
        reason += f" ({fingerprint})"

    if probe_github_ssh(key_path):
        return KeyState.REGISTERED, reason + " — github accepts key", key_path
    else:
        # distinguish UNREGISTERED from REVOKED by checking history
        prev_state = load_cached_state()
        if prev_state and prev_state.get("state") == KeyState.REGISTERED:
            return KeyState.REVOKED, reason + " — was registered, now rejected", key_path
        else:
            return KeyState.UNREGISTERED, reason + " — github rejects key", key_path


def load_cached_state() -> Optional[dict]:
    """Load the last known state from cache file."""
    try:
        if STATE_CACHE.exists():
            return json.loads(STATE_CACHE.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_cached_state(state: KeyState, reason: str, key_path: str = "") -> None:
    """Persist the current state to cache for next invocation."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state.value,
        "reason": reason,
        "key_path": key_path,
        "since": now_iso(),
    }
    STATE_CACHE.write_text(json.dumps(payload, indent=2) + "\n")


def append_transition(t: Transition) -> None:
    """Append a state transition to the JSONL log."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LIFECYCLE_LOG, "a") as f:
        f.write(json.dumps(asdict(t)) + "\n")


def load_transitions() -> list[dict]:
    """Load all transitions from the JSONL log."""
    if not LIFECYCLE_LOG.exists():
        return []
    transitions = []
    for line in LIFECYCLE_LOG.read_text().strip().split("\n"):
        if line.strip():
            try:
                transitions.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return transitions


def check_and_record() -> tuple[KeyState, str, bool]:
    """Detect state, compare to cached, record transition if changed.

    Returns (current_state, reason, transition_recorded).
    """
    state, reason, key_path = detect_current_state()
    key_path_str = str(key_path) if key_path else ""
    fingerprint = get_fingerprint(key_path) if key_path else ""

    cached = load_cached_state()
    old_state = cached.get("state", "") if cached else ""

    transitioned = False
    if old_state != state.value:
        t = Transition(
            timestamp=now_iso(),
            old_state=old_state or "UNKNOWN",
            new_state=state.value,
            reason=reason,
            key_path=key_path_str,
            fingerprint=fingerprint,
        )
        append_transition(t)
        transitioned = True

    save_cached_state(state, reason, key_path_str)
    return state, reason, transitioned


def compute_stats() -> LifecycleStats:
    """Compute lifecycle statistics from transition history."""
    transitions = load_transitions()
    cached = load_cached_state()
    stats = LifecycleStats()

    stats.total_transitions = len(transitions)

    today = today_str()
    stats.transitions_today = sum(
        1 for t in transitions
        if t.get("timestamp", "").startswith(today)
    )

    if cached:
        stats.current_state = cached.get("state", "MISSING")
        stats.current_state_since = cached.get("since", "")

    # compute time in each state
    state_durations = {"MISSING": 0.0, "UNREGISTERED": 0.0, "REGISTERED": 0.0, "REVOKED": 0.0}
    recovery_times = []

    sorted_transitions = sorted(transitions, key=lambda t: t.get("timestamp", ""))

    for i, t in enumerate(sorted_transitions):
        ts = t.get("timestamp", "")
        old = t.get("old_state", "")
        new = t.get("new_state", "")

        if old in state_durations and i > 0:
            prev_ts = sorted_transitions[i - 1].get("timestamp", "")
            if prev_ts and ts:
                try:
                    t1 = time.mktime(time.strptime(prev_ts[:19], "%Y-%m-%dT%H:%M:%S"))
                    t2 = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
                    duration = max(0, t2 - t1)
                    state_durations[old] += duration
                except (ValueError, OverflowError):
                    pass

        # track recovery time (non-REGISTERED → REGISTERED)
        if new == "REGISTERED" and old in ("MISSING", "UNREGISTERED", "REVOKED"):
            # find when we left REGISTERED before this
            for j in range(i - 1, -1, -1):
                if sorted_transitions[j].get("old_state") == "REGISTERED":
                    leave_ts = sorted_transitions[j].get("timestamp", "")
                    if leave_ts and ts:
                        try:
                            t1 = time.mktime(time.strptime(leave_ts[:19], "%Y-%m-%dT%H:%M:%S"))
                            t2 = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
                            recovery_times.append(max(0, t2 - t1))
                        except (ValueError, OverflowError):
                            pass
                    break

    stats.time_in_state = {k: round(v, 1) for k, v in state_durations.items()}

    if recovery_times:
        stats.mttr_seconds = round(sum(recovery_times) / len(recovery_times), 1)

    total_time = sum(state_durations.values())
    if total_time > 0:
        stats.uptime_ratio = round(state_durations.get("REGISTERED", 0) / total_time, 3)

    return stats


def format_history(n: int = 10) -> str:
    """Format the last n transitions as human-readable text."""
    transitions = load_transitions()
    if not transitions:
        return "no transitions recorded yet."

    lines = []
    for t in transitions[-n:]:
        ts = t.get("timestamp", "?")
        old = t.get("old_state", "?")
        new = t.get("new_state", "?")
        reason = t.get("reason", "")
        lines.append(f"  {ts}  {old} → {new}  ({reason})")

    return f"last {min(n, len(transitions))} transitions:\n" + "\n".join(lines)


def format_stats(stats: LifecycleStats) -> str:
    """Format lifecycle statistics as human-readable text."""
    lines = [
        f"current state: {stats.current_state}",
        f"  since: {stats.current_state_since or 'unknown'}",
        f"total transitions: {stats.total_transitions}",
        f"transitions today: {stats.transitions_today}",
        f"MTTR: {stats.mttr_seconds:.0f}s" if stats.mttr_seconds else "MTTR: n/a (no recovery recorded)",
        f"uptime ratio: {stats.uptime_ratio:.1%}" if stats.uptime_ratio else "uptime ratio: n/a",
    ]
    if stats.time_in_state:
        lines.append("time in state:")
        for state, seconds in sorted(stats.time_in_state.items()):
            if seconds > 0:
                hours = seconds / 3600
                lines.append(f"  {state}: {hours:.1f}h ({seconds:.0f}s)")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="track deploy key lifecycle state transitions"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    parser.add_argument("--history", type=int, default=0, help="show last N transitions")
    parser.add_argument("--stats", action="store_true", help="show lifecycle statistics")
    parser.add_argument("--no-record", action="store_true", help="check state without recording")
    args = parser.parse_args()

    if args.no_record:
        state, reason, _ = detect_current_state()
        transitioned = False
    else:
        state, reason, transitioned = check_and_record()

    exit_code = {
        KeyState.REGISTERED: 0,
        KeyState.UNREGISTERED: 1,
        KeyState.REVOKED: 1,
        KeyState.MISSING: 2,
    }.get(state, 3)

    if args.json:
        output = {
            "state": state.value,
            "reason": reason,
            "transitioned": transitioned,
            "timestamp": now_iso(),
        }
        if args.stats:
            stats = compute_stats()
            output["stats"] = asdict(stats)
        print(json.dumps(output, indent=2))
    elif args.history > 0:
        print(format_history(args.history))
    elif args.stats:
        stats = compute_stats()
        print(format_stats(stats))
    else:
        prefix = "[transition] " if transitioned else ""
        print(f"{prefix}{state.value}: {reason}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
