"""restart_warmup_tracker — measure post-restart cadence recovery time.

After a process restart the writer doesn't instantly reach its target
cadence.  There is a warm-up period: module imports, file I/O setup,
git index hydration, and the first few strokes finding their rhythm.

This module quantifies that warm-up.  Given a list of stroke timestamps
and a *restart epoch* (the moment the writer came back online), it
measures:

- **warmup_s**: seconds from restart until the rolling median gap
  stabilises within ``tolerance`` of the expected cadence.
- **first_stroke_latency_s**: time from restart to the first stroke.
- **warmup_strokes**: how many strokes were written before the cadence
  settled.
- **warmup_grade**: a human-readable label:
  ``INSTANT`` (< 30 s), ``QUICK`` (< 2 min), ``GRADUAL`` (< 5 min),
  ``SLOW`` (>= 5 min), or ``UNSETTLED`` (never stabilised in the
  observation window).

Public API::

    from iamai.restart_warmup_tracker import (
        RestartWarmupTracker, WarmupReport, warmup_check,
    )

    tracker = RestartWarmupTracker(expected_cadence_s=15)
    report = tracker.measure(restart_epoch, timestamps)

    print(report.warmup_s)            # 47.3
    print(report.warmup_grade)        # 'QUICK'
    print(report.first_stroke_latency_s)  # 3.1

    # convenience one-liner
    report = warmup_check(restart_epoch, timestamps, expected_cadence_s=15)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Grade thresholds (seconds)
# ---------------------------------------------------------------------------

_INSTANT_S = 30.0
_QUICK_S = 120.0
_GRADUAL_S = 300.0

_GRADE_LABELS = [
    (_INSTANT_S, "INSTANT"),
    (_QUICK_S, "QUICK"),
    (_GRADUAL_S, "GRADUAL"),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WarmupReport:
    """Result of a warm-up measurement."""

    restart_epoch: float
    expected_cadence_s: float
    tolerance: float
    window_size: int

    first_stroke_latency_s: float
    warmup_s: Optional[float]
    warmup_strokes: int
    settled: bool
    total_strokes_observed: int

    @property
    def warmup_grade(self) -> str:
        if not self.settled:
            return "UNSETTLED"
        for threshold, label in _GRADE_LABELS:
            if self.warmup_s < threshold:
                return label
        return "SLOW"

    @property
    def efficiency(self) -> float:
        """Ratio of ideal warmup (window_size * expected_cadence_s) to actual.

        1.0 = settled in exactly the minimum number of strokes.
        >1.0 = took longer than the theoretical minimum.
        Clamped to [0, 1] for display convenience.
        """
        if not self.settled or self.warmup_s <= 0:
            return 0.0
        ideal = self.window_size * self.expected_cadence_s
        return min(1.0, ideal / self.warmup_s)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _classify(warmup_s: Optional[float], settled: bool) -> str:
    """Map a warmup duration to a grade label."""
    if not settled or warmup_s is None:
        return "UNSETTLED"
    for threshold, label in _GRADE_LABELS:
        if warmup_s < threshold:
            return label
    return "SLOW"


class RestartWarmupTracker:
    """Measure how quickly a writer reaches stable cadence after restart."""

    def __init__(
        self,
        expected_cadence_s: float = 15.0,
        tolerance: float = 0.25,
        window_size: int = 5,
    ) -> None:
        """
        Parameters
        ----------
        expected_cadence_s:
            Target inter-stroke gap in seconds (default 15).
        tolerance:
            Fractional tolerance around *expected_cadence_s*.  The rolling
            median must land in
            ``[expected * (1-tol), expected * (1+tol)]`` to count as settled.
        window_size:
            Number of consecutive gaps used for the rolling median.
        """
        if expected_cadence_s <= 0:
            raise ValueError("expected_cadence_s must be positive")
        if not (0 < tolerance < 1):
            raise ValueError("tolerance must be in (0, 1)")
        if window_size < 2:
            raise ValueError("window_size must be >= 2")

        self.expected_cadence_s = expected_cadence_s
        self.tolerance = tolerance
        self.window_size = window_size

    def measure(
        self,
        restart_epoch: float,
        timestamps: Sequence[float],
    ) -> WarmupReport:
        """Analyse warm-up behaviour for a single restart event.

        Parameters
        ----------
        restart_epoch:
            Epoch timestamp when the writer process started.
        timestamps:
            Sorted (ascending) stroke timestamps produced after the restart.
        """
        # Only consider strokes *after* the restart.
        ts = sorted(t for t in timestamps if t >= restart_epoch)
        total = len(ts)

        # First-stroke latency.
        first_latency = (ts[0] - restart_epoch) if ts else 0.0

        # Need at least window_size + 1 timestamps to compute window_size gaps.
        min_needed = self.window_size + 1
        if total < min_needed:
            return WarmupReport(
                restart_epoch=restart_epoch,
                expected_cadence_s=self.expected_cadence_s,
                tolerance=self.tolerance,
                window_size=self.window_size,
                first_stroke_latency_s=first_latency,
                warmup_s=None,
                warmup_strokes=total,
                settled=False,
                total_strokes_observed=total,
            )

        # Compute inter-stroke gaps.
        gaps = [ts[i + 1] - ts[i] for i in range(total - 1)]

        lo = self.expected_cadence_s * (1 - self.tolerance)
        hi = self.expected_cadence_s * (1 + self.tolerance)

        # Slide a window of `window_size` consecutive gaps and check
        # whether the median falls in [lo, hi].
        warmup_s: Optional[float] = None
        warmup_strokes = total  # default: all of them
        settled = False

        for start in range(len(gaps) - self.window_size + 1):
            window = gaps[start : start + self.window_size]
            med = statistics.median(window)
            if lo <= med <= hi:
                # The *end* of the first qualifying window is the settle point.
                settle_idx = start + self.window_size  # index into `gaps`
                # settle_idx-th gap corresponds to ts[settle_idx + 1].
                # warmup_s = time from restart to that stroke.
                settle_ts = ts[settle_idx]
                warmup_s = settle_ts - restart_epoch
                warmup_strokes = settle_idx + 1  # +1 because stroke 0 is the first
                settled = True
                break

        return WarmupReport(
            restart_epoch=restart_epoch,
            expected_cadence_s=self.expected_cadence_s,
            tolerance=self.tolerance,
            window_size=self.window_size,
            first_stroke_latency_s=first_latency,
            warmup_s=warmup_s,
            warmup_strokes=warmup_strokes,
            settled=settled,
            total_strokes_observed=total,
        )


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def warmup_check(
    restart_epoch: float,
    timestamps: Sequence[float],
    expected_cadence_s: float = 15.0,
    tolerance: float = 0.25,
    window_size: int = 5,
) -> WarmupReport:
    """One-liner warm-up measurement.

    >>> report = warmup_check(1000.0, [1003, 1018, 1033, 1048, 1063, 1078, 1093])
    >>> report.settled
    True
    """
    tracker = RestartWarmupTracker(
        expected_cadence_s=expected_cadence_s,
        tolerance=tolerance,
        window_size=window_size,
    )
    return tracker.measure(restart_epoch, timestamps)
