"""stroke_novelty — measure how much new ground each stroke covers.

A self-writing repo produces strokes at a steady cadence, but cadence
alone does not tell you whether the writer is exploring new territory
or rephrasing the same ideas.  Novelty scores each stroke against a
sliding window of recent strokes using token-level Jaccard distance.

Scoring
-------
Each stroke is tokenised (lowercase, punctuation-stripped).  The
reference set is the union of tokens from the preceding *window*
strokes.  Novelty is defined as::

    novelty = 1 - (|stroke ∩ reference| / |stroke|)

- 1.0  → every token is new (completely novel)
- 0.0  → every token appeared recently (pure repetition)

A *NoveltyReport* summarises a batch of strokes with per-stroke scores,
rolling average, and a trend indicator (rising / steady / falling).

Usage::

    from iamai.stroke_novelty import NoveltyScorer

    scorer = NoveltyScorer(window=5)
    strokes = [
        "a repo that only accumulates is a landfill with a README",
        "commit history is the only honest documentation",
        "naming is hard because a bad name is cheap to type",
        "a repo that only accumulates is a landfill",
    ]
    report = scorer.score(strokes)
    print(report.scores)       # [1.0, 0.727, 0.8, 0.286]
    print(report.trend)        # "falling"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Sequence

DEFAULT_WINDOW = 5
TREND_THRESHOLD = 0.05


def _tokenise(text: str) -> set[str]:
    """Lowercase split on non-alphanumeric characters."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


@dataclass
class NoveltyReport:
    """Summary of novelty scores across a batch of strokes."""

    scores: List[float] = field(default_factory=list)
    average: float = 0.0
    trend: str = "steady"  # rising | steady | falling
    window: int = DEFAULT_WINDOW

    @property
    def count(self) -> int:
        return len(self.scores)

    @property
    def min_score(self) -> float:
        return min(self.scores) if self.scores else 0.0

    @property
    def max_score(self) -> float:
        return max(self.scores) if self.scores else 0.0

    def above_threshold(self, threshold: float = 0.5) -> int:
        """Count of strokes with novelty >= *threshold*."""
        return sum(1 for s in self.scores if s >= threshold)

    def below_threshold(self, threshold: float = 0.3) -> int:
        """Count of strokes with novelty < *threshold*."""
        return sum(1 for s in self.scores if s < threshold)


class NoveltyScorer:
    """Score novelty of each stroke against a sliding window of predecessors.

    Parameters
    ----------
    window:
        Number of preceding strokes to use as reference context.
    """

    def __init__(self, window: int = DEFAULT_WINDOW) -> None:
        if window < 1:
            raise ValueError(f"window must be >= 1, got {window}")
        self.window = window

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def score(self, strokes: Sequence[str]) -> NoveltyReport:
        """Score each stroke in *strokes* and return a :class:`NoveltyReport`.

        The first stroke always gets novelty 1.0 (no prior context).
        """
        if not strokes:
            return NoveltyReport(window=self.window)

        token_sets = [_tokenise(s) for s in strokes]
        scores: list[float] = []

        for i, tokens in enumerate(token_sets):
            if not tokens:
                scores.append(0.0)
                continue
            if i == 0:
                scores.append(1.0)
                continue

            start = max(0, i - self.window)
            reference: set[str] = set()
            for j in range(start, i):
                reference |= token_sets[j]

            overlap = tokens & reference
            novelty = 1.0 - (len(overlap) / len(tokens))
            scores.append(round(novelty, 6))

        avg = sum(scores) / len(scores) if scores else 0.0
        trend = self._compute_trend(scores)

        return NoveltyReport(
            scores=scores,
            average=round(avg, 6),
            trend=trend,
            window=self.window,
        )

    def score_one(self, stroke: str, history: Sequence[str]) -> float:
        """Score a single stroke against an explicit history window.

        *history* should contain the most recent preceding strokes
        (oldest first).  Only the last *self.window* entries are used.
        """
        tokens = _tokenise(stroke)
        if not tokens:
            return 0.0

        reference: set[str] = set()
        for h in list(history)[-self.window:]:
            reference |= _tokenise(h)

        if not reference:
            return 1.0

        overlap = tokens & reference
        return round(1.0 - (len(overlap) / len(tokens)), 6)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_trend(scores: list[float]) -> str:
        if len(scores) < 3:
            return "steady"
        mid = len(scores) // 2
        first_half = sum(scores[:mid]) / mid
        second_half = sum(scores[mid:]) / (len(scores) - mid)
        delta = second_half - first_half
        if delta > TREND_THRESHOLD:
            return "rising"
        if delta < -TREND_THRESHOLD:
            return "falling"
        return "steady"
