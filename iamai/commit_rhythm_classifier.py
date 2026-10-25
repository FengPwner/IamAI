"""commit_rhythm_classifier — classify inter-commit gap sequences into rhythm patterns.

A commit stream's *rhythm* is the shape of its inter-commit gaps over a
window.  Two streams with identical mean rates can have radically
different rhythms: one may tick like a metronome, another may cluster
into bursts separated by long silences.

This module classifies a sequence of inter-commit gaps into one of five
rhythm categories:

===========  =============================================================
category     description
===========  =============================================================
metronome    gaps are tightly clustered — low variance, steady cadence
bursty       short gaps clustered in bursts, separated by long pauses
accelerating gaps are systematically shrinking — writer is speeding up
decelerating gaps are systematically growing — writer is slowing down
irregular    no discernible pattern — high variance, no trend
===========  =============================================================

This module fills the gap between:

- ``commit_gap_analyzer``, which classifies *individual* gaps into
  diagnostic categories (regular, accelerated, stalled, dead) but does
  not characterise the sequence as a whole;
- ``commit_phase_detector``, which uses sliding-window *rate* analysis
  to identify lifecycle phases (boot, growth, steady, stall, recovery,
  decay);
- ``commit_momentum``, which computes a scalar momentum score.

The rhythm classifier answers: *what is the temporal shape of this
commit window, and how confident are we in that classification?*

Usage::

    from iamai.commit_rhythm_classifier import classify_rhythm, RhythmReport

    gaps = [600, 610, 590, 605, 600, 595, 610]  # seconds
    report = classify_rhythm(gaps)
    print(report.category)     # "metronome"
    print(report.confidence)   # 0.92
    print(report.trend_slope)  # -0.3 (slightly accelerating)

All inputs are plain lists of floats (seconds).  No file I/O is
performed, making the module trivially testable.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

__all__ = [
    "RhythmReport",
    "classify_rhythm",
    "RHYTHM_CATEGORIES",
    "DEFAULT_METRONOME_CV",
    "DEFAULT_TREND_THRESHOLD",
    "DEFAULT_BURST_RATIO",
]

# ---------------------------------------------------------------------------
# configuration defaults
# ---------------------------------------------------------------------------

RHYTHM_CATEGORIES = (
    "metronome",
    "bursty",
    "accelerating",
    "decelerating",
    "irregular",
)

# Coefficient of variation below which gaps are considered "tight".
DEFAULT_METRONOME_CV = 0.15

# Absolute normalised slope above which a trend is detected.
# Slope is computed via least-squares linear regression on gap indices,
# normalised by mean gap so the threshold is scale-free.
DEFAULT_TREND_THRESHOLD = 0.02

# Ratio of (max gap / median gap) above which a sequence is bursty.
# A bursty sequence has a few very long gaps amid mostly short ones.
DEFAULT_BURST_RATIO = 3.0


# ---------------------------------------------------------------------------
# data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RhythmReport:
    """Classification result for a gap sequence."""

    category: str
    confidence: float
    trend_slope: float
    cv: float
    mean_gap: float
    median_gap: float
    gap_count: int
    max_gap: float
    min_gap: float
    burst_ratio: float

    @property
    def is_steady(self) -> bool:
        """True if rhythm is metronome or very mild deceleration."""
        return self.category in ("metronome",) or (
            self.category == "decelerating" and abs(self.trend_slope) < DEFAULT_TREND_THRESHOLD * 2
        )

    @property
    def is_trending(self) -> bool:
        """True if rhythm shows a clear acceleration or deceleration."""
        return self.category in ("accelerating", "decelerating")

    @property
    def is_healthy(self) -> bool:
        """True if rhythm indicates a functioning writer."""
        return self.category in ("metronome", "accelerating", "decelerating")

    @property
    def summary_line(self) -> str:
        """One-line human-readable summary."""
        return (
            f"{self.category} (confidence={self.confidence:.2f}, "
            f"cv={self.cv:.3f}, slope={self.trend_slope:+.4f}, "
            f"n={self.gap_count})"
        )


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _linear_slope(values: Sequence[float]) -> float:
    """Compute the slope of a least-squares line fit to *values*.

    x-values are 0, 1, 2, ... len(values)-1.  Returns 0.0 for fewer
    than 2 data points.
    """
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = statistics.mean(values)
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _compute_cv(values: Sequence[float]) -> float:
    """Coefficient of variation (stdev / mean).  Returns inf if mean=0."""
    if not values:
        return float("inf")
    m = statistics.mean(values)
    if m == 0:
        return float("inf")
    return statistics.stdev(values) / m if len(values) > 1 else 0.0


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def classify_rhythm(
    gaps: Sequence[float],
    *,
    metronome_cv: float = DEFAULT_METRONOME_CV,
    trend_threshold: float = DEFAULT_TREND_THRESHOLD,
    burst_ratio: float = DEFAULT_BURST_RATIO,
) -> RhythmReport:
    """Classify a sequence of inter-commit gaps into a rhythm category.

    Parameters
    ----------
    gaps : sequence of float
        Inter-commit gaps in seconds.  Must contain at least 2 values
        for meaningful classification; a single gap returns "irregular"
        with confidence 0.
    metronome_cv : float
        CV threshold for metronome classification.
    trend_threshold : float
        Normalised slope threshold for trend detection.
    burst_ratio : float
        max/median ratio threshold for bursty classification.

    Returns
    -------
    RhythmReport
    """
    if not gaps:
        raise ValueError("gaps must be non-empty")

    gap_list = list(gaps)
    n = len(gap_list)
    mean_g = statistics.mean(gap_list)
    median_g = statistics.median(gap_list)
    max_g = max(gap_list)
    min_g = min(gap_list)
    cv = _compute_cv(gap_list)
    br = (max_g / median_g) if median_g > 0 else float("inf")
    raw_slope = _linear_slope(gap_list)
    norm_slope = (raw_slope / mean_g) if mean_g > 0 else 0.0

    # --- classification logic ---

    # 1. metronome: low CV and no strong trend
    if cv < metronome_cv and abs(norm_slope) < trend_threshold:
        category = "metronome"
        confidence = max(0.0, 1.0 - cv / metronome_cv)

    # 2. bursty: high burst ratio (long tail amid short gaps)
    elif br >= burst_ratio:
        category = "bursty"
        # Confidence scales with how far above threshold we are.
        confidence = min(1.0, (br - burst_ratio) / burst_ratio + 0.5)

    # 3. accelerating: negative slope (gaps shrinking)
    elif norm_slope < -trend_threshold:
        category = "accelerating"
        confidence = min(1.0, abs(norm_slope) / (trend_threshold * 5))

    # 4. decelerating: positive slope (gaps growing)
    elif norm_slope > trend_threshold:
        category = "decelerating"
        confidence = min(1.0, abs(norm_slope) / (trend_threshold * 5))

    # 5. irregular: everything else
    else:
        category = "irregular"
        # Confidence is inverse of how close we are to a boundary.
        dist_to_trend = abs(norm_slope) / trend_threshold if trend_threshold else 0
        dist_to_cv = cv / metronome_cv if metronome_cv else 0
        confidence = max(0.0, 1.0 - max(dist_to_trend, dist_to_cv))

    return RhythmReport(
        category=category,
        confidence=round(confidence, 4),
        trend_slope=round(norm_slope, 6),
        cv=round(cv, 6),
        mean_gap=round(mean_g, 2),
        median_gap=round(median_g, 2),
        gap_count=n,
        max_gap=round(max_g, 2),
        min_gap=round(min_g, 2),
        burst_ratio=round(br, 4),
    )


def rhythm_timeline(
    gaps: Sequence[float],
    window: int = 10,
    **kwargs,
) -> List[RhythmReport]:
    """Classify rhythm over a sliding window of gaps.

    Parameters
    ----------
    gaps : sequence of float
        Full inter-commit gap sequence.
    window : int
        Number of gaps per analysis window.  Must be >= 2.
    **kwargs
        Forwarded to ``classify_rhythm``.

    Returns
    -------
    list of RhythmReport
        One report per window position.  Length = len(gaps) - window + 1.
    """
    if window < 2:
        raise ValueError("window must be >= 2")
    gap_list = list(gaps)
    if len(gap_list) < window:
        return [classify_rhythm(gap_list, **kwargs)]
    return [
        classify_rhythm(gap_list[i : i + window], **kwargs)
        for i in range(len(gap_list) - window + 1)
    ]
