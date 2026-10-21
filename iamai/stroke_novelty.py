"""stroke_novelty — detect when the writer is stuck repeating itself.

``stroke_diversity`` measures the *kind distribution* (are all six stroke
types being used?).  ``stroke_half_life`` measures *topic recurrence*
(how often does the writer circle back to a subject?).  Neither catches
the most insidious failure mode of a long-running automated writer:
**semantic repetition** — producing text that says the same thing in
slightly different words, or worse, in exactly the same words with only
the timestamp changed.

This module fills that gap.  Given a sequence of stroke texts, it
computes a *novelty score* for each stroke relative to its recent
predecessors, and classifies the overall stream health.

Concept
-------

For each stroke, compare its text against the previous ``lookback``
strokes using **word-level Jaccard similarity** after stripping:

- punctuation
- digits (repo stats change every run, masking real repetition)
- common stop-words

The similarity to the nearest neighbour (most similar predecessor) is
the stroke's *repetition score*.  Novelty is ``1 - repetition``.

Classification per stroke::

    fresh       novelty >= 0.70  — genuinely new content
    familiar    0.40 <= novelty < 0.70  — variation on a known theme
    repetitive  0.15 <= novelty < 0.40  — mostly recycled phrasing
    clone       novelty < 0.15   — near-duplicate of a recent stroke

Stream verdict (over the last ``window`` strokes)::

    healthy     >= 70 % of strokes are fresh or familiar
    stagnating  >= 40 % are repetitive or clone
    loop        >= 60 % are clone

Why Jaccard
-----------

Jaccard similarity is cheap, dependency-free, and surprisingly effective
at catching the failure mode where an LLM rephrases the same aphorism
for the dozenth time.  It does not catch *thematic* repetition (same
idea, totally different words) — that would need embeddings, which would
break the "no external dependencies" rule.

Usage::

    from iamai.stroke_novelty import StrokeNovelty

    sn = StrokeNovelty()
    sn.score_stroke("tests are the part of a repository that argues back")
    sn.score_stroke("tests are the part of a codebase that argues back")
    sn.score_stroke("the build server caught fire again at 3am")

    sn.stream_verdict()  # "stagnating" or worse
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

# ---------------------------------------------------------------------------
# Stop-words (small, targeted — not a general English list)
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did will "
    "would shall should may might can could of in to for on with at by from "
    "as into through during before after above below between out off over "
    "under again further then once here there when where why how all each "
    "every both few more most other some such no nor not only own same so "
    "than too very just because if while that this it its he she they them "
    "their his her we you your our us me my i am".split()
)

# Precompiled pattern for tokenisation: lowercase, split on non-alpha.
_TOKEN_RE = re.compile(r"[a-z]+")


def _tokenise(text: str) -> set[str]:
    """Lowercase, strip digits/punctuation, remove stop-words."""
    tokens = _TOKEN_RE.findall(text.lower())
    return {t for t in tokens if t not in _STOP_WORDS and len(t) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two sets.  Returns 0.0 if both empty."""
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


# ---------------------------------------------------------------------------
# Per-stroke result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrokeNoveltyResult:
    """Result of scoring a single stroke."""

    seq: int
    novelty: float
    repetition: float
    nearest_neighbour: int  # seq of the most similar predecessor (-1 if none)
    verdict: str  # fresh | familiar | repetitive | clone

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "novelty": round(self.novelty, 4),
            "repetition": round(self.repetition, 4),
            "nearest_neighbour": self.nearest_neighbour,
            "verdict": self.verdict,
        }


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def classify_novelty(score: float) -> str:
    """Classify a single novelty score."""
    if score >= 0.70:
        return "fresh"
    if score >= 0.40:
        return "familiar"
    if score >= 0.15:
        return "repetitive"
    return "clone"


def classify_stream(clone_frac: float, repetitive_or_clone_frac: float) -> str:
    """Classify the overall stream health.

    Parameters
    ----------
    clone_frac : float
        Fraction of strokes classified as ``clone``.
    repetitive_or_clone_frac : float
        Fraction of strokes that are ``repetitive`` or ``clone``.
    """
    if clone_frac >= 0.60:
        return "loop"
    if repetitive_or_clone_frac >= 0.40:
        return "stagnating"
    return "healthy"


# ---------------------------------------------------------------------------
# Main analyser
# ---------------------------------------------------------------------------


class StrokeNovelty:
    """Analyse content novelty across a stream of strokes.

    Parameters
    ----------
    lookback : int
        How many previous strokes to compare each new stroke against.
        Larger values are more thorough but O(n * lookback).
    """

    def __init__(self, lookback: int = 10):
        self.lookback = max(1, lookback)
        self._history: list[tuple[int, set[str]]] = []  # (seq, tokens)
        self._results: list[StrokeNoveltyResult] = []

    # -- single stroke -------------------------------------------------------

    def score_stroke(self, text: str, seq: int = -1) -> StrokeNoveltyResult:
        """Score a single stroke against recent history.

        Parameters
        ----------
        text : str
            The stroke's text content.
        seq : int
            Sequence number.  If -1, auto-increments from the last seen.

        Returns
        -------
        StrokeNoveltyResult
        """
        if seq == -1:
            seq = (self._results[-1].seq + 1) if self._results else 0

        tokens = _tokenise(text)

        if not self._history or not tokens:
            # First stroke or empty text → fresh by definition.
            result = StrokeNoveltyResult(
                seq=seq, novelty=1.0, repetition=0.0,
                nearest_neighbour=-1, verdict="fresh",
            )
        else:
            # Compare against the last ``lookback`` entries.
            window = self._history[-self.lookback:]
            best_sim = 0.0
            best_seq = -1
            for prev_seq, prev_tokens in window:
                sim = _jaccard(tokens, prev_tokens)
                if sim > best_sim:
                    best_sim = sim
                    best_seq = prev_seq

            repetition = best_sim
            novelty = 1.0 - repetition
            verdict = classify_novelty(novelty)
            result = StrokeNoveltyResult(
                seq=seq, novelty=novelty, repetition=repetition,
                nearest_neighbour=best_seq, verdict=verdict,
            )

        self._results.append(result)
        self._history.append((seq, tokens))
        return result

    # -- bulk ----------------------------------------------------------------

    def score_many(self, strokes: Sequence[dict]) -> list[StrokeNoveltyResult]:
        """Score a batch of strokes.

        Each dict must have ``"text"``; ``"seq"`` is optional.
        """
        results = []
        for s in strokes:
            seq = s.get("seq", -1)
            results.append(self.score_stroke(s["text"], seq))
        return results

    # -- stream verdict ------------------------------------------------------

    def stream_verdict(self, window: int = 20) -> dict:
        """Compute an overall health verdict over recent strokes.

        Returns
        -------
        dict with keys:
            verdict : str  — "healthy" | "stagnating" | "loop"
            total : int
            fresh : int
            familiar : int
            repetitive : int
            clone : int
            avg_novelty : float
        """
        recent = self._results[-window:] if self._results else []
        if not recent:
            return {
                "verdict": "healthy",
                "total": 0,
                "fresh": 0, "familiar": 0, "repetitive": 0, "clone": 0,
                "avg_novelty": 1.0,
            }

        counts = {"fresh": 0, "familiar": 0, "repetitive": 0, "clone": 0}
        total_novelty = 0.0
        for r in recent:
            counts[r.verdict] += 1
            total_novelty += r.novelty

        n = len(recent)
        clone_frac = counts["clone"] / n
        rep_or_clone_frac = (counts["repetitive"] + counts["clone"]) / n

        return {
            "verdict": classify_stream(clone_frac, rep_or_clone_frac),
            "total": n,
            "fresh": counts["fresh"],
            "familiar": counts["familiar"],
            "repetitive": counts["repetitive"],
            "clone": counts["clone"],
            "avg_novelty": round(total_novelty / n, 4),
        }

    # -- convenience ---------------------------------------------------------

    def reset(self) -> None:
        """Clear all history and results."""
        self._history.clear()
        self._results.clear()

    @property
    def count(self) -> int:
        return len(self._results)
