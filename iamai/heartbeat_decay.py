"""Heartbeat decay — is the writer slowing down or about to stall?

Each stroke the writer produces carries a timestamp.  In a healthy run the
intervals between strokes are roughly uniform (e.g. every ~200 s).  When the
process is starved, rate-limited, or about to crash, intervals stretch.

This module detects that *decay* early so the caretaker can intervene before
a full stall.

Core metrics
~~~~~~~~~~~~

- **decay_score**: ratio of recent mean interval to baseline mean interval.
  ``1.0`` = steady, ``> 1.0`` = slowing down, ``< 1.0`` = speeding up.
- **acceleration**: second derivative — is the decay itself getting worse?
  Positive = decelerating further, negative = recovering.
- **max_gap_ratio**: largest single gap as a multiple of the baseline.
  Spikes indicate one-off hiccups; sustained high values indicate systemic
  issues.
- **verdict**: human-readable classification:
  ``"steady"`` | ``"drifting"`` | ``"slowing"`` | ``"stalling"``

Usage::

    from iamai.heartbeat_decay import HeartbeatMonitor

    monitor = HeartbeatMonitor(baseline_interval=200, window=12)
    report = monitor.analyse(timestamps)
    print(report["verdict"])   # "steady"
    print(report["decay_score"])  # 1.02
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union


# Verdict thresholds — (lower_exclusive, label)
_VERDICT_BANDS = [
    (2.0, "stalling"),
    (1.4, "slowing"),
    (1.15, "drifting"),
]


def _to_epoch(ts: Union[str, float, datetime]) -> float:
    """Convert a timestamp to a UNIX epoch float."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, datetime):
        return ts.timestamp()
    # ISO-8601 string
    s = ts
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).timestamp()


def intervals(timestamps: List[Union[str, float, datetime]]) -> List[float]:
    """Return consecutive intervals (seconds) from a sorted timestamp list.

    The input is sorted internally so callers can pass timestamps in any order.
    Returns an empty list if fewer than 2 timestamps are given.
    """
    if len(timestamps) < 2:
        return []
    epochs = sorted(_to_epoch(t) for t in timestamps)
    return [epochs[i + 1] - epochs[i] for i in range(len(epochs) - 1)]


def mean_interval(
    timestamps: List[Union[str, float, datetime]],
    window: Optional[int] = None,
) -> float:
    """Mean interval over the last *window* intervals (or all if ``None``).

    Returns 0.0 if fewer than 2 timestamps exist.
    """
    ivs = intervals(timestamps)
    if not ivs:
        return 0.0
    if window is not None and window > 0:
        ivs = ivs[-window:]
    return sum(ivs) / len(ivs)


def decay_score(
    timestamps: List[Union[str, float, datetime]],
    baseline: float,
    window: int = 12,
) -> float:
    """Ratio of recent mean interval to *baseline*.

    A score of 1.0 means the writer is keeping perfect pace.
    Above 1.0 means it is slowing; below 1.0 means it is running faster than
    the baseline.

    Returns 0.0 if the baseline is zero or fewer than 2 timestamps exist.
    """
    if baseline <= 0:
        return 0.0
    recent_mean = mean_interval(timestamps, window)
    if recent_mean == 0.0:
        return 0.0
    return recent_mean / baseline


def acceleration(
    timestamps: List[Union[str, float, datetime]],
    window: int = 12,
) -> Optional[float]:
    """Second derivative: is the interval itself growing or shrinking?

    Computed as the difference between the mean of the *second half* and the
    *first half* of the last ``2 * window`` intervals.  Positive means the
    writer is decelerating further; negative means it is recovering.

    Returns ``None`` if fewer than ``2 * window`` intervals exist.
    """
    ivs = intervals(timestamps)
    needed = 2 * window
    if len(ivs) < needed:
        return None
    recent = ivs[-needed:]
    half = len(recent) // 2
    first_half = sum(recent[:half]) / half
    second_half = sum(recent[half:]) / (len(recent) - half)
    return second_half - first_half


def max_gap_ratio(
    timestamps: List[Union[str, float, datetime]],
    baseline: float,
    window: int = 20,
) -> float:
    """Largest single gap as a multiple of *baseline*.

    Returns 0.0 if baseline is zero or fewer than 2 timestamps exist.
    """
    if baseline <= 0:
        return 0.0
    ivs = intervals(timestamps)
    if not ivs:
        return 0.0
    recent = ivs[-window:]
    return max(recent) / baseline


def verdict(score: float) -> str:
    """Classify a decay score into a human-readable verdict.

    >>> verdict(1.0)
    'steady'
    >>> verdict(1.1)
    'steady'
    >>> verdict(1.2)
    'drifting'
    >>> verdict(1.5)
    'slowing'
    >>> verdict(2.5)
    'stalling'
    """
    for threshold, label in _VERDICT_BANDS:
        if score >= threshold:
            return label
    return "steady"


class HeartbeatMonitor:
    """Stateful analyser for writer heartbeat health."""

    def __init__(self, baseline_interval: float = 200.0, window: int = 12):
        """
        Parameters
        ----------
        baseline_interval:
            Expected seconds between strokes under normal operation.
        window:
            Number of recent intervals to consider for the decay score.
        """
        self.baseline_interval = baseline_interval
        self.window = window

    def analyse(
        self, timestamps: List[Union[str, float, datetime]]
    ) -> Dict[str, Any]:
        """Return a comprehensive heartbeat-decay report.

        Keys:
            decay_score, acceleration, max_gap_ratio, verdict,
            mean_interval, sample_count, baseline
        """
        score = decay_score(timestamps, self.baseline_interval, self.window)
        accel = acceleration(timestamps, self.window)
        mgr = max_gap_ratio(timestamps, self.baseline_interval)
        mi = mean_interval(timestamps, self.window)
        return {
            "decay_score": round(score, 4),
            "acceleration": round(accel, 4) if accel is not None else None,
            "max_gap_ratio": round(mgr, 4),
            "verdict": verdict(score),
            "mean_interval": round(mi, 2),
            "sample_count": len(timestamps),
            "baseline": self.baseline_interval,
        }
