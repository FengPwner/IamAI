#!/usr/bin/env python3
"""process_liveness.py — quick health check for writer + batch committer.

Reports whether each process is alive, whether its pidfile matches reality,
and how long it has been running. Designed for caretaker scripts that need
a single-command verdict before deciding to restart.

Usage:
    python3 tools/process_liveness.py [--writer qwen] [--json]

Exit codes:
    0  both processes alive and healthy
    1  at least one process is dead or pidfile is stale
"""

import argparse
import json
import os
import signal
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class ProcessStatus:
    name: str
    pidfile: str
    pid: Optional[int]
    alive: bool
    pidfile_exists: bool
    pidfile_stale: bool  # pidfile exists but process is gone
    uptime_seconds: Optional[float]
    command: Optional[str]

    @property
    def verdict(self) -> str:
        if self.alive and not self.pidfile_stale:
            return "healthy"
        if self.pidfile_stale:
            return "stale_pidfile"
        if not self.pidfile_exists:
            return "no_pidfile"
        return "dead"


def _read_pidfile(path: str) -> Optional[int]:
    try:
        return int(Path(path).read_text().strip())
    except (FileNotFoundError, ValueError, PermissionError):
        return None


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _process_start_time(pid: int) -> Optional[float]:
    """Read /proc/<pid>/stat for process start time (field 22, in clock ticks)."""
    try:
        stat_path = Path(f"/proc/{pid}/stat")
        content = stat_path.read_text()
        # field index 21 (0-based) = starttime in clock ticks since boot
        parts = content.split()
        if len(parts) > 21:
            ticks = int(parts[21])
            # convert to seconds using sysconf
            hz = os.sysconf("SC_CLK_TCK")
            # boot time from /proc/stat
            boot_line = Path("/proc/stat").read_text().split("\n")[0]
            # not reliable across kernels; fallback to pidfile mtime
            return None  # simplified: use pidfile mtime instead
    except (FileNotFoundError, ValueError, IndexError, PermissionError):
        pass
    return None


def _pidfile_mtime(path: str) -> Optional[float]:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _process_command(pid: int) -> Optional[str]:
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        return cmdline.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except (FileNotFoundError, PermissionError):
        return None


def check_process(name: str, pidfile_path: str) -> ProcessStatus:
    pidfile_exists = os.path.exists(pidfile_path)
    pid = _read_pidfile(pidfile_path)
    alive = _is_alive(pid) if pid is not None else False
    stale = pidfile_exists and not alive

    uptime = None
    if alive and pidfile_exists:
        mtime = _pidfile_mtime(pidfile_path)
        if mtime is not None:
            uptime = time.time() - mtime

    cmd = _process_command(pid) if alive and pid else None

    return ProcessStatus(
        name=name,
        pidfile=pidfile_path,
        pid=pid,
        alive=alive,
        pidfile_exists=pidfile_exists,
        pidfile_stale=stale,
        uptime_seconds=uptime,
        command=cmd,
    )


def main():
    parser = argparse.ArgumentParser(description="Check writer + batch liveness")
    parser.add_argument("--writer", default=os.environ.get("IAMAII_WRITER", "qwen"),
                        help="Writer ID (default: qwen)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    wid = args.writer
    writer_pid = f"/tmp/iamai-writer-{wid}.pid"
    batch_pid = f"/tmp/iamai-batch-{wid}.pid"

    writer_status = check_process("writer", writer_pid)
    batch_status = check_process("batch", batch_pid)

    if args.json:
        result = {
            "writer": asdict(writer_status),
            "batch": asdict(batch_status),
            "all_healthy": writer_status.verdict == "healthy" and batch_status.verdict == "healthy",
        }
        print(json.dumps(result, indent=2, default=str))
    else:
        for s in (writer_status, batch_status):
            uptime_str = ""
            if s.uptime_seconds is not None:
                mins = int(s.uptime_seconds // 60)
                uptime_str = f"  uptime {mins}m"
            print(f"{s.name:8s} [{wid}]: {s.verdict:14s}  pid={s.pid or '-':>6}{uptime_str}")
            if s.command:
                print(f"         cmd: {s.command[:80]}")

    all_ok = writer_status.verdict == "healthy" and batch_status.verdict == "healthy"
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
