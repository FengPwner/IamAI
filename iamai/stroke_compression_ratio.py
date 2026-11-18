#!/usr/bin/env python3
"""stroke_compression_ratio — measure information density of strokes.

The writer produces short texts (aphorisms, observations, metrics, code
snippets).  Over time, the *raw length* of strokes may stay constant
while their *information content* quietly deflates — the same ideas
repackaged in different words, boilerplate padding, or template fills
that add characters without adding meaning.

This module quantifies the **compression ratio** of each stroke: how
much unique information is packed into its raw token count.

Core metric
-----------

``compression_ratio = unique_tokens / total_tokens``

A ratio of 1.0 means every token is unique (maximum density).
A ratio of 0.3 in a 10-token stroke means 7 tokens are repeated words
(articles, conjunctions, template fragments).

Analysis dimensions
-------------------

===================  ====================================================
metric               meaning
===================  ====================================================
global_ratio         mean compression ratio across the entire corpus
kind_ratios          per-kind mean compression ratios
length_correlation   Pearson r between stroke length and compression
                     ratio; negative = longer strokes are more padded
recent_trend         slope of compression ratio over the last N strokes;
                     negative = information density is declining
diminishing_returns  fraction of strokes in the second half that score
                     below the first-half median
worst_strokes        list of (seq, text, ratio) for the N lowest-density
                     strokes
===================  ====================================================

Interpretation guide
--------------------

=========  ========  ===================================================
ratio      grade     meaning
=========  ========  ===================================================
≥ 0.80     A         high density — nearly every word earns its place
0.60–0.79  B         good — natural language with some function words
0.40–0.59  C         moderate — noticeable padding or repetition
0.20–0.39  D         low — heavily templated or boilerplate
< 0.20     F         near-zero information — mostly filler
=========  ========  ===================================================

The ``diminishing_returns`` metric is the key signal for writer fatigue:
when later strokes consistently score below the earlier median, the
writer is running out of things to say and filling space.

Public API
----------
- ``CompressionReport``: dataclass with all analysis dimensions
- ``compress_ratio(text) -> float``: single-stroke density
- ``analyze_corpus(strokes, ...) -> CompressionReport``
- ``grade_ratio(ratio) -> str``: letter grade for a ratio value

Usage::

    from iamai.stroke_compression_ratio import analyze_corpus
    import json

    strokes = [json.loads(line) for line in open("data/strokes.jsonl")]
    report = analyze_corpus(strokes)
    print(report.global_ratio)        # 0.62
    print(report.recent_trend)        # -0.003
    print(report.diminishing_returns)  # 0.71
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StrokeScore:
    """Compression score for a single stroke."""

    seq: int
    text: str
    kind: str
    total_tokens: int
    unique_tokens: int
    ratio: float

    def grade(self) -> str:
        return grade_ratio(self.ratio)


@dataclass
class CompressionReport:
    """Aggregate compression analysis of a stroke corpus."""

    global_ratio: float
    kind_ratios: dict
    length_correlation: float
    recent_trend: float
    diminishing_returns: float
    worst_strokes: list
    total_strokes: int
    mean_length: float
    scores: list = field(default_factory=list, repr=False)


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-zA-Z0-9']+")


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenise, keeping alphanumeric + apostrophe."""
    return _TOKEN_RE.findall(text.lower())


# ---------------------------------------------------------------------------
# Core metric
# ---------------------------------------------------------------------------

def compress_ratio(text: str) -> float:
    """Return the compression ratio for a single text.

    Returns 1.0 for empty text (no padding possible).
    """
    tokens = _tokenize(text)
    if not tokens:
        return 1.0
    return len(set(tokens)) / len(tokens)


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

_GRADE_TABLE = [
    (0.80, "A"),
    (0.60, "B"),
    (0.40, "C"),
    (0.20, "D"),
    (0.00, "F"),
]


def grade_ratio(ratio: float) -> str:
    """Map a compression ratio to a letter grade."""
    for threshold, grade in _GRADE_TABLE:
        if ratio >= threshold:
            return grade
    return "F"


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation coefficient.  Returns 0.0 for degenerate input."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = statistics.mean(xs)
    my = statistics.mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / n)
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / n)
    if sx == 0.0 or sy == 0.0:
        return 0.0
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    return cov / (sx * sy)


def _linear_slope(ys: Sequence[float]) -> float:
    """Slope of OLS fit y ~ x for x = 0, 1, 2, ….  Returns 0.0 for <2 pts."""
    n = len(ys)
    if n < 2:
        return 0.0
    xs_mean = (n - 1) / 2.0
    ys_mean = statistics.mean(ys)
    num = sum((i - xs_mean) * (y - ys_mean) for i, y in enumerate(ys))
    den = sum((i - xs_mean) ** 2 for i in range(n))
    if den == 0.0:
        return 0.0
    return num / den


# ---------------------------------------------------------------------------
# Corpus analysis
# ---------------------------------------------------------------------------

def _score_stroke(stroke: dict) -> StrokeScore:
    """Score a single stroke dict."""
    text = stroke.get("text", "")
    kind = stroke.get("kind", "unknown")
    seq = stroke.get("seq", 0)
    tokens = _tokenize(text)
    total = len(tokens)
    unique = len(set(tokens))
    ratio = (unique / total) if total > 0 else 1.0
    return StrokeScore(
        seq=seq,
        text=text,
        kind=kind,
        total_tokens=total,
        unique_tokens=unique,
        ratio=ratio,
    )


def analyze_corpus(
    strokes: list[dict],
    recent_window: int = 50,
    worst_count: int = 5,
) -> CompressionReport:
    """Analyse compression ratios across a corpus of strokes.

    Parameters
    ----------
    strokes:
        List of stroke dicts, each with at least ``text`` and ``kind``.
        Must contain at least 1 stroke; empty lists raise ValueError.
    recent_window:
        Number of trailing strokes to use for ``recent_trend``.
    worst_count:
        How many lowest-density strokes to include in ``worst_strokes``.

    Returns
    -------
    CompressionReport with all dimensions populated.
    """
    if not strokes:
        raise ValueError("strokes list must not be empty")

    scores = [_score_stroke(s) for s in strokes]
    ratios = [s.ratio for s in scores]
    lengths = [s.total_tokens for s in scores]

    # Global ratio
    global_ratio = statistics.mean(ratios) if ratios else 1.0

    # Per-kind ratios
    kind_buckets: dict[str, list[float]] = {}
    for s in scores:
        kind_buckets.setdefault(s.kind, []).append(s.ratio)
    kind_ratios = {
        k: statistics.mean(v) for k, v in sorted(kind_buckets.items())
    }

    # Length correlation
    length_correlation = _pearson(lengths, ratios)

    # Recent trend (slope over trailing window)
    recent = ratios[-recent_window:] if len(ratios) >= recent_window else ratios
    recent_trend = _linear_slope(recent)

    # Diminishing returns: fraction of second-half below first-half median
    mid = len(scores) // 2
    if mid < 1:
        diminishing_returns = 0.0
    else:
        first_half_median = statistics.median(ratios[:mid])
        second_half = ratios[mid:]
        below_count = sum(1 for r in second_half if r < first_half_median)
        diminishing_returns = below_count / len(second_half)

    # Worst strokes
    sorted_scores = sorted(scores, key=lambda s: s.ratio)
    worst_strokes = [
        (s.seq, s.text[:80], round(s.ratio, 4))
        for s in sorted_scores[:worst_count]
    ]

    mean_length = statistics.mean(lengths) if lengths else 0.0

    return CompressionReport(
        global_ratio=round(global_ratio, 4),
        kind_ratios={k: round(v, 4) for k, v in kind_ratios.items()},
        length_correlation=round(length_correlation, 4),
        recent_trend=round(recent_trend, 6),
        diminishing_returns=round(diminishing_returns, 4),
        worst_strokes=worst_strokes,
        total_strokes=len(scores),
        mean_length=round(mean_length, 2),
        scores=scores,
    )
