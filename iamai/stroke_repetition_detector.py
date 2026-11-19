"""stroke_repetition_detector — detect self-plagiarism in the stroke stream.

While ``stroke_novelty`` scores each stroke against a sliding window of
recent neighbours and ``stroke_vocabulary_growth`` tracks macro-level
vocabulary expansion, neither directly answers: *is the writer producing
near-duplicate content?*

A self-writing repo running for thousands of strokes inevitably starts
paraphrasing itself.  This module quantifies the problem at three levels:

1. **Stroke-level** — find pairs of strokes whose character-n-gram
   fingerprints are nearly identical (Jaccard similarity ≥ threshold).
2. **Phrase-level** — surface word n-grams that recur disproportionately
   often (a sign of template-thinking).
3. **Category cycling** — detect if the writer cycles through stroke
   categories in a fixed order (devlog→thought→note→snippet→repeat)
   rather than writing whatever the moment calls for.

Algorithm
---------
*Character-n-gram fingerprinting* is cheap, needs no tokeniser, and
handles minor paraphrases (word-order swaps, added adjectives) better
than bag-of-words Jaccard on tokens.

    n-grams(s, k)  = { s[i:i+k] : 0 ≤ i ≤ len(s)-k }
    sim(A, B)      = |n-grams(A) ∩ n-grams(B)| / |n-grams(A) ∪ n-grams(B)|

A pair with sim ≥ 0.70 is flagged as *near-duplicate*.

Regime classification (based on freshness_ratio = 1 − dup_fraction):

==================  =====================================================
freshness_ratio     regime
==================  =====================================================
≥ 0.95              **fresh** — almost no detectable repetition
0.85 – 0.95         **healthy** — occasional echoes, within tolerance
0.70 – 0.85         **echoing** — significant self-plagiarism
< 0.70              **stale** — writer is stuck in a rut
==================  =====================================================

Edge cases
----------
* Empty input -> zeroed report.
* Single stroke -> no pairs possible, freshness = 1.0.
* All strokes identical -> freshness = 1/N (one unique, rest dupes).
* Very short strokes (< k chars) -> excluded from pair detection but
  counted in totals.

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 727, 2026-11-19.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

_NORMALISE_RE = re.compile(r"[^a-z0-9\s]")
_SPACE_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    t = _NORMALISE_RE.sub(" ", text.lower())
    return _SPACE_RE.sub(" ", t).strip()


def char_ngrams(text: str, k: int = 4) -> Set[str]:
    """Return the set of character k-grams in *text*.

    Returns an empty set when the text is shorter than *k* characters
    after normalisation — callers must handle this gracefully.
    """
    t = _normalise(text)
    if len(t) < k:
        return set()
    return {t[i : i + k] for i in range(len(t) - k + 1)}


def jaccard_similarity(a: Set[str], b: Set[str]) -> float:
    """Jaccard coefficient between two sets.

    Returns 0.0 when both sets are empty (no overlap possible).
    """
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def word_ngrams(text: str, n: int = 3) -> List[str]:
    """Return list of word-level n-grams (as joined strings)."""
    words = _normalise(text).split()
    if len(words) < n:
        return []
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DuplicatePair:
    """A pair of strokes flagged as near-duplicates."""

    index_a: int
    index_b: int
    similarity: float
    snippet_a: str
    snippet_b: str

    def __repr__(self) -> str:
        return (
            f"DuplicatePair({self.index_a}↔{self.index_b}, "
            f"sim={self.similarity:.3f})"
        )


@dataclass
class RepetitionReport:
    """Summary of repetition analysis over a batch of strokes."""

    total_strokes: int = 0
    analysable_strokes: int = 0  # strokes long enough for n-gram analysis
    duplicate_pairs: int = 0
    freshness_ratio: float = 1.0
    regime: str = "fresh"
    worst_pairs: List[DuplicatePair] = field(default_factory=list)
    frequent_phrases: List[Tuple[str, int]] = field(default_factory=list)
    category_cycle_score: float = 0.0  # 0 = no cycling, 1 = perfect cycle

    def summary(self) -> Dict:
        """Return a JSON-friendly summary dict."""
        return {
            "total_strokes": self.total_strokes,
            "analysable_strokes": self.analysable_strokes,
            "duplicate_pairs": self.duplicate_pairs,
            "freshness_ratio": round(self.freshness_ratio, 4),
            "regime": self.regime,
            "worst_pairs": [
                {
                    "a": p.index_a,
                    "b": p.index_b,
                    "sim": round(p.similarity, 4),
                    "snippet_a": p.snippet_a[:60],
                    "snippet_b": p.snippet_b[:60],
                }
                for p in self.worst_pairs[:5]
            ],
            "top_phrases": [
                {"phrase": phrase, "count": count}
                for phrase, count in self.frequent_phrases[:10]
            ],
            "category_cycle_score": round(self.category_cycle_score, 4),
        }


# ---------------------------------------------------------------------------
# Core: stroke-level duplicate detection
# ---------------------------------------------------------------------------


def detect_duplicate_pairs(
    texts: Sequence[str],
    threshold: float = 0.70,
    k: int = 4,
    max_pairs: int = 100,
) -> Tuple[List[DuplicatePair], int]:
    """Find all stroke pairs with Jaccard similarity ≥ threshold.

    Parameters
    ----------
    texts : sequence of raw stroke texts
    threshold : float
        Minimum Jaccard similarity to flag as duplicate.
    k : int
        Character n-gram size.
    max_pairs : int
        Stop collecting after this many pairs (performance cap).

    Returns
    -------
    (pairs, analysable_count)
        pairs sorted by similarity descending;
        analysable_count = number of strokes with fingerprints.
    """
    # Pre-compute fingerprints; keep original text for snippets.
    fingerprints: List[Optional[Set[str]]] = []
    for t in texts:
        fp = char_ngrams(t, k)
        fingerprints.append(fp if fp else None)

    analysable = sum(1 for fp in fingerprints if fp is not None)
    pairs: List[DuplicatePair] = []

    # O(n²) scan — fine for repo-sized batches (hundreds to low thousands).
    # For very large streams a minhash / LSH pre-filter would help,
    # but this stays dependency-free.
    n = len(texts)
    for i in range(n):
        if fingerprints[i] is None:
            continue
        for j in range(i + 1, n):
            if fingerprints[j] is None:
                continue
            sim = jaccard_similarity(fingerprints[i], fingerprints[j])
            if sim >= threshold:
                pairs.append(
                    DuplicatePair(
                        index_a=i,
                        index_b=j,
                        similarity=sim,
                        snippet_a=texts[i][:80],
                        snippet_b=texts[j][:80],
                    )
                )
                if len(pairs) >= max_pairs:
                    break
        if len(pairs) >= max_pairs:
            break

    pairs.sort(key=lambda p: p.similarity, reverse=True)
    return pairs, analysable


# ---------------------------------------------------------------------------
# Core: phrase-level repetition
# ---------------------------------------------------------------------------


def find_frequent_phrases(
    texts: Sequence[str],
    n: int = 3,
    min_count: int = 3,
    top_k: int = 20,
) -> List[Tuple[str, int]]:
    """Find word n-grams that appear ≥ min_count times across all strokes.

    Parameters
    ----------
    texts : sequence of raw stroke texts
    n : int
        Word n-gram size.
    min_count : int
        Minimum occurrences to report.
    top_k : int
        Maximum phrases to return.

    Returns
    -------
    List of (phrase, count) sorted by count descending.
    """
    counter: Counter = Counter()
    for t in texts:
        counter.update(word_ngrams(t, n))
    return [
        (phrase, count)
        for phrase, count in counter.most_common(top_k)
        if count >= min_count
    ]


# ---------------------------------------------------------------------------
# Core: category cycling detection
# ---------------------------------------------------------------------------


def detect_category_cycling(
    categories: Sequence[str],
    cycle_lengths: Sequence[int] = (2, 3, 4, 5, 6),
) -> float:
    """Score how strongly the category sequence follows a fixed cycle.

    Tests each candidate cycle length and returns the best match score.

    Parameters
    ----------
    categories : sequence of category labels (e.g. "thought", "note")
    cycle_lengths : candidate cycle periods to test

    Returns
    -------
    float in [0, 1] — fraction of positions that match the best-fit cycle.
    0.0 means no detectable cycling; 1.0 means perfect periodicity.
    """
    if len(categories) < 4:
        return 0.0

    best_score = 0.0
    for period in cycle_lengths:
        if period >= len(categories):
            continue
        # The candidate cycle is the first `period` categories.
        pattern = list(categories[:period])
        matches = sum(
            1 for i, cat in enumerate(categories) if cat == pattern[i % period]
        )
        score = matches / len(categories)
        best_score = max(best_score, score)

    # Subtract the chance-match baseline: with C unique categories and
    # period P, random assignment matches ~1/C of the time.  Rescale
    # so that random -> ~0, perfect -> 1.
    unique_cats = len(set(categories))
    if unique_cats <= 1:
        return 0.0
    chance = 1.0 / unique_cats
    if best_score <= chance:
        return 0.0
    return (best_score - chance) / (1.0 - chance)


# ---------------------------------------------------------------------------
# Regime classification
# ---------------------------------------------------------------------------

def _classify_freshness(freshness: float) -> str:
    if freshness >= 0.95:
        return "fresh"
    if freshness >= 0.85:
        return "healthy"
    if freshness >= 0.70:
        return "echoing"
    return "stale"


# ---------------------------------------------------------------------------
# Top-level analysis
# ---------------------------------------------------------------------------


def analyse_repetition(
    texts: Sequence[str],
    threshold: float = 0.70,
    k: int = 4,
    phrase_n: int = 3,
    phrase_min_count: int = 3,
    categories: Optional[Sequence[str]] = None,
) -> RepetitionReport:
    """Run full repetition analysis on a batch of stroke texts.

    Parameters
    ----------
    texts : sequence of raw stroke texts
    threshold : float
        Jaccard similarity threshold for duplicate detection.
    k : int
        Character n-gram size for fingerprinting.
    phrase_n : int
        Word n-gram size for phrase frequency analysis.
    phrase_min_count : int
        Minimum phrase occurrence count to report.
    categories : optional sequence of category labels
        If provided, category cycling is also analysed.

    Returns
    -------
    RepetitionReport
    """
    total = len(texts)
    if total == 0:
        return RepetitionReport()

    pairs, analysable = detect_duplicate_pairs(texts, threshold, k)

    # Freshness: fraction of strokes NOT involved in any duplicate pair.
    dup_indices: Set[int] = set()
    for p in pairs:
        dup_indices.add(p.index_a)
        dup_indices.add(p.index_b)
    # A stroke appearing in multiple pairs is still counted once.
    dup_count = len(dup_indices)
    freshness = (analysable - dup_count) / analysable if analysable > 0 else 1.0
    freshness = max(0.0, min(1.0, freshness))

    phrases = find_frequent_phrases(texts, phrase_n, phrase_min_count)

    cycle_score = 0.0
    if categories is not None and len(categories) >= 4:
        cycle_score = detect_category_cycling(categories)

    return RepetitionReport(
        total_strokes=total,
        analysable_strokes=analysable,
        duplicate_pairs=len(pairs),
        freshness_ratio=freshness,
        regime=_classify_freshness(freshness),
        worst_pairs=pairs[:10],
        frequent_phrases=phrases[:10],
        category_cycle_score=cycle_score,
    )


# ---------------------------------------------------------------------------
# Sliding-window analysis
# ---------------------------------------------------------------------------


def analyse_repetition_windows(
    texts: Sequence[str],
    window_size: int = 50,
    step: int = 25,
    threshold: float = 0.70,
    k: int = 4,
) -> List[RepetitionReport]:
    """Sliding-window repetition analysis to track freshness over time.

    Parameters
    ----------
    texts : sequence of raw stroke texts
    window_size : int
        Number of strokes per window.
    step : int
        Stride between consecutive windows.
    threshold : float
        Jaccard similarity threshold.
    k : int
        Character n-gram size.

    Returns
    -------
    List of RepetitionReport, one per window.
    """
    if window_size < 2 or step < 1:
        raise ValueError("window_size must be >= 2 and step must be >= 1")

    reports: List[RepetitionReport] = []
    for start in range(0, len(texts) - window_size + 1, step):
        window = texts[start : start + window_size]
        reports.append(analyse_repetition(window, threshold=threshold, k=k))
    return reports
