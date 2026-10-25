"""Track how long writer and batch processes have been running.

Process uptime is a useful signal for caretakers:

- A writer that's been up for hours is stable.
- A writer that was restarted 30 seconds ago might crash again.
- If uptime is shorter than the stall gap, the current session
  didn't cause the stall — the previous one did.

This module reads the PID file's modification time (which ``writer_loop``
touches on start) and compares it to the current time. No external
dependencies, no state files — just filesystem metadata and arithmetic.

Usage::

    from iamai.uptime_tracker import process_uptime, uptime_summary

    info = process_uptime("qwen")
    print(info["writer_uptime_seconds"])   # e.g. 3600
    print(info["batch_uptime_seconds"])    # e.g. 3600
    print(info["writer_pid"])              # e.g. 1301

    summary = uptime_summary("qwen")
    print(summary)  # "writer: 1h0m, batch: 1h0m, both alive"
"""

from __future__ import annotations

import os
import time
from pathlib import Path


def _pid_file(writer_id: str, kind: str) -> Path:
    """Return the PID file path for a given writer and process kind."""
    return Path(f"/tmp/iamai-{kind}-{writer_id}.pid")


def _read_pid(path: Path) -> int | None:
    """Read a PID from a file, returning None if unreadable."""
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _is_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _file_age_seconds(path: Path) -> float | None:
    """Return how many seconds ago a file was last modified, or None."""
    try:
        mtime = path.stat().st_mtime
        return max(0.0, time.time() - mtime)
    except OSError:
        return None


def process_uptime(writer_id: str = "qwen") -> dict:
    """Get uptime and status for writer and batch processes.

    Args:
        writer_id: the writer identifier (default "qwen")

    Returns:
        Dict with keys:
        - writer_pid: int or None
        - batch_pid: int or None
        - writer_alive: bool
        - batch_alive: bool
        - writer_uptime_seconds: float or None (None if no PID file)
        - batch_uptime_seconds: float or None
    """
    writer_pf = _pid_file(writer_id, "writer")
    batch_pf = _pid_file(writer_id, "batch")

    writer_pid = _read_pid(writer_pf)
    batch_pid = _read_pid(batch_pf)

    writer_alive = _is_alive(writer_pid) if writer_pid is not None else False
    batch_alive = _is_alive(batch_pid) if batch_pid is not None else False

    writer_uptime = _file_age_seconds(writer_pf) if writer_alive else None
    batch_uptime = _file_age_seconds(batch_pf) if batch_alive else None

    return {
        "writer_pid": writer_pid,
        "batch_pid": batch_pid,
        "writer_alive": writer_alive,
        "batch_alive": batch_alive,
        "writer_uptime_seconds": round(writer_uptime, 1) if writer_uptime is not None else None,
        "batch_uptime_seconds": round(batch_uptime, 1) if batch_uptime is not None else None,
    }


def format_duration(seconds: float | None) -> str:
    """Format seconds into a human-readable duration string.

    Args:
        seconds: duration in seconds, or None

    Returns:
        Formatted string like "2h15m", "45m30s", "12s", or "n/a"

    Examples:
        >>> format_duration(7200)
        '2h0m'
        >>> format_duration(90)
        '1m30s'
        >>> format_duration(45)
        '45s'
        >>> format_duration(None)
        'n/a'
    """
    if seconds is None:
        return "n/a"
    seconds = int(seconds)
    if seconds < 0:
        return "n/a"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m{secs}s" if secs else f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h{mins}m"


def uptime_summary(writer_id: str = "qwen") -> str:
    """One-line human-readable uptime summary.

    Args:
        writer_id: the writer identifier

    Returns:
        Summary string like "writer: 2h15m, batch: 2h15m, both alive"
    """
    info = process_uptime(writer_id)
    w_dur = format_duration(info["writer_uptime_seconds"])
    b_dur = format_duration(info["batch_uptime_seconds"])

    parts = [f"writer: {w_dur}", f"batch: {b_dur}"]

    if info["writer_alive"] and info["batch_alive"]:
        parts.append("both alive")
    elif info["writer_alive"]:
        parts.append("batch DOWN")
    elif info["batch_alive"]:
        parts.append("writer DOWN")
    else:
        parts.append("BOTH DOWN")

    return ", ".join(parts)


def is_fresh(writer_id: str = "qwen", threshold_seconds: int = 120) -> bool:
    """Check if processes were recently (re)started.

    Useful for deciding whether a stall was caused by the current
    session or a previous one. If uptime < threshold, the restart
    is too recent to have caused long gaps.

    Args:
        writer_id: the writer identifier
        threshold_seconds: how many seconds counts as "fresh"

    Returns:
        True if writer uptime is below threshold (recently restarted)
    """
    info = process_uptime(writer_id)
    uptime = info["writer_uptime_seconds"]
    if uptime is None:
        return True  # no uptime data → assume fresh/dead
    return uptime < threshold_seconds
