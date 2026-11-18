#!/usr/bin/env python3
"""vitality_trend — track vitality index scores over time and detect trends.

The ``repo_vitality_index`` module answers "how healthy is the repo *right
now*?"  This module answers the complementary question: "is the repo
getting healthier or sicker over time?"

It stores timestamped vitality snapshots and derives:

===================  =======================================================
metric               meaning
===================  =======================================================
direction            ``improving`` / ``stable`` / ``declining``
velocity             rate of change in vitality points per hour
inflection_points    timestamps where direction reversed
forecast             next-expected vitality score (linear extrapolation)
window_stats         min, max, mean, std over a trailing window
===================  =======================================================

Direction is classified from the slope of a least-squares linear fit
over the trailing ``window`` snapshots:

=======================  ========================
slope (pts/hr)           direction
=======================  ========================
> +2.0                   ``improving``
-2.0 … +2.0             ``stable``
< -2.0                   ``declining``
=======================  ========================

An *inflection point* is recorded whenever the direction flips between
consecutive assessments.

Usage::

    from iamai.vitality_trend import VitalityTrend

    trend = VitalityTrend()
    trend.add(85.0)  # uses current time
    trend.add(72.0, at="2026-11-19T03:00:00+00:00")
    report = trend.assess()
    print(report.direction, report.velocity)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ts(raw: str) -> float:
    """Parse an ISO-8601 timestamp string to epoch seconds."""
    if not raw:
        return 0.0
    s = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


def _linear_fit(points: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """Ordinary least-squares fit: returns (slope, intercept).

    ``points`` is a sequence of (x, y) pairs.  If fewer than two distinct
    x-values are present the slope is 0 and the intercept is the mean y.
    """
    n = len(points)
    if n == 0:
        return (0.0, 0.0)
    if n == 1:
        return (0.0, points[0][1])

    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)

    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        return (0.0, sy / n)

    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return (slope, intercept)


# ---------------------------------------------------------------------------
# Snapshot dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VitalitySnapshot:
    """One timestamped vitality score."""
    epoch: float
    score: float

    def to_dict(self) -> dict:
        return {"epoch": self.epoch, "score": self.score}


# ---------------------------------------------------------------------------
# Trend report
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrendReport:
    """Result of a trend assessment."""
    direction: str           # improving | stable | declining
    velocity: float          # pts per hour
    slope_raw: float         # pts per second (internal)
    forecast: float          # predicted next score
    inflection_points: List[float] = field(default_factory=list)
    window_min: float = 0.0
    window_max: float = 0.0
    window_mean: float = 0.0
    window_std: float = 0.0
    n_snapshots: int = 0

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "velocity_pts_per_hour": round(self.velocity, 4),
            "slope_raw_pts_per_sec": round(self.slope_raw, 8),
            "forecast": round(self.forecast, 2),
            "inflection_points": self.inflection_points,
            "window": {
                "min": round(self.window_min, 2),
                "max": round(self.window_max, 2),
                "mean": round(self.window_mean, 2),
                "std": round(self.window_std, 2),
            },
            "n_snapshots": self.n_snapshots,
        }


# ---------------------------------------------------------------------------
# Direction threshold
# ---------------------------------------------------------------------------

_IMPROVING_THRESHOLD = 2.0  # pts/hr above which we say "improving"
_DECLINING_THRESHOLD = -2.0  # pts/hr below which we say "declining"


def _classify_direction(velocity_pts_per_hour: float) -> str:
    if velocity_pts_per_hour > _IMPROVING_THRESHOLD:
        return "improving"
    if velocity_pts_per_hour < _DECLINING_THRESHOLD:
        return "declining"
    return "stable"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class VitalityTrend:
    """Accumulates vitality snapshots and assesses trends."""

    def __init__(self, window: int = 20) -> None:
        """
        Parameters
        ----------
        window : int
            Number of trailing snapshots used for trend assessment.
            Must be ≥ 2.
        """
        if window < 2:
            raise ValueError("window must be >= 2")
        self._window = window
        self._snapshots: List[VitalitySnapshot] = []
        self._prev_direction: Optional[str] = None

    @property
    def window(self) -> int:
        return self._window

    @property
    def snapshots(self) -> List[VitalitySnapshot]:
        return list(self._snapshots)

    def add(
        self,
        score: float,
        at: Optional[str] = None,
    ) -> VitalitySnapshot:
        """Record a vitality snapshot.

        Parameters
        ----------
        score : float
            Vitality score (0–100).  Clamped to [0, 100].
        at : str or None
            ISO-8601 timestamp.  If ``None``, uses current UTC time.
        """
        clamped = max(0.0, min(100.0, float(score)))
        epoch = _parse_ts(at) if at else _now_epoch()
        snap = VitalitySnapshot(epoch=epoch, score=clamped)
        self._snapshots.append(snap)
        return snap

    def assess(self) -> TrendReport:
        """Compute the trend over the trailing ``window`` snapshots.

        Returns
        -------
        TrendReport
            Always returns a report, even if no snapshots are available
            (all values default to zero / "stable").
        """
        if len(self._snapshots) < 2:
            return TrendReport(
                direction="stable",
                velocity=0.0,
                slope_raw=0.0,
                forecast=self._snapshots[0].score if self._snapshots else 0.0,
                n_snapshots=len(self._snapshots),
            )

        trailing = self._snapshots[-self._window:]
        n = len(trailing)

        # Build (x, y) pairs where x = seconds since first snapshot
        t0 = trailing[0].epoch
        points = [(s.epoch - t0, s.score) for s in trailing]

        slope, intercept = _linear_fit(points)
        velocity_hr = slope * 3600.0
        direction = _classify_direction(velocity_hr)

        # Forecast: predict score at the next expected snapshot interval
        if n >= 2:
            avg_interval = (trailing[-1].epoch - trailing[0].epoch) / (n - 1)
        else:
            avg_interval = 300.0  # 5-min default
        next_x = trailing[-1].epoch - t0 + avg_interval
        forecast = slope * next_x + intercept
        forecast = max(0.0, min(100.0, forecast))

        # Inflection points: direction flips between consecutive pairs
        inflections: List[float] = []
        if n >= 3:
            for i in range(2, n):
                sub_points = [(trailing[j].epoch - t0, trailing[j].score)
                              for j in range(i - 1, i + 1)]
                sub_slope, _ = _linear_fit(sub_points)
                sub_vel = sub_slope * 3600.0
                sub_dir = _classify_direction(sub_vel)
                if i >= 3:
                    prev_points = [(trailing[j].epoch - t0, trailing[j].score)
                                   for j in range(i - 2, i)]
                    prev_slope, _ = _linear_fit(prev_points)
                    prev_vel = prev_slope * 3600.0
                    prev_dir = _classify_direction(prev_vel)
                    if prev_dir != sub_dir:
                        inflections.append(trailing[i].epoch)

        # Window statistics
        scores = [s.score for s in trailing]
        w_min = min(scores)
        w_max = max(scores)
        w_mean = sum(scores) / n
        if n > 1:
            variance = sum((s - w_mean) ** 2 for s in scores) / (n - 1)
            w_std = math.sqrt(variance)
        else:
            w_std = 0.0

        self._prev_direction = direction

        return TrendReport(
            direction=direction,
            velocity=velocity_hr,
            slope_raw=slope,
            forecast=forecast,
            inflection_points=inflections,
            window_min=w_min,
            window_max=w_max,
            window_mean=w_mean,
            window_std=w_std,
            n_snapshots=n,
        )

    def clear(self) -> None:
        """Remove all snapshots."""
        self._snapshots.clear()
        self._prev_direction = None
