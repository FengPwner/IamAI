#!/usr/bin/env python3
"""stroke_tempo_analyzer — analyze writing rhythm and tempo patterns.

The IamAI writer is designed to produce one stroke every ~15 seconds,
committed in batches every ~600 seconds.  In practice the cadence
drifts: process recycling, resource pressure, and content-generation
complexity all introduce jitter.  This module quantifies the *tempo*
of the stroke log — not just whether strokes exist, but how they flow
through time.

Analysis dimensions
-------------------

==================  =====================================================
metric              meaning
==================  =====================================================
mean_interval       average seconds between consecutive strokes
median_interval     median seconds (robust to outliers)
std_interval        standard deviation of intervals
cv                  coefficient of variation (std / mean); >1 = erratic
burst_count         number of burst windows (≥N strokes within T seconds)
drought_count       number of drought gaps (>K× the median interval)
acceleration        slope of a linear fit over recent interval trends;
                    negative = speeding up, positive = slowing down
tempo_class         one of "steady", "erratic", "accelerating",
                    "decelerating", "dormant"
==================  ===================================================

Tempo classification heuristic
-----------------------------
1. If fewer than 2 strokes exist → ``dormant``.
2. Compute CV (coefficient of variation of intervals).
   - CV ≤ 0.3 → base class ``steady``.
   - CV > 1.0 → base class ``erratic``.
   - Otherwise → check acceleration slope:
     - slope < -threshold → ``accelerating``
     - slope > +threshold → ``decelerating``
     - else ``steady``
3. If the most recent interval exceeds ``drought_factor × median``
   the class is overridden to ``dormant`` (the writer has stalled).

Public API
----------
- ``TempoReport``: dataclass with all analysis dimensions
- ``analyze(strokes, ...) -> TempoReport``
- ``classify_tempo(intervals, ...) -> str``
- ``find_bursts(strokes, max_gap=30, min_count=5) -> list[Burst]``
- ``find_droughts(strokes, factor=10) -> list[Drought]``

Usage::

    from iamai.stroke_tempo_analyzer import analyze
    import json

    strokes = [json.loads(line) for line in open("data/strokes.jsonl")]
    report = analyze(strokes)
    print(report.tempo_class)    # "steady"
    print(report.mean_interval)  # 15.3
    print(report.burst_count)    # 2
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Burst:
    """A cluster of strokes that arrived unusually close together."""

    start_index: int
    end_index: int  # inclusive
    count: int
    span_seconds: float

    def __len__(self) -> int:
        return self.count


@dataclass(frozen=True)
class Drought:
    """A gap between consecutive strokes that is unusually long."""

    before_index: int
    after_index: int
    gap_seconds: float

    def __repr__(self) -> str:
        return (
            f"Drought(gap={self.gap_seconds:.0f}s "
            f"between strokes {self.before_index}→{self.after_index})"
        )


@dataclass(frozen=True)
class TempoReport:
    """Full tempo analysis of a stroke sequence."""

    stroke_count: int
    mean_interval: float
    median_interval: float
    std_interval: float
    cv: float
    burst_count: int
    drought_count: int
    acceleration: float
    tempo_class: str
    bursts: tuple[Burst, ...] = ()
    droughts: tuple[Drought, ...] = ()
    recent_interval: Optional[float] = None

    def is_healthy(self) -> bool:
        """Return True if the tempo is steady or accelerating."""
        return self.tempo_class in ("steady", "accelerating")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    # Handle both +00:00 and Z suffixes
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _extract_intervals(strokes: Sequence[dict]) -> list[float]:
    """Compute inter-stroke intervals in seconds.

    Strokes must have an ``at`` field with ISO-8601 timestamps.
    Returns a list of length ``len(strokes) - 1``.
    """
    if len(strokes) < 2:
        return []

    timestamps = [_parse_ts(s["at"]) for s in strokes]
    intervals = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        intervals.append(max(delta, 0.0))  # clamp negative clock skew
    return intervals


def _linear_slope(values: Sequence[float]) -> float:
    """Compute the slope of a simple linear regression over indices.

    Returns 0.0 if fewer than 2 data points.
    Uses the closed-form least-squares formula:
        slope = (n·Σ(xy) - Σx·Σy) / (n·Σ(x²) - (Σx)²)
    where x = index, y = value.
    """
    n = len(values)
    if n < 2:
        return 0.0

    sum_x = n * (n - 1) / 2.0
    sum_x2 = n * (n - 1) * (2 * n - 1) / 6.0
    sum_y = sum(values)
    sum_xy = sum(i * v for i, v in enumerate(values))

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return 0.0

    return (n * sum_xy - sum_x * sum_y) / denom


# ---------------------------------------------------------------------------
# Tempo classification
# ---------------------------------------------------------------------------

# Thresholds (can be overridden via analyze() kwargs)
DEFAULT_CV_STEADY = 0.3
DEFAULT_CV_ERRATIC = 1.0
DEFAULT_ACCEL_THRESHOLD = 0.5  # seconds-per-stroke change per stroke
DEFAULT_DROUGHT_FACTOR = 10.0
DEFAULT_BURST_MAX_GAP = 30.0  # seconds
DEFAULT_BURST_MIN_COUNT = 5


def classify_tempo(
    intervals: Sequence[float],
    *,
    cv_steady: float = DEFAULT_CV_STEADY,
    cv_erratic: float = DEFAULT_CV_ERRATIC,
    accel_threshold: float = DEFAULT_ACCEL_THRESHOLD,
    drought_factor: float = DEFAULT_DROUGHT_FACTOR,
) -> str:
    """Classify the writing tempo from a sequence of intervals.

    Returns one of: "steady", "erratic", "accelerating", "decelerating",
    "dormant".
    """
    if len(intervals) < 1:
        return "dormant"

    median_val = statistics.median(intervals)
    recent = intervals[-1]

    # Dormant override: most recent gap is far above typical
    if median_val > 0 and recent > drought_factor * median_val:
        return "dormant"

    if len(intervals) < 2:
        return "steady"

    mean_val = statistics.mean(intervals)
    std_val = statistics.stdev(intervals)

    if mean_val == 0:
        return "steady"

    cv = std_val / mean_val

    if cv <= cv_steady:
        return "steady"
    if cv > cv_erratic:
        return "erratic"

    # In the ambiguous zone — check trend
    slope = _linear_slope(intervals)
    if slope < -accel_threshold:
        return "accelerating"
    if slope > accel_threshold:
        return "decelerating"
    return "steady"


# ---------------------------------------------------------------------------
# Burst / drought detection
# ---------------------------------------------------------------------------

def find_bursts(
    strokes: Sequence[dict],
    max_gap: float = DEFAULT_BURST_MAX_GAP,
    min_count: int = DEFAULT_BURST_MIN_COUNT,
) -> list[Burst]:
    """Find windows where strokes arrive unusually close together.

    A burst is a maximal run of consecutive strokes where every
    inter-stroke gap is ≤ ``max_gap`` seconds, and the run contains
    at least ``min_count`` strokes.
    """
    if len(strokes) < min_count:
        return []

    intervals = _extract_intervals(strokes)
    bursts: list[Burst] = []

    run_start = 0
    for i, gap in enumerate(intervals):
        if gap > max_gap:
            # End of a potential burst
            run_len = i - run_start + 1  # strokes in [run_start, i]
            if run_len >= min_count:
                span = sum(intervals[run_start:i])
                bursts.append(Burst(
                    start_index=run_start,
                    end_index=i,
                    count=run_len,
                    span_seconds=span,
                ))
            run_start = i + 1

    # Check trailing run
    run_len = len(intervals) - run_start + 1
    if run_len >= min_count:
        span = sum(intervals[run_start:])
        bursts.append(Burst(
            start_index=run_start,
            end_index=len(intervals),
            count=run_len,
            span_seconds=span,
        ))

    return bursts


def find_droughts(
    strokes: Sequence[dict],
    factor: float = DEFAULT_DROUGHT_FACTOR,
) -> list[Drought]:
    """Find gaps between strokes that are unusually long.

    A drought is any inter-stroke interval exceeding ``factor × median``
    of all intervals.
    """
    intervals = _extract_intervals(strokes)
    if not intervals:
        return []

    median_val = statistics.median(intervals)
    if median_val == 0:
        return []

    threshold = factor * median_val
    droughts: list[Drought] = []
    for i, gap in enumerate(intervals):
        if gap > threshold:
            droughts.append(Drought(
                before_index=i,
                after_index=i + 1,
                gap_seconds=gap,
            ))
    return droughts


# ---------------------------------------------------------------------------
# Main analysis entry point
# ---------------------------------------------------------------------------

def analyze(
    strokes: Sequence[dict],
    *,
    cv_steady: float = DEFAULT_CV_STEADY,
    cv_erratic: float = DEFAULT_CV_ERRATIC,
    accel_threshold: float = DEFAULT_ACCEL_THRESHOLD,
    drought_factor: float = DEFAULT_DROUGHT_FACTOR,
    burst_max_gap: float = DEFAULT_BURST_MAX_GAP,
    burst_min_count: int = DEFAULT_BURST_MIN_COUNT,
) -> TempoReport:
    """Produce a full tempo report from a sequence of strokes.

    Each stroke must have an ``at`` field with an ISO-8601 timestamp.
    Strokes should be sorted chronologically; if not, they will be
    sorted before analysis.
    """
    if not strokes:
        return TempoReport(
            stroke_count=0,
            mean_interval=0.0,
            median_interval=0.0,
            std_interval=0.0,
            cv=0.0,
            burst_count=0,
            drought_count=0,
            acceleration=0.0,
            tempo_class="dormant",
        )

    # Sort by timestamp if needed
    sorted_strokes = sorted(strokes, key=lambda s: s["at"])

    intervals = _extract_intervals(sorted_strokes)

    if not intervals:
        return TempoReport(
            stroke_count=len(sorted_strokes),
            mean_interval=0.0,
            median_interval=0.0,
            std_interval=0.0,
            cv=0.0,
            burst_count=0,
            drought_count=0,
            acceleration=0.0,
            tempo_class="dormant" if len(sorted_strokes) < 2 else "steady",
        )

    mean_val = statistics.mean(intervals)
    median_val = statistics.median(intervals)
    std_val = statistics.stdev(intervals) if len(intervals) >= 2 else 0.0
    cv = (std_val / mean_val) if mean_val > 0 else 0.0
    slope = _linear_slope(intervals)

    tempo_class = classify_tempo(
        intervals,
        cv_steady=cv_steady,
        cv_erratic=cv_erratic,
        accel_threshold=accel_threshold,
        drought_factor=drought_factor,
    )

    bursts = find_bursts(
        sorted_strokes,
        max_gap=burst_max_gap,
        min_count=burst_min_count,
    )
    droughts = find_droughts(sorted_strokes, factor=drought_factor)

    return TempoReport(
        stroke_count=len(sorted_strokes),
        mean_interval=round(mean_val, 3),
        median_interval=round(median_val, 3),
        std_interval=round(std_val, 3),
        cv=round(cv, 4),
        burst_count=len(bursts),
        drought_count=len(droughts),
        acceleration=round(slope, 4),
        tempo_class=tempo_class,
        bursts=tuple(bursts),
        droughts=tuple(droughts),
        recent_interval=round(intervals[-1], 3) if intervals else None,
    )
