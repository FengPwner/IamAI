"""stall_loss_estimator — quantify how many strokes the writer *should* have
produced during each stall gap, and how quickly it recovered afterwards.

The writer ticks every `cadence` seconds (default 15).  When the interval
between two consecutive strokes exceeds `gap_threshold` seconds (default
2× the batch interval = 1200 s), we call it a *stall*.  For each stall we
report:

  - gap_seconds:        wall-clock silence duration
  - expected_strokes:   gap_seconds / cadence  (strokes that *should* exist)
  - actual_strokes:     always 0 inside a gap  (by definition)
  - recovery_seconds:   time from stall-end to the *next* normal-interval
                        stroke (measures how fast the writer re-stabilised)
  - loss_severity:      'minor' (< 100 lost) | 'moderate' (100–500) |
                        'severe' (> 500)

This is pure-Python with no subprocess calls so it can be unit-tested
with synthetic timestamps.

Usage from other modules::

    from iamai.stall_loss_estimator import estimate_losses
    report = estimate_losses(timestamps, cadence=15, gap_threshold=1200)
    for stall in report.stalls:
        print(stall.as_dict())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StallEvent:
    """One detected stall in the stroke timeline."""

    index: int                # position in the timestamp array where gap starts
    gap_seconds: float
    expected_strokes: int
    recovery_seconds: float
    cadence: float

    @property
    def loss_severity(self) -> str:
        if self.expected_strokes < 100:
            return "minor"
        if self.expected_strokes <= 500:
            return "moderate"
        return "severe"

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "gap_seconds": round(self.gap_seconds, 1),
            "expected_strokes": self.expected_strokes,
            "recovery_seconds": round(self.recovery_seconds, 1),
            "loss_severity": self.loss_severity,
        }


@dataclass(frozen=True)
class LossReport:
    """Aggregate result of analysing a stroke timeline."""

    stalls: List[StallEvent] = field(default_factory=list)
    total_strokes: int = 0
    total_gap_seconds: float = 0.0
    total_expected_lost: int = 0

    @property
    def stall_count(self) -> int:
        return len(self.stalls)

    @property
    def worst_severity(self) -> Optional[str]:
        if not self.stalls:
            return None
        order = {"severe": 3, "moderate": 2, "minor": 1}
        return max((s.loss_severity for s in self.stalls), key=lambda s: order.get(s, 0))

    @property
    def health_score(self) -> float:
        """0.0 = perfect (no stalls), 1.0 = catastrophic loss."""
        if self.total_strokes == 0:
            return 1.0
        lost_ratio = self.total_expected_lost / (self.total_strokes + self.total_expected_lost)
        return round(min(lost_ratio, 1.0), 4)

    def as_dict(self) -> dict:
        return {
            "stall_count": self.stall_count,
            "total_strokes": self.total_strokes,
            "total_gap_seconds": round(self.total_gap_seconds, 1),
            "total_expected_lost": self.total_expected_lost,
            "worst_severity": self.worst_severity,
            "health_score": self.health_score,
        }


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def estimate_losses(
    timestamps: Sequence[float],
    cadence: float = 15.0,
    gap_threshold: float = 1200.0,
    recovery_window: int = 5,
) -> LossReport:
    """Scan a sorted sequence of epoch timestamps for stall gaps.

    Parameters
    ----------
    timestamps:
        Sorted (ascending) list of stroke epoch times.
    cadence:
        Expected seconds between strokes under normal operation.
    gap_threshold:
        Minimum gap (seconds) to classify as a stall.
    recovery_window:
        Number of post-stall strokes to examine when measuring recovery.
        Recovery is the time from the first post-gap stroke until the
        intervals between subsequent strokes return to ≤ 2× cadence.
    """
    ts = list(timestamps)
    if len(ts) < 2:
        return LossReport(total_strokes=len(ts))

    stalls: List[StallEvent] = []
    total_gap = 0.0
    total_lost = 0

    for i in range(len(ts) - 1):
        gap = ts[i + 1] - ts[i]
        if gap <= gap_threshold:
            continue

        expected = int(gap / cadence)
        # measure recovery: look at the next few strokes after the gap
        recovery = 0.0
        for j in range(i + 1, min(i + 1 + recovery_window, len(ts) - 1)):
            interval = ts[j + 1] - ts[j]
            if interval <= 2 * cadence:
                break
            recovery += interval

        stall = StallEvent(
            index=i,
            gap_seconds=gap,
            expected_strokes=expected,
            recovery_seconds=recovery,
            cadence=cadence,
        )
        stalls.append(stall)
        total_gap += gap
        total_lost += expected

    return LossReport(
        stalls=stalls,
        total_strokes=len(ts),
        total_gap_seconds=total_gap,
        total_expected_lost=total_lost,
    )
