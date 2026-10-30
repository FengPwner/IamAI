"""Restart cost analyser — measure what each process restart actually costs.

Every restart means a window of silence: no strokes produced, no commits
flowing, the garden frozen.  This module quantifies that cost so caretakers
can answer: "is this restart worth it?" and "how long until the writer
catches up?"

Metrics computed:
- silence_gap: seconds between the last stroke before restart and the
  first stroke after restart (the "dead zone")
- catchup_time: seconds from restart until the writer resumes its normal
  cadence (inter-stroke interval returns to baseline)
- strokes_lost: estimated number of strokes the writer *would* have
  produced during the silence gap, given its baseline cadence
- recovery_ratio: (strokes produced in first post-restart window) /
  (strokes expected in that window) — >1.0 means the writer is
  sprinting to catch up, <1.0 means it is still warming up

Usage::

    from iamai.restart_cost import analyse_restart

    # timestamps are epoch floats
    pre_strokes = [1729400000, 1729400900, 1729401800]  # last 3 before gap
    post_strokes = [1729403600, 1729403700, 1729403800]  # first 3 after gap
    restart_ts = 1729403500

    report = analyse_restart(pre_strokes, post_strokes, restart_ts)
    print(report["silence_gap"])    # seconds
    print(report["strokes_lost"])   # estimated
    print(report["recovery_ratio"]) # 1.0 = normal pace
"""

from __future__ import annotations

from typing import List, Optional


def _baseline_cadence(timestamps: List[float], sample: int = 5) -> float:
    """Return the median inter-stroke interval from the last *sample* strokes.

    Returns seconds per stroke.  Empty or single-element lists return 0.
    """
    if len(timestamps) < 2:
        return 0.0
    recent = sorted(timestamps)[-sample - 1:]
    intervals = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
    intervals.sort()
    mid = len(intervals) // 2
    if len(intervals) % 2 == 0:
        return (intervals[mid - 1] + intervals[mid]) / 2.0
    return float(intervals[mid])


def silence_gap(
    last_pre: Optional[float],
    first_post: Optional[float],
) -> float:
    """Seconds between last pre-restart stroke and first post-restart stroke.

    Returns 0.0 if either side is missing (cannot measure a gap with one end).
    """
    if last_pre is None or first_post is None:
        return 0.0
    return max(0.0, first_post - last_pre)


def strokes_lost(gap_seconds: float, cadence_seconds: float) -> float:
    """Estimated strokes the writer would have produced during the gap.

    Returns 0.0 if cadence is zero (no baseline to project from).
    """
    if cadence_seconds <= 0:
        return 0.0
    return gap_seconds / cadence_seconds


def recovery_ratio(
    post_timestamps: List[float],
    window_seconds: float,
    cadence_seconds: float,
) -> float:
    """How fast the writer is producing post-restart relative to baseline.

    Counts strokes in the first *window_seconds* after restart, compares
    to how many baseline cadence would predict.  Returns 0.0 if there is
    no baseline or no window.
    """
    if cadence_seconds <= 0 or window_seconds <= 0 or not post_timestamps:
        return 0.0
    start = post_timestamps[0]
    cutoff = start + window_seconds
    actual = sum(1 for t in post_timestamps if start <= t <= cutoff)
    expected = window_seconds / cadence_seconds
    if expected <= 0:
        return 0.0
    return actual / expected


def catchup_time(
    post_timestamps: List[float],
    cadence_seconds: float,
    tolerance: float = 1.5,
) -> float:
    """Seconds from first post-restart stroke until cadence returns to baseline.

    Scans inter-stroke intervals; the first interval that falls within
    *tolerance* × baseline is considered "caught up."  Returns the elapsed
    time from the first post-restart stroke to that point.

    Returns 0.0 if the writer never catches up within the available data,
    or if there is no baseline.
    """
    if cadence_seconds <= 0 or len(post_timestamps) < 2:
        return 0.0
    threshold = cadence_seconds * tolerance
    ts = sorted(post_timestamps)
    for i in range(1, len(ts)):
        interval = ts[i] - ts[i - 1]
        if 0 < interval <= threshold:
            return ts[i] - ts[0]
    return 0.0  # never caught up


def analyse_restart(
    pre_timestamps: List[float],
    post_timestamps: List[float],
    restart_ts: float,
    recovery_window: float = 3600.0,
) -> dict:
    """Full restart-cost report.

    Parameters
    ----------
    pre_timestamps : list[float]
        Epoch timestamps of the last N strokes before the restart.
    post_timestamps : list[float]
        Epoch timestamps of strokes produced after the restart.
    restart_ts : float
        Epoch timestamp of when the restart was initiated.
    recovery_window : float
        How many seconds after the first post-restart stroke to measure
        recovery (default 3600 = one hour).

    Returns
    -------
    dict with keys:
        silence_gap, catchup_time, strokes_lost, recovery_ratio,
        baseline_cadence, last_pre, first_post
    """
    pre_sorted = sorted(pre_timestamps) if pre_timestamps else []
    post_sorted = sorted(post_timestamps) if post_timestamps else []

    last_pre = pre_sorted[-1] if pre_sorted else None
    first_post = post_sorted[0] if post_sorted else None

    cadence = _baseline_cadence(pre_sorted)
    gap = silence_gap(last_pre, first_post)
    lost = strokes_lost(gap, cadence)
    recov = recovery_ratio(post_sorted, recovery_window, cadence)
    catchup = catchup_time(post_sorted, cadence)

    return {
        "silence_gap": round(gap, 1),
        "catchup_time": round(catchup, 1),
        "strokes_lost": round(lost, 1),
        "recovery_ratio": round(recov, 2),
        "baseline_cadence": round(cadence, 1),
        "last_pre": last_pre,
        "first_post": first_post,
    }
