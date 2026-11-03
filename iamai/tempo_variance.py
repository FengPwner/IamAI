#!/usr/bin/env python3
"""tempo_variance — measure consistency of writer cadence.

A healthy automated writer produces strokes at roughly regular intervals.
When the variance in inter-stroke gaps spikes, something is wrong: the
process was paused, the machine went to sleep, or the writer hit a
slow path.  This module quantifies that consistency.

Public API
----------

``gap_seconds(timestamps) -> list[float]``
    Compute inter-stroke gaps in seconds from a sorted list of ISO-8601
    timestamps.

``variance(gaps) -> float``
    Population variance of a list of gap values (seconds²).

``stddev(gaps) -> float``
    Population standard deviation (seconds).

``coefficient_of_variation(gaps) -> float``
    stddev / mean — dimensionless measure of relative variability.
    Returns 0.0 when mean is zero or fewer than two gaps.

``classify(cv, thresholds=None) -> str``
    Map coefficient of variation to a label:
      cv < 0.1  → "steady"
      cv < 0.3  → "normal"
      cv < 0.6  → "irregular"
      cv >= 0.6 → "erratic"
    Custom thresholds can override these boundaries.

``is_steady(gaps, max_cv=0.3) -> bool``
    True when cadence is steady or better (cv <= max_cv).

``from_strokes(jsonl_path, last_n=None) -> dict``
    Convenience: read timestamps from a strokes.jsonl file, compute
    gaps and all metrics, return a summary dict.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


def gap_seconds(timestamps: Sequence[str]) -> List[float]:
    """Compute inter-stroke gaps in seconds from ISO-8601 timestamps.

    Parameters
    ----------
    timestamps : sequence of str
        ISO-8601 datetime strings (must be parseable by datetime.fromisoformat).
        Need not be sorted — will be sorted internally.

    Returns
    -------
    list of float
        Gaps in seconds between consecutive timestamps.  Length is
        len(timestamps) - 1.  Empty list if fewer than 2 timestamps.
    """
    if len(timestamps) < 2:
        return []
    dts = sorted(datetime.fromisoformat(t) for t in timestamps)
    return [(dts[i + 1] - dts[i]).total_seconds() for i in range(len(dts) - 1)]


def variance(gaps: Sequence[float]) -> float:
    """Population variance of gap values."""
    n = len(gaps)
    if n == 0:
        return 0.0
    mean = sum(gaps) / n
    return sum((g - mean) ** 2 for g in gaps) / n


def stddev(gaps: Sequence[float]) -> float:
    """Population standard deviation of gap values."""
    return math.sqrt(variance(gaps))


def coefficient_of_variation(gaps: Sequence[float]) -> float:
    """Coefficient of variation (stddev / mean).  Dimensionless."""
    n = len(gaps)
    if n < 2:
        return 0.0
    mean = sum(gaps) / n
    if mean == 0.0:
        return 0.0
    return stddev(gaps) / mean


DEFAULT_THRESHOLDS: List[Tuple[float, str]] = [
    (0.1, "steady"),
    (0.3, "normal"),
    (0.6, "irregular"),
]


def classify(
    cv: float,
    thresholds: Optional[List[Tuple[float, str]]] = None,
) -> str:
    """Classify a coefficient of variation into a cadence label."""
    for limit, label in (thresholds or DEFAULT_THRESHOLDS):
        if cv < limit:
            return label
    return "erratic"


def is_steady(gaps: Sequence[float], max_cv: float = 0.3) -> bool:
    """True when cadence cv <= max_cv."""
    return coefficient_of_variation(gaps) <= max_cv


def from_strokes(
    jsonl_path: str | Path,
    last_n: Optional[int] = None,
) -> Dict:
    """Read strokes file and compute tempo summary.

    Parameters
    ----------
    jsonl_path : path
        Path to a JSONL file where each line has an ``at`` field.
    last_n : int, optional
        If set, only use the last *n* strokes.

    Returns
    -------
    dict with keys: count, gaps, variance, stddev, cv, label, steady.
    """
    path = Path(jsonl_path)
    timestamps: List[str] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "at" in obj:
                timestamps.append(obj["at"])
    if last_n is not None:
        timestamps = timestamps[-last_n:]
    gaps = gap_seconds(timestamps)
    cv = coefficient_of_variation(gaps)
    return {
        "count": len(timestamps),
        "gaps": len(gaps),
        "variance": round(variance(gaps), 2),
        "stddev": round(stddev(gaps), 2),
        "cv": round(cv, 4),
        "label": classify(cv),
        "steady": is_steady(gaps),
    }
