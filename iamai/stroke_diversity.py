"""stroke_diversity — measure category rotation balance across recent strokes.

The writer loop cycles through six output kinds: devlog, garden, snippet,
thought, metrics, note. A healthy writer distributes strokes roughly evenly.
One that fixates on a single kind may be stuck in a loop, misconfigured,
or starving other categories of attention.

This module quantifies that distribution using Shannon entropy normalized
to a 0–1 diversity index, and classifies the result.

Diversity labels
----------------

==========  =====================================================
label       meaning
==========  =====================================================
balanced    diversity_index >= 0.85 — all kinds well represented
skewed      0.65 <= diversity_index < 0.85 — some kinds underused
fixated     diversity_index < 0.65 — dominated by one kind
==========  =====================================================

Zero dependencies.  stdlib only.

>>> kinds = ["devlog", "garden", "snippet", "thought", "metrics", "note",
...          "devlog", "garden", "snippet", "thought", "metrics", "note"]
>>> r = diversity_report(kinds)
>>> r["label"]
'balanced'
>>> r["diversity_index"]
1.0
>>> r["missing_kinds"]
[]

>>> fixated = ["thought"] * 20 + ["devlog"] * 2
>>> r2 = diversity_report(fixated)
>>> r2["label"]
'fixated'
>>> r2["dominant_kind"]
'thought'
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Sequence


ALL_KINDS: tuple[str, ...] = ("devlog", "garden", "snippet", "thought", "metrics", "note")


# ---------------------------------------------------------------------------
# Label classification
# ---------------------------------------------------------------------------

def classify_diversity(diversity_index: float) -> str:
    """Classify diversity from a normalized index (0–1).

    Args:
        diversity_index: normalized Shannon entropy, 0 = monoculture, 1 = uniform

    Returns:
        One of: "balanced", "skewed", "fixated"

    Examples:
        >>> classify_diversity(0.95)
        'balanced'
        >>> classify_diversity(0.75)
        'skewed'
        >>> classify_diversity(0.50)
        'fixated'
    """
    if diversity_index < 0:
        diversity_index = 0.0
    if diversity_index >= 0.85:
        return "balanced"
    if diversity_index >= 0.65:
        return "skewed"
    return "fixated"


# ---------------------------------------------------------------------------
# Entropy computation
# ---------------------------------------------------------------------------

def _shannon_entropy(counts: Dict[str, int], total: int) -> float:
    """Compute Shannon entropy in bits from a category count dict.

    Args:
        counts: mapping of category → count
        total: sum of all counts

    Returns:
        entropy in bits (>= 0)
    """
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def diversity_report(
    kinds: Sequence[str],
    fixation_threshold: float = 0.4,
) -> dict[str, Any]:
    """Build a diversity report from a sequence of stroke kind strings.

    Args:
        kinds: ordered sequence of kind labels (e.g., "devlog", "garden")
        fixation_threshold: dominant_share above which is_fixated=True

    Returns:
        dict with keys: count, diversity_index, entropy, max_entropy,
        dominant_kind, dominant_share, missing_kinds, kind_counts,
        is_fixated, label
    """
    n = len(kinds)

    if n < 6:
        return {
            "count": n,
            "diversity_index": 0.0,
            "entropy": 0.0,
            "max_entropy": round(math.log2(len(ALL_KINDS)), 4),
            "dominant_kind": "",
            "dominant_share": 0.0,
            "missing_kinds": list(ALL_KINDS),
            "kind_counts": {k: 0 for k in ALL_KINDS},
            "is_fixated": False,
            "label": "insufficient_data",
        }

    counter = Counter(kinds)
    kind_counts: Dict[str, int] = {k: counter.get(k, 0) for k in ALL_KINDS}
    # Include any unknown kinds
    for k, v in counter.items():
        if k not in kind_counts:
            kind_counts[k] = v

    total = sum(kind_counts.values())
    entropy = _shannon_entropy(kind_counts, total)

    distinct_possible = max(len(ALL_KINDS), len(kind_counts))
    max_entropy = math.log2(distinct_possible) if distinct_possible > 1 else 1.0
    diversity_index = entropy / max_entropy if max_entropy > 0 else 0.0

    dominant_kind = max(kind_counts, key=lambda k: kind_counts[k])
    dominant_share = kind_counts[dominant_kind] / total if total > 0 else 0.0

    missing_kinds = sorted(k for k in ALL_KINDS if kind_counts.get(k, 0) == 0)
    is_fixated = dominant_share > fixation_threshold

    label = classify_diversity(diversity_index)

    return {
        "count": total,
        "diversity_index": round(diversity_index, 4),
        "entropy": round(entropy, 4),
        "max_entropy": round(max_entropy, 4),
        "dominant_kind": dominant_kind,
        "dominant_share": round(dominant_share, 4),
        "missing_kinds": missing_kinds,
        "kind_counts": dict(sorted(kind_counts.items())),
        "is_fixated": is_fixated,
        "label": label,
    }


# ---------------------------------------------------------------------------
# One-line summary
# ---------------------------------------------------------------------------

def diversity_summary(kinds: Sequence[str]) -> str:
    """One-line human-readable diversity summary.

    Examples:
        >>> diversity_summary(["devlog", "garden", "snippet",
        ...     "thought", "metrics", "note"] * 2)
        '12 strokes: diversity 1.0000 (balanced), dominant: devlog at 16.7%'
    """
    r = diversity_report(kinds)
    if r["label"] == "insufficient_data":
        return f"{r['count']} strokes: insufficient data (need >= 6)"
    return (
        f"{r['count']} strokes: "
        f"diversity {r['diversity_index']:.4f} ({r['label']}), "
        f"dominant: {r['dominant_kind']} at {r['dominant_share']:.1%}"
    )


# ---------------------------------------------------------------------------
# Kind-specific helpers
# ---------------------------------------------------------------------------

def missing_kind_count(kinds: Sequence[str]) -> int:
    """Count how many of the standard kinds have zero strokes.

    Examples:
        >>> missing_kind_count(["devlog", "garden", "snippet",
        ...     "thought", "metrics", "note"])
        0
        >>> missing_kind_count(["thought"] * 10)
        5
    """
    counter = Counter(kinds)
    return sum(1 for k in ALL_KINDS if counter.get(k, 0) == 0)


def kind_share(kinds: Sequence[str], target_kind: str) -> float:
    """Fraction of strokes belonging to target_kind.

    Examples:
        >>> kind_share(["devlog", "garden", "devlog", "thought"], "devlog")
        0.5
        >>> kind_share([], "devlog")
        0.0
    """
    if not kinds:
        return 0.0
    counter = Counter(kinds)
    return counter.get(target_kind, 0) / len(kinds)
