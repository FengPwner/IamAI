#!/usr/bin/env python3
"""content_drift_index — measure topic diversity across a stroke window.

The stroke_dedup module catches *structural* repetition: the same sentence
template with different numbers plugged in.  But a writer can produce
structurally varied sentences while staying locked on a single topic.
This module catches *thematic* stagnation.

Why this matters
----------------
Visit 780 showed the writer cycling through seven aphorism templates,
each ending with "-- measured now: <metric>".  Dedup caught the structural
exhaustion.  But even if the templates were varied, the *topic* was always
the same: repo metrics.  A content drift index would have flagged this
earlier — the structural fingerprint was diverse, but the semantic content
had flatlined.

The distinction matters for caretaker decision-making:

- **Structural exhaustion + topic stagnation** → the writer needs a
  complete redesign (new prompt, new data sources, new generation strategy)
- **Structural exhaustion + topic drift present** → the writer has ideas
  but is expressing them through a narrow template set (inject templates)
- **Structural diversity + topic stagnation** → the writer is healthy
  syntactically but thematically stuck (inject topics or seed prompts)
- **Structural diversity + topic diversity** → healthy, no intervention

This module provides the second half of that matrix.

Approach
--------

1. **Tokenize** — split text on whitespace and punctuation, lowercase,
   remove stopwords (configurable set).

2. **Content-word extraction** — keep only words longer than
   ``min_word_length`` (default 4) that are not in the stopword set.

3. **Vocabulary richness** — for a window of N strokes, compute:

   - **type_token_ratio (TTR)**: unique content words / total content words.
     High TTR = diverse vocabulary = likely diverse topics.
     Low TTR = repetitive vocabulary = likely stuck on one topic.

   - **hapax_ratio**: words appearing exactly once / total unique words.
     High hapax ratio = many words used only once = exploration.
     Low hapax ratio = same words reused = fixation.

   - **topic_entropy**: Shannon entropy of the word-frequency distribution.
     High entropy = words evenly distributed = broad coverage.
     Low entropy = few words dominate = narrow focus.

4. **Drift score** — composite of the three signals, weighted:

   ``drift = 0.4 * ttr + 0.3 * hapax_ratio + 0.3 * normalised_entropy``

   Where ``normalised_entropy = entropy / log2(vocabulary_size)`` to
   keep it in [0, 1].

5. **Classification**:

   ============  ============  ===============================
   verdict       score range   meaning
   ============  ============  ===============================
   ``drifting``  ≥ 0.70        healthy topic diversity
   ``stable``    0.45 – 0.69   moderate variety, acceptable
   ``anchored``  0.25 – 0.44   narrow topic focus
   ``frozen``    < 0.25        severe topic stagnation
   ============  ============  ===============================

Public API
----------
- ``tokenize(text, stopwords=None, min_word_length=4) -> list[str]``
- ``vocabulary_stats(tokens) -> VocabStats``
- ``drift_score(tokens) -> float``
- ``classify(score) -> str``
- ``analyse_strokes(strokes, window=50, **kw) -> DriftReport``
- ``analyse_jsonl(path, tail=50, **kw) -> DriftReport``

Usage::

    from iamai.content_drift_index import analyse_strokes

    report = analyse_strokes(strokes, window=100)
    print(f"drift={report.score:.3f} verdict={report.verdict}")
    # → drift=0.312 verdict=anchored

    if report.verdict == "frozen":
        print("writer is thematically stuck — inject new topics")
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Default English stopwords (small, focused set for tech-writing context)
# ---------------------------------------------------------------------------

DEFAULT_STOPWORDS: frozenset[str] = frozenset({
    # articles, prepositions, conjunctions
    "the", "a", "an", "and", "or", "but", "not", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "could", "should", "may", "might", "shall",
    "can", "need", "dare", "ought", "used", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "both", "each", "few", "more", "most",
    "other", "some", "such", "no", "nor", "only", "own", "same", "so",
    "than", "too", "very", "just", "because", "this", "that", "these",
    "those", "what", "which", "who", "whom", "its", "it", "they",
    "them", "their", "our", "we", "you", "your", "he", "she", "him",
    "her", "his", "my", "me", "if", "about", "up",
    # common tech-writing fillers
    "also", "however", "therefore", "thus", "hence", "although",
    "though", "while", "whether", "since", "until", "unless",
})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class VocabStats:
    """Statistics about a token set."""
    total_tokens: int = 0
    unique_tokens: int = 0
    type_token_ratio: float = 0.0
    hapax_legomena: int = 0
    hapax_ratio: float = 0.0
    entropy: float = 0.0
    normalised_entropy: float = 0.0


@dataclass
class DriftReport:
    """Result of drift analysis on a stroke window."""
    score: float = 0.0
    verdict: str = "frozen"
    vocab_stats: VocabStats = field(default_factory=VocabStats)
    window_size: int = 0
    stroke_count: int = 0
    top_words: list = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "verdict": self.verdict,
            "window_size": self.window_size,
            "stroke_count": self.stroke_count,
            "type_token_ratio": round(self.vocab_stats.type_token_ratio, 4),
            "hapax_ratio": round(self.vocab_stats.hapax_ratio, 4),
            "entropy": round(self.vocab_stats.entropy, 4),
            "normalised_entropy": round(self.vocab_stats.normalised_entropy, 4),
            "top_words": self.top_words[:10],
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def tokenize(
    text: str,
    stopwords: Optional[frozenset[str]] = None,
    min_word_length: int = 4,
) -> list[str]:
    """Tokenize text into content words.

    Splits on non-alphanumeric boundaries, lowercases, removes stopwords
    and words shorter than ``min_word_length``.

    Parameters
    ----------
    text : str
        Input text.
    stopwords : frozenset[str] | None
        Words to exclude.  Defaults to ``DEFAULT_STOPWORDS``.
    min_word_length : int
        Minimum word length to keep (default 4).

    Returns
    -------
    list[str]
        Filtered content-word tokens.
    """
    if stopwords is None:
        stopwords = DEFAULT_STOPWORDS

    raw = re.split(r"[^a-zA-Z0-9]+", text.lower())
    return [
        w for w in raw
        if len(w) >= min_word_length and w not in stopwords
    ]


def vocabulary_stats(tokens: Sequence[str]) -> VocabStats:
    """Compute vocabulary statistics from a token list.

    Parameters
    ----------
    tokens : Sequence[str]
        Content-word tokens (already filtered).

    Returns
    -------
    VocabStats
        Computed statistics.  All fields are zero when ``tokens`` is empty.
    """
    n = len(tokens)
    if n == 0:
        return VocabStats()

    counter = Counter(tokens)
    unique = len(counter)
    ttr = unique / n

    hapax = sum(1 for c in counter.values() if c == 1)
    hapax_r = hapax / unique if unique > 0 else 0.0

    # Shannon entropy
    entropy = 0.0
    for count in counter.values():
        p = count / n
        if p > 0:
            entropy -= p * math.log2(p)

    # Normalise by maximum possible entropy for this vocabulary size
    max_entropy = math.log2(unique) if unique > 1 else 1.0
    norm_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

    return VocabStats(
        total_tokens=n,
        unique_tokens=unique,
        type_token_ratio=ttr,
        hapax_legomena=hapax,
        hapax_ratio=hapax_r,
        entropy=entropy,
        normalised_entropy=norm_entropy,
    )


def drift_score(stats: VocabStats) -> float:
    """Compute composite drift score from vocabulary statistics.

    Formula::

        score = 0.4 * TTR + 0.3 * hapax_ratio + 0.3 * normalised_entropy

    Returns
    -------
    float
        Score in [0.0, 1.0].  Higher = more topic diversity.
    """
    return (
        0.4 * stats.type_token_ratio
        + 0.3 * stats.hapax_ratio
        + 0.3 * stats.normalised_entropy
    )


def classify(score: float) -> str:
    """Classify a drift score into a verdict string.

    Returns
    -------
    str
        One of ``'drifting'``, ``'stable'``, ``'anchored'``, ``'frozen'``.
    """
    if score >= 0.70:
        return "drifting"
    if score >= 0.45:
        return "stable"
    if score >= 0.25:
        return "anchored"
    return "frozen"


def _top_words(tokens: Sequence[str], n: int = 10) -> list[tuple[str, int]]:
    """Return the *n* most common tokens with their counts."""
    return Counter(tokens).most_common(n)


def analyse_strokes(
    strokes: Sequence[dict],
    window: int = 50,
    text_field: str = "text",
    stopwords: Optional[frozenset[str]] = None,
    min_word_length: int = 4,
) -> DriftReport:
    """Analyse topic drift over a window of recent strokes.

    Parameters
    ----------
    strokes : Sequence[dict]
        Stroke dicts, each containing a ``text_field`` key.
    window : int
        Number of most-recent strokes to analyse.
    text_field : str
        Key in each dict that holds the stroke text.
    stopwords : frozenset[str] | None
        Override stopword set.
    min_word_length : int
        Minimum content-word length.

    Returns
    -------
    DriftReport
        Analysis result.
    """
    if not strokes:
        return DriftReport(
            score=0.0,
            verdict="frozen",
            reason="no strokes provided",
        )

    recent = strokes[-window:]
    all_tokens: list[str] = []
    for s in recent:
        text = s.get(text_field, "")
        if text:
            all_tokens.extend(tokenize(text, stopwords, min_word_length))

    stats = vocabulary_stats(all_tokens)
    score = drift_score(stats)
    verdict = classify(score)
    top = _top_words(all_tokens)

    reason_parts = [
        f"TTR={stats.type_token_ratio:.3f}",
        f"hapax={stats.hapax_ratio:.3f}",
        f"norm_entropy={stats.normalised_entropy:.3f}",
    ]

    return DriftReport(
        score=score,
        verdict=verdict,
        vocab_stats=stats,
        window_size=window,
        stroke_count=len(recent),
        top_words=[(w, c) for w, c in top],
        reason=" | ".join(reason_parts),
    )


def analyse_jsonl(
    path: str | Path,
    tail: int = 50,
    **kwargs,
) -> DriftReport:
    """Read a JSONL strokes file and analyse the last *tail* entries.

    Parameters
    ----------
    path : str | Path
        Path to ``strokes.jsonl``.
    tail : int
        Number of trailing lines to read.
    **kwargs
        Forwarded to ``analyse_strokes``.

    Returns
    -------
    DriftReport
    """
    p = Path(path)
    if not p.exists():
        return DriftReport(
            score=0.0,
            verdict="frozen",
            reason=f"file not found: {path}",
        )

    lines = p.read_text(encoding="utf-8").strip().splitlines()
    tail_lines = lines[-tail:]

    strokes: list[dict] = []
    for line in tail_lines:
        line = line.strip()
        if not line:
            continue
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return analyse_strokes(strokes, window=tail, **kwargs)
