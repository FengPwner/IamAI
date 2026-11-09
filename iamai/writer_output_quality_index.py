"""writer_output_quality_index — aggregate writer health into a single quality score.

The writer is monitored by dozens of individual modules (cadence adherence,
content diversity, loop detection, freshness, …), each producing its own
metric.  This module combines the most important *independent* signals into
one composite **Output Quality Index** (OQI) in [0, 1], so that the
caretaker can glance at a single number to decide whether intervention is
needed.

Signal dimensions
-----------------

Each dimension is normalised to [0, 1] (1 = healthy) before aggregation:

====================  =================================================
dimension             how it is scored
====================  =================================================
cadence_adherence     |actual_median_gap − target_gap| / target_gap
                      → 1 when gap matches target, decays linearly
diversity             fraction of unique kind labels in the window
                      → 1 when all six kinds are present
freshness             fraction of strokes whose text hash is new
                      (not seen in the previous window)
loop_freedom          1 − loop_confidence (from content_loop_detector)
                      → 1 when no structural loop is detected
volume                actual stroke count / expected count for the
                      elapsed window duration
====================  =================================================

Aggregation
-----------

By default the OQI is the **geometric mean** of the five dimensions.
Geometric mean penalises any single very-low score (a writer that is
fast but stuck in a loop should not score well overall).

A caller-supplied ``weights`` dict can override the default equal
weighting.  Weights are normalised internally so they need not sum to 1.

Grades
------

=====  ==============================================
grade  meaning
=====  ==============================================
A      OQI ≥ 0.85 — writer is healthy across all dims
B      0.65 ≤ OQI < 0.85 — minor issues, monitor
C      0.45 ≤ OQI < 0.65 — degraded, intervention soon
D      OQI < 0.45 — writer is unhealthy, act now
=====  ==============================================

Public API
----------
- ``compute_oqi(strokes, target_gap=15, window=1800) -> OQIReport``
- ``grade_oqi(score) -> str``

Usage::

    from iamai.writer_output_quality_index import compute_oqi

    report = compute_oqi(strokes)
    print(report.score)   # 0.78
    print(report.grade)   # 'B'
    print(report.dimensions)
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OQIReport:
    """Immutable result of a quality-index computation."""

    score: float
    grade: str
    dimensions: Dict[str, float]
    stroke_count: int
    window_seconds: float

    def __str__(self) -> str:
        dims = "  ".join(f"{k}={v:.2f}" for k, v in self.dimensions.items())
        return f"OQI {self.score:.3f} [{self.grade}]  ({dims})"


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

_KINDS = {"devlog", "garden", "note", "thought", "metrics", "snippet"}


def _parse_at(at_str: str) -> float:
    """Parse an ISO-8601 timestamp to epoch seconds."""
    at_str = at_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(at_str)
    except (ValueError, TypeError):
        return 0.0
    return dt.timestamp()


def _text_hash(stroke: Dict[str, Any]) -> str:
    """Cheap hash of a stroke's text content for dedup."""
    text = stroke.get("text", "") or stroke.get("content", "")
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _score_cadence(gaps: List[float], target_gap: float) -> float:
    """Score how close the median inter-stroke gap is to target."""
    if not gaps:
        return 0.0
    med = median(gaps)
    if target_gap <= 0:
        return 0.0
    deviation = abs(med - target_gap) / target_gap
    return max(0.0, 1.0 - deviation)


def _score_diversity(kinds: List[str]) -> float:
    """Fraction of the expected kind set that is present."""
    if not kinds:
        return 0.0
    present = set(kinds) & _KINDS
    return len(present) / len(_KINDS)


def _score_freshness(hashes: List[str]) -> float:
    """Fraction of content hashes that are unique within the window."""
    if not hashes:
        return 0.0
    unique = len(set(hashes))
    return unique / len(hashes)


def _score_loop_freedom(labels: List[str]) -> float:
    """Detect simple periodic loops and return 1 − confidence."""
    n = len(labels)
    if n < 6:
        return 1.0  # not enough data to detect a loop

    best_ratio = 0.0
    for p in range(2, n // 2 + 1):
        candidate = labels[:p]
        matches = sum(
            1 for i in range(n) if labels[i] == candidate[i % p]
        )
        ratio = matches / n
        if ratio > best_ratio:
            best_ratio = ratio
    # Only penalise if the loop confidence is high (> 0.6)
    if best_ratio < 0.6:
        return 1.0
    return max(0.0, 1.0 - best_ratio)


def _score_volume(actual: int, expected: int) -> float:
    """Score actual stroke count against expected."""
    if expected <= 0:
        return 1.0 if actual > 0 else 0.0
    ratio = actual / expected
    return min(1.0, ratio)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_oqi(
    strokes: Sequence[Dict[str, Any]],
    target_gap: float = 15.0,
    window: float = 1800.0,
    weights: Optional[Dict[str, float]] = None,
) -> OQIReport:
    """Compute the Output Quality Index for a sequence of strokes.

    Parameters
    ----------
    strokes : list of stroke dicts
        Each must have at least ``'at'`` (ISO timestamp) and optionally
        ``'kind'`` (category label) and ``'text'`` / ``'content'``.
    target_gap : float
        Expected seconds between strokes (default 15).
    window : float
        Analysis window in seconds, measured back from the newest stroke.
    weights : dict, optional
        Dimension → weight.  Missing keys get weight 1.0.

    Returns
    -------
    OQIReport
    """
    empty_dims = {
        "cadence": 0.0,
        "diversity": 0.0,
        "freshness": 0.0,
        "loop_freedom": 1.0,
        "volume": 0.0,
    }

    if not strokes:
        return OQIReport(
            score=0.0, grade="D", dimensions=empty_dims,
            stroke_count=0, window_seconds=window,
        )

    # Sort by timestamp
    sorted_strokes = sorted(strokes, key=lambda s: _parse_at(s.get("at", "")))

    # Window: take the last `window` seconds of strokes
    newest = _parse_at(sorted_strokes[-1].get("at", ""))
    cutoff = newest - window
    window_strokes = [
        s for s in sorted_strokes if _parse_at(s.get("at", "")) >= cutoff
    ]

    if not window_strokes:
        return OQIReport(
            score=0.0, grade="D", dimensions=empty_dims,
            stroke_count=len(strokes), window_seconds=window,
        )

    # Extract signals
    timestamps = [_parse_at(s.get("at", "")) for s in window_strokes]
    gaps = [
        timestamps[i + 1] - timestamps[i]
        for i in range(len(timestamps) - 1)
        if timestamps[i + 1] >= timestamps[i]
    ]
    kinds = [s.get("kind", "unknown") for s in window_strokes]
    hashes = [_text_hash(s) for s in window_strokes]

    # Score each dimension
    dims = {
        "cadence": _score_cadence(gaps, target_gap),
        "diversity": _score_diversity(kinds),
        "freshness": _score_freshness(hashes),
        "loop_freedom": _score_loop_freedom(kinds),
        "volume": _score_volume(
            len(window_strokes), int(window / max(target_gap, 1))
        ),
    }

    # Weighted geometric mean
    w = {k: 1.0 for k in dims}
    if weights:
        w.update(weights)
    total_w = sum(w.values())
    if total_w <= 0:
        total_w = 1.0

    log_sum = sum(w[k] * math.log(max(dims[k], 1e-9)) for k in dims)
    score = math.exp(log_sum / total_w)
    score = round(min(1.0, max(0.0, score)), 4)

    return OQIReport(
        score=score,
        grade=grade_oqi(score),
        dimensions=dims,
        stroke_count=len(strokes),
        window_seconds=window,
    )


def grade_oqi(score: float) -> str:
    """Map an OQI score to a letter grade."""
    if score >= 0.85:
        return "A"
    if score >= 0.65:
        return "B"
    if score >= 0.45:
        return "C"
    return "D"
