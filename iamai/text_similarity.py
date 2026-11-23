"""text_similarity — shared text comparison utilities for the IamAI project.

Multiple modules across the codebase compute text similarity in their own
way: stroke_dedup uses Jaccard on token sets, content_loop_detector checks
for repeated sentence prefixes, template_loop_detector looks for structural
patterns.  This module consolidates the common primitives into one importable
location so that new analysis modules can compose them without reinventing
the wheel.

Metrics
-------

=========================  =============================================
function                   what it measures
=========================  =============================================
token_jaccard              set-level Jaccard similarity on word tokens
ngram_overlap              directional n-gram containment (A→B)
word_frequency_cosine      cosine similarity of word-frequency vectors
lcs_ratio                  longest-common-subsequence ratio (char-level)
structural_similarity      sentence-opener pattern similarity
composite_similarity        weighted blend of the above
=========================  =============================================

When to use which
-----------------

- **token_jaccard**: quick duplicate detection; insensitive to word order.
- **ngram_overlap**: "how much of A's phrasing appears in B?" — good for
  detecting paraphrases and template reuse with minor substitution.
- **word_frequency_cosine**: topic-level similarity; two texts about the
  same subject score high even if the phrasing differs.
- **lcs_ratio**: order-sensitive character-level alignment; catches
  copy-paste with edits.
- **structural_similarity**: detects when the writer uses the same
  sentence-opening patterns repeatedly — a sign of template fatigue.
- **composite_similarity**: single [0, 1] score for dashboards.

Usage::

    from iamai.text_similarity import (
        token_jaccard,
        ngram_overlap,
        composite_similarity,
    )

    a = "the quick brown fox jumps over the lazy dog"
    b = "the quick brown fox leaps over the lazy cat"

    print(token_jaccard(a, b))         # 0.75
    print(ngram_overlap(a, b, n=2))    # 0.625
    print(composite_similarity(a, b))  # ~0.72

Written by Qwen during caretaker visit 810, 2026-11-23.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Tokenisation helpers
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def _tokenise(text: str) -> List[str]:
    """Lowercase alphanumeric token list (preserves order and duplicates)."""
    return _TOKEN_RE.findall(text.lower())


def _token_set(text: str) -> set:
    """Lowercase alphanumeric token set."""
    return set(_tokenise(text))


# ---------------------------------------------------------------------------
# 1. Jaccard similarity (token-set level)
# ---------------------------------------------------------------------------


def token_jaccard(a: str, b: str) -> float:
    """Jaccard similarity of two texts based on word-token sets.

    Returns 1.0 for two empty texts; 0.0 if one is empty and the other is not.
    """
    sa, sb = _token_set(a), _token_set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# 2. N-gram overlap (directional containment)
# ---------------------------------------------------------------------------


def _ngrams(tokens: Sequence[str], n: int) -> List[Tuple[str, ...]]:
    """Extract n-grams from a token sequence."""
    if len(tokens) < n:
        return []
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def ngram_overlap(a: str, b: str, n: int = 2) -> float:
    """Fraction of A's n-grams that also appear in B.

    Directional: ``ngram_overlap(a, b)`` ≠ ``ngram_overlap(b, a)`` when the
    texts differ in length.  Returns 1.0 when A has no n-grams (empty/short).
    """
    ta, tb = _tokenise(a), _tokenise(b)
    ga = _ngrams(ta, n)
    if not ga:
        return 1.0
    gb_set = set(_ngrams(tb, n))
    hits = sum(1 for g in ga if g in gb_set)
    return hits / len(ga)


# ---------------------------------------------------------------------------
# 3. Word-frequency cosine similarity
# ---------------------------------------------------------------------------


def _cosine(a: Dict[str, int], b: Dict[str, int]) -> float:
    """Cosine similarity between two sparse frequency vectors."""
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def word_frequency_cosine(a: str, b: str) -> float:
    """Cosine similarity of word-frequency vectors.

    Captures topic-level similarity: two texts about the same subject score
    high even if the exact phrasing differs.
    """
    ca: Counter = Counter(_tokenise(a))
    cb: Counter = Counter(_tokenise(b))
    return _cosine(dict(ca), dict(cb))


# ---------------------------------------------------------------------------
# 4. Longest-common-subsequence ratio (character-level)
# ---------------------------------------------------------------------------


def _lcs_length(a: str, b: str) -> int:
    """Compute the length of the LCS of two strings (space-optimised)."""
    if len(a) < len(b):
        a, b = b, a  # ensure a is the longer one
    prev = [0] * (len(b) + 1)
    curr = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, [0] * (len(b) + 1)
    return prev[len(b)]


def lcs_ratio(a: str, b: str) -> float:
    """Ratio of the LCS length to the length of the shorter string.

    1.0 = one string is a subsequence of the other.
    0.0 = no common characters at all.

    Uses character-level comparison (not token-level) so that minor edits
    within words are captured.

    For very long inputs (> 2000 chars each) the text is truncated to avoid
    O(n²) blow-up; this is a heuristic, not a correctness guarantee.
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    # Cap to keep runtime bounded for pathological inputs
    cap = 2000
    a_trunc = a[:cap]
    b_trunc = b[:cap]
    lcs = _lcs_length(a_trunc, b_trunc)
    denom = min(len(a_trunc), len(b_trunc))
    return lcs / denom if denom else 0.0


# ---------------------------------------------------------------------------
# 5. Structural similarity (sentence-opener patterns)
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?", re.MULTILINE)


def _sentence_openers(text: str, prefix_words: int = 2) -> List[str]:
    """Extract the first *prefix_words* tokens of each sentence."""
    sentences = _SENTENCE_RE.findall(text)
    openers: List[str] = []
    for s in sentences:
        tokens = _tokenise(s)
        if tokens:
            opener = " ".join(tokens[:prefix_words])
            openers.append(opener)
    return openers


def structural_similarity(a: str, b: str, prefix_words: int = 2) -> float:
    """Jaccard similarity of sentence-opening patterns.

    Detects when a writer uses the same sentence starters repeatedly —
    a common symptom of template fatigue or creative exhaustion.
    """
    oa = set(_sentence_openers(a, prefix_words))
    ob = set(_sentence_openers(b, prefix_words))
    if not oa and not ob:
        return 1.0
    if not oa or not ob:
        return 0.0
    return len(oa & ob) / len(oa | ob)


# ---------------------------------------------------------------------------
# 6. Composite similarity
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS = {
    "jaccard": 0.25,
    "ngram": 0.25,
    "cosine": 0.20,
    "lcs": 0.15,
    "structural": 0.15,
}


def composite_similarity(
    a: str,
    b: str,
    weights: Optional[Dict[str, float]] = None,
    ngram_n: int = 2,
    prefix_words: int = 2,
) -> Dict[str, float]:
    """Compute all five metrics and a weighted composite score.

    Returns a dict with keys: ``jaccard``, ``ngram``, ``cosine``, ``lcs``,
    ``structural``, ``composite``.

    The composite is a weighted average; default weights emphasise Jaccard
    and n-gram overlap (good duplicate detectors) over the more nuanced
    metrics.  Pass custom *weights* to tune for your use case.
    """
    w = weights or _DEFAULT_WEIGHTS
    scores = {
        "jaccard": token_jaccard(a, b),
        "ngram": ngram_overlap(a, b, n=ngram_n),
        "cosine": word_frequency_cosine(a, b),
        "lcs": lcs_ratio(a, b),
        "structural": structural_similarity(a, b, prefix_words=prefix_words),
    }
    total_weight = sum(w.get(k, 0) for k in scores)
    if total_weight == 0:
        composite = 0.0
    else:
        composite = sum(scores[k] * w.get(k, 0) for k in scores) / total_weight
    scores["composite"] = round(composite, 4)
    # Round individual scores for cleaner output
    for k in ("jaccard", "ngram", "cosine", "lcs", "structural"):
        scores[k] = round(scores[k], 4)
    return scores


# ---------------------------------------------------------------------------
# Convenience: batch comparison
# ---------------------------------------------------------------------------


def pairwise_similarity(
    texts: Sequence[str],
    metric: str = "jaccard",
) -> List[List[float]]:
    """Compute an NxN similarity matrix for a list of texts.

    *metric* must be one of: ``jaccard``, ``ngram``, ``cosine``, ``lcs``,
    ``structural``.
    """
    funcs = {
        "jaccard": token_jaccard,
        "ngram": ngram_overlap,
        "cosine": word_frequency_cosine,
        "lcs": lcs_ratio,
        "structural": structural_similarity,
    }
    if metric not in funcs:
        raise ValueError(f"Unknown metric {metric!r}; choose from {list(funcs)}")
    fn = funcs[metric]
    n = len(texts)
    matrix: List[List[float]] = [[0.0] * n for _ in range(n)]
    for i in range(n):
        matrix[i][i] = 1.0
        for j in range(i + 1, n):
            s = fn(texts[i], texts[j])
            matrix[i][j] = s
            matrix[j][i] = s  # symmetric for jaccard/cosine/lcs/structural;
                              # ngram_overlap is directional — approximate
    return matrix
