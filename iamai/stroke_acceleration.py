"""stroke_acceleration — measure momentum in stroke production.

``cadence_adherence`` tells you *consistency*: are inter-stroke gaps
stable or erratic?  ``stall_classifier`` tells you *status*: is the
writer alive right now?  Neither tells you *direction*: is the writer
speeding up, slowing down, or holding pace?

``stroke_acceleration`` fits a linear trend to recent inter-stroke
intervals and classifies the result.

Scoring
-------
Given *n* timestamps, compute *n-1* intervals (seconds between
consecutive strokes).  Fit a simple linear regression over the most
recent *window* intervals where the x-axis is the interval index and
the y-axis is the interval duration.  The slope (seconds-per-interval)
drives classification:

| slope (s/interval)  | label          |
|---------------------|----------------|
| < -threshold        | accelerating   |
| within ±threshold   | steady         |
| > +threshold        | decelerating   |
| mean > stall_factor × expected | stalled   |

A separate **momentum** score combines velocity and consistency::

    momentum = consistency × velocity_ratio

where ``consistency = 1 - cv`` (clamped to [0, 1]) and
``velocity_ratio = expected / mean_interval`` (capped at 1.0).

Momentum near 1.0 means the writer is on-time and consistent.
Momentum near 0.0 means it is either erratic, slow, or both.

Usage::

    from iamai.stroke_acceleration import StrokeAccelerator

    accel = StrokeAccelerator(expected_cadence=15, window=20)
    result = accel.analyse(timestamps)
    print(result.label)      # "steady"
    print(result.momentum)   # 0.87
    print(result.slope)      # -0.03
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import List, Optional, Sequence

DEFAULT_EXPECTED_CADENCE = 15  # seconds
DEFAULT_WINDOW = 20            # number of recent intervals to analyse
DEFAULT_THRESHOLD = 0.5        # s/interval to distinguish steady from trend
DEFAULT_STALL_FACTOR = 4.0     # mean interval > this × expected → stalled


@dataclass(frozen=True)
class AccelerationResult:
    """Outcome of a single acceleration analysis."""

    label: str                 # accelerating | steady | decelerating | stalled
    slope: float               # linear-regression slope (s per interval)
    momentum: float            # 0.0–1.0 composite score
    mean_interval: float       # mean of analysed intervals (seconds)
    median_interval: float     # median (robust to outlier stalls)
    jitter: float              # coefficient of variation (stddev / mean)
    n_intervals: int           # how many intervals were analysed

    @property
    def is_healthy(self) -> bool:
        return self.label in ("steady", "accelerating") and self.momentum >= 0.5


def _compute_intervals(timestamps: Sequence[float]) -> List[float]:
    """Return sorted-ascending inter-stroke intervals in seconds.

    Timestamps need not be pre-sorted; they are sorted before diffing.
    """
    if len(timestamps) < 2:
        return []
    ts = sorted(timestamps)
    return [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]


def _linear_slope(values: Sequence[float]) -> float:
    """Ordinary-least-squares slope over y=values, x=0..len-1.

    Returns 0.0 when fewer than two data points or when all x are
    identical (degenerate case).
    """
    n = len(values)
    if n < 2:
        return 0.0
    # x = 0, 1, ..., n-1  →  mean_x = (n-1)/2
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    num = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    if den == 0.0:
        return 0.0
    return num / den


def _coefficient_of_variation(values: Sequence[float]) -> float:
    """CV = stddev / mean.  Returns 0.0 for empty or zero-mean input."""
    if len(values) < 2:
        return 0.0
    m = statistics.mean(values)
    if m == 0.0:
        return 0.0
    return statistics.stdev(values) / m


class StrokeAccelerator:
    """Analyse stroke-production momentum from raw timestamps.

    Parameters
    ----------
    expected_cadence : float
        Nominal seconds between strokes (default 15).
    window : int
        How many of the most recent intervals to analyse (default 20).
    threshold : float
        Slope magnitude below which the label is "steady" (default 0.5).
    stall_factor : float
        If mean interval exceeds ``stall_factor × expected_cadence``,
        the label is forced to "stalled" regardless of slope.
    """

    def __init__(
        self,
        expected_cadence: float = DEFAULT_EXPECTED_CADENCE,
        window: int = DEFAULT_WINDOW,
        threshold: float = DEFAULT_THRESHOLD,
        stall_factor: float = DEFAULT_STALL_FACTOR,
    ) -> None:
        if expected_cadence <= 0:
            raise ValueError("expected_cadence must be positive")
        if window < 1:
            raise ValueError("window must be >= 1")
        if threshold < 0:
            raise ValueError("threshold must be non-negative")
        if stall_factor <= 0:
            raise ValueError("stall_factor must be positive")
        self.expected_cadence = expected_cadence
        self.window = window
        self.threshold = threshold
        self.stall_factor = stall_factor

    def analyse(self, timestamps: Sequence[float]) -> AccelerationResult:
        """Compute acceleration result for a series of epoch timestamps.

        Parameters
        ----------
        timestamps : sequence of float
            Unix-epoch timestamps of stroke production events.

        Returns
        -------
        AccelerationResult

        Raises
        ------
        ValueError
            If fewer than 2 timestamps are provided.
        """
        if len(timestamps) < 2:
            raise ValueError("Need at least 2 timestamps to compute acceleration")

        all_intervals = _compute_intervals(timestamps)
        # Take only the most recent `window` intervals
        intervals = all_intervals[-self.window:]
        n = len(intervals)

        slope = _linear_slope(intervals)
        mean_iv = statistics.mean(intervals)
        median_iv = statistics.median(intervals)
        jitter = _coefficient_of_variation(intervals)

        # Classify
        if mean_iv > self.stall_factor * self.expected_cadence:
            label = "stalled"
        elif slope < -self.threshold:
            label = "accelerating"
        elif slope > self.threshold:
            label = "decelerating"
        else:
            label = "steady"

        # Momentum: consistency × velocity_ratio, both in [0, 1]
        consistency = max(0.0, 1.0 - jitter)
        velocity_ratio = min(1.0, self.expected_cadence / mean_iv) if mean_iv > 0 else 1.0
        momentum = consistency * velocity_ratio

        return AccelerationResult(
            label=label,
            slope=round(slope, 4),
            momentum=round(momentum, 4),
            mean_interval=round(mean_iv, 2),
            median_interval=round(median_iv, 2),
            jitter=round(jitter, 4),
            n_intervals=n,
        )


def acceleration_summary(
    timestamps: Sequence[float],
    expected_cadence: float = DEFAULT_EXPECTED_CADENCE,
    window: int = DEFAULT_WINDOW,
) -> str:
    """One-line human-readable summary suitable for caretaker logs.

    Example output::

        stroke_accel: steady, momentum 0.87, mean 16.2s, jitter 0.12 (20 intervals)
    """
    accel = StrokeAccelerator(expected_cadence=expected_cadence, window=window)
    r = accel.analyse(timestamps)
    return (
        f"stroke_accel: {r.label}, momentum {r.momentum:.2f}, "
        f"mean {r.mean_interval:.1f}s, jitter {r.jitter:.2f} "
        f"({r.n_intervals} intervals)"
    )
