"""commit_throughput — measure commit rate over a sliding window.

While ``commit_interval`` tracks the regularity of commit spacing
and ``stall_predictor`` estimates whether the writer is dead *right
now*, this module answers a different question: **how many commits
per hour is the repo producing over a given lookback window?**

This is useful for:

- detecting gradual slowdowns (throughput trending down)
- comparing day-vs-night productivity
- feeding caretaker briefings with a single "commits/hour" number

Design
------

Given a list of commit timestamps (ISO-8601 or epoch seconds) and
a window size in seconds (default 3600 = one hour), throughput is::

    throughput = count(commits within window) / (window / 3600)

The result is commits-per-hour, normalised so that different window
sizes are comparable.

Edge cases
==========

- Empty timestamps → 0.0
- Window of zero → ValueError
- All timestamps older than window → 0.0
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Union


def _to_epoch(ts: Union[str, float, int]) -> float:
    """Convert a timestamp to epoch seconds."""
    if isinstance(ts, (int, float)):
        return float(ts)
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def commits_in_window(
    timestamps: List[Union[str, float, int]],
    now: Optional[Union[str, float, int]] = None,
    window_seconds: float = 3600.0,
) -> int:
    """Count commits falling within the trailing window.

    Parameters
    ----------
    timestamps : list
        Commit timestamps (ISO-8601 strings or epoch seconds).
    now : optional
        Reference time (defaults to current UTC time).
    window_seconds : float
        Lookback window in seconds (default 3600).

    Returns
    -------
    int
        Number of commits within [now - window, now].
    """
    if window_seconds <= 0:
        raise ValueError(f"window must be > 0, got {window_seconds}")
    if not timestamps:
        return 0

    now_epoch = _to_epoch(now) if now is not None else datetime.now(timezone.utc).timestamp()
    cutoff = now_epoch - window_seconds
    return sum(1 for ts in timestamps if _to_epoch(ts) >= cutoff)


def throughput(
    timestamps: List[Union[str, float, int]],
    now: Optional[Union[str, float, int]] = None,
    window_seconds: float = 3600.0,
) -> float:
    """Commits per hour over the trailing window.

    Parameters
    ----------
    timestamps : list
        Commit timestamps.
    now : optional
        Reference time.
    window_seconds : float
        Lookback window (default 3600).

    Returns
    -------
    float
        Commits per hour, rounded to 2 decimal places.
    """
    if window_seconds <= 0:
        raise ValueError(f"window must be > 0, got {window_seconds}")
    count = commits_in_window(timestamps, now, window_seconds)
    hours = window_seconds / 3600.0
    return round(count / hours, 2)


def throughput_trend(
    timestamps: List[Union[str, float, int]],
    now: Optional[Union[str, float, int]] = None,
    window_seconds: float = 3600.0,
    buckets: int = 4,
) -> List[float]:
    """Throughput over multiple consecutive windows (oldest → newest).

    Splits the total lookback into ``buckets`` equal sub-windows and
    returns throughput for each, from oldest to newest.

    Parameters
    ----------
    timestamps : list
        Commit timestamps.
    now : optional
        Reference time.
    window_seconds : float
        Total lookback (default 3600).
    buckets : int
        Number of sub-windows (default 4).

    Returns
    -------
    list[float]
        Per-bucket throughput values (oldest first).
    """
    if buckets < 1:
        raise ValueError(f"buckets must be >= 1, got {buckets}")
    if window_seconds <= 0:
        raise ValueError(f"window must be > 0, got {window_seconds}")

    now_epoch = _to_epoch(now) if now is not None else datetime.now(timezone.utc).timestamp()
    bucket_size = window_seconds / buckets
    result = []
    for i in range(buckets):
        bucket_end = now_epoch - (buckets - 1 - i) * bucket_size
        bucket_start = bucket_end - bucket_size
        count = sum(
            1 for ts in timestamps
            if bucket_start <= _to_epoch(ts) < bucket_end
        )
        hours = bucket_size / 3600.0
        result.append(round(count / hours, 2))
    return result


def throughput_summary(
    timestamps: List[Union[str, float, int]],
    now: Optional[Union[str, float, int]] = None,
    window_seconds: float = 3600.0,
) -> dict:
    """Compact summary for caretaker consumption.

    Returns a dict with:
      - throughput_cph: commits per hour
      - commits_in_window: raw count
      - trend: list of per-quarter throughputs
      - verdict: str (healthy / slowing / stalled)
    """
    tp = throughput(timestamps, now, window_seconds)
    count = commits_in_window(timestamps, now, window_seconds)
    trend = throughput_trend(timestamps, now, window_seconds, buckets=4)

    if tp == 0:
        verdict = "stalled"
    elif len(trend) >= 2 and trend[-1] < trend[0] * 0.5:
        verdict = "slowing"
    else:
        verdict = "healthy"

    return {
        "throughput_cph": tp,
        "commits_in_window": count,
        "window_seconds": window_seconds,
        "trend": trend,
        "verdict": verdict,
        "checked_at": (
            datetime.fromtimestamp(_to_epoch(now), tz=timezone.utc)
            if now is not None
            else datetime.now(timezone.utc)
        ).isoformat(),
    }
