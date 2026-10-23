"""commit_rhythm — analyze commit spacing patterns for health signals.

Healthy autonomous writers commit at a roughly steady cadence.
When commit intervals become erratic — long silences followed by
burst dumps, or accelerating frequency approaching zero-length gaps —
the underlying process is usually degraded.

This module provides:

- **rhythm_score**: 0.0 (completely erratic) to 1.0 (perfectly steady)
- **interval_stats**: mean, median, std-dev, min, max of commit gaps
- **pattern classification**: steady, drifting, bursty, stalled

Pattern definitions:

==========  =========================================================
pattern     meaning
==========  =========================================================
steady      intervals cluster tightly around the target cadence
drifting    intervals slowly increasing or decreasing over time
bursty      long gaps alternating with rapid-fire clusters
stalled     one or more gaps exceed 10× the target cadence
==========  =========================================================

Usage::

    from iamai.commit_rhythm import analyze_rhythm

    timestamps = [
        "2026-10-24T01:00:00+08:00",
        "2026-10-24T01:10:00+08:00",
        "2026-10-24T01:20:00+08:00",
        "2026-10-24T01:30:00+08:00",
    ]

    result = analyze_rhythm(timestamps, target_interval_seconds=600)
    print(result["score"])    # ~1.0
    print(result["pattern"])  # "steady"
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime
from typing import Any


_STALL_MULTIPLIER = 10.0       # gap > 10× target → stalled
_BURST_CV_THRESHOLD = 0.8      # coefficient of variation indicating bursty
_DRIFT_CORRELATION_THRESHOLD = 0.5  # trend correlation for drifting


def _parse_ts(ts: str | datetime) -> datetime:
    """Parse a timestamp string or return datetime as-is."""
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(ts)


def _compute_intervals(timestamps: list[str | datetime]) -> list[float]:
    """Compute sorted intervals (seconds) between consecutive timestamps."""
    parsed = sorted(_parse_ts(t) for t in timestamps)
    return [
        (parsed[i + 1] - parsed[i]).total_seconds()
        for i in range(len(parsed) - 1)
    ]


def _coefficient_of_variation(values: list[float]) -> float:
    """Coefficient of variation (std / mean). Returns 0.0 for single values."""
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return float("inf")
    return statistics.stdev(values) / mean


def _trend_correlation(values: list[float]) -> float:
    """Pearson correlation between index and value. -1 to +1."""
    n = len(values)
    if n < 3:
        return 0.0
    indices = list(range(n))
    mean_x = statistics.mean(indices)
    mean_y = statistics.mean(values)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(indices, values))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in indices))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in values))
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def rhythm_score(
    intervals: list[float],
    target_interval_seconds: float = 600.0,
) -> float:
    """Score rhythm regularity from 0.0 (erratic) to 1.0 (perfect).

    Scoring:
    - Perfect score when all intervals equal the target
    - Penalized by deviation from target (normalized by target)
    - Score drops to 0.0 when deviation exceeds target
    """
    if not intervals:
        return 0.0

    deviations = [
        abs(iv - target_interval_seconds) / target_interval_seconds
        for iv in intervals
    ]
    mean_deviation = statistics.mean(deviations)
    # Clamp: 0 deviation → 1.0, deviation ≥ 1.0 → 0.0
    return max(0.0, 1.0 - mean_deviation)


def classify_pattern(
    intervals: list[float],
    target_interval_seconds: float = 600.0,
) -> str:
    """Classify the commit interval pattern.

    Returns one of: 'steady', 'drifting', 'bursty', 'stalled'.
    Priority: stalled > bursty > drifting > steady.
    """
    if not intervals:
        return "stalled"

    # Check stalled: any gap > 10× target
    stall_threshold = target_interval_seconds * _STALL_MULTIPLIER
    if any(iv > stall_threshold for iv in intervals):
        return "stalled"

    # Check bursty: high coefficient of variation
    cv = _coefficient_of_variation(intervals)
    if cv > _BURST_CV_THRESHOLD:
        return "bursty"

    # Check drifting: strong trend in intervals
    corr = _trend_correlation(intervals)
    if abs(corr) > _DRIFT_CORRELATION_THRESHOLD:
        return "drifting"

    return "steady"


def interval_stats(intervals: list[float]) -> dict[str, Any]:
    """Compute descriptive statistics for commit intervals."""
    if not intervals:
        return {
            "count": 0,
            "mean": 0.0,
            "median": 0.0,
            "stdev": 0.0,
            "min": 0.0,
            "max": 0.0,
        }
    result: dict[str, Any] = {
        "count": len(intervals),
        "mean": statistics.mean(intervals),
        "median": statistics.median(intervals),
        "min": min(intervals),
        "max": max(intervals),
    }
    if len(intervals) >= 2:
        result["stdev"] = statistics.stdev(intervals)
    else:
        result["stdev"] = 0.0
    return result


def analyze_rhythm(
    timestamps: list[str | datetime],
    target_interval_seconds: float = 600.0,
) -> dict[str, Any]:
    """Full rhythm analysis: score, pattern, and interval statistics.

    Parameters
    ----------
    timestamps:
        List of commit timestamps (ISO strings or datetimes).
        Need not be sorted — will be sorted internally.
    target_interval_seconds:
        Expected commit interval in seconds (default: 600 = 10 min).

    Returns
    -------
    dict with keys:
        - score: float 0.0–1.0
        - pattern: str (steady|drifting|bursty|stalled)
        - intervals: dict of descriptive stats
        - cv: coefficient of variation
        - trend: Pearson correlation of interval over time
    """
    if len(timestamps) < 2:
        return {
            "score": 0.0,
            "pattern": "stalled" if not timestamps else "steady",
            "intervals": interval_stats([]),
            "cv": 0.0,
            "trend": 0.0,
        }

    ivs = _compute_intervals(timestamps)
    return {
        "score": rhythm_score(ivs, target_interval_seconds),
        "pattern": classify_pattern(ivs, target_interval_seconds),
        "intervals": interval_stats(ivs),
        "cv": _coefficient_of_variation(ivs),
        "trend": _trend_correlation(ivs),
    }
