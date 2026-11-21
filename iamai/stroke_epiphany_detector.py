#!/usr/bin/env python3
"""stroke_epiphany_detector — detect and score 'aha moments' in strokes.

An epiphany is a moment where the writer shifts from *observing* to
*understanding*.  It is linguistically marked by:

1. **realization phrases** — "turns out", "I realize", "the key is",
   "what actually matters", "the insight is", "it became clear"
2. **contrast markers** — "not X but Y", "actually", "in fact",
   "rather than", "the opposite", "counterintuitive"
3. **reversal markers** — "I used to think", "initially", "at first",
   "what I missed was", "I was wrong", "the opposite is true"
4. **crystallisation** — short, punchy summaries that compress a longer
   chain of reasoning into one line — detected heuristically as a
   sentence under a word-count threshold that contains a contrast or
   a realisation marker.

per stroke:
  - epiphany_score: float in [0, 1]
  - markers_found: list of marker category hits
  - is_epiphany: bool (score >= threshold)

aggregate (over a series):
  - epiphany_rate: fraction of strokes that qualify as epiphanies
  - mean_epiphany_score: average score across the series
  - epiphany_trend: linear slope (positive = insights accelerating)
  - total_epiphanies: absolute count
  - top_epiphanies: the highest-scoring strokes (capped)

This module is orthogonal to the existing metrics:

- **grounding_density** measures concrete-vs-abstract evidence.
  An epiphany can be grounded (a specific insight about commit 587)
  or ungrounded (a meta-realisation about the nature of writing).

- **specificity_scorer** measures precision of reference.
  An epiphany is precise about *what changed in understanding*, not
  necessarily about external facts.

- **synthesis_depth** measures combination of prior ideas.
  An epiphany *is* a synthesis, but synthesis is not always an
  epiphany — you can combine ideas without a breakthrough moment.

- **novelty** measures information-theoretic surprise.
  An epiphany is subjectively surprising to the *writer*, even if
  the content is informationally similar to prior strokes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# marker patterns
# ---------------------------------------------------------------------------

_REALIZATION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bturns?\s+out\b", re.I),
    re.compile(r"\bi\s+realize[d]?\b", re.I),
    re.compile(r"\bi\s+realise[d]?\b", re.I),
    re.compile(r"\bthe\s+key\s+(?:is|was|insight)\b", re.I),
    re.compile(r"\bwhat\s+actually\s+matters\b", re.I),
    re.compile(r"\bthe\s+insight\s+(?:is|was)\b", re.I),
    re.compile(r"\bit\s+became?\s+clear\b", re.I),
    re.compile(r"\bnow\s+i\s+see\b", re.I),
    re.compile(r"\bthe\s+aha\b", re.I),
    re.compile(r"\bhere.s\s+the\s+thing\b", re.I),
    re.compile(r"\bthat.s\s+the\s+point\b", re.I),
    re.compile(r"\bsuddenly\b", re.I),
    re.compile(r"\bof\s+course[!.]\b", re.I),
    re.compile(r"\bthe\s+real\s+(?:issue|problem|reason|cause)\b", re.I),
    re.compile(r"\bwhat\s+i\s+missed\b", re.I),
    re.compile(r"\bthe\s+missing\s+piece\b", re.I),
]

_CONTRAST_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bnot\s+\w+\s+but\b", re.I),
    re.compile(r"\bactually\b", re.I),
    re.compile(r"\bin\s+fact\b", re.I),
    re.compile(r"\brather\s+than\b", re.I),
    re.compile(r"\bthe\s+opposite\b", re.I),
    re.compile(r"\bcounterintuitive\b", re.I),
    re.compile(r"\bparadoxically\b", re.I),
    re.compile(r"\bon\s+the\s+contrary\b", re.I),
    re.compile(r"\bironically\b", re.I),
    re.compile(r"\bnot\s+\w+\s*[;,]\s+\w+\b", re.I),
]

_REVERSAL_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bi\s+(?:used\s+to|would)\s+think\b", re.I),
    re.compile(r"\binitially\b", re.I),
    re.compile(r"\bat\s+first\b", re.I),
    re.compile(r"\bi\s+was\s+wrong\b", re.I),
    re.compile(r"\bi\s+had\s+it\s+backwards?\b", re.I),
    re.compile(r"\bwhat\s+i\s+missed\s+was\b", re.I),
    re.compile(r"\bthe\s+opposite\s+is\s+true\b", re.I),
    re.compile(r"\bmy\s+mistake\s+was\b", re.I),
    re.compile(r"\bi\s+overlooked\b", re.I),
    re.compile(r"\bi\s+assumed\b", re.I),
]


# ---------------------------------------------------------------------------
# weights
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "realization": 0.40,
    "contrast": 0.25,
    "reversal": 0.35,
}

_EPIPHANY_THRESHOLD = 0.35
_SHORT_SENTENCE_WORDS = 18  # crystallisation heuristic


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------


@dataclass
class EpiphanyResult:
    """Per-stroke epiphany analysis."""

    epiphany_score: float
    markers_found: Dict[str, List[str]] = field(default_factory=dict)
    is_epiphany: bool = False


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _count_pattern_matches(
    patterns: Sequence[re.Pattern], text: str
) -> tuple[int, List[str]]:
    """Return (count, list of matched pattern strings)."""
    matched: List[str] = []
    count = 0
    for pat in patterns:
        hits = pat.findall(text)
        if hits:
            count += len(hits)
            matched.extend(hits)
    return count, matched


def _sentence_count(text: str) -> int:
    """Rough sentence count via terminal punctuation."""
    if not text.strip():
        return 0
    # split on sentence-ending punctuation
    sentences = re.split(r"[.!?]+", text)
    return max(1, sum(1 for s in sentences if s.strip()))


def _word_count(text: str) -> int:
    """Simple whitespace word count."""
    return len(text.split())


def _has_crystallisation(text: str, has_marker: bool) -> bool:
    """Detect short, punchy sentences that contain a contrast or realisation."""
    if not has_marker:
        return False
    sentences = re.split(r"[.!?]+", text)
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        wc = _word_count(sent)
        if wc <= _SHORT_SENTENCE_WORDS and wc >= 3:
            # check if this specific sentence has a marker
            for pats in [_REALIZATION_PATTERNS, _CONTRAST_PATTERNS, _REVERSAL_PATTERNS]:
                for pat in pats:
                    if pat.search(sent):
                        return True
    return False


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def score(text: str) -> EpiphanyResult:
    """Score a single stroke for epiphany markers.

    Returns an EpiphanyResult with score in [0, 1].
    """
    if not text or not text.strip():
        return EpiphanyResult(epiphany_score=0.0)

    real_count, real_matches = _count_pattern_matches(_REALIZATION_PATTERNS, text)
    cont_count, cont_matches = _count_pattern_matches(_CONTRAST_PATTERNS, text)
    rev_count, rev_matches = _count_pattern_matches(_REVERSAL_PATTERNS, text)

    # normalise by word count to avoid bias toward long strokes
    wc = max(1, _word_count(text))
    rate_factor = min(1.0, 10.0 / wc)  # 10 words = full weight, fewer = less

    # weighted score from marker counts (diminishing returns via tanh-like cap)
    raw = (
        _WEIGHTS["realization"] * min(real_count, 3)
        + _WEIGHTS["contrast"] * min(cont_count, 3)
        + _WEIGHTS["reversal"] * min(rev_count, 2)
    )

    # cap at 3.0 raw → normalise to [0, 1]
    normalised = min(1.0, raw / 2.0)

    # crystallisation bonus: a short punchy sentence with a marker
    has_any_marker = bool(real_matches or cont_matches or rev_matches)
    if _has_crystallisation(text, has_any_marker):
        normalised = min(1.0, normalised + 0.15)

    # rate adjustment: very short texts get a mild discount
    score_val = normalised * (0.7 + 0.3 * rate_factor)
    score_val = round(min(1.0, max(0.0, score_val)), 4)

    markers: Dict[str, List[str]] = {}
    if real_matches:
        markers["realization"] = real_matches
    if cont_matches:
        markers["contrast"] = cont_matches
    if rev_matches:
        markers["reversal"] = rev_matches

    return EpiphanyResult(
        epiphany_score=score_val,
        markers_found=markers,
        is_epiphany=score_val >= _EPIPHANY_THRESHOLD,
    )


def aggregate(
    results: Sequence[EpiphanyResult],
) -> Dict[str, Any]:
    """Aggregate per-stroke results into series-level metrics.

    Parameters
    ----------
    results : sequence of EpiphanyResult
        Per-stroke scores in chronological order.

    Returns
    -------
    dict with keys:
        total_strokes, total_epiphanies, epiphany_rate,
        mean_epiphany_score, max_epiphany_score, min_epiphany_score,
        median_epiphany_score, epiphany_trend, epiphany_indices
    """
    n = len(results)
    if n == 0:
        return {
            "total_strokes": 0,
            "total_epiphanies": 0,
            "epiphany_rate": 0.0,
            "mean_epiphany_score": 0.0,
            "max_epiphany_score": 0.0,
            "min_epiphany_score": 0.0,
            "median_epiphany_score": 0.0,
            "epiphany_trend": 0.0,
            "epiphany_indices": [],
        }

    scores = [r.epiphany_score for r in results]
    epiphany_indices = [i for i, r in enumerate(results) if r.is_epiphany]
    total_epiphanies = len(epiphany_indices)

    # basic stats
    mean_score = sum(scores) / n
    sorted_scores = sorted(scores)
    if n % 2 == 1:
        median_score = sorted_scores[n // 2]
    else:
        median_score = (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2.0

    # trend: simple linear regression on scores
    trend = _linear_slope(scores)

    return {
        "total_strokes": n,
        "total_epiphanies": total_epiphanies,
        "epiphany_rate": round(total_epiphanies / n, 4),
        "mean_epiphany_score": round(mean_score, 4),
        "max_epiphany_score": round(max(scores), 4),
        "min_epiphany_score": round(min(scores), 4),
        "median_epiphany_score": round(median_score, 4),
        "epiphany_trend": round(trend, 6),
        "epiphany_indices": epiphany_indices,
    }


def _linear_slope(values: Sequence[float]) -> float:
    """Compute the slope of a simple linear regression y = a + b*x."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator
