#!/usr/bin/env python3
"""process_uptime.py — report how long writer/batch processes have been alive.

When the automated writing system restarts frequently, raw "is it running?"
checks miss the instability. A process that has been up for 30 seconds after
three crashes in an hour is technically "running" but clearly sick.

This tool reads the PID files, queries /proc for process start times, and
reports uptime in human-readable form. It exits non-zero when a process is
missing or younger than a configurable threshold (useful as a health gate
inside commit_batch or an external watchdog).

Usage:
    python3 tools/process_uptime.py
    python3 tools/process_uptime.py --writer qwen --min-uptime 300
    python3 tools/process_uptime.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai import writer  # noqa: E402


def process_start_time(pid: int) -> float | None:
    """Return the epoch start time of `pid` from /proc, or None if gone."""
    stat = Path(f"/proc/{pid}/stat")
    if not stat.exists():
        return None
    try:
        raw = stat.read_text(encoding="utf-8")
        # Field 22 (1-indexed) is starttime in clock ticks after boot.
        # Field index 21 in 0-indexed split.
        parts = raw.split(")")[-1].split()
        # After the closing ')' of comm field, offset 0 = state, 19 = starttime
        starttime_ticks = int(parts[19])
        # Read boot time from /proc/stat
        btime_line = [
            l for l in Path("/proc/stat").read_text().splitlines()
            if l.startswith("btime")
        ]
        if not btime_line:
            return None
        btime = int(btime_line[0].split()[1])
        clk_tck = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        return btime + starttime_ticks / clk_tck
    except (IndexError, ValueError, OSError):
        return None


def uptime_seconds(pid: int) -> float | None:
    """Seconds the process has been alive, or None if not running."""
    start = process_start_time(pid)
    if start is None:
        return None
    return max(0.0, time.time() - start)


def format_duration(seconds: float) -> str:
    """Human-friendly duration string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    if seconds < 86400:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h{m}m"
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    return f"{d}d{h}h"


def read_pid(writer_id: str | None, role: str) -> int | None:
    """Read PID from the pidfile for the given writer and role."""
    if role == "writer":
        pf = writer.pid_file(writer_id)
    elif role == "batch":
        pf = writer.batch_pid_file(writer_id)
    else:
        return None
    if not pf.exists():
        return None
    try:
        return int(pf.read_text().strip())
    except (ValueError, OSError):
        return None


def check_process(writer_id: str | None, role: str, min_uptime: float) -> dict:
    """Return a status dict for one process."""
    pid = read_pid(writer_id, role)
    if pid is None:
        return {"role": role, "running": False, "pid": None, "uptime": None,
                "uptime_str": "not running", "healthy": False}
    up = uptime_seconds(pid)
    if up is None:
        return {"role": role, "running": False, "pid": pid, "uptime": None,
                "uptime_str": "stale pidfile", "healthy": False}
    return {"role": role, "running": True, "pid": pid, "uptime": round(up, 1),
            "uptime_str": format_duration(up), "healthy": up >= min_uptime}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default=None,
                    help="writer id, e.g. qwen / kimi (or env IAMAI_WRITER)")
    ap.add_argument("--min-uptime", type=float, default=60,
                    help="seconds; processes younger than this are unhealthy (default 60)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = ap.parse_args()

    wid = args.writer or os.environ.get("IAMAI_WRITER")
    results = [
        check_process(wid, "writer", args.min_uptime),
        check_process(wid, "batch", args.min_uptime),
    ]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            status = "UP" if r["running"] else "DOWN"
            health = "healthy" if r.get("healthy") else "unhealthy"
            print(f"  {r['role']:>8}: {status}  pid={r['pid']}  "
                  f"uptime={r['uptime_str']}  [{health}]")

    all_healthy = all(r["healthy"] for r in results)
    return 0 if all_healthy else 1


if __name__ == "__main__":
    sys.exit(main())
