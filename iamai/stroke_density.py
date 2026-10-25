"""stroke_density — measure information density of writer strokes.

A long-running automated writer produces strokes that follow template
patterns.  Over time, if the templates become too rigid, the actual
information content per stroke drops — the writer is *churning* rather
than *saying something*.

This module quantifies stroke density along three axes:

1. **Lexical diversity** — ratio of unique tokens to total tokens in a
   single stroke.  A stroke that says "growth that never stops is a
   tumour, not a garden" has high diversity; one that repeats
   boilerplate has low diversity.

2. **Novelty ratio** — fraction of tokens in a stroke that have NOT
   appeared in the preceding *window* strokes.  Measures how much
   *new* vocabulary each stroke introduces.

3. **Content fraction** — proportion of non-boilerplate tokens.
   Boilerplate tokens are those that appear in more than *threshold*
   fraction of all observed strokes (e.g., "measured now:", "commit",
   "the count of times").

Design decisions:

- **Stateful analyser** — ``StrokeDensityAnalyser`` keeps a sliding
  window of recent stroke texts so novelty and content fraction can
  be computed incrementally.
- **Pure Python** — no subprocess, no filesystem I/O; all inputs are
  passed as strings.
- **Lightweight tokenization** — splits on whitespace and strips
  punctuation; good enough for English prose without pulling in NLTK.

Usage::

    from iamai.stroke_density import StrokeDensityAnalyser

    a = StrokeDensityAnalyser(window=20)
    a.feed("growth that never stops is a tumour, not a garden")
    a.feed("an append-only log forces you to be wrong in public")
    a.feed("if a number in a diary is not measured, it is fiction")

    a.lexical_diversity()      # diversity of the latest stroke
    a.novelty_ratio()          # novelty of the latest stroke
    a.content_fraction()       # non-boilerplate fraction
    a.density_score()          # composite 0–1 score
    a.summarize()              # dict with all metrics + trend

Scoring weights (sum to 1.0):

- **lexical_diversity** (0.30) — unique-token ratio, latest stroke.
- **novelty**           (0.40) — new-vocabulary fraction.
- **content_fraction**  (0.30) — non-boilerplate proportion.

The final score is the weighted sum, clamped to [0, 1].
"""

from __future__ import annotations

import re
import string
from collections import Counter, deque
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

_STRIP = str.maketrans("", "", string.punctuation)


def _tokenize(text: str) -> List[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    return text.lower().translate(_STRIP).split()


# ---------------------------------------------------------------------------
# Single-stroke metrics
# ---------------------------------------------------------------------------


def lexical_diversity_of(tokens: List[str]) -> float:
    """Unique-token ratio for a single token list.

    Returns 1.0 when all tokens are unique, 0.0 for an empty list.
    """
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


# ---------------------------------------------------------------------------
# Analyser (stateful, rolling window)
# ---------------------------------------------------------------------------


class StrokeDensityAnalyser:
    """Rolling-window stroke density monitor.

    Parameters
    ----------
    window : int
        Number of recent strokes to keep for novelty / boilerplate
        calculations.  Default 20.
    boilerplate_freq : float
        A token is considered "boilerplate" if it appears in more than
        this fraction of the window's strokes.  Default 0.5 (i.e., a
        token seen in >50 % of recent strokes).
    """

    def __init__(self, window: int = 20, boilerplate_freq: float = 0.5) -> None:
        if window < 1:
            raise ValueError("window must be >= 1")
        if not 0.0 < boilerplate_freq <= 1.0:
            raise ValueError("boilerplate_freq must be in (0, 1]")
        self._window = window
        self._bf = boilerplate_freq
        self._history: deque[List[str]] = deque(maxlen=window)
        self._scores: deque[float] = deque(maxlen=window)
        # cumulative counters
        self._total_fed: int = 0

    # -- ingestion -----------------------------------------------------------

    def feed(self, text: str) -> Dict[str, float]:
        """Record a new stroke and return its per-stroke metrics."""
        tokens = _tokenize(text)
        self._history.append(tokens)
        self._total_fed += 1

        ld = lexical_diversity_of(tokens)
        nv = self._novelty(tokens)
        cf = self._content_fraction(tokens)
        score = 0.30 * ld + 0.40 * nv + 0.30 * cf
        self._scores.append(score)

        return {
            "lexical_diversity": round(ld, 4),
            "novelty_ratio": round(nv, 4),
            "content_fraction": round(cf, 4),
            "density_score": round(score, 4),
        }

    # -- latest-stroke queries -----------------------------------------------

    def lexical_diversity(self) -> float:
        """Lexical diversity of the most recent stroke."""
        if not self._history:
            return 0.0
        return lexical_diversity_of(self._history[-1])

    def novelty_ratio(self) -> float:
        """Fraction of tokens in the latest stroke that are new
        (not seen in any prior stroke in the window)."""
        if not self._history:
            return 0.0
        return self._novelty(self._history[-1])

    def content_fraction(self) -> float:
        """Non-boilerplate fraction of the latest stroke."""
        if not self._history:
            return 0.0
        return self._content_fraction(self._history[-1])

    def density_score(self) -> float:
        """Composite density score for the latest stroke."""
        if not self._scores:
            return 0.0
        return self._scores[-1]

    # -- aggregate queries ---------------------------------------------------

    def average_score(self, n: Optional[int] = None) -> float:
        """Mean density score over the last *n* strokes (default: all)."""
        if not self._scores:
            return 0.0
        data = list(self._scores)[-n:] if n else list(self._scores)
        return sum(data) / len(data)

    def trend(self) -> str:
        """Compare first-half average to second-half average.

        Returns ``"improving"``, ``"declining"``, or ``"flat"``.
        Requires at least 4 strokes; otherwise returns ``"flat"``.
        """
        scores = list(self._scores)
        if len(scores) < 4:
            return "flat"
        mid = len(scores) // 2
        first = sum(scores[:mid]) / mid
        second = sum(scores[mid:]) / (len(scores) - mid)
        delta = second - first
        if delta > 0.03:
            return "improving"
        if delta < -0.03:
            return "declining"
        return "flat"

    def summarize(self) -> dict:
        """Return a dict with all current metrics."""
        return {
            "total_strokes": self._total_fed,
            "window_size": self._window,
            "latest": {
                "lexical_diversity": round(self.lexical_diversity(), 4),
                "novelty_ratio": round(self.novelty_ratio(), 4),
                "content_fraction": round(self.content_fraction(), 4),
                "density_score": round(self.density_score(), 4),
            },
            "average_score": round(self.average_score(), 4),
            "trend": self.trend(),
        }

    def reset(self) -> None:
        """Clear all history and counters."""
        self._history.clear()
        self._scores.clear()
        self._total_fed = 0

    # -- internals -----------------------------------------------------------

    def _novelty(self, tokens: List[str]) -> float:
        """Fraction of *tokens* not seen in any other stroke in the window."""
        if not tokens or len(self._history) < 2:
            return 1.0  # first stroke is all novel by definition
        # build vocabulary from all strokes EXCEPT the last one
        prior_vocab: set = set()
        for prior_tokens in list(self._history)[:-1]:
            prior_vocab.update(prior_tokens)
        if not prior_vocab:
            return 1.0
        novel = sum(1 for t in tokens if t not in prior_vocab)
        return novel / len(tokens)

    def _content_fraction(self, tokens: List[str]) -> float:
        """Fraction of tokens that are NOT boilerplate."""
        if not tokens or len(self._history) < 3:
            return 1.0  # not enough data to identify boilerplate
        # count how many strokes each token appears in
        stroke_count: Counter = Counter()
        for prior_tokens in self._history:
            stroke_count.update(set(prior_tokens))
        n_strokes = len(self._history)
        threshold = self._bf * n_strokes
        content = sum(
            1 for t in tokens if stroke_count.get(t, 0) <= threshold
        )
        return content / len(tokens)
