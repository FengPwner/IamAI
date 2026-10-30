"""Restart frequency — how often do writer/batch processes get recycled?

The IamAI writer runs inside containers that periodically reclaim idle
processes.  This module tracks restart events by comparing pid file ages
against log session boundaries, and detects patterns in the reclamation
cycle.

Three public functions:

- ``recent_restarts(writer_id, window_hours)`` — list of restart events
  within the given time window, each with timestamp and gap from the
  previous restart.
- ``mean_time_between_restarts(writer_id, window_hours)`` — average
  seconds between restarts; ``None`` when fewer than two events exist.
- ``restart_summary(writer_id)`` — one-liner for caretaker reports.

Scale (time between consecutive restarts):

==============  =================================================
verdict         meaning
==============  =================================================
``stable``      gap > 7200s (2 hours) — rare reclamation
``normal``      3600s < gap ≤ 7200s — roughly hourly cycle
``aggressive``  1800s < gap ≤ 3600s — sub-hourly reclamation
``thrashing``   gap ≤ 1800s — something is very wrong
==============  =================================================

Edge cases:

- No pid file → ``recent_restarts`` returns an empty list.
- Only one restart event → ``mean_time_between_restarts`` returns ``None``.
- Multiple writers on the same host → each writer_id is tracked separately.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

_PID_DIR = Path("/tmp")
_LOG_DIR = Path("/tmp")

# Thresholds in seconds
_STABLE = 7200       # > 2 hours
_NORMAL = 3600       # 1–2 hours
_AGGRESSIVE = 1800   # 30 min – 1 hour
# below 30 min → thrashing

# Timestamp pattern in log files
_TS_RE = None  # lazy import to avoid circular deps


def _pid_file(writer_id: str) -> Path:
    return _PID_DIR / f"iamai-writer-{writer_id}.pid"


def _batch_pid_file(writer_id: str) -> Path:
    return _PID_DIR / f"iamai-batch-{writer_id}.pid"


def _pid_file_age(path: Path) -> Optional[float]:
    """Seconds since the pid file was last modified, or None if missing."""
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        return round(time.time() - mtime, 1)
    except OSError:
        return None


def _classify_gap(seconds: float) -> str:
    """Classify the time between two restarts."""
    if seconds > _STABLE:
        return "stable"
    if seconds > _NORMAL:
        return "normal"
    if seconds > _AGGRESSIVE:
        return "aggressive"
    return "thrashing"


def _log_session_boundaries(log_path: Path) -> list[float]:
    """Extract restart-boundary timestamps from a writer log.

    A restart boundary is detected when the gap between two consecutive
    timestamped lines exceeds 60 seconds (the batch commit interval is
    600s; the stroke interval is 15s; a 60s gap is unambiguously a
    restart rather than normal cadence jitter).
    """
    import re
    if not log_path.exists():
        return []

    ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")
    boundaries: list[float] = []
    prev_ts: Optional[float] = None

    try:
        for line in log_path.read_text(errors="replace").splitlines():
            m = ts_re.match(line)
            if not m:
                continue
            try:
                dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                ts = dt.timestamp()
            except ValueError:
                continue

            if prev_ts is not None and (ts - prev_ts) > 60:
                # This line starts a new session
                boundaries.append(ts)
            prev_ts = ts
    except OSError:
        return []

    return boundaries


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def recent_restarts(
    writer_id: str = "qwen",
    window_hours: float = 24.0,
) -> list[dict]:
    """List restart events within the given time window.

    Each event is a dict::

        {
            "at": "2026-10-15 18:00:03",
            "epoch": 1760551203.0,
            "gap_seconds": 3600.0,   # None for the first event
            "verdict": "normal",     # None for the first event
        }

    Returns an empty list when no restart data is available.
    """
    log_path = _LOG_DIR / f"iamai-{writer_id}.log"
    boundaries = _log_session_boundaries(log_path)

    # Also consider pid file age as a "current session start" marker
    pf = _pid_file(writer_id)
    pf_age = _pid_file_age(pf)
    if pf_age is not None:
        current_start = time.time() - pf_age
        # Only add if it's not already captured by log boundaries
        if not boundaries or abs(current_start - boundaries[-1]) > 120:
            boundaries.append(current_start)

    if not boundaries:
        return []

    boundaries.sort()
    cutoff = time.time() - (window_hours * 3600)
    filtered = [b for b in boundaries if b >= cutoff]

    events: list[dict] = []
    for i, ts in enumerate(filtered):
        dt = datetime.fromtimestamp(ts)
        gap = None
        verdict = None
        if i > 0:
            gap = round(ts - filtered[i - 1], 1)
            verdict = _classify_gap(gap)
        events.append({
            "at": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "epoch": ts,
            "gap_seconds": gap,
            "verdict": verdict,
        })

    return events


def mean_time_between_restarts(
    writer_id: str = "qwen",
    window_hours: float = 24.0,
) -> Optional[float]:
    """Average seconds between restarts.

    Returns ``None`` when fewer than two restart events exist in the window.
    """
    events = recent_restarts(writer_id, window_hours)
    gaps = [e["gap_seconds"] for e in events if e["gap_seconds"] is not None]
    if not gaps:
        return None
    return round(sum(gaps) / len(gaps), 1)


def restart_summary(writer_id: str = "qwen") -> str:
    """One-liner for caretaker status reports.

    Example outputs::

        restarts(qwen): 3 in 24h, avg gap 3600s (normal)
        restarts(qwen): 8 in 24h, avg gap 900s (thrashing!)
        restarts(qwen): 0 in 24h (stable)
        restarts(qwen): no data
    """
    events = recent_restarts(writer_id)
    if not events:
        return f"restarts({writer_id}): no data"

    mtbr = mean_time_between_restarts(writer_id)
    count = len(events)

    if mtbr is None:
        return f"restarts({writer_id}): {count} in 24h, single session"

    verdict = _classify_gap(mtbr)
    alarm = "!" if verdict == "thrashing" else ""
    return (
        f"restarts({writer_id}): {count} in 24h, "
        f"avg gap {int(mtbr)}s ({verdict}{alarm})"
    )
