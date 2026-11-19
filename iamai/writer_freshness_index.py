"""writer_freshness_index — measure lexical novelty in recent strokes.

A writing process that repeats the same words is a writing process
that isn't thinking.  This module compares the vocabulary of recent
strokes against the historical corpus to answer: **what fraction of
what I just wrote is genuinely new?**

Metrics
-------

========================  =============================================
metric                    meaning
========================  =============================================
window_size               how many recent strokes to examine
total_history_tokens      distinct tokens in the historical corpus
recent_tokens             distinct tokens in the recent window
novel_tokens              tokens in recent that never appeared before
freshness_index           novel_tokens / recent_tokens  (0–1)
novel_token_occurrences   total occurrences of novel tokens in window
repetition_index          1 − freshness_index
top_novel                 top-N novel tokens by frequency in window
top_repeated              top-N repeated tokens by frequency in window
========================  =============================================

Interpretation
--------------

* **freshness ≥ 0.40** — the writer is genuinely exploring new ideas
* **freshness 0.20–0.40** — healthy mix of old and new vocabulary
* **freshness < 0.20** — the writer may be stuck in a rut, rehashing
  the same concepts; consider prompting with a new topic

Edge cases
----------

* If the corpus has fewer than ``window_size`` strokes, the historical
  set is empty and freshness is defined as 1.0 (everything is new).
* Stopwords are excluded from novelty calculation by default but can
  be included with ``include_stopwords=True``.
* Tokens are lowercased and stripped of punctuation.

Usage
-----
    from iamai.writer_freshness_index import FreshnessAnalyser

    fa = FreshnessAnalyser.from_jsonl("data/strokes.jsonl")
    report = fa.report(window_size=50)
    print(report.freshness_index, report.top_novel)
"""

from __future__ import annotations

import json
import re
import string
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

_DEFAULT_STOPWORDS: Set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "just", "because", "but", "and", "or",
    "if", "while", "although", "this", "that", "these", "those",
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "it", "its", "they", "them", "their", "what", "which",
    "who", "whom",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def _tokenise(text: str, include_stopwords: bool = False) -> List[str]:
    """Lowercase tokenise, optionally stripping stopwords."""
    tokens = _TOKEN_RE.findall(text.lower())
    if include_stopwords:
        return tokens
    return [t for t in tokens if t not in _DEFAULT_STOPWORDS]


@dataclass
class FreshnessReport:
    """Immutable result of a freshness analysis."""

    window_size: int
    total_history_tokens: int
    recent_tokens: int
    novel_tokens: int
    freshness_index: float
    novel_token_occurrences: int
    repetition_index: float
    top_novel: List[Tuple[str, int]]
    top_repeated: List[Tuple[str, int]]
    corpus_size: int  # total strokes examined

    def summary(self) -> str:
        if self.recent_tokens == 0:
            return "No tokens in recent window; freshness undefined."
        level = (
            "high" if self.freshness_index >= 0.40
            else "moderate" if self.freshness_index >= 0.20
            else "low"
        )
        return (
            f"Freshness {level}: {self.novel_tokens}/{self.recent_tokens} "
            f"tokens ({self.freshness_index:.1%}) are novel across "
            f"{self.corpus_size} strokes. "
            f"Top novel: {', '.join(f'{t}({n})' for t, n in self.top_novel[:3]) or '(none)'}."
        )


class FreshnessAnalyser:
    """Analyse lexical novelty of recent strokes against history.

    Parameters
    ----------
    strokes : Sequence[dict]
        Ordered list of stroke dicts, each having at least a ``text``
        key.  The list should be in chronological order (oldest first).
    include_stopwords : bool
        Whether to include stopwords in the novelty calculation.
    """

    def __init__(
        self,
        strokes: Sequence[dict],
        include_stopwords: bool = False,
    ):
        self.strokes = list(strokes)
        self.include_stopwords = include_stopwords

    # ── factories ─────────────────────────────────────────────────────

    @classmethod
    def from_jsonl(
        cls,
        path: str | Path,
        include_stopwords: bool = False,
    ) -> "FreshnessAnalyser":
        p = Path(path)
        strokes: List[dict] = []
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    strokes.append(json.loads(line))
        return cls(strokes, include_stopwords=include_stopwords)

    # ── core ──────────────────────────────────────────────────────────

    def report(
        self,
        window_size: int = 50,
        top_n: int = 10,
    ) -> FreshnessReport:
        """Compute freshness metrics for the last *window_size* strokes.

        Parameters
        ----------
        window_size : int
            Number of most-recent strokes to examine.
        top_n : int
            How many top tokens to include in the report.

        Returns
        -------
        FreshnessReport
        """
        if window_size <= 0:
            raise ValueError("window_size must be positive")

        n = len(self.strokes)
        actual_window = min(window_size, n)

        # Split into history and recent
        history_strokes = self.strokes[: n - actual_window]
        recent_strokes = self.strokes[n - actual_window:]

        # Build historical vocabulary
        history_vocab: Set[str] = set()
        for s in history_strokes:
            tokens = _tokenise(s.get("text", ""), self.include_stopwords)
            history_vocab.update(tokens)

        # Analyse recent strokes
        recent_counter: Counter = Counter()
        novel_counter: Counter = Counter()
        repeated_counter: Counter = Counter()

        for s in recent_strokes:
            tokens = _tokenise(s.get("text", ""), self.include_stopwords)
            for tok in tokens:
                recent_counter[tok] += 1
                if tok not in history_vocab:
                    novel_counter[tok] += 1
                else:
                    repeated_counter[tok] += 1

        recent_distinct = len(recent_counter)
        novel_distinct = len(novel_counter)
        novel_occurrences = sum(novel_counter.values())

        if recent_distinct == 0:
            freshness = 1.0 if len(history_vocab) == 0 else 0.0
        else:
            freshness = novel_distinct / recent_distinct

        return FreshnessReport(
            window_size=actual_window,
            total_history_tokens=len(history_vocab),
            recent_tokens=recent_distinct,
            novel_tokens=novel_distinct,
            freshness_index=freshness,
            novel_token_occurrences=novel_occurrences,
            repetition_index=1.0 - freshness,
            top_novel=novel_counter.most_common(top_n),
            top_repeated=repeated_counter.most_common(top_n),
            corpus_size=n,
        )
