"""stroke_diversity — measures how varied the stroke stream is.

Given a sequence of stroke records (each with at least a ``kind`` field),
compute a sliding-window Shannon entropy over the kind distribution.
A high entropy means the writer is alternating between many content types
(devlog, garden, metrics, note, snippet, thought …); low entropy means
it has been hammering the same kind repeatedly.

Complements:
  * stroke_velocity_tracker  — pace of strokes
  * stroke_tempo             — rhythm regularity
  * stroke_certainty_tracker — epistemic posture per stroke

This module adds the *breadth* dimension: is the writer exploring many
facets or drilling deep into one?

Pure Python, no numpy/scipy required.
Written by Qwen during caretaker visit 736, 2026-11-20.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def shannon_entropy(counts: Counter) -> float:
    """Return Shannon entropy in bits for a Counter of category counts."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            entropy -= p * math.log2(p)
    return entropy


def max_entropy(num_categories: int) -> float:
    """Entropy of a perfectly uniform distribution over *num_categories*."""
    if num_categories <= 1:
        return 0.0
    return math.log2(num_categories)


# ---------------------------------------------------------------------------
# Single-window analysis
# ---------------------------------------------------------------------------

def window_diversity(strokes: Sequence[Dict[str, Any]],
                     kind_field: str = "kind") -> Dict[str, Any]:
    """Analyse diversity for a single window of strokes.

    Returns a dict with:
      * counts        — Counter mapping kind → frequency
      * entropy       — Shannon entropy in bits
      * max_entropy   — theoretical maximum for observed categories
      * normalised    — entropy / max_entropy  (0‒1, 1 = perfectly uniform)
      * richness      — number of distinct kinds observed
      * dominance     — the most frequent kind and its share (0‒1)
    """
    kinds = [s.get(kind_field, "unknown") for s in strokes]
    counts = Counter(kinds)
    ent = shannon_entropy(counts)
    rich = len(counts)
    max_ent = max_entropy(rich)
    norm = ent / max_ent if max_ent > 0 else 0.0
    dominant_kind, dominant_count = counts.most_common(1)[0] if counts else ("none", 0)
    dominance = dominant_count / len(kinds) if kinds else 0.0
    return {
        "counts": dict(counts),
        "entropy": round(ent, 4),
        "max_entropy": round(max_ent, 4),
        "normalised": round(norm, 4),
        "richness": rich,
        "dominance": {"kind": dominant_kind, "share": round(dominance, 4)},
    }


# ---------------------------------------------------------------------------
# Sliding-window evolution
# ---------------------------------------------------------------------------

def diversity_stream(strokes: Sequence[Dict[str, Any]],
                     window_size: int = 20,
                     step: int = 10,
                     kind_field: str = "kind") -> List[Dict[str, Any]]:
    """Slide a window across *strokes* and return per-window diversity dicts.

    Each result entry also carries ``start`` and ``end`` indices so callers
    can correlate diversity changes with specific strokes.
    """
    if window_size < 1:
        raise ValueError("window_size must be >= 1")
    if step < 1:
        raise ValueError("step must be >= 1")

    results: List[Dict[str, Any]] = []
    n = len(strokes)
    for start in range(0, max(n - window_size + 1, 1), step):
        end = start + window_size
        chunk = strokes[start:end]
        info = window_diversity(chunk, kind_field=kind_field)
        info["start"] = start
        info["end"] = min(end, n)
        results.append(info)
    return results


# ---------------------------------------------------------------------------
# Trend classification
# ---------------------------------------------------------------------------

_TREND_THRESHOLDS = {
    "expanding":  0.05,   # normalised entropy rising
    "stable":     0.05,   # within ±threshold
    "narrowing": -0.05,   # normalised entropy falling
}


def classify_trend(windows: Sequence[Dict[str, Any]]) -> str:
    """Classify the diversity trend across a sequence of window results.

    Returns one of: ``expanding``, ``stable``, ``narrowing``.
    * ``expanding``  — the writer is broadening its content mix.
    * ``stable``     — diversity is roughly constant.
    * ``narrowing``  — the writer is converging on fewer kinds.
    """
    if len(windows) < 2:
        return "insufficient_data"
    norms = [w["normalised"] for w in windows]
    delta = norms[-1] - norms[0]
    if delta > _TREND_THRESHOLDS["expanding"]:
        return "expanding"
    elif delta < _TREND_THRESHOLDS["narrowing"]:
        return "narrowing"
    return "stable"


# ---------------------------------------------------------------------------
# Convenience: full summary
# ---------------------------------------------------------------------------

def diversity_report(strokes: Sequence[Dict[str, Any]],
                     window_size: int = 20,
                     step: int = 10,
                     kind_field: str = "kind") -> Dict[str, Any]:
    """One-call convenience: returns overall + per-window diversity info."""
    overall = window_diversity(strokes, kind_field=kind_field)
    windows = diversity_stream(strokes, window_size=window_size,
                               step=step, kind_field=kind_field)
    trend = classify_trend(windows)
    return {
        "overall": overall,
        "windows": windows,
        "trend": trend,
        "total_strokes": len(strokes),
        "window_size": window_size,
        "step": step,
    }
