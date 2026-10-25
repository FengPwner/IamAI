"""Stroke quality gate — score each stroke before it enters the ledger.

An automated writer can produce text that is *technically* valid but
semantically hollow: the same sentence recycled, a one-word entry, a
wall of filler.  This module assigns each stroke a composite quality
score across four dimensions and emits a verdict:

* **pass**  — score ≥ 0.60; commit-worthy.
* **warn**  — score in [0.35, 0.60); borderline, flag for review.
* **fail**  — score < 0.35; do not commit, alert caretaker.

Dimensions (each normalised to [0, 1]):

| Dimension      | What it measures                                   |
|----------------|----------------------------------------------------|
| *length*       | Is the stroke long enough to carry information?    |
| *vocabulary*   | Type-token ratio — lexical richness.               |
| *repetition*   | Inverse of bigram overlap with the previous stroke.|
| *density*      | Ratio of unique trigrams to total words.           |

The composite score is a weighted average::

    score = 0.20·length + 0.30·vocabulary + 0.25·repetition + 0.25·density

Weights can be overridden per-instance.  Every helper is a pure function
so the gate can be unit-tested without any git or file I/O.

Usage::

    from iamai.stroke_quality_gate import QualityGate

    gate = QualityGate()
    verdict = gate.evaluate("naming is hard because a bad name is cheap to type")
    print(verdict.label)   # "pass"
    print(verdict.score)   # 0.78

    # batch mode — evaluate a window of recent strokes
    results = gate.evaluate_window(strokes)
    fail_rate = results.fail_rate
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-zA-Z\u4e00-\u9fff]+", re.UNICODE)


def _tokenize(text: str) -> List[str]:
    """Split *text* into lower-case word tokens."""
    return [w.lower() for w in _WORD_RE.findall(text)]


def _bigrams(tokens: Sequence[str]) -> List[str]:
    """Return a list of space-joined bigrams."""
    return [f"{tokens[i]} {tokens[i + 1]}" for i in range(len(tokens) - 1)]


def _trigrams(tokens: Sequence[str]) -> List[str]:
    """Return a list of space-joined trigrams."""
    return [
        f"{tokens[i]} {tokens[i+1]} {tokens[i+2]}"
        for i in range(len(tokens) - 2)
    ]


# ---------------------------------------------------------------------------
# Dimension scorers (each returns float in [0, 1])
# ---------------------------------------------------------------------------

def score_length(text: str, *, min_words: int = 5, max_words: int = 80) -> float:
    """Score based on word count.

    * 0.0 for fewer than *min_words*.
    * 1.0 for *max_words* or more.
    * Linear interpolation in between.
    """
    n = len(_tokenize(text))
    if n < min_words:
        return n / min_words if min_words > 0 else 0.0
    if n >= max_words:
        return 1.0
    return (n - min_words) / (max_words - min_words)


def score_vocabulary(text: str) -> float:
    """Type-token ratio (unique words / total words).

    Returns 0.0 for empty text.  Capped at 1.0.
    """
    tokens = _tokenize(text)
    if not tokens:
        return 0.0
    return min(len(set(tokens)) / len(tokens), 1.0)


def score_repetition(text: str, previous: str = "") -> float:
    """1 − Jaccard overlap of bigram sets between *text* and *previous*.

    Returns 1.0 (no repetition) when *previous* is empty.
    """
    if not previous:
        return 1.0
    cur = set(_bigrams(_tokenize(text)))
    prev = set(_bigrams(_tokenize(previous)))
    if not cur and not prev:
        return 1.0
    if not cur or not prev:
        return 1.0
    intersection = cur & prev
    union = cur | prev
    return 1.0 - (len(intersection) / len(union))


def score_density(text: str) -> float:
    """Ratio of unique trigrams to total word count.

    Rewards information-dense prose; penalises repetitive filler.
    Returns 0.0 when there are fewer than 3 words.
    """
    tokens = _tokenize(text)
    if len(tokens) < 3:
        return 0.0
    tri = _trigrams(tokens)
    unique = set(tri)
    return min(len(unique) / len(tokens), 1.0)


# ---------------------------------------------------------------------------
# Composite evaluation
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: Dict[str, float] = {
    "length": 0.20,
    "vocabulary": 0.30,
    "repetition": 0.25,
    "density": 0.25,
}

_PASS_THRESHOLD = 0.60
_WARN_THRESHOLD = 0.35


@dataclass
class StrokeVerdict:
    """Result of evaluating a single stroke."""

    text: str
    score: float
    label: str  # "pass" | "warn" | "fail"
    breakdown: Dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"StrokeVerdict(score={self.score:.3f}, label={self.label!r})"


@dataclass
class QualityGate:
    """Evaluate strokes against configurable quality thresholds."""

    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    pass_threshold: float = _PASS_THRESHOLD
    warn_threshold: float = _WARN_THRESHOLD

    def _validate_weights(self) -> None:
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"weights must sum to 1.0, got {total:.6f}")

    def evaluate(self, text: str, previous: str = "") -> StrokeVerdict:
        """Score a single stroke and return a verdict."""
        self._validate_weights()
        dims = {
            "length": score_length(text),
            "vocabulary": score_vocabulary(text),
            "repetition": score_repetition(text, previous),
            "density": score_density(text),
        }
        score = sum(self.weights[k] * dims[k] for k in self.weights)
        if score >= self.pass_threshold:
            label = "pass"
        elif score >= self.warn_threshold:
            label = "warn"
        else:
            label = "fail"
        return StrokeVerdict(text=text, score=score, label=label, breakdown=dims)

    def evaluate_window(
        self, strokes: Sequence[str]
    ) -> "WindowResult":
        """Evaluate a sequence of strokes and return aggregate stats."""
        verdicts: List[StrokeVerdict] = []
        for i, s in enumerate(strokes):
            prev = strokes[i - 1] if i > 0 else ""
            verdicts.append(self.evaluate(s, prev))
        return WindowResult(verdicts=verdicts)


# ---------------------------------------------------------------------------
# Window result
# ---------------------------------------------------------------------------

@dataclass
class WindowResult:
    """Aggregate quality stats over a window of strokes."""

    verdicts: List[StrokeVerdict] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.verdicts)

    @property
    def pass_count(self) -> int:
        return sum(1 for v in self.verdicts if v.label == "pass")

    @property
    def warn_count(self) -> int:
        return sum(1 for v in self.verdicts if v.label == "warn")

    @property
    def fail_count(self) -> int:
        return sum(1 for v in self.verdicts if v.label == "fail")

    @property
    def fail_rate(self) -> float:
        return self.fail_count / self.count if self.count else 0.0

    @property
    def pass_rate(self) -> float:
        return self.pass_count / self.count if self.count else 0.0

    @property
    def mean_score(self) -> float:
        if not self.verdicts:
            return 0.0
        return sum(v.score for v in self.verdicts) / self.count

    @property
    def worst(self) -> Optional[StrokeVerdict]:
        if not self.verdicts:
            return None
        return min(self.verdicts, key=lambda v: v.score)

    @property
    def best(self) -> Optional[StrokeVerdict]:
        if not self.verdicts:
            return None
        return max(self.verdicts, key=lambda v: v.score)

    def summary(self) -> Dict[str, object]:
        return {
            "count": self.count,
            "pass_rate": round(self.pass_rate, 4),
            "fail_rate": round(self.fail_rate, 4),
            "mean_score": round(self.mean_score, 4),
            "worst_score": round(self.worst.score, 4) if self.worst else None,
            "best_score": round(self.best.score, 4) if self.best else None,
        }
