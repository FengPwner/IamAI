"""stroke_stall_indicator — leading indicator for impending writer stalls.

``stall_predictor`` works at the *commit* level: it measures elapsed
time since the last commit and compares it to recent commit intervals.
By the time it fires, the writer has already been silent for a full
commit cycle.

``stroke_stall_indicator`` operates one level deeper — at the *stroke*
level.  It detects the subtle degradation patterns that precede a full
stall: cadence drift, rising jitter, and deceleration.  When the score
is high, the writer is *about to* stall, not stalled yet.

Signals
-------

Three independent signals are computed from recent inter-stroke
intervals and combined into a single 0–1 risk score:

1. **cadence_ratio** — how far the mean interval has drifted from the
   expected cadence.  ``ratio = mean / expected``; when ratio > 1 the
   writer is slowing down.  Signal = ``clamp((ratio - 1) / (max_ratio - 1), 0, 1)``.

2. **acceleration_signal** — from the linear slope of recent intervals.
   Positive slope means decelerating (intervals growing).
   Signal = ``clamp(slope / max_slope, 0, 1)`` (only positive slope contributes).

3. **jitter_signal** — coefficient of variation.  High CV means erratic
   production, often a precursor to stalls.
   Signal = ``clamp((cv - min_cv) / (max_cv - min_cv), 0, 1)``.

Final score::

    score = w_cadence * cadence_signal
          + w_accel   * accel_signal
          + w_jitter  * jitter_signal

Weights default to (0.50, 0.30, 0.20) — cadence drift is the strongest
single predictor, followed by deceleration, then jitter.

Tiers
=====

==========  =============================================
tier        meaning
==========  =============================================
healthy     score < 0.25 — within normal parameters
watchful    0.25–0.50 — slight degradation, monitor
warning     0.50–0.75 — significant drift, intervention likely needed
critical    >= 0.75 — stall imminent or already happening
==========  =============================================

Usage::

    from iamai.stroke_stall_indicator import StrokeStallIndicator

    ind = StrokeStallIndicator(expected_cadence=15)
    result = ind.analyse(timestamps)
    print(result.score)   # 0.38
    print(result.tier)    # "watchful"
    print(result.signals) # {'cadence': 0.20, 'acceleration': 0.45, 'jitter': 0.60}
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

# Default parameters
DEFAULT_EXPECTED_CADENCE = 15  # seconds between strokes
DEFAULT_WINDOW = 20            # number of recent intervals to analyse
DEFAULT_MAX_RATIO = 4.0        # cadence ratio at which signal saturates
DEFAULT_MAX_SLOPE = 5.0        # slope (s/interval) at which accel signal saturates
DEFAULT_MIN_CV = 0.1           # CV below which jitter signal is 0
DEFAULT_MAX_CV = 1.0           # CV at which jitter signal saturates

# Signal weights
DEFAULT_W_CADENCE = 0.50
DEFAULT_W_ACCEL = 0.30
DEFAULT_W_JITTER = 0.20

# Tier thresholds
_TIER_THRESHOLDS: list[tuple[float, str]] = [
    (0.25, "healthy"),
    (0.50, "watchful"),
    (0.75, "warning"),
]
_TIER_CRITICAL = "critical"


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


def _classify(score: float) -> str:
    """Return the tier label for a given score."""
    for threshold, label in _TIER_THRESHOLDS:
        if score < threshold:
            return label
    return _TIER_CRITICAL


@dataclass(frozen=True)
class StallIndicatorResult:
    """Outcome of a single stall-indicator analysis."""

    score: float                          # 0.0–1.0 composite risk score
    tier: str                             # healthy | watchful | warning | critical
    signals: Dict[str, float] = field(default_factory=dict)  # individual signal values
    mean_interval: float = 0.0            # mean of analysed intervals
    n_intervals: int = 0                  # how many intervals were analysed

    @property
    def is_healthy(self) -> bool:
        return self.tier == "healthy"

    @property
    def needs_attention(self) -> bool:
        return self.tier in ("warning", "critical")


class StrokeStallIndicator:
    """Leading indicator for writer stalls based on stroke-level data.

    Parameters
    ----------
    expected_cadence : float
        Nominal seconds between strokes (default 15).
    window : int
        How many of the most recent intervals to analyse (default 20).
    max_ratio : float
        Cadence ratio (mean/expected) at which signal saturates to 1.0.
    max_slope : float
        Positive slope (s/interval) at which acceleration signal saturates.
    min_cv : float
        CV below which jitter signal is 0.
    max_cv : float
        CV at which jitter signal saturates to 1.0.
    w_cadence : float
        Weight for cadence signal (default 0.50).
    w_accel : float
        Weight for acceleration signal (default 0.30).
    w_jitter : float
        Weight for jitter signal (default 0.20).
    """

    def __init__(
        self,
        expected_cadence: float = DEFAULT_EXPECTED_CADENCE,
        window: int = DEFAULT_WINDOW,
        max_ratio: float = DEFAULT_MAX_RATIO,
        max_slope: float = DEFAULT_MAX_SLOPE,
        min_cv: float = DEFAULT_MIN_CV,
        max_cv: float = DEFAULT_MAX_CV,
        w_cadence: float = DEFAULT_W_CADENCE,
        w_accel: float = DEFAULT_W_ACCEL,
        w_jitter: float = DEFAULT_W_JITTER,
    ) -> None:
        if expected_cadence <= 0:
            raise ValueError("expected_cadence must be positive")
        if window < 2:
            raise ValueError("window must be >= 2")
        if max_ratio <= 1.0:
            raise ValueError("max_ratio must be > 1.0")
        if max_slope <= 0:
            raise ValueError("max_slope must be positive")
        if min_cv < 0:
            raise ValueError("min_cv must be non-negative")
        if max_cv <= min_cv:
            raise ValueError("max_cv must be > min_cv")
        # Weights should sum to ~1.0 but we don't enforce strictly
        if w_cadence < 0 or w_accel < 0 or w_jitter < 0:
            raise ValueError("weights must be non-negative")

        self.expected_cadence = expected_cadence
        self.window = window
        self.max_ratio = max_ratio
        self.max_slope = max_slope
        self.min_cv = min_cv
        self.max_cv = max_cv
        self.w_cadence = w_cadence
        self.w_accel = w_accel
        self.w_jitter = w_jitter

    def analyse(self, timestamps: Sequence[float]) -> StallIndicatorResult:
        """Compute stall indicator score from stroke timestamps.

        Parameters
        ----------
        timestamps : sequence of float
            Unix-epoch timestamps of stroke production events.

        Returns
        -------
        StallIndicatorResult

        Raises
        ------
        ValueError
            If fewer than 3 timestamps are provided.
        """
        if len(timestamps) < 3:
            raise ValueError("Need at least 3 timestamps to compute stall indicator")

        # Compute intervals
        ts = sorted(timestamps)
        all_intervals = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
        intervals = all_intervals[-self.window:]
        n = len(intervals)

        mean_iv = statistics.mean(intervals)

        # Signal 1: cadence ratio
        ratio = mean_iv / self.expected_cadence
        cadence_signal = _clamp(
            (ratio - 1.0) / (self.max_ratio - 1.0), 0.0, 1.0
        )

        # Signal 2: acceleration (positive slope = decelerating)
        slope = self._linear_slope(intervals)
        accel_signal = _clamp(slope / self.max_slope, 0.0, 1.0)

        # Signal 3: jitter (CV)
        cv = self._cv(intervals)
        if self.max_cv > self.min_cv:
            jitter_signal = _clamp(
                (cv - self.min_cv) / (self.max_cv - self.min_cv), 0.0, 1.0
            )
        else:
            jitter_signal = 0.0

        # Combined score
        score = (
            self.w_cadence * cadence_signal
            + self.w_accel * accel_signal
            + self.w_jitter * jitter_signal
        )
        score = round(score, 4)

        return StallIndicatorResult(
            score=score,
            tier=_classify(score),
            signals={
                "cadence": round(cadence_signal, 4),
                "acceleration": round(accel_signal, 4),
                "jitter": round(jitter_signal, 4),
            },
            mean_interval=round(mean_iv, 2),
            n_intervals=n,
        )

    @staticmethod
    def _linear_slope(values: Sequence[float]) -> float:
        """OLS slope over y=values, x=0..len-1."""
        n = len(values)
        if n < 2:
            return 0.0
        mean_x = (n - 1) / 2.0
        mean_y = sum(values) / n
        num = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(values))
        den = sum((i - mean_x) ** 2 for i in range(n))
        if den == 0.0:
            return 0.0
        return num / den

    @staticmethod
    def _cv(values: Sequence[float]) -> float:
        """Coefficient of variation = stdev / mean."""
        if len(values) < 2:
            return 0.0
        m = statistics.mean(values)
        if m == 0.0:
            return 0.0
        return statistics.stdev(values) / m


def stall_indicator_summary(
    timestamps: Sequence[float],
    expected_cadence: float = DEFAULT_EXPECTED_CADENCE,
    window: int = DEFAULT_WINDOW,
) -> str:
    """One-line summary suitable for caretaker logs.

    Example output::

        stall_indicator: 0.38 watchful (cadence 0.20, accel 0.45, jitter 0.60) — 20 intervals
    """
    ind = StrokeStallIndicator(expected_cadence=expected_cadence, window=window)
    r = ind.analyse(timestamps)
    sig = r.signals
    return (
        f"stall_indicator: {r.score:.2f} {r.tier} "
        f"(cadence {sig['cadence']:.2f}, accel {sig['acceleration']:.2f}, "
        f"jitter {sig['jitter']:.2f}) — {r.n_intervals} intervals"
    )
