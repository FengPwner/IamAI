"""Measure whether consecutive strokes stay on-topic or jump randomly.

A writer that produces 400+ strokes over weeks needs to maintain topical
continuity within a session. If stroke N talks about commit hygiene and
stroke N+1 talks about caretaker visits and stroke N+2 jumps back to
git internals — the writer is producing coherent content. If each stroke
is about a completely unrelated topic, the output reads like noise even
when each individual stroke passes quality gates.

This module computes pairwise keyword overlap between consecutive strokes
and returns an aggregate continuity score. It deliberately uses a simple
token-overlap approach rather than embeddings: the check runs inside the
commit pipeline on every batch, so it must stay fast and dependency-free.

Scoring
-------

For each pair of consecutive strokes:

1. Extract "keywords" — lowercase alpha tokens ≥ 4 chars, excluding stopwords.
2. Compute Jaccard similarity between the two keyword sets.
3. The pair score is the Jaccard value (0.0 – 1.0).

The session continuity score is the mean of all pair scores, scaled to 0–100.

Verdicts:

- **continuous** (≥ 30): strokes share vocabulary; the session has a thread.
- **fragmented** (10–29): some overlap but no strong thread.
- **scattered** (< 10): strokes are effectively independent random topics.

Usage::

    from iamai.topic_continuity import assess_session

    strokes = [
        "add commit message quality scoring with length and mood checks",
        "extend commit message quality to detect vague subject lines",
        "the caretaker visit log now records restart events per session",
    ]
    result = assess_session(strokes)
    print(result["score"])      # e.g. 42
    print(result["verdict"])    # "continuous"
    print(result["pair_count"]) # 2
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence


# High-frequency words that carry no topical signal.
# Kept deliberately small: over-aggressive stopword lists kill real overlap.
_STOPWORDS = frozenset({
    "that", "this", "with", "from", "have", "been", "were", "will",
    "would", "could", "should", "their", "there", "when", "what",
    "which", "about", "into", "than", "then", "them", "these",
    "those", "some", "more", "also", "just", "only", "each",
    "other", "because", "does", "done", "being", "where", "after",
    "before", "during", "through", "without", "within", "between",
    "above", "below", "here", "very", "much", "such", "even",
    "most", "many", "like", "well", "back", "still", "already",
    "always", "never", "often", "sometimes", "usually",
})

_MIN_TOKEN_LEN = 4


def _extract_keywords(text: str) -> set[str]:
    """Return the set of meaningful lowercase tokens from *text*."""
    if not text:
        return set()
    tokens = text.lower().split()
    result = set()
    for t in tokens:
        cleaned = t.strip(".,;:!?\"'()[]{}")
        if len(cleaned) >= _MIN_TOKEN_LEN and cleaned.isalpha() and cleaned not in _STOPWORDS:
            result.add(cleaned)
    return result


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets. Returns 0.0 for two empty sets."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def assess_pair(text_a: str, text_b: str) -> Dict[str, Any]:
    """Score the topical overlap between two consecutive strokes.

    Returns a dict with ``score`` (0.0–1.0), ``shared`` (set of shared
    keywords), and ``keywords_a`` / ``keywords_b`` (each stroke's keywords).
    """
    kw_a = _extract_keywords(text_a)
    kw_b = _extract_keywords(text_b)
    shared = kw_a & kw_b
    j = _jaccard(kw_a, kw_b)
    return {
        "score": round(j, 4),
        "shared": sorted(shared),
        "keywords_a": sorted(kw_a),
        "keywords_b": sorted(kw_b),
    }


def assess_session(strokes: Sequence[str]) -> Dict[str, Any]:
    """Score topical continuity across a session's strokes.

    Parameters
    ----------
    strokes : sequence of str
        The stroke texts in chronological order.

    Returns
    -------
    dict with keys:
        ``score`` — 0–100 continuity score
        ``verdict`` — "continuous", "fragmented", or "scattered"
        ``pair_count`` — number of consecutive pairs evaluated
        ``pair_scores`` — list of per-pair Jaccard scores
        ``weakest_pair`` — index of the lowest-scoring pair (or None)
    """
    if len(strokes) < 2:
        return {
            "score": 0,
            "verdict": "scattered",
            "pair_count": 0,
            "pair_scores": [],
            "weakest_pair": None,
        }

    pair_scores: List[float] = []
    for i in range(len(strokes) - 1):
        result = assess_pair(strokes[i], strokes[i + 1])
        pair_scores.append(result["score"])

    mean = sum(pair_scores) / len(pair_scores)
    scaled = round(mean * 100, 1)

    if scaled >= 30:
        verdict = "continuous"
    elif scaled >= 10:
        verdict = "fragmented"
    else:
        verdict = "scattered"

    weakest = pair_scores.index(min(pair_scores)) if pair_scores else None

    return {
        "score": scaled,
        "verdict": verdict,
        "pair_count": len(pair_scores),
        "pair_scores": pair_scores,
        "weakest_pair": weakest,
    }
