#!/usr/bin/env python3
"""writer_vocabulary_richness — is the writer's lexicon growing or stagnating?

An automated writer that keeps producing text is not necessarily
*thinking*.  One sign of genuine variety is **vocabulary richness**:
does each new piece use words and constructions the previous pieces
didn't?  A writer trapped in templates repeats the same stock phrases
with minor substitutions, and that shows up in the numbers long before
a human reader notices.

This module quantifies lexical diversity across a sliding window of
text samples (strokes, commit messages, notes, anything) and tracks
whether richness is improving over time.

Signal dimensions
-----------------

========================  ================================================
metric                    meaning
========================  ================================================
type_token_ratio          unique tokens / total tokens (Yule's TTR)
hapax_ratio               tokens used exactly once / unique tokens
lexical_density           content-word tokens / total tokens
phrase_repetition         fraction of 3-gram phrases seen more than once
                          in the window
novelty_fraction          fraction of tokens in the *current* sample that
                          do not appear in any prior sample in the window
richness_score            composite 0.0–1.0 score
richness_class            flourishing | growing | stable | narrowing |
                          stagnant
========================  ================================================

Richness classes
-----------------

==============  ============================================================
class           meaning
==============  ============================================================
flourishing     score ≥ 0.80 — vocabulary is expanding rapidly
growing         0.60 ≤ score < 0.80 — steady expansion
stable          0.40 ≤ score < 0.60 — holding steady, acceptable reuse
narrowing       0.20 ≤ score < 0.40 — vocabulary shrinking toward clichés
stagnant        score < 0.20 — near-total repetition, template output
==============  ============================================================

Public API
----------
- ``TextSample`` — data class for one text sample
- ``RichnessResult`` — data class for one window's analysis
- ``RichnessTrend`` — data class for a trend across windows
- ``compute_richness(samples, *, window=5) -> RichnessResult``
- ``classify_richness(score) -> str``
- ``richness_report(result) -> str``
- ``richness_trend(results) -> RichnessTrend``
- ``trend_report(trend) -> str``

Usage::

    from iamai.writer_vocabulary_richness import TextSample, compute_richness

    samples = [
        TextSample(label="stroke-1", text="the caretaker visits and fixes the broken pipe"),
        TextSample(label="stroke-2", text="the caretaker notices a crack in the foundation"),
        TextSample(label="stroke-3", text="a new visitor arrives carrying a lantern and a map"),
    ]
    r = compute_richness(samples)
    print(r.richness_class)   # "growing"
    print(r.richness_score)  # 0.68
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Set


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TextSample:
    """One piece of text from the writer."""

    label: str = ""
    text: str = ""


@dataclass
class RichnessResult:
    """Analysis result for one window of samples."""

    sample_count: int = 0
    window_size: int = 0
    type_token_ratio: float = 0.0
    hapax_ratio: float = 0.0
    lexical_density: float = 0.0
    phrase_repetition: float = 0.0
    novelty_fraction: float = 0.0
    richness_score: float = 0.0
    richness_class: str = "stagnant"
    total_tokens: int = 0
    unique_tokens: int = 0
    hapax_count: int = 0


@dataclass
class RichnessTrend:
    """Trend analysis across multiple richness windows."""

    scores: List[float] = field(default_factory=list)
    trend: str = "unknown"
    slope: float = 0.0
    mean: float = 0.0
    stddev: float = 0.0


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

# Common English stop words (minimal set; not aggressive)
_STOP_WORDS: Set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "no", "only", "own", "same", "than",
    "too", "very", "just", "because", "if", "when", "where", "how",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "it", "its", "i", "me", "my", "we", "our", "you", "your", "he",
    "him", "his", "she", "her", "they", "them", "their",
}

_TOKEN_RE = re.compile(r"[a-z']+")


def _tokenise(text: str) -> List[str]:
    """Lowercase tokenise, keeping alphabetic tokens only."""
    return _TOKEN_RE.findall(text.lower())


def _content_tokens(tokens: Sequence[str]) -> List[str]:
    """Filter out stop words to get content-bearing tokens."""
    return [t for t in tokens if t not in _STOP_WORDS]


# ---------------------------------------------------------------------------
# Metric computations
# ---------------------------------------------------------------------------


def _type_token_ratio(tokens: Sequence[str]) -> float:
    """Yule's type-token ratio: unique / total."""
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def _hapax_ratio(tokens: Sequence[str]) -> float:
    """Fraction of unique tokens that appear exactly once (hapax legomena)."""
    if not tokens:
        return 0.0
    freq: dict[str, int] = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    hapax = sum(1 for v in freq.values() if v == 1)
    unique = len(freq)
    if unique == 0:
        return 0.0
    return hapax / unique


def _lexical_density(tokens: Sequence[str]) -> float:
    """Content tokens / total tokens."""
    if not tokens:
        return 0.0
    content = _content_tokens(tokens)
    return len(set(content)) / len(tokens)


def _trigrams(tokens: Sequence[str]) -> List[str]:
    """Extract space-joined trigram phrases."""
    if len(tokens) < 3:
        return []
    return [f"{tokens[i]} {tokens[i+1]} {tokens[i+2]}"
            for i in range(len(tokens) - 2)]


def _phrase_repetition(tokens: Sequence[str]) -> float:
    """Fraction of trigram phrases that appear more than once."""
    tris = _trigrams(tokens)
    if not tris:
        return 0.0
    freq: dict[str, int] = {}
    for t in tris:
        freq[t] = freq.get(t, 0) + 1
    repeated = sum(1 for v in freq.values() if v > 1)
    total_unique = len(freq)
    if total_unique == 0:
        return 0.0
    return repeated / total_unique


def _novelty_fraction(
    current_tokens: Sequence[str],
    prior_tokens: Sequence[str],
) -> float:
    """Fraction of current tokens not seen in prior samples."""
    if not current_tokens:
        return 0.0
    prior_set = set(prior_tokens)
    novel = sum(1 for t in set(current_tokens) if t not in prior_set)
    unique_current = len(set(current_tokens))
    if unique_current == 0:
        return 0.0
    return novel / unique_current


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------


def _compute_score(
    ttr: float,
    hapax: float,
    lex_density: float,
    phrase_rep: float,
    novelty: float,
) -> float:
    """Weighted composite score, clamped to [0, 1].

    Weights:
        TTR       0.25 — basic diversity signal
        hapax     0.20 — one-shot usage indicates exploration
        lex_dens  0.15 — content density vs filler
        phrase_rep 0.15 — inverted: repetition is bad
        novelty   0.25 — new words relative to prior window
    """
    raw = (
        0.25 * ttr
        + 0.20 * hapax
        + 0.15 * lex_density
        + 0.15 * (1.0 - phrase_rep)
        + 0.25 * novelty
    )
    return round(max(0.0, min(1.0, raw)), 4)


def classify_richness(score: float) -> str:
    """Map a 0–1 score to a richness class label."""
    s = max(0.0, min(1.0, score))
    if s >= 0.80:
        return "flourishing"
    if s >= 0.60:
        return "growing"
    if s >= 0.40:
        return "stable"
    if s >= 0.20:
        return "narrowing"
    return "stagnant"


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------


def compute_richness(
    samples: Sequence[TextSample],
    *,
    window: int = 5,
) -> RichnessResult:
    """Analyse vocabulary richness over the last ``window`` samples.

    Parameters
    ----------
    samples:
        Ordered sequence of TextSample (oldest first).
    window:
        Number of samples to include.  If fewer samples exist, uses all.

    Returns
    -------
    RichnessResult with all metrics computed.
    """
    if not samples:
        return RichnessResult(window_size=window)

    effective = samples[-window:]
    effective_window = len(effective)

    # Tokenise each sample
    tokenised = [_tokenise(s.text) for s in effective]
    all_tokens = [t for toks in tokenised for t in toks]

    if not all_tokens:
        return RichnessResult(
            sample_count=effective_window,
            window_size=window,
        )

    # Metrics on the combined window
    ttr = _type_token_ratio(all_tokens)
    hapax = _hapax_ratio(all_tokens)
    lex_density = _lexical_density(all_tokens)
    phrase_rep = _phrase_repetition(all_tokens)

    # Novelty: current sample vs all prior in the window
    current_tokens = tokenised[-1] if tokenised else []
    prior_tokens = [t for toks in tokenised[:-1] for t in toks]
    novelty = _novelty_fraction(current_tokens, prior_tokens)

    score = _compute_score(ttr, hapax, lex_density, phrase_rep, novelty)

    return RichnessResult(
        sample_count=effective_window,
        window_size=window,
        type_token_ratio=round(ttr, 4),
        hapax_ratio=round(hapax, 4),
        lexical_density=round(lex_density, 4),
        phrase_repetition=round(phrase_rep, 4),
        novelty_fraction=round(novelty, 4),
        richness_score=score,
        richness_class=classify_richness(score),
        total_tokens=len(all_tokens),
        unique_tokens=len(set(all_tokens)),
        hapax_count=sum(
            1 for t in set(all_tokens)
            if all_tokens.count(t) == 1
        ),
    )


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


def _linear_slope(values: Sequence[float]) -> float:
    """Simple linear regression slope (y ~ index)."""
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


def _stddev(values: Sequence[float]) -> float:
    """Population standard deviation."""
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return variance ** 0.5


def richness_trend(results: Sequence[RichnessResult]) -> RichnessTrend:
    """Analyse the trend across multiple richness windows.

    Parameters
    ----------
    results:
        Ordered sequence of RichnessResult (oldest first).

    Returns
    -------
    RichnessTrend with slope, trend label, and summary stats.
    """
    if not results:
        return RichnessTrend()

    scores = [r.richness_score for r in results]
    slope = _linear_slope(scores)
    mean = sum(scores) / len(scores)
    sd = _stddev(scores)

    if slope > 0.02:
        trend = "improving"
    elif slope < -0.02:
        trend = "degrading"
    else:
        trend = "stable"

    return RichnessTrend(
        scores=scores,
        trend=trend,
        slope=round(slope, 4),
        mean=round(mean, 4),
        stddev=round(sd, 4),
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def richness_report(result: RichnessResult) -> str:
    """Human-readable summary of a vocabulary richness analysis."""
    lines = [
        f"Vocabulary richness: {result.richness_class} "
        f"(score={result.richness_score:.2f})",
        f"  samples analysed : {result.sample_count}",
        f"  window size      : {result.window_size}",
        f"  total tokens     : {result.total_tokens}",
        f"  unique tokens    : {result.unique_tokens}",
        f"  type-token ratio : {result.type_token_ratio:.3f}",
        f"  hapax ratio      : {result.hapax_ratio:.3f}",
        f"  lexical density  : {result.lexical_density:.3f}",
        f"  phrase repetition: {result.phrase_repetition:.3f}",
        f"  novelty fraction : {result.novelty_fraction:.3f}",
    ]
    return "\n".join(lines)


def trend_report(trend: RichnessTrend) -> str:
    """Human-readable summary of a vocabulary richness trend."""
    if not trend.scores:
        return "No vocabulary richness data available."
    lines = [
        f"Vocabulary trend: {trend.trend} (slope={trend.slope:+.4f})",
        f"  windows analysed: {len(trend.scores)}",
        f"  mean score      : {trend.mean:.2f}",
        f"  stddev          : {trend.stddev:.2f}",
        f"  recent scores   : "
        f"{', '.join(f'{s:.2f}' for s in trend.scores[-5:])}",
    ]
    return "\n".join(lines)
