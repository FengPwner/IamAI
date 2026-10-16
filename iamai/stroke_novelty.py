"""Detect whether a new stroke is too similar to recent ones.

``stroke_coherence`` tells you if a single stroke is garbage.
``content_diversity`` tells you if the *kind distribution* is lopsided.
But neither catches the case where the writer keeps producing
*individually coherent* strokes that all say the same thing with
slight variations — the "polite zombie" failure mode.

This module fills that gap.  It compares a candidate stroke against
a window of recent strokes using character-level shingle Jaccard
similarity and returns a novelty verdict.

Design choices
--------------

- **Character shingles** (n-grams) rather than word tokens: works on
  any language, no tokenizer dependency, and resilient to minor
  rewording that preserves character runs.
- **Jaccard index** over shingle *sets* (not multisets): cheap,
  bounded [0, 1], and insensitive to stroke length differences.
- **Configurable thresholds** so caretakers can tune strictness per
  kind — thoughts might tolerate more repetition than devlog entries.

Verdicts
--------

- **FRESH** — max similarity below ``warn_threshold``; commit freely.
- **REPETITIVE** — at least one recent stroke above ``warn_threshold``
  but none above ``reject_threshold``; log a warning.
- **DUPLICATE** — at least one recent stroke above ``reject_threshold``;
  skip or rewrite before committing.

Usage::

    from iamai.stroke_novelty import check_novelty, NoveltyVerdict

    recent = [
        "The writer produced 400 strokes today across six kinds.",
        "Today the writer logged 400 strokes in six categories.",
    ]
    candidate = "The writer produced 401 strokes today across six kinds."

    result = check_novelty(candidate, recent)
    print(result.verdict)       # NoveltyVerdict.DUPLICATE
    print(result.max_similarity)  # ~0.92
    print(result.nearest_index)   # 0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

class NoveltyVerdict(str, Enum):
    FRESH = "fresh"
    REPETITIVE = "repetitive"
    DUPLICATE = "duplicate"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NoveltyResult:
    """Outcome of a single novelty check."""

    verdict: NoveltyVerdict
    max_similarity: float  # highest Jaccard against any recent stroke
    nearest_index: int  # index into the recent list (-1 when empty)
    similarities: list[float] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict == NoveltyVerdict.FRESH


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SHINGLE_SIZE = 4
DEFAULT_WARN_THRESHOLD = 0.55
DEFAULT_REJECT_THRESHOLD = 0.80


# ---------------------------------------------------------------------------
# Shingle extraction
# ---------------------------------------------------------------------------

def _shingles(text: str, n: int = DEFAULT_SHINGLE_SIZE) -> set[str]:
    """Return the set of character n-grams in *text*.

    Returns an empty set when the text is shorter than *n* characters.
    """
    if n < 1:
        raise ValueError(f"shingle size must be >= 1, got {n}")
    text = text.strip()
    if len(text) < n:
        return set()
    return {text[i : i + n] for i in range(len(text) - n + 1)}


# ---------------------------------------------------------------------------
# Jaccard similarity
# ---------------------------------------------------------------------------

def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard index between two sets.  Returns 0.0 when both are empty."""
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def check_novelty(
    candidate: str,
    recent: Sequence[str],
    *,
    shingle_size: int = DEFAULT_SHINGLE_SIZE,
    warn_threshold: float = DEFAULT_WARN_THRESHOLD,
    reject_threshold: float = DEFAULT_REJECT_THRESHOLD,
) -> NoveltyResult:
    """Score *candidate* against *recent* strokes for novelty.

    Parameters
    ----------
    candidate:
        The text of the stroke about to be committed.
    recent:
        Ordered sequence of recent stroke texts (newest last).
    shingle_size:
        Character n-gram width.
    warn_threshold:
        Jaccard similarity above which a stroke is "repetitive".
    reject_threshold:
        Jaccard similarity above which a stroke is a "duplicate".

    Returns
    -------
    NoveltyResult with verdict, max_similarity, and reasons.
    """
    if not recent:
        return NoveltyResult(
            verdict=NoveltyVerdict.FRESH,
            max_similarity=0.0,
            nearest_index=-1,
            similarities=[],
            reasons=[],
        )

    cand_shingles = _shingles(candidate, shingle_size)
    similarities: list[float] = []

    for text in recent:
        sim = _jaccard(cand_shingles, _shingles(text, shingle_size))
        similarities.append(round(sim, 6))

    max_sim = max(similarities) if similarities else 0.0
    nearest = similarities.index(max_sim) if similarities else -1

    # Determine verdict
    if max_sim >= reject_threshold:
        verdict = NoveltyVerdict.DUPLICATE
        reasons = [
            f"max Jaccard {max_sim:.3f} >= reject threshold {reject_threshold} "
            f"(nearest: recent[{nearest}])"
        ]
    elif max_sim >= warn_threshold:
        verdict = NoveltyVerdict.REPETITIVE
        reasons = [
            f"max Jaccard {max_sim:.3f} >= warn threshold {warn_threshold} "
            f"(nearest: recent[{nearest}])"
        ]
    else:
        verdict = NoveltyVerdict.FRESH
        reasons = []

    return NoveltyResult(
        verdict=verdict,
        max_similarity=max_sim,
        nearest_index=nearest,
        similarities=similarities,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Batch check
# ---------------------------------------------------------------------------

def check_batch(
    candidates: Sequence[str],
    recent: Sequence[str],
    **kwargs,
) -> list[NoveltyResult]:
    """Check a batch of candidates against the same recent window."""
    return [check_novelty(c, recent, **kwargs) for c in candidates]


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------

def summary(
    candidates: Sequence[str],
    recent: Sequence[str],
    **kwargs,
) -> str:
    """One-line summary of a batch novelty check.

    Example output::

        novelty: 3 fresh, 1 repetitive, 1 duplicate out of 5 candidates
    """
    results = check_batch(candidates, recent, **kwargs)
    counts = {v: 0 for v in NoveltyVerdict}
    for r in results:
        counts[r.verdict] += 1
    total = len(results)
    parts = [f"{counts[v]} {v.value}" for v in NoveltyVerdict]
    return f"novelty: {', '.join(parts)} out of {total} candidates"
