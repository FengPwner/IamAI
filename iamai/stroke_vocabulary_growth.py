"""Stroke vocabulary growth — is the writer's lexicon expanding or plateauing?

``stroke_echo`` catches short-term repetition.  ``stroke_yield_analyzer``
flags retreads at the stroke level.  ``stroke_diversity`` measures category
balance.  None of these answer a longer-range question: **is the writer's
vocabulary growing over time, or has it plateaued?**

A writer that keeps using the same words is not necessarily broken — it
may be深耕 a narrow domain.  But a writer whose vocabulary *never*
expands is likely in a rut: generating text that looks varied on the
surface but says the same things in the same ways.

This module tracks **type-token ratio (TTR)** and its moving variant
over time windows, then classifies the growth trend.

Concepts
--------

======================  ================================================
term                    meaning
======================  ================================================
**type-token ratio**    unique words / total words in a text sample;
                        higher = more diverse vocabulary
**moving TTR**          TTR computed over a sliding window of N strokes;
                        smooths out local variation
**growth_rate**         change in moving TTR between the first and second
                        half of the analysis window
**novel_word_ratio**     fraction of words in recent strokes that do not
                        appear in earlier strokes
======================  ================================================

Growth bands
------------

==============  =====================================================
band            meaning
==============  =====================================================
``expanding``   growth_rate > +0.02 — vocabulary is broadening
``stable``      |growth_rate| <= 0.02 — vocabulary is steady
``contracting`` growth_rate < -0.02 — vocabulary is narrowing
``depleted``    novel_word_ratio < 0.05 in the most recent quarter —
                the writer is almost entirely reusing old words
==============  =====================================================

Public API
----------

- ``vocabulary_growth(strokes, window=100) -> dict``
- ``classify_growth(growth_rate, novel_word_ratio) -> str``
- ``compute_ttr(words) -> float``
- ``moving_ttr(strokes, window_size=20) -> list[float]``
- ``novel_words(recent_words, baseline_words) -> set[str]``
- ``growth_summary(strokes, window=100) -> str``
"""

from __future__ import annotations

import re
from typing import Sequence


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.IGNORECASE)

# Common English stop words that add bulk without signal.
_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "because", "but", "and", "or", "if", "while",
    "that", "this", "these", "those", "it", "its", "they", "them",
    "their", "we", "our", "you", "your", "i", "me", "my", "he", "she",
    "him", "her", "his", "what", "which", "who", "whom",
})


def _tokenise(text: str) -> list[str]:
    """Lowercase tokenise, stripping stop words and short tokens."""
    words = _WORD_RE.findall(text.lower())
    return [w for w in words if len(w) > 1 and w not in _STOP_WORDS]


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------


def compute_ttr(words: Sequence[str]) -> float:
    """Type-token ratio: unique words / total words.

    Returns 0.0 for an empty sequence.

    >>> compute_ttr(["alpha", "beta", "alpha", "gamma"])
    0.75
    >>> compute_ttr([])
    0.0
    """
    if not words:
        return 0.0
    return len(set(words)) / len(words)


def moving_ttr(
    strokes: list[dict],
    window_size: int = 20,
    text_key: str = "text",
) -> list[float]:
    """Compute TTR over a sliding window of strokes.

    Each stroke's text is tokenised; the TTR is computed over the
    concatenated tokens in the window centred (as possible) on each
    stroke.

    Returns a list of TTR values, one per stroke (padded at edges so
    the output length equals the input length).

    >>> strokes = [{"text": "alpha beta gamma"}] * 5
    >>> m = moving_ttr(strokes, window_size=3)
    >>> len(m)
    5
    """
    if not strokes:
        return []

    all_tokens: list[list[str]] = []
    for s in strokes:
        all_tokens.append(_tokenise(s.get(text_key, "")))

    half = window_size // 2
    results: list[float] = []

    for i in range(len(strokes)):
        lo = max(0, i - half)
        hi = min(len(strokes), i + half + 1)
        window_words: list[str] = []
        for j in range(lo, hi):
            window_words.extend(all_tokens[j])
        results.append(compute_ttr(window_words))

    return results


def novel_words(
    recent_words: Sequence[str],
    baseline_words: Sequence[str],
) -> set[str]:
    """Words appearing in *recent* but not in *baseline*.

    >>> novel_words(["alpha", "beta", "gamma"], ["alpha", "delta"])
    {'beta', 'gamma'}
    """
    baseline_set = set(baseline_words)
    return set(recent_words) - baseline_set


def _split_words(
    strokes: list[dict],
    text_key: str = "text",
) -> tuple[list[str], list[str]]:
    """Split stroke tokens into first-half (baseline) and second-half (recent)."""
    all_words: list[str] = []
    for s in strokes:
        all_words.extend(_tokenise(s.get(text_key, "")))
    mid = len(all_words) // 2
    return all_words[:mid], all_words[mid:]


def classify_growth(growth_rate: float, novel_word_ratio: float) -> str:
    """Classify vocabulary growth trend.

    Args:
        growth_rate: change in TTR between halves (positive = expanding)
        novel_word_ratio: fraction of recent words that are novel

    Returns one of: ``expanding``, ``stable``, ``contracting``, ``depleted``.

    >>> classify_growth(0.05, 0.3)
    'expanding'
    >>> classify_growth(0.01, 0.2)
    'stable'
    >>> classify_growth(-0.04, 0.1)
    'contracting'
    >>> classify_growth(-0.01, 0.02)
    'depleted'
    """
    if novel_word_ratio < 0.05:
        return "depleted"
    if growth_rate > 0.02:
        return "expanding"
    if growth_rate < -0.02:
        return "contracting"
    return "stable"


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def vocabulary_growth(
    strokes: list[dict],
    window: int = 100,
    text_key: str = "text",
) -> dict:
    """Analyse vocabulary growth over a window of strokes.

    Args:
        strokes: list of stroke dicts, each with a ``text`` field
        window: max number of recent strokes to analyse
        text_key: key for the text field in each stroke dict

    Returns:
        dict with keys:
            - ``band``: expanding / stable / contracting / depleted
            - ``ttr_first_half``: TTR of the baseline half
            - ``ttr_second_half``: TTR of the recent half
            - ``growth_rate``: ttr_second_half - ttr_first_half
            - ``novel_word_count``: number of words new to recent half
            - ``novel_word_ratio``: novel words / total recent words
            - ``total_words``: total content words analysed
            - ``unique_words``: total unique content words
            - ``overall_ttr``: TTR over the entire window
            - ``stroke_count``: number of strokes analysed
    """
    recent_strokes = strokes[-window:] if len(strokes) > window else strokes

    all_words: list[str] = []
    for s in recent_strokes:
        all_words.extend(_tokenise(s.get(text_key, "")))

    if len(all_words) < 4:
        return {
            "band": "stable",
            "ttr_first_half": 0.0,
            "ttr_second_half": 0.0,
            "growth_rate": 0.0,
            "novel_word_count": 0,
            "novel_word_ratio": 0.0,
            "total_words": len(all_words),
            "unique_words": len(set(all_words)),
            "overall_ttr": compute_ttr(all_words),
            "stroke_count": len(recent_strokes),
        }

    mid = len(all_words) // 2
    baseline_words = all_words[:mid]
    recent_words = all_words[mid:]

    ttr_baseline = compute_ttr(baseline_words)
    ttr_recent = compute_ttr(recent_words)
    growth_rate = ttr_recent - ttr_baseline

    novel = novel_words(recent_words, baseline_words)
    novel_ratio = len(novel) / len(recent_words) if recent_words else 0.0

    band = classify_growth(growth_rate, novel_ratio)

    return {
        "band": band,
        "ttr_first_half": round(ttr_baseline, 4),
        "ttr_second_half": round(ttr_recent, 4),
        "growth_rate": round(growth_rate, 4),
        "novel_word_count": len(novel),
        "novel_word_ratio": round(novel_ratio, 4),
        "total_words": len(all_words),
        "unique_words": len(set(all_words)),
        "overall_ttr": round(compute_ttr(all_words), 4),
        "stroke_count": len(recent_strokes),
    }


def growth_summary(
    strokes: list[dict],
    window: int = 100,
    text_key: str = "text",
) -> str:
    """One-line summary of vocabulary growth for caretaker logs.

    Example::

        "expanding — TTR 0.42→0.47 (+0.05), 38 novel words (18.2% of recent), 860 words total"
    """
    info = vocabulary_growth(strokes, window=window, text_key=text_key)
    return (
        f"{info['band']} — TTR {info['ttr_first_half']}→{info['ttr_second_half']} "
        f"({info['growth_rate']:+.4f}), "
        f"{info['novel_word_count']} novel words "
        f"({info['novel_word_ratio']:.1%} of recent), "
        f"{info['total_words']} words total"
    )
