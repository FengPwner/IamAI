#!/usr/bin/env python3
"""stall_cooldown.py — exponential backoff for restart loops.

when auto_restart.py keeps finding dead processes, the system is in a
restart loop: start → crash → restart → crash. each cycle burns CPU and
writes garbage into the log. this tool tracks restart timestamps in a
small JSON file and answers one question: *should we restart now, or wait?*

cooldown schedule:
    attempt 1 — immediate
    attempt 2 — wait 60s
    attempt 3 — wait 300s (5 min)
    attempt 4 — wait 900s (15 min)
    attempt 5+ — wait 3600s (1 hour), capped

the counter resets when both processes have been alive for at least
``--stable-window`` seconds (default 600 = 10 min).

usage:
    python3 tools/stall_cooldown.py                    # should I restart now?
    python3 tools/stall_cooldown.py --record           # record a restart event
    python3 tools/stall_cooldown.py --status           # show cooldown state
    python3 tools/stall_cooldown.py --json             # machine-readable
    python3 tools/stall_cooldown.py --reset            # clear history

exit codes:
    0 — go ahead and restart
    1 — in cooldown, wait before retrying
    2 — error
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

DEFAULT_STATE_FILE = Path("/tmp/iamai-cooldown-state.json")
BACKOFF_SCHEDULE = [0, 60, 300, 900, 3600]  # seconds per attempt
STABLE_WINDOW_DEFAULT = 600  # 10 min alive → reset counter


class CooldownState:
    """Persistent restart cooldown tracker."""

    __slots__ = ("state_file", "data")

    def __init__(self, state_file: Path = DEFAULT_STATE_FILE) -> None:
        self.state_file = state_file
        self.data = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"restarts": [], "last_stable": None}

    def save(self) -> None:
        self.state_file.write_text(json.dumps(self.data, indent=2))

    @property
    def restart_count(self) -> int:
        return len(self.data.get("restarts", []))

    @property
    def last_restart_ts(self) -> float | None:
        restarts = self.data.get("restarts", [])
        return restarts[-1] if restarts else None

    def record_restart(self) -> None:
        """Record that a restart just happened."""
        if "restarts" not in self.data:
            self.data["restarts"] = []
        self.data["restarts"].append(time.time())
        # Keep only last 20 entries to avoid unbounded growth
        self.data["restarts"] = self.data["restarts"][-20:]
        self.save()

    def cooldown_remaining(self) -> float:
        """Seconds until restart is allowed. 0 means go ahead."""
        last = self.last_restart_ts
        if last is None:
            return 0.0

        attempt_idx = min(self.restart_count - 1, len(BACKOFF_SCHEDULE) - 1)
        wait = BACKOFF_SCHEDULE[max(0, attempt_idx)]
        elapsed = time.time() - last
        return max(0.0, wait - elapsed)

    def should_restart(self) -> bool:
        return self.cooldown_remaining() <= 0

    def mark_stable(self) -> None:
        """Record that processes have been stable (alive for stable_window)."""
        self.data["last_stable"] = time.time()
        self.data["restarts"] = []  # reset counter on stability
        self.save()

    def check_stability(self, writer_alive: bool, batch_alive: bool,
                        stable_window: int = STABLE_WINDOW_DEFAULT) -> bool:
        """If both alive for stable_window, reset the counter."""
        if not (writer_alive and batch_alive):
            return False

        # If no restarts recorded, already stable
        if not self.data.get("restarts"):
            return True

        # Check if enough time has passed since last restart with both alive
        last = self.last_restart_ts
        if last and (time.time() - last) >= stable_window:
            self.mark_stable()
            return True
        return False

    def reset(self) -> None:
        self.data = {"restarts": [], "last_stable": None}
        self.save()

    def summary(self) -> dict:
        remaining = self.cooldown_remaining()
        return {
            "restart_count": self.restart_count,
            "last_restart_ts": self.last_restart_ts,
            "cooldown_remaining_s": round(remaining, 1),
            "should_restart": remaining <= 0,
            "last_stable": self.data.get("last_stable"),
            "backoff_schedule": BACKOFF_SCHEDULE,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE,
                        help="path to cooldown state file")
    parser.add_argument("--record", action="store_true",
                        help="record a restart event now")
    parser.add_argument("--status", action="store_true",
                        help="show current cooldown state")
    parser.add_argument("--reset", action="store_true",
                        help="clear all cooldown history")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output")
    parser.add_argument("--stable-window", type=int, default=STABLE_WINDOW_DEFAULT,
                        help=f"seconds of stability to reset counter (default {STABLE_WINDOW_DEFAULT})")
    args = parser.parse_args()

    state = CooldownState(args.state_file)

    if args.reset:
        state.reset()
        print("Cooldown state cleared.")
        return 0

    if args.record:
        state.record_restart()
        summary = state.summary()
        if args.json:
            print(json.dumps(summary))
        else:
            print(f"Recorded restart #{summary['restart_count']}.")
            remaining = summary["cooldown_remaining_s"]
            if remaining > 0:
                print(f"Next restart allowed in {remaining:.0f}s.")
            else:
                print("Next restart allowed immediately.")
        return 0

    if args.status:
        summary = state.summary()
        if args.json:
            print(json.dumps(summary))
        else:
            print(f"Restart count: {summary['restart_count']}")
            if summary["last_restart_ts"]:
                ago = time.time() - summary["last_restart_ts"]
                print(f"Last restart: {ago:.0f}s ago")
            remaining = summary["cooldown_remaining_s"]
            if remaining > 0:
                print(f"Cooldown active: {remaining:.0f}s remaining")
            else:
                print("No cooldown — restart allowed")
            if summary["last_stable"]:
                stable_ago = time.time() - summary["last_stable"]
                print(f"Last stable period: {stable_ago:.0f}s ago")
        return 0

    # Default: should I restart now?
    if state.should_restart():
        if args.json:
            print(json.dumps({"decision": "restart", "detail": state.summary()}))
        else:
            print("✓ Restart allowed.")
        return 0
    else:
        remaining = state.cooldown_remaining()
        if args.json:
            print(json.dumps({"decision": "wait", "wait_seconds": round(remaining, 1),
                              "detail": state.summary()}))
        else:
            print(f"✗ Cooldown active. Wait {remaining:.0f}s before restarting.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
