"""Process liveness detector — are the writer and batch committer alive?

Every caretaker visit starts with the same question: *are the processes
still running?*  This module answers it in one call.

``check_liveness()`` inspects the system process table and returns a
structured ``LivenessReport`` covering:

- **writer_alive** / **batch_alive**: boolean flags
- **writer_pid** / **batch_pid**: PIDs if found, else ``None``
- **writer_uptime** / **batch_uptime**: seconds since process start
  (requires ``/proc/<pid>/stat``; ``None`` on non-Linux or when the
  process has already exited)
- **zombie**: ``True`` if the PID exists but the process is a zombie
- **verdict**: one of ``healthy``, ``degraded``, ``dead``

The verdict logic:

===========  =================================================
verdict      condition
===========  =================================================
``healthy``  both writer and batch are alive, neither zombie
``degraded`` exactly one is alive (or one is zombie)
``dead``     neither is alive
===========  =================================================

Usage::

    from iamai.process_liveness import check_liveness, liveness_report

    report = check_liveness()
    print(liveness_report(report))
    # → "healthy: writer pid 10195 (up 312s), batch pid 10196 (up 312s)"

    if report["verdict"] != "healthy":
        # restart logic here
        ...
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ProcessInfo:
    """Information about a single process."""

    alive: bool = False
    pid: Optional[int] = None
    uptime: Optional[float] = None
    zombie: bool = False
    cmdline: str = ""


@dataclass
class LivenessReport:
    """Structured liveness report for the repo's automated processes."""

    writer: ProcessInfo = field(default_factory=ProcessInfo)
    batch: ProcessInfo = field(default_factory=ProcessInfo)
    verdict: str = "dead"
    checked_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "writer_alive": self.writer.alive,
            "writer_pid": self.writer.pid,
            "writer_uptime": self.writer.uptime,
            "writer_zombie": self.writer.zombie,
            "batch_alive": self.batch.alive,
            "batch_pid": self.batch.pid,
            "batch_uptime": self.batch.uptime,
            "batch_zombie": self.batch.zombie,
            "verdict": self.verdict,
            "checked_at": self.checked_at,
        }


def _find_process(pattern: str) -> Optional[int]:
    """Find the PID of a process whose command line contains *pattern*.

    Uses ``ps aux`` and filters in Python to avoid platform-specific
    ``pgrep`` flag differences.  Returns the first matching PID or
    ``None``.
    """
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        if pattern in line and "grep" not in line:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1])
                except ValueError:
                    continue
    return None


def _read_proc_uptime(pid: int) -> Optional[float]:
    """Read process start time from ``/proc/<pid>/stat`` and compute uptime.

    Returns seconds since the process started, or ``None`` if ``/proc``
    is unavailable (macOS, Windows) or the PID no longer exists.
    """
    stat_path = Path(f"/proc/{pid}/stat")
    if not stat_path.exists():
        return None

    try:
        stat_text = stat_path.read_text()
        # Field 22 (1-indexed) is starttime in clock ticks since boot.
        # We need to parse carefully because the comm field (field 2)
        # can contain spaces and parentheses.
        # Find the last ')' to skip past the comm field.
        comm_end = stat_text.rfind(")")
        if comm_end == -1:
            return None
        fields_after_comm = stat_text[comm_end + 2 :].split()
        # After comm, field index 0 = state (field 3),
        # starttime is field 22 - 3 = index 19
        if len(fields_after_comm) < 20:
            return None
        starttime_ticks = int(fields_after_comm[19])

        # Read system uptime and clock ticks per second
        uptime_path = Path("/proc/uptime")
        if not uptime_path.exists():
            return None
        system_uptime = float(uptime_path.read_text().split()[0])
        clk_tck = os.sysconf("SC_CLK_TCK")

        process_uptime = system_uptime - (starttime_ticks / clk_tck)
        return max(0.0, process_uptime)
    except (ValueError, IndexError, OSError):
        return None


def _is_zombie(pid: int) -> bool:
    """Check whether a process is in zombie state via ``/proc/<pid>/stat``."""
    stat_path = Path(f"/proc/{pid}/stat")
    if not stat_path.exists():
        return False
    try:
        stat_text = stat_path.read_text()
        comm_end = stat_text.rfind(")")
        if comm_end == -1:
            return False
        state = stat_text[comm_end + 2 :].split()[0]
        return state == "Z"
    except (IndexError, OSError):
        return False


def _inspect_process(pattern: str) -> ProcessInfo:
    """Inspect a single process by command-line pattern."""
    pid = _find_process(pattern)
    if pid is None:
        return ProcessInfo()

    zombie = _is_zombie(pid)
    uptime = _read_proc_uptime(pid)

    # Read cmdline for diagnostics
    cmdline = ""
    try:
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        if cmdline_path.exists():
            cmdline = cmdline_path.read_text().replace("\x00", " ").strip()
    except OSError:
        pass

    return ProcessInfo(
        alive=True,
        pid=pid,
        uptime=uptime,
        zombie=zombie,
        cmdline=cmdline,
    )


def check_liveness(
    writer_pattern: str = "writer_loop.py",
    batch_pattern: str = "commit_batch.py",
) -> LivenessReport:
    """Check whether the writer and batch committer are alive.

    Parameters
    ----------
    writer_pattern : str
        Substring to match in the writer process command line.
    batch_pattern : str
        Substring to match in the batch committer command line.

    Returns
    -------
    LivenessReport
        Structured report with per-process info and an overall verdict.
    """
    writer = _inspect_process(writer_pattern)
    batch = _inspect_process(batch_pattern)

    writer_ok = writer.alive and not writer.zombie
    batch_ok = batch.alive and not batch.zombie

    if writer_ok and batch_ok:
        verdict = "healthy"
    elif writer_ok or batch_ok:
        verdict = "degraded"
    else:
        verdict = "dead"

    return LivenessReport(
        writer=writer,
        batch=batch,
        verdict=verdict,
        checked_at=time.time(),
    )


def liveness_report(report: LivenessReport) -> str:
    """Format a ``LivenessReport`` as a one-line human-readable string.

    Suitable for caretaker logs and commit messages.
    """
    def _fmt(info: ProcessInfo, label: str) -> str:
        if not info.alive:
            return f"{label}: NOT running"
        if info.zombie:
            return f"{label}: ZOMBIE pid {info.pid}"
        up = ""
        if info.uptime is not None:
            if info.uptime < 60:
                up = f" (up {info.uptime:.0f}s)"
            elif info.uptime < 3600:
                up = f" (up {info.uptime / 60:.1f}m)"
            else:
                up = f" (up {info.uptime / 3600:.1f}h)"
        return f"{label}: pid {info.pid}{up}"

    parts = [
        report.verdict,
        _fmt(report.writer, "writer"),
        _fmt(report.batch, "batch"),
    ]
    return ", ".join(parts)
