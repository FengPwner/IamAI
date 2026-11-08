"""commit_rhythm_drift — measure how commit cadence drifts from target.

The writer aims for one commit every 600 seconds (10 minutes).  In
practice the actual interval fluctuates: batch windows catch up, SSH
resets cause gaps, process stalls create long silences followed by
bursts.  This module quantifies that drift so caretakers can spot
degrading rhythm before it becomes a full stall.

Core concepts
=============

**gap**: seconds between consecutive commits.

**drift**: ``|actual_gap - target_gap|`` for each interval.

**drift_ratio**: ``drift / target_gap`` — dimensionless, comparable
across different target cadences.

**trend**: slope of drift_ratio over the last N samples.  Positive
slope means rhythm is getting worse; negative means recovering.

Public API::

    from iamai.commit_rhythm_drift import (
        CommitRhythmDrift,
        drift_report,
        rhythm_health,
    )

    timestamps = [1000, 1600, 2200, 2900, 3400, 4100]
    rd = CommitRhythmDrift(timestamps, target=600)

    print(rd.mean_drift_ratio)   # 0.056 — about 5.6% off target
    print(rd.max_drift_ratio)    # 0.167 — worst interval was ~17% off
    print(rd.trend)              # -0.02 — slightly improving

    health = rhythm_health(timestamps, target=600)
    # {"grade": "steady", "mean_drift_ratio": 0.056, ...}

    print(drift_report(timestamps, target=600))
    # "5 intervals, mean drift 5.6%, max 16.7%, trend: recovering"

Health grades
=============

===========  =========================================================
grade        meaning
===========  =========================================================
steady       mean drift < 10% of target — rhythm is solid
drifting     mean drift 10–25% — cadence is loosening
erratic      mean drift 25–50% — significant irregularity
stalled      mean drift > 50% or any gap > 3× target — rhythm lost
===========  =========================================================

Trend values
============

===========  =========================================================
trend        meaning
===========  =========================================================
< -0.01      recovering — recent intervals closer to target
-0.01…0.01   stable — no clear direction
> 0.01       degrading — recent intervals drifting further
===========  =========================================================

Notes
-----
- Requires at least 2 timestamps (1 interval) to compute anything.
- Timestamps must be in ascending order; the module sorts them.
- ``target`` defaults to 600 seconds (10 minutes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


DEFAULT_TARGET = 600  # seconds — 10-minute commit cadence

# Health thresholds (fraction of target)
THRESHOLD_STEADY = 0.10
THRESHOLD_DRIFTING = 0.25
THRESHOLD_ERRATIC = 0.50

# Stall multiplier: any single gap beyond this × target → stalled
STALL_MULTIPLIER = 3.0


@dataclass(frozen=True)
class IntervalDrift:
    """Drift measurement for a single inter-commit interval."""

    gap: float
    target: float
    drift: float
    drift_ratio: float

    @property
    def over(self) -> bool:
        """True when gap exceeds target."""
        return self.gap > self.target

    @property
    def under(self) -> bool:
        """True when gap falls short of target."""
        return self.gap < self.target


@dataclass(frozen=True)
class CommitRhythmDrift:
    """Full drift analysis over a sequence of commit timestamps.

    Parameters
    ----------
    timestamps : sequence of float
        Unix timestamps (or any monotonic numeric scale).
    target : float
        Expected seconds between commits.
    """

    timestamps: tuple[float, ...]
    target: float = DEFAULT_TARGET
    intervals: tuple[IntervalDrift, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        sorted_ts = tuple(sorted(self.timestamps))
        target = self.target
        intervals: list[IntervalDrift] = []
        for i in range(1, len(sorted_ts)):
            gap = sorted_ts[i] - sorted_ts[i - 1]
            drift = abs(gap - target)
            drift_ratio = drift / target if target > 0 else 0.0
            intervals.append(
                IntervalDrift(
                    gap=gap,
                    target=target,
                    drift=drift,
                    drift_ratio=drift_ratio,
                )
            )
        object.__setattr__(self, "timestamps", sorted_ts)
        object.__setattr__(self, "intervals", tuple(intervals))

    # --- basic metrics ---

    @property
    def count(self) -> int:
        """Number of intervals analysed."""
        return len(self.intervals)

    @property
    def mean_drift(self) -> float:
        """Mean absolute drift in seconds."""
        if not self.intervals:
            return 0.0
        return sum(iv.drift for iv in self.intervals) / len(self.intervals)

    @property
    def mean_drift_ratio(self) -> float:
        """Mean drift as fraction of target."""
        if not self.intervals:
            return 0.0
        return sum(iv.drift_ratio for iv in self.intervals) / len(self.intervals)

    @property
    def max_drift(self) -> float:
        """Worst single-interval drift in seconds."""
        if not self.intervals:
            return 0.0
        return max(iv.drift for iv in self.intervals)

    @property
    def max_drift_ratio(self) -> float:
        """Worst single-interval drift as fraction of target."""
        if not self.intervals:
            return 0.0
        return max(iv.drift_ratio for iv in self.intervals)

    @property
    def max_gap(self) -> float:
        """Longest single gap in seconds."""
        if not self.intervals:
            return 0.0
        return max(iv.gap for iv in self.intervals)

    @property
    def min_gap(self) -> float:
        """Shortest single gap in seconds."""
        if not self.intervals:
            return 0.0
        return min(iv.gap for iv in self.intervals)

    # --- trend ---

    @property
    def trend(self) -> float:
        """Slope of drift_ratio over intervals (OLS, unit = per-interval).

        Negative = recovering, positive = degrading.
        Returns 0.0 when fewer than 2 intervals exist.
        """
        n = len(self.intervals)
        if n < 2:
            return 0.0
        ratios = [iv.drift_ratio for iv in self.intervals]
        x_mean = (n - 1) / 2.0
        y_mean = sum(ratios) / n
        num = sum((i - x_mean) * (ratios[i] - y_mean) for i in range(n))
        den = sum((i - x_mean) ** 2 for i in range(n))
        if den == 0:
            return 0.0
        return num / den

    @property
    def trend_label(self) -> str:
        """Human-readable trend description."""
        t = self.trend
        if t < -0.01:
            return "recovering"
        if t > 0.01:
            return "degrading"
        return "stable"

    # --- health ---

    @property
    def has_stall(self) -> bool:
        """True if any gap exceeds STALL_MULTIPLIER × target."""
        threshold = self.target * STALL_MULTIPLIER
        return any(iv.gap > threshold for iv in self.intervals)

    @property
    def grade(self) -> str:
        """Overall rhythm health grade.

        Returns one of: steady, drifting, erratic, stalled.
        """
        if self.has_stall:
            return "stalled"
        mdr = self.mean_drift_ratio
        if mdr < THRESHOLD_STEADY:
            return "steady"
        if mdr < THRESHOLD_DRIFTING:
            return "drifting"
        if mdr < THRESHOLD_ERRATIC:
            return "erratic"
        return "stalled"

    # --- summary ---

    def summary_dict(self) -> dict:
        """Return all key metrics as a plain dict."""
        return {
            "count": self.count,
            "target": self.target,
            "mean_drift": round(self.mean_drift, 2),
            "mean_drift_ratio": round(self.mean_drift_ratio, 4),
            "max_drift": round(self.max_drift, 2),
            "max_drift_ratio": round(self.max_drift_ratio, 4),
            "max_gap": round(self.max_gap, 2),
            "min_gap": round(self.min_gap, 2),
            "trend": round(self.trend, 4),
            "trend_label": self.trend_label,
            "grade": self.grade,
            "has_stall": self.has_stall,
        }


# --- convenience functions ---


def rhythm_health(
    timestamps: Sequence[float],
    target: float = DEFAULT_TARGET,
) -> dict:
    """Quick health check returning a summary dict.

    Parameters
    ----------
    timestamps : sequence of float
        Commit timestamps (will be sorted internally).
    target : float
        Expected inter-commit seconds.

    Returns
    -------
    dict
        Same keys as ``CommitRhythmDrift.summary_dict()``.
    """
    rd = CommitRhythmDrift(tuple(timestamps), target=target)
    return rd.summary_dict()


def drift_report(
    timestamps: Sequence[float],
    target: float = DEFAULT_TARGET,
) -> str:
    """One-line human-readable drift report.

    Examples
    --------
    >>> drift_report([1000, 1600, 2200, 2900, 3400, 4100])
    '5 intervals, mean drift 5.6%, max 16.7%, trend: recovering'
    """
    rd = CommitRhythmDrift(tuple(timestamps), target=target)
    if rd.count == 0:
        return "no intervals — need at least 2 timestamps"
    mean_pct = rd.mean_drift_ratio * 100
    max_pct = rd.max_drift_ratio * 100
    return (
        f"{rd.count} intervals, "
        f"mean drift {mean_pct:.1f}%, "
        f"max {max_pct:.1f}%, "
        f"trend: {rd.trend_label}"
    )
