"""stroke_rhythm_monitor — real-time stroke rhythm health scoring.

The writer produces strokes at a configured cadence (default 15 s).
Many modules measure individual aspects — gap size, cadence jitter,
stall duration — but none roll them into a single *rhythm health*
indicator that a caretaker can glance at.

This module fills that gap.  It ingests a sliding window of recent
stroke timestamps and produces:

- **rhythm_score** (0.0–1.0): composite health of the writing rhythm.
  1.0 means perfectly regular; lower values indicate degradation.
- **rhythm_grade**: letter grade A/B/C/D/F derived from the score.
- **dominant_issue**: the single biggest factor dragging the score down
  (or ``None`` when grade is A).

Scoring formula::

    score = w_cadence * cadence_component
          + w_regularity * regularity_component
          + w_freshness * freshness_component

where each component is clamped to [0, 1] and the weights sum to 1.

Public API::

    from iamai.stroke_rhythm_monitor import (
        StrokeRhythmMonitor, RhythmReport, rhythm_check,
    )

    monitor = StrokeRhythmMonitor(expected_cadence_s=15)
    report = monitor.check(timestamps)

    print(report.rhythm_score)   # 0.87
    print(report.rhythm_grade)   # 'B'
    print(report.dominant_issue) # 'irregularity'

    # convenience one-liner
    report = rhythm_check(timestamps, expected_cadence_s=15)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Weight configuration
# ---------------------------------------------------------------------------

_W_CADENCE = 0.40       # how close median gap is to expected
_W_REGULARITY = 0.35    # how consistent the gaps are (low variance)
_W_FRESHNESS = 0.25     # how recent the last stroke is

_GRADE_THRESHOLDS = [
    (0.90, "A"),
    (0.75, "B"),
    (0.55, "C"),
    (0.35, "D"),
    (0.00, "F"),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RhythmReport:
    """Snapshot of stroke rhythm health."""

    rhythm_score: float
    rhythm_grade: str
    cadence_component: float
    regularity_component: float
    freshness_component: float
    median_gap_s: float
    p95_gap_s: float
    last_gap_s: float
    sample_count: int
    dominant_issue: Optional[str]

    def is_healthy(self) -> bool:
        """True when rhythm grade is A or B."""
        return self.rhythm_grade in ("A", "B")


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def _cadence_component(expected_s: float, gaps: Sequence[float]) -> float:
    """Score how close the median gap is to expected.

    Returns 1.0 when median == expected, decaying towards 0 as the
    ratio diverges in either direction.
    """
    if not gaps or expected_s <= 0:
        return 0.0
    median = statistics.median(gaps)
    ratio = median / expected_s
    # symmetric decay: ratio=1 → 1.0, ratio=0.5 or 2.0 → 0.5, etc.
    if ratio >= 1.0:
        return max(0.0, 1.0 - (ratio - 1.0))
    return max(0.0, ratio)


def _regularity_component(gaps: Sequence[float]) -> float:
    """Score gap consistency via coefficient of variation.

    CV = stdev / mean.  Low CV → high regularity → score near 1.
    """
    if len(gaps) == 0:
        return 0.0  # no data → no regularity signal
    if len(gaps) == 1:
        return 1.0  # single gap is trivially consistent
    mean = statistics.mean(gaps)
    if mean <= 0:
        return 0.0
    cv = statistics.stdev(gaps) / mean
    # CV of 0 → 1.0, CV of 1 → 0.0, clamp below 0
    return max(0.0, 1.0 - cv)


def _freshness_component(expected_s: float, last_gap_s: float) -> float:
    """Score how recent the last stroke is relative to expected cadence.

    A gap of 1× expected → 1.0; 10× → 0.1; 100× → 0.0.
    """
    if expected_s <= 0 or last_gap_s < 0:
        return 0.0
    ratio = last_gap_s / expected_s
    # logarithmic decay: score = max(0, 1 - log10(ratio))
    if ratio <= 1.0:
        return 1.0
    import math
    return max(0.0, 1.0 - math.log10(ratio))


def _score_to_grade(score: float) -> str:
    for threshold, grade in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def _dominant_issue(
    cadence: float, regularity: float, freshness: float,
) -> Optional[str]:
    """Identify the weakest component, if any component is below 0.8."""
    components = {
        "cadence_drift": cadence,
        "irregularity": regularity,
        "staleness": freshness,
    }
    weakest_name = min(components, key=components.get)
    weakest_val = components[weakest_name]
    if weakest_val >= 0.8:
        return None
    return weakest_name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class StrokeRhythmMonitor:
    """Stateful stroke rhythm monitor.

    Parameters
    ----------
    expected_cadence_s : float
        Expected seconds between strokes (default 15).
    window_size : int
        Number of recent gaps to consider (default 100).
    """

    def __init__(
        self,
        expected_cadence_s: float = 15.0,
        window_size: int = 100,
    ) -> None:
        self.expected_cadence_s = expected_cadence_s
        self.window_size = window_size

    def check(self, timestamps: Sequence[float]) -> RhythmReport:
        """Compute a rhythm report from a list of epoch timestamps."""
        # Sort and compute inter-stroke gaps
        ts_sorted = sorted(timestamps)
        all_gaps = [
            ts_sorted[i + 1] - ts_sorted[i]
            for i in range(len(ts_sorted) - 1)
        ]
        # Apply window
        gaps = all_gaps[-self.window_size:] if all_gaps else []

        cad = _cadence_component(self.expected_cadence_s, gaps)
        reg = _regularity_component(gaps)
        last_gap = gaps[-1] if gaps else float("inf")
        fresh = _freshness_component(self.expected_cadence_s, last_gap)

        score = (
            _W_CADENCE * cad
            + _W_REGULARITY * reg
            + _W_FRESHNESS * fresh
        )
        score = max(0.0, min(1.0, score))

        p95 = (
            sorted(gaps)[int(len(gaps) * 0.95)]
            if len(gaps) >= 20
            else (max(gaps) if gaps else 0.0)
        )

        return RhythmReport(
            rhythm_score=round(score, 4),
            rhythm_grade=_score_to_grade(score),
            cadence_component=round(cad, 4),
            regularity_component=round(reg, 4),
            freshness_component=round(fresh, 4),
            median_gap_s=round(statistics.median(gaps), 2) if gaps else 0.0,
            p95_gap_s=round(p95, 2),
            last_gap_s=round(last_gap, 2) if last_gap != float("inf") else -1.0,
            sample_count=len(gaps),
            dominant_issue=_dominant_issue(cad, reg, fresh),
        )


def rhythm_check(
    timestamps: Sequence[float],
    expected_cadence_s: float = 15.0,
    window_size: int = 100,
) -> RhythmReport:
    """Convenience one-liner: compute a rhythm report without instantiation."""
    monitor = StrokeRhythmMonitor(
        expected_cadence_s=expected_cadence_s,
        window_size=window_size,
    )
    return monitor.check(timestamps)
