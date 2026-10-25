"""Stroke diversity analyser — measure how varied the generated strokes are.

A writer that produces the same sentence shapes over and over is not
really writing; it is echoing.  This module answers the question:
"is the garden growing, or is it photocopying itself?"

Metrics computed:
- vocabulary_richness: unique tokens / total tokens (higher = more diverse)
- mean_length: average character count per stroke
- repetition_ratio: fraction of strokes that are near-duplicates of a
  recent predecessor (cosine similarity on token sets, threshold 0.85)
- theme_entropy: Shannon entropy over the ``kind`` field (note, thought,
  snippet, devlog, garden, metrics) — measures whether the writer spreads
  its attention evenly or obsesses over one category
- drift_score: how much the vocabulary has shifted in the most recent
  window compared to the preceding window (Jaccard distance on token sets)

Usage::

    from iamai.stroke_diversity import analyse

    with open("data/strokes.jsonl") as f:
        strokes = [json.loads(line) for line in f]

    report = analyse(strokes, window=100)
    print(report["vocabulary_richness"])   # 0.0–1.0
    print(report["repetition_ratio"])      # 0.0–1.0
    print(report["theme_entropy"])         # bits
    print(report["drift_score"])           # 0.0–1.0

Can also be invoked from the CLI wrapper
``tools/stroke_diversity.py`` (not included here but follows the same
pattern as ``tools/stall_classifier.py``).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# tokenisation
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-zA-Z0-9]+|[^\s\w]", re.UNICODE)


def _tokenise(text: str) -> List[str]:
    """Lowercase word-tokenise, stripping pure whitespace."""
    return [t.lower() for t in _WORD_RE.findall(text or "")]


# ---------------------------------------------------------------------------
# similarity
# ---------------------------------------------------------------------------


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _cosine_token_sets(a: set, b: set) -> float:
    """Cosine similarity treating each token set as a binary vector."""
    if not a and not b:
        return 1.0
    dot = len(a & b)
    mag = math.sqrt(len(a)) * math.sqrt(len(b))
    if mag == 0:
        return 0.0
    return dot / mag


# ---------------------------------------------------------------------------
# core metrics
# ---------------------------------------------------------------------------


def vocabulary_richness(strokes: Sequence[Dict[str, Any]]) -> float:
    """Unique tokens / total tokens across all stroke texts."""
    all_tokens: List[str] = []
    for s in strokes:
        all_tokens.extend(_tokenise(s.get("text", "")))
    if not all_tokens:
        return 0.0
    return len(set(all_tokens)) / len(all_tokens)


def mean_length(strokes: Sequence[Dict[str, Any]]) -> float:
    """Mean character count of stroke texts."""
    lengths = [len(s.get("text", "")) for s in strokes]
    if not lengths:
        return 0.0
    return sum(lengths) / len(lengths)


def repetition_ratio(
    strokes: Sequence[Dict[str, Any]],
    threshold: float = 0.85,
    lookback: int = 5,
) -> float:
    """Fraction of strokes whose cosine similarity to any of the
    preceding *lookback* strokes exceeds *threshold*.

    A high ratio means the writer is stuck in a rut, producing near-
    identical outputs.
    """
    if len(strokes) < 2:
        return 0.0

    token_sets = [set(_tokenise(s.get("text", ""))) for s in strokes]
    repeats = 0
    for i in range(1, len(strokes)):
        window_start = max(0, i - lookback)
        for j in range(window_start, i):
            if _cosine_token_sets(token_sets[i], token_sets[j]) >= threshold:
                repeats += 1
                break
    return repeats / len(strokes)


def theme_entropy(strokes: Sequence[Dict[str, Any]]) -> float:
    """Shannon entropy (bits) over the ``kind`` field."""
    if not strokes:
        return 0.0
    counts: Counter = Counter()
    for s in strokes:
        counts[s.get("kind", "unknown")] += 1
    total = sum(counts.values())
    entropy = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            entropy -= p * math.log2(p)
    return entropy


def drift_score(
    strokes: Sequence[Dict[str, Any]],
    window: int = 50,
) -> float:
    """Jaccard distance between the vocabulary of the most recent
    *window* strokes and the *window* strokes before that.

    Returns 0.0 when both halves have identical vocabularies (no drift)
    and 1.0 when they share no tokens at all (complete drift).
    """
    if len(strokes) < 2 * window:
        return 0.0

    recent_tokens: set = set()
    for s in strokes[-window:]:
        recent_tokens.update(_tokenise(s.get("text", "")))

    older_tokens: set = set()
    for s in strokes[-2 * window : -window]:
        older_tokens.update(_tokenise(s.get("text", "")))

    return 1.0 - _jaccard(recent_tokens, older_tokens)


# ---------------------------------------------------------------------------
# composite report
# ---------------------------------------------------------------------------


def analyse(
    strokes: Sequence[Dict[str, Any]],
    window: int = 100,
) -> Dict[str, Any]:
    """Run all diversity metrics and return a report dict.

    Parameters
    ----------
    strokes : sequence of stroke dicts (each has at least ``text`` and
              optionally ``kind``)
    window  : number of recent strokes to use for drift_score; also
              used as the lookback reference for repetition_ratio

    Returns
    -------
    dict with keys:
        vocabulary_richness  (float, 0–1)
        mean_length          (float, chars)
        repetition_ratio     (float, 0–1, lower is better)
        theme_entropy        (float, bits)
        drift_score          (float, 0–1)
        stroke_count         (int)
        verdict              (str: "healthy" | "stale" | "sparse")
    """
    vr = vocabulary_richness(strokes)
    ml = mean_length(strokes)
    rr = repetition_ratio(strokes)
    te = theme_entropy(strokes)
    ds = drift_score(strokes, window=min(window, len(strokes) // 2))

    # simple verdict logic
    if len(strokes) < 10:
        verdict = "sparse"
    elif rr > 0.4:
        verdict = "stale"
    elif vr < 0.15 and ds < 0.05:
        verdict = "stale"
    else:
        verdict = "healthy"

    return {
        "vocabulary_richness": round(vr, 4),
        "mean_length": round(ml, 1),
        "repetition_ratio": round(rr, 4),
        "theme_entropy": round(te, 4),
        "drift_score": round(ds, 4),
        "stroke_count": len(strokes),
        "verdict": verdict,
    }
