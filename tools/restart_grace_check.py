#!/usr/bin/env python3
"""restart_grace_check.py — verify restarted processes survived their grace period.

After a caretaker restarts writer_loop and commit_batch, the first 60 seconds
are the danger zone: import errors, missing files, or SSH problems can crash
the process immediately. This tool checks whether each process has been alive
long enough to be considered stable.

Reads /proc/<pid>/stat for process start time and compares against the
configured grace period. Reports:
  - "stable"   : process alive and past grace period
  - "in-grace" : process alive but still within grace period
  - "dead"     : process no longer running (crashed during or after grace)
  - "unknown"  : pid file missing or unreadable

Usage:
    python3 tools/restart_grace_check.py
    python3 tools/restart_grace_check.py --grace 120    # 2-minute grace period
    python3 tools/restart_grace_check.py --json
    python3 tools/restart_grace_check.py --pid-writer 5646 --pid-batch 5647

Exit codes:
    0 — all processes stable (past grace period)
    1 — at least one process dead or still in grace period
    2 — unexpected error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PID_DIR = REPO / "data" / "pids"
DEFAULT_GRACE = 60  # seconds


@dataclass
class ProcessStatus:
    name: str
    pid: int | None
    state: str          # stable, in-grace, dead, unknown
    uptime_s: float     # seconds since process start
    grace_s: float      # configured grace period


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) to find the repo root."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / "data" / "strokes.jsonl").exists():
            return parent
    return p


def get_process_start_time(pid: int) -> float | None:
    """Read process start time from /proc/<pid>/stat (field 22, in clock ticks).

    Returns the start time as a Unix timestamp (seconds since epoch),
    or None if the process doesn't exist.
    """
    stat_path = Path(f"/proc/{pid}/stat")
    if not stat_path.exists():
        return None

    try:
        content = stat_path.read_text()
        # Field 22 (1-indexed) is starttime in clock ticks after boot
        # The comm field (field 2) can contain spaces and parens, so split
        # after the last ')' to avoid parsing issues
        match = re.match(r"(\d+)\s+\(.*?\)\s+(.*)", content)
        if not match:
            return None
        fields = match.group(2).split()
        # starttime is field 22, but fields[0] is field 3 (state),
        # so starttime is fields[19] (index 19 in the post-comm list)
        starttime_ticks = int(fields[19])

        # Convert clock ticks to seconds
        clk_tck = os.sysconf("SC_CLK_TCK")  # typically 100

        # Get system boot time from /proc/stat
        boot_time = _get_boot_time()
        if boot_time is None:
            return None

        return boot_time + (starttime_ticks / clk_tck)
    except (IndexError, ValueError, OSError):
        return None


def _get_boot_time() -> float | None:
    """Read system boot time from /proc/stat (btime line)."""
    try:
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("btime "):
                    return float(line.split()[1])
    except OSError:
        pass
    return None


def is_process_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def read_pid_file(repo: Path, name: str) -> int | None:
    """Read a PID from data/pids/<name>.pid."""
    pid_path = repo / "data" / "pids" / f"{name}.pid"
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return None


def check_process(
    name: str,
    pid: int | None,
    grace_s: float,
    now: float | None = None,
) -> ProcessStatus:
    """Evaluate a single process against the grace period."""
    now = now or time.time()

    if pid is None:
        return ProcessStatus(name=name, pid=None, state="unknown",
                             uptime_s=0, grace_s=grace_s)

    if not is_process_alive(pid):
        return ProcessStatus(name=name, pid=pid, state="dead",
                             uptime_s=0, grace_s=grace_s)

    start_time = get_process_start_time(pid)
    if start_time is None:
        # Process alive but can't read start time — treat as unknown
        return ProcessStatus(name=name, pid=pid, state="unknown",
                             uptime_s=0, grace_s=grace_s)

    uptime = now - start_time
    state = "stable" if uptime >= grace_s else "in-grace"
    return ProcessStatus(name=name, pid=pid, state=state,
                         uptime_s=round(uptime, 1), grace_s=grace_s)


def check_all(
    repo: Path,
    grace_s: float = DEFAULT_GRACE,
    pid_writer: int | None = None,
    pid_batch: int | None = None,
) -> list[ProcessStatus]:
    """Check both writer and batch processes."""
    writer_pid = pid_writer or read_pid_file(repo, "writer")
    batch_pid = pid_batch or read_pid_file(repo, "batch")

    return [
        check_process("writer", writer_pid, grace_s),
        check_process("batch", batch_pid, grace_s),
    ]


def format_report(statuses: list[ProcessStatus]) -> str:
    """Format a human-readable report."""
    lines = ["=== Restart Grace Check ==="]
    for s in statuses:
        pid_str = str(s.pid) if s.pid else "N/A"
        if s.state == "stable":
            icon = "✓"
            detail = f"uptime {s.uptime_s:.0f}s > grace {s.grace_s:.0f}s"
        elif s.state == "in-grace":
            icon = "◐"
            remaining = s.grace_s - s.uptime_s
            detail = f"uptime {s.uptime_s:.0f}s, {remaining:.0f}s remaining"
        elif s.state == "dead":
            icon = "✗"
            detail = "process not running"
        else:
            icon = "?"
            detail = "cannot determine"
        lines.append(f"  {icon} {s.name:8s} pid={pid_str:6s}  {s.state:8s}  {detail}")

    all_stable = all(s.state == "stable" for s in statuses)
    any_dead = any(s.state == "dead" for s in statuses)
    if all_stable:
        lines.append("→ All processes past grace period. Stable.")
    elif any_dead:
        lines.append("→ WARNING: At least one process crashed. Investigate immediately.")
    else:
        lines.append("→ Processes still in grace period. Wait before declaring stable.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check if restarted processes survived grace period")
    parser.add_argument("--grace", type=float, default=DEFAULT_GRACE,
                        help=f"Grace period in seconds (default: {DEFAULT_GRACE})")
    parser.add_argument("--pid-writer", type=int, default=None,
                        help="Override writer PID (default: read from pid file)")
    parser.add_argument("--pid-batch", type=int, default=None,
                        help="Override batch PID (default: read from pid file)")
    parser.add_argument("--repo", type=str, default=None,
                        help="Path to repo root")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON instead of text")
    args = parser.parse_args()

    repo = find_repo_root(Path(args.repo) if args.repo else None)
    statuses = check_all(repo, grace_s=args.grace,
                         pid_writer=args.pid_writer, pid_batch=args.pid_batch)

    if args.json:
        print(json.dumps([asdict(s) for s in statuses], indent=2))
    else:
        print(format_report(statuses))

    all_stable = all(s.state == "stable" for s in statuses)
    any_dead = any(s.state == "dead" for s in statuses)
    if all_stable:
        return 0
    elif any_dead:
        return 1
    else:
        return 1  # in-grace or unknown — not yet confirmed stable


if __name__ == "__main__":
    sys.exit(main())
