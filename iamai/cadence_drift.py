#!/usr/bin/env python3
"""cadence_drift — measure how far the writer's actual cadence drifts from target.

The writer targets one stroke every *target_gap* seconds (default 15 s).
In practice I/O waits, GIL contention, process scheduling, and container
recycling push the real interval above or below that target.  This module
computes the **rolling drift**: how far the actual cadence has wandered
from the configured one, and classifies it into severity bands.

Why this matters
----------------
A restart tells you the process died.  A stall tells you it stopped.
**Cadence drift** tells you it's *degrading* — still alive, still writing,
but gradually losing pace.  A drift that creeps from *tight* → *warm* →
*hot* over hours predicts a future stall better than a point-in-time
snapshot.

Signal dimensions
-----------------

==================  ====================================================
metric              meaning
==================  ====================================================
mean_interval       average seconds between strokes in the window
median_interval     median seconds (robust to outlier gaps)
drift_pct           (mean − target) / target × 100
drift_class         tight (<5%), warm (5–20%), hot (>20%)
stability           coefficient of variation (σ/μ) — lower is steadier
jitter_count        number of intervals deviating >2× from target
==================  ====================================================

Public API
----------
- ``compute_drift(intervals, target=15, window=60) -> DriftReport``
- ``classify_drift(drift_pct) -> str``
- ``compute_stability(intervals) -> float``
- ``extract_intervals_from_strokes(strokes) -> list[float]``

Usage::

    from iamai.cadence_drift import compute_drift

    intervals = [14.8, 15.1, 16.2, 15.0, 14.9, ...]
    report = compute_drift(intervals, target=15, window=60)
    print(report.drift_class)   # "tight"
    print(report.stability)     # 0.031
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DriftReport:
    """Result of a cadence-drift analysis."""

    sample_size: int
    target_s: float
    mean_interval_s: float
    median_interval_s: float
    drift_pct: float
    drift_class: str
    stability: float
    jitter_count: int
    min_s: float
    max_s: float

    def summary(self) -> str:
        """One-line human-readable summary."""
        if self.sample_size == 0:
            return "cadence drift: no intervals to measure"
        return (
            f"cadence drift: {self.mean_interval_s:.1f}s "
            f"(target {self.target_s:.0f}s, drift {self.drift_pct:+.1f}%, "
            f"{self.drift_class}, stability {self.stability:.3f})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "sample_size": self.sample_size,
            "target_s": self.target_s,
            "mean_interval_s": self.mean_interval_s,
            "median_interval_s": self.median_interval_s,
            "drift_pct": self.drift_pct,
            "drift_class": self.drift_class,
            "stability": self.stability,
            "jitter_count": self.jitter_count,
            "min_s": self.min_s,
            "max_s": self.max_s,
        }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_drift(drift_pct: float) -> str:
    """Classify drift severity from percentage deviation.

    Returns one of: "tight", "warm", "hot".

    - tight: |drift| < 5%
    - warm:  5% ≤ |drift| < 20%
    - hot:   |drift| ≥ 20%
    """
    abs_drift = abs(drift_pct)
    if abs_drift < 5:
        return "tight"
    elif abs_drift < 20:
        return "warm"
    else:
        return "hot"


# ---------------------------------------------------------------------------
# Stability
# ---------------------------------------------------------------------------

def compute_stability(intervals: list[float]) -> float:
    """Coefficient of variation (σ/μ) of intervals.

    Lower values indicate a steadier cadence.
    Returns 0.0 for empty or single-element input.
    """
    if len(intervals) < 2:
        return 0.0
    mean = sum(intervals) / len(intervals)
    if mean <= 0:
        return 0.0
    variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
    stddev = math.sqrt(variance)
    return stddev / mean


# ---------------------------------------------------------------------------
# Jitter detection
# ---------------------------------------------------------------------------

def count_jitter(intervals: list[float], target: float) -> int:
    """Count intervals deviating more than 2× from the target.

    An interval is "jitter" if it is either:
    - less than target / 2 (too fast, likely burst), or
    - greater than target * 2 (too slow, likely stall).
    """
    if target <= 0:
        return 0
    low = target / 2
    high = target * 2
    return sum(1 for iv in intervals if iv < low or iv > high)


# ---------------------------------------------------------------------------
# Interval extraction
# ---------------------------------------------------------------------------

def _parse_ts(s: str) -> datetime | None:
    """Parse an ISO-8601 timestamp string."""
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def extract_intervals_from_strokes(strokes: list[dict[str, Any]]) -> list[float]:
    """Compute seconds between consecutive strokes.

    Each stroke must have an ``at`` field (ISO-8601 string).
    Skips negative intervals (clock skew) silently.

    Returns a list of intervals (length = len(strokes) - 1 at most).
    """
    if len(strokes) < 2:
        return []

    timestamps = []
    for s in strokes:
        ts = _parse_ts(s.get("at", ""))
        if ts is not None:
            timestamps.append(ts)
    timestamps.sort()

    intervals = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if delta >= 0:
            intervals.append(delta)
    return intervals


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def compute_drift(
    intervals: list[float],
    target: float = 15.0,
    window: int = 60,
) -> DriftReport:
    """Compute cadence drift over the most recent *window* intervals.

    Parameters
    ----------
    intervals : list[float]
        Seconds between consecutive strokes.
    target : float
        Target cadence in seconds (default 15).
    window : int
        Number of most-recent intervals to analyse.

    Returns
    -------
    DriftReport with all metrics populated.
    """
    if not intervals:
        return DriftReport(
            sample_size=0, target_s=target,
            mean_interval_s=0.0, median_interval_s=0.0,
            drift_pct=0.0, drift_class="tight",
            stability=0.0, jitter_count=0,
            min_s=0.0, max_s=0.0,
        )

    recent = intervals[-window:]
    n = len(recent)
    mean_val = sum(recent) / n

    sorted_vals = sorted(recent)
    mid = n // 2
    if n % 2 == 0:
        median_val = (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
    else:
        median_val = sorted_vals[mid]

    drift_pct = ((mean_val - target) / target) * 100 if target > 0 else 0.0
    drift_class = classify_drift(drift_pct)
    stability = compute_stability(recent)
    jitter = count_jitter(recent, target)

    return DriftReport(
        sample_size=n,
        target_s=target,
        mean_interval_s=round(mean_val, 2),
        median_interval_s=round(median_val, 2),
        drift_pct=round(drift_pct, 2),
        drift_class=drift_class,
        stability=round(stability, 4),
        jitter_count=jitter,
        min_s=round(min(recent), 2),
        max_s=round(max(recent), 2),
    )


# ---------------------------------------------------------------------------
# Trend detection
# ---------------------------------------------------------------------------

def detect_trend(
    intervals: list[float],
    chunk_size: int = 20,
) -> str:
    """Detect whether cadence is improving, stable, or degrading.

    Splits intervals into chunks and compares the mean of the first and
    last chunk.  Returns:
    - "improving" if the latest chunk is closer to target
    - "degrading" if the latest chunk is farther from target
    - "stable" if they are within 5% of each other

    Requires at least 2 × chunk_size intervals.
    """
    if len(intervals) < 2 * chunk_size:
        return "insufficient_data"

    first_chunk = intervals[:chunk_size]
    last_chunk = intervals[-chunk_size:]

    first_mean = sum(first_chunk) / len(first_chunk)
    last_mean = sum(last_chunk) / len(last_chunk)

    if first_mean <= 0:
        return "stable"

    change_pct = ((last_mean - first_mean) / first_mean) * 100

    if abs(change_pct) < 5:
        return "stable"
    elif change_pct > 0:
        return "degrading"
    else:
        return "improving"


# ---------------------------------------------------------------------------
# Convenience: load from writer state file
# ---------------------------------------------------------------------------

def load_intervals_from_state(state_path: Path) -> list[float]:
    """Load intervals from a writer state JSON file.

    The state file is expected to have a ``history`` list with ``at`` fields.
    """
    if not state_path.exists():
        return []
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    history = data.get("history", [])
    return extract_intervals_from_strokes(history)


def load_intervals_from_jsonl(jsonl_path: Path) -> list[float]:
    """Load intervals from a strokes JSONL file.

    Each line is a JSON object with an ``at`` field.
    """
    if not jsonl_path.exists():
        return []

    strokes = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                strokes.append(entry)
            except (json.JSONDecodeError, TypeError):
                continue

    return extract_intervals_from_strokes(strokes)
