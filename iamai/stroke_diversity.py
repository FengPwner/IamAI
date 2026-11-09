#!/usr/bin/env python3
"""stroke_diversity — measure the variety of stroke types over time.

A healthy writer produces a balanced mix across categories (metrics,
note, snippet, thought, devlog, garden, reading).  When diversity
collapses the writer is usually stuck in a single mode — endlessly
appending metrics, or repeating the same note format.  This module
quantifies diversity so the caretaker can detect and correct monotony.

Metrics
-------

shannon_entropy
    Shannon entropy of the category distribution, normalised to [0, 1].
    1.0 = perfectly uniform; 0.0 = every stroke is the same type.

richness
    Fraction of known categories that have been seen at least once
    in the window.  ``seen / total_categories``.

dominance
    The share of the most frequent category.  Closer to ``1/n`` is
    healthier; 1.0 means total monopoly.

evenness
    Pielou's evenness index — ``H / ln(S)`` where *S* is the number
    of observed categories.  1.0 = perfectly even.

diversity_score
    Weighted composite: ``0.4 * evenness + 0.3 * richness + 0.3 * (1 - dominance)``.
    Designed to be intuitive at a glance.

Public API
----------

>>> from iamai.stroke_diversity import analyse_strokes
>>> report = analyse_strokes(strokes, window=200)
>>> report["diversity_score"]
0.87
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Optional

KNOWN_CATEGORIES = frozenset(
    {"metrics", "note", "snippet", "thought", "devlog", "garden", "reading"}
)


def _category_of(stroke: Any) -> str:
    """Extract category string from a stroke dict or legacy tuple."""
    if isinstance(stroke, dict):
        return str(stroke.get("kind", stroke.get("category", "unknown")))
    if isinstance(stroke, (list, tuple)) and len(stroke) >= 2:
        return str(stroke[1])
    return "unknown"


def analyse_strokes(
    strokes: List[Any],
    window: Optional[int] = None,
    known_categories: Optional[frozenset] = None,
) -> Dict[str, Any]:
    """Analyse stroke-type diversity over the given window.

    Parameters
    ----------
    strokes : list
        Stroke records — each a dict with ``"kind"`` / ``"category"``,
        or a tuple ``(timestamp, kind, ...)``.
    window : int, optional
        Number of most-recent strokes to consider.  ``None`` uses all.
    known_categories : frozenset, optional
        Override the default set of recognised categories.

    Returns
    -------
    dict
        ``{shannon_entropy, richness, dominance, evenness, diversity_score,
        distribution, sample_size, verdict}``
    """
    cats = known_categories or KNOWN_CATEGORIES
    if window is not None:
        strokes = strokes[-window:]
    if not strokes:
        return _empty_report(cats)

    counter: Counter = Counter(_category_of(s) for s in strokes)
    total = sum(counter.values())
    if total == 0:
        return _empty_report(cats)

    # Shannon entropy (natural log)
    probs = [c / total for c in counter.values() if c > 0]
    h = -sum(p * math.log(p) for p in probs)
    max_h = math.log(len(probs)) if len(probs) > 1 else 1.0
    norm_entropy = h / max_h if max_h > 0 else 0.0

    # Richness — fraction of known categories seen
    seen = set(counter.keys()) & cats
    richness = len(seen) / len(cats) if cats else 0.0

    # Dominance — share of most frequent category
    dominance = max(counter.values()) / total

    # Evenness (Pielou)
    s = len(probs)
    evenness = h / math.log(s) if s > 1 else 0.0

    # Composite score
    diversity_score = round(
        0.4 * evenness + 0.3 * richness + 0.3 * (1.0 - dominance), 4
    )

    # Verdict
    if diversity_score >= 0.75:
        verdict = "HEALTHY"
    elif diversity_score >= 0.50:
        verdict = "FAIR"
    elif diversity_score >= 0.25:
        verdict = "NARROW"
    else:
        verdict = "MONOTONE"

    return {
        "shannon_entropy": round(norm_entropy, 4),
        "richness": round(richness, 4),
        "dominance": round(dominance, 4),
        "evenness": round(evenness, 4),
        "diversity_score": diversity_score,
        "distribution": dict(counter.most_common()),
        "sample_size": total,
        "verdict": verdict,
    }


def _empty_report(cats: frozenset) -> Dict[str, Any]:
    """Return a zeroed-out report when there are no strokes to analyse."""
    return {
        "shannon_entropy": 0.0,
        "richness": 0.0,
        "dominance": 0.0,
        "evenness": 0.0,
        "diversity_score": 0.0,
        "distribution": {},
        "sample_size": 0,
        "verdict": "EMPTY",
    }


# ---------------------------------------------------------------------------
# CLI shortcut
# ---------------------------------------------------------------------------

def brief(report: Dict[str, Any]) -> str:
    """One-line human summary of a diversity report."""
    d = report["diversity_score"]
    v = report["verdict"]
    n = report["sample_size"]
    top = next(iter(report["distribution"]), "-")
    return f"diversity={d:.2f} ({v}) · {n} strokes · top={top}"
