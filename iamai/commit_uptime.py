"""commit_uptime — measure commit stream availability over time.

While ``commit_velocity`` captures momentum, ``cadence_drift`` / ``cadence_jitter``
measure regularity, and ``commit_recovery_time`` quantifies bounce-back speed,
none of these answer the simplest operational question: *what fraction of the
time is the commit stream actually alive?*

This module borrows the concept of **uptime** from systems engineering (the
familiar "five nines" = 99.999% availability) and applies it to commit
streams.  The timeline is divided into fixed-width windows; a window is
**alive** if it contains at least one commit, **dead** otherwise.  The
resulting ``UptimeReport`` gives:

- ``uptime_fraction`` — overall alive / total windows
- ``recent_uptime_fraction`` — alive / total for the last *N* windows
- ``max_consecutive_dead`` — longest streak of dead windows (worst outage)
- ``mean_time_between_outages`` — average gaps between dead-window clusters
- ``classification``:

  ===================  ==================================================
  uptime_fraction      label
  ===================  ==================================================
  ≥ 0.99               **five_nines** — near-continuous activity
  ≥ 0.95               **high** — occasional gaps
  ≥ 0.80               **moderate** — regular quiet periods
  ≥ 0.50               **degraded** — more dead than not is approaching
  < 0.50               **unreliable** — stream is down more than up
  ===================  ==================================================

Algorithm
---------
1. Accept a sorted list of commit timestamps (ISO-8601, epoch, datetime).
2. Determine the window size: either the caller's ``window_seconds`` or
   the median inter-commit gap (auto-detected, robust to outliers).
3. Lay a grid of windows from the first to the last timestamp.
4. For each window, check whether any commit falls inside it.
5. Aggregate into ``UptimeReport``.

Edge cases
----------
* Fewer than 2 commits → zeroed report (cannot determine uptime).
* All commits at the same timestamp → single window, uptime = 1.0.
* ``window_seconds`` of 0 or negative → ``ValueError``.

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 725, 2026-11-19.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Union


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OutageEvent:
    """A contiguous run of dead windows."""

    start_index: int
    end_index: int  # inclusive
    duration_seconds: float
    n_windows: int

    def to_dict(self) -> dict:
        return {
            "start_index": self.start_index,
            "end_index": self.end_index,
            "duration_seconds": round(self.duration_seconds, 2),
            "n_windows": self.n_windows,
        }


@dataclass
class UptimeReport:
    """Result of commit uptime analysis."""

    n_commits: int
    window_seconds: float
    total_windows: int
    alive_windows: int
    dead_windows: int
    uptime_fraction: float
    recent_uptime_fraction: float
    max_consecutive_dead: int
    mean_time_between_outages: float
    n_outages: int
    classification: str  # five_nines | high | moderate | degraded | unreliable
    outages: List[OutageEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "n_commits": self.n_commits,
            "window_seconds": round(self.window_seconds, 2),
            "total_windows": self.total_windows,
            "alive_windows": self.alive_windows,
            "dead_windows": self.dead_windows,
            "uptime_fraction": round(self.uptime_fraction, 4),
            "recent_uptime_fraction": round(self.recent_uptime_fraction, 4),
            "max_consecutive_dead": self.max_consecutive_dead,
            "mean_time_between_outages": round(self.mean_time_between_outages, 2),
            "n_outages": self.n_outages,
            "classification": self.classification,
            "outages": [o.to_dict() for o in self.outages],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_epoch(ts: Union[str, int, float, datetime]) -> float:
    """Convert a timestamp to epoch seconds."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.timestamp()
    if isinstance(ts, str):
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # Try epoch string
            return float(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    raise TypeError(f"Unsupported timestamp type: {type(ts)}")


def _classify(uptime: float) -> str:
    """Classify uptime fraction into a label."""
    if uptime >= 0.99:
        return "five_nines"
    if uptime >= 0.95:
        return "high"
    if uptime >= 0.80:
        return "moderate"
    if uptime >= 0.50:
        return "degraded"
    return "unreliable"


def _zero_report(n_commits: int, window_seconds: float = 0.0) -> UptimeReport:
    """Return a zeroed-out report for degenerate inputs."""
    return UptimeReport(
        n_commits=n_commits,
        window_seconds=window_seconds,
        total_windows=0,
        alive_windows=0,
        dead_windows=0,
        uptime_fraction=0.0,
        recent_uptime_fraction=0.0,
        max_consecutive_dead=0,
        mean_time_between_outages=0.0,
        n_outages=0,
        classification="unreliable",
        outages=[],
    )


def _detect_outages(alive: List[bool]) -> List[OutageEvent]:
    """Find contiguous runs of dead windows."""
    outages: List[OutageEvent] = []
    i = 0
    n = len(alive)
    while i < n:
        if not alive[i]:
            start = i
            while i < n and not alive[i]:
                i += 1
            end = i - 1
            outages.append(OutageEvent(
                start_index=start,
                end_index=end,
                duration_seconds=0.0,  # filled in by caller with window_seconds
                n_windows=end - start + 1,
            ))
        else:
            i += 1
    return outages


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyse_uptime(
    timestamps: Sequence[Union[str, int, float, datetime]],
    window_seconds: Optional[float] = None,
    recent_windows: int = 20,
) -> UptimeReport:
    """Analyse commit stream uptime.

    Parameters
    ----------
    timestamps : sequence of timestamps (need not be sorted)
        At least 2 commits are required for meaningful analysis.
    window_seconds : float, optional
        Width of each observation window in seconds.  If ``None``, uses
        the median inter-commit gap (auto-detected).
    recent_windows : int
        Number of trailing windows to compute ``recent_uptime_fraction``.

    Returns
    -------
    UptimeReport
    """
    if len(timestamps) < 2:
        ws = window_seconds if window_seconds and window_seconds > 0 else 0.0
        return _zero_report(len(timestamps), ws)

    epochs = sorted(_to_epoch(t) for t in timestamps)
    n = len(epochs)

    # Auto-detect window size from median gap
    gaps = [epochs[i + 1] - epochs[i] for i in range(n - 1)]
    median_gap = statistics.median(gaps)

    if window_seconds is None:
        ws = max(median_gap, 1.0)  # at least 1 second
    else:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        ws = float(window_seconds)

    # Edge: all same timestamp
    span = epochs[-1] - epochs[0]
    if span == 0:
        return UptimeReport(
            n_commits=n,
            window_seconds=ws,
            total_windows=1,
            alive_windows=1,
            dead_windows=0,
            uptime_fraction=1.0,
            recent_uptime_fraction=1.0,
            max_consecutive_dead=0,
            mean_time_between_outages=0.0,
            n_outages=0,
            classification="five_nines",
            outages=[],
        )

    # Lay grid of windows
    total_windows = math.ceil(span / ws) + 1  # +1 to include the last commit
    alive = [False] * total_windows

    for ts in epochs:
        idx = int((ts - epochs[0]) / ws)
        idx = min(idx, total_windows - 1)
        alive[idx] = True

    alive_count = sum(alive)
    dead_count = total_windows - alive_count
    uptime_frac = alive_count / total_windows

    # Recent uptime
    recent_n = min(recent_windows, total_windows)
    recent_alive = sum(alive[-recent_n:])
    recent_uptime_frac = recent_alive / recent_n

    # Max consecutive dead
    max_consec = 0
    current_run = 0
    for a in alive:
        if not a:
            current_run += 1
            max_consec = max(max_consec, current_run)
        else:
            current_run = 0

    # Outages
    outages = _detect_outages(alive)
    # Fill in durations
    for out in outages:
        out.duration_seconds = out.n_windows * ws

    # Mean time between outages (start-to-start)
    if len(outages) >= 2:
        starts = [o.start_index * ws for o in outages]
        mtbo = statistics.mean(
            starts[i + 1] - starts[i] for i in range(len(starts) - 1)
        )
    else:
        mtbo = 0.0

    return UptimeReport(
        n_commits=n,
        window_seconds=ws,
        total_windows=total_windows,
        alive_windows=alive_count,
        dead_windows=dead_count,
        uptime_fraction=uptime_frac,
        recent_uptime_fraction=recent_uptime_frac,
        max_consecutive_dead=max_consec,
        mean_time_between_outages=mtbo,
        n_outages=len(outages),
        classification=_classify(uptime_frac),
        outages=outages,
    )


def analyse_uptime_windows(
    timestamps: Sequence[Union[str, int, float, datetime]],
    window_sizes: Optional[Sequence[float]] = None,
    recent_windows: int = 20,
) -> List[UptimeReport]:
    """Analyse uptime at multiple window granularities.

    Parameters
    ----------
    timestamps : sequence of timestamps
    window_sizes : list of floats, optional
        Window widths in seconds.  Defaults to ``[60, 300, 600]``
        (1 min, 5 min, 10 min).
    recent_windows : int
        Passed through to ``analyse_uptime``.

    Returns
    -------
    List of UptimeReport, one per window size.
    """
    if window_sizes is None:
        window_sizes = [60.0, 300.0, 600.0]
    return [
        analyse_uptime(timestamps, window_seconds=ws, recent_windows=recent_windows)
        for ws in window_sizes
    ]
