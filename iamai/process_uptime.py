"""process_uptime — track how long writer and batch processes have been alive.

Motivation
----------

Every caretaker visit starts with the same question: *are the processes
still running, and for how long?*  ``tools/run_both.sh --status`` answers
the first half (alive or not) but not the second (uptime).

A process that has been alive for four hours is healthy.  One that has
been alive for four minutes after a restart is a canary — it might not
survive the hour.  And one that has been alive for forty-eight hours
without producing strokes has a different problem entirely.

This module reads the pid files written by ``run_both.sh``, queries the
OS for each process's start time, and returns a structured report that
downstream tools (dashboards, health scores, visit notes) can consume
without shelling out to ``ps``.

Public API
----------

.. code-block:: python

    from iamai.process_uptime import get_uptime_report, UptimeReport

    report = get_uptime_report(writer_id="qwen")

    print(report.writer.alive)       # True
    print(report.writer.uptime_s)    # 14523.7
    print(report.writer.uptime_human) # "4h 2m"
    print(report.batch.alive)        # True
    print(report.both_alive)         # True

Design notes
------------

- Start time is read from ``/proc/<pid>/stat`` on Linux (field 22,
  ``starttime``, in clock ticks since boot).  Falls back to
  ``os.path.getmtime`` on the pid file when ``/proc`` is unavailable.
- ``alive`` uses ``kill(pid, 0)`` — the standard POSIX liveness check
  that sends no signal.
- No external dependencies; stdlib only.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ProcessInfo:
    """Uptime information for a single process."""

    name: str
    pid: Optional[int]
    alive: bool
    start_time: Optional[float] = None  # Unix timestamp
    uptime_s: Optional[float] = None  # seconds since start
    uptime_human: str = ""  # human-readable duration

    @property
    def pid_file(self) -> str:
        """Default pid file path for this process name."""
        return f"/tmp/iamai-{self.name}.pid"


@dataclass
class UptimeReport:
    """Combined uptime report for writer and batch processes."""

    writer: ProcessInfo
    batch: ProcessInfo

    @property
    def both_alive(self) -> bool:
        return self.writer.alive and self.batch.alive

    @property
    def any_alive(self) -> bool:
        return self.writer.alive or self.batch.alive

    def summary(self) -> str:
        """One-line summary suitable for a caretaker visit note."""
        parts = []
        for proc in (self.writer, self.batch):
            status = f"pid {proc.pid} up {proc.uptime_human}" if proc.alive else "NOT running"
            parts.append(f"{proc.name}: {status}")
        return "  |  ".join(parts)


def _read_pid(pid_file: str) -> Optional[int]:
    """Read a pid from a file, returning None on any failure."""
    try:
        text = Path(pid_file).read_text().strip()
        pid = int(text)
        return pid if pid > 0 else None
    except (OSError, ValueError):
        return None


def _is_alive(pid: int) -> bool:
    """POSIX liveness check: kill(pid, 0) succeeds iff process exists
    and we have permission to signal it."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _get_start_time_proc(pid: int) -> Optional[float]:
    """Read process start time from /proc/<pid>/stat (Linux only).

    Field 22 (1-indexed) is ``starttime`` in clock ticks since boot.
    We convert to a Unix timestamp using the system boot time from
    ``/proc/stat`` and the clock ticks per second from ``os.sysconf``.
    """
    try:
        # Read system boot time
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("btime "):
                    boot_time = int(line.split()[1])
                    break
            else:
                return None

        # Read process start time in clock ticks since boot
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().split()
            # Field 22 is index 21 (0-indexed), but the comm field (index 1)
            # can contain spaces if wrapped in parens. Find the closing paren
            # and count from there.
            raw = f.seek(0) or f.read()
            close_paren = raw.rfind(")")
            if close_paren < 0:
                return None
            after_comm = raw[close_paren + 2:].split()
            # after_comm[0] is field 3 (state), so starttime is after_comm[19]
            if len(after_comm) < 20:
                return None
            starttime_ticks = int(after_comm[19])

        hz = os.sysconf("SC_CLK_TCK")  # typically 100
        return boot_time + starttime_ticks / hz
    except (OSError, ValueError, IndexError):
        return None


def _get_start_time_pidfile(pid_file: str) -> Optional[float]:
    """Fallback: use pid file modification time as a proxy for start time.

    This is less accurate (the file might have been touched without
    restarting the process) but works when /proc is unavailable.
    """
    try:
        return os.path.getmtime(pid_file)
    except OSError:
        return None


def _format_duration(seconds: float) -> str:
    """Format seconds into a compact human-readable string."""
    if seconds < 0:
        return "0s"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"


def _process_info(name: str, pid_file: str) -> ProcessInfo:
    """Build a ProcessInfo for one process."""
    pid = _read_pid(pid_file)
    if pid is None:
        return ProcessInfo(name=name, pid=None, alive=False, uptime_human="n/a")

    alive = _is_alive(pid)
    if not alive:
        return ProcessInfo(name=name, pid=pid, alive=False, uptime_human="n/a")

    # Try /proc first, fall back to pid file mtime
    start_time = _get_start_time_proc(pid)
    if start_time is None:
        start_time = _get_start_time_pidfile(pid_file)

    uptime_s = None
    uptime_human = "unknown"
    if start_time is not None:
        uptime_s = time.time() - start_time
        uptime_human = _format_duration(uptime_s)

    return ProcessInfo(
        name=name,
        pid=pid,
        alive=True,
        start_time=start_time,
        uptime_s=uptime_s,
        uptime_human=uptime_human,
    )


def get_uptime_report(
    writer_id: str = "qwen",
    writer_pid_file: Optional[str] = None,
    batch_pid_file: Optional[str] = None,
) -> UptimeReport:
    """Get uptime information for the writer and batch processes.

    Parameters
    ----------
    writer_id : str
        The writer identifier (matches ``$IAMAII_WRITER``).
    writer_pid_file : str, optional
        Override the default writer pid file path.
    batch_pid_file : str, optional
        Override the default batch pid file path.

    Returns
    -------
    UptimeReport
        Combined report with writer and batch process info.
    """
    w_pid = writer_pid_file or f"/tmp/iamai-writer-{writer_id}.pid"
    b_pid = batch_pid_file or f"/tmp/iamai-batch-{writer_id}.pid"

    writer = _process_info(f"writer[{writer_id}]", w_pid)
    batch = _process_info(f"batch[{writer_id}]", b_pid)

    return UptimeReport(writer=writer, batch=batch)
