"""stroke_vitality — composite health score for the writing process.

Individual metrics (rate, novelty, kind balance, coherence) each capture
one dimension of writer health.  Vitality combines them into a single
0–100 score with a qualitative verdict, so a caretaker can glance at
one number instead of juggling four dashboards.

Dimensions
----------

===============  =====================================================
dimension        what it measures
===============  =====================================================
rate             strokes/hour vs. a configurable target rate
novelty          token-level Jaccard novelty against a sliding window
kind_balance     Shannon entropy of kind distribution, normalised
coherence        pairwise Jaccard similarity between consecutive strokes
===============  =====================================================

Each dimension is independently scored 0.0–1.0, then weighted:

====================  =======
dimension             weight
====================  =======
rate                  0.25
novelty               0.30
kind_balance          0.25
coherence             0.20
====================  =======

Novelty gets the heaviest weight because a self-writing repo that
produces volume without variety is a landfill with a README.

Verdicts
--------

============  =================================================
verdict       meaning
============  =================================================
thriving      score >= 80 — all dimensions healthy
healthy       score >= 60 — minor issues, nothing urgent
struggling    score >= 40 — at least one dimension degraded
stagnant      score <  40 — multiple dimensions failing
============  =================================================

Usage::

    from iamai.stroke_vitality import VitalityScorer

    scorer = VitalityScorer()
    report = scorer.assess(
        strokes=[
            {"kind": "note", "text": "the garden grows slowly"},
            {"kind": "devlog", "text": "commit pipeline refactored"},
            {"kind": "note", "text": "roots deepen before branches spread"},
        ],
        rate_per_hour=240.0,
        target_rate=300.0,
    )
    print(report.score)     # e.g. 72
    print(report.verdict)   # "healthy"
    print(report.breakdown) # {"rate": 0.8, "novelty": 0.75, ...}

Design decisions:

1. **Pure functions** — all inputs are arguments, no I/O.
2. **Tokenisation** — lowercase, alphanumeric only (same as stroke_novelty).
3. **Graceful degradation** — if a dimension has insufficient data,
   it scores 0.5 (neutral) rather than crashing.
4. **Deterministic** — same input always gives same output.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WEIGHTS: Dict[str, float] = {
    "rate": 0.25,
    "novelty": 0.30,
    "kind_balance": 0.25,
    "coherence": 0.20,
}

VERDICT_THRESHOLDS: List[tuple[float, str]] = [
    (80.0, "thriving"),
    (60.0, "healthy"),
    (40.0, "struggling"),
    (0.0, "stagnant"),
]

ALL_KINDS: List[str] = [
    "devlog",
    "garden",
    "snippet",
    "note",
    "metrics",
    "reading",
    "caretaker",
    "thought",
]

DEFAULT_NOVELTY_WINDOW = 10
DEFAULT_TARGET_RATE = 300.0  # strokes per hour

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would shall should may might can could of in to for on with "
    "at by from as into through during before after above below up down "
    "out off over under again further then once here there when where "
    "why how all each every both few more most other some such no nor "
    "not only own same so than too very just that this these those "
    "it its he she they them his her their what which who whom "
    "i me my we our you your".split()
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VitalityReport:
    """Complete vitality assessment."""

    score: float  # 0–100
    verdict: str  # thriving | healthy | struggling | stagnant
    breakdown: Dict[str, float]  # dimension → 0.0–1.0
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_healthy(self) -> bool:
        return self.score >= 60.0

    @property
    def weakest_dimension(self) -> str:
        if not self.breakdown:
            return "unknown"
        return min(self.breakdown, key=self.breakdown.get)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "verdict": self.verdict,
            "breakdown": self.breakdown,
            "weakest": self.weakest_dimension,
            **self.details,
        }


# ---------------------------------------------------------------------------
# Tokenisation helpers
# ---------------------------------------------------------------------------


def _tokenise(text: str, strip_stopwords: bool = False) -> set[str]:
    """Lowercase split on non-alphanumeric characters."""
    tokens = set(_TOKEN_RE.findall(text.lower()))
    if strip_stopwords:
        tokens -= _STOPWORDS
    return tokens


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------


def _score_rate(rate_per_hour: float, target_rate: float) -> float:
    """Score rate as fraction of target, capped at 1.0.

    A rate at or above target scores 1.0.
    A rate at zero scores 0.0.
    Linear interpolation in between.
    """
    if target_rate <= 0:
        return 1.0 if rate_per_hour > 0 else 0.5
    if rate_per_hour <= 0:
        return 0.0
    return min(1.0, rate_per_hour / target_rate)


def _score_novelty(strokes: Sequence[Dict[str, Any]], window: int) -> float:
    """Average token-level Jaccard novelty over the last *window* strokes.

    For each stroke (starting from the second), compute the fraction
    of its tokens that did NOT appear in the preceding *window* strokes.
    Return the average over all scored strokes.
    """
    texts = [s.get("text", "") for s in strokes]
    if len(texts) < 2:
        return 0.5  # insufficient data

    token_sets = [_tokenise(t) for t in texts]
    novelties: list[float] = []

    for i in range(1, len(token_sets)):
        tokens = token_sets[i]
        if not tokens:
            continue

        start = max(0, i - window)
        reference: set[str] = set()
        for j in range(start, i):
            reference |= token_sets[j]

        if not reference:
            novelties.append(1.0)
            continue

        overlap = tokens & reference
        novelty = 1.0 - (len(overlap) / len(tokens))
        novelties.append(novelty)

    if not novelties:
        return 0.5

    return sum(novelties) / len(novelties)


def _score_kind_balance(strokes: Sequence[Dict[str, Any]]) -> float:
    """Normalised Shannon entropy of the kind distribution.

    H_norm = H / log2(K)  where K = number of distinct kinds present.
    A uniform distribution over all 8 kinds scores 1.0.
    A single kind scores 0.0.
    """
    if not strokes:
        return 0.5

    from collections import Counter

    kind_counts = Counter(s.get("kind", "thought") for s in strokes)
    k = len(kind_counts)
    if k <= 1:
        return 0.0

    total = sum(kind_counts.values())
    entropy = 0.0
    for count in kind_counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)

    max_entropy = math.log2(k)
    if max_entropy <= 0:
        return 0.0

    return min(1.0, entropy / max_entropy)


def _score_coherence(strokes: Sequence[Dict[str, Any]]) -> float:
    """Mean pairwise Jaccard similarity between consecutive strokes.

    High similarity → strokes build on each other (coherent thread).
    Very low similarity → random topic jumps.
    We use stopwords-stripped tokens for cleaner signal.
    """
    if len(strokes) < 2:
        return 0.5

    token_sets = [
        _tokenise(s.get("text", ""), strip_stopwords=True) for s in strokes
    ]

    similarities: list[float] = []
    for i in range(1, len(token_sets)):
        a, b = token_sets[i - 1], token_sets[i]
        union = a | b
        if not union:
            continue
        sim = len(a & b) / len(union)
        similarities.append(sim)

    if not similarities:
        return 0.5

    # Normalise: raw Jaccard over short texts is typically 0.0–0.4.
    # We map 0.0→0.2 (random jumps = weak coherence) and 0.3+→1.0.
    avg = sum(similarities) / len(similarities)
    return min(1.0, max(0.0, (avg - 0.0) / 0.3))


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------


class VitalityScorer:
    """Compute a composite vitality score for a batch of strokes.

    Parameters
    ----------
    novelty_window:
        Number of preceding strokes for novelty comparison.
    target_rate:
        Target strokes per hour (for rate dimension).
    """

    def __init__(
        self,
        novelty_window: int = DEFAULT_NOVELTY_WINDOW,
        target_rate: float = DEFAULT_TARGET_RATE,
    ) -> None:
        if novelty_window < 1:
            raise ValueError(f"novelty_window must be >= 1, got {novelty_window}")
        if target_rate <= 0:
            raise ValueError(f"target_rate must be > 0, got {target_rate}")
        self.novelty_window = novelty_window
        self.target_rate = target_rate

    def assess(
        self,
        strokes: Sequence[Dict[str, Any]],
        rate_per_hour: Optional[float] = None,
        target_rate: Optional[float] = None,
    ) -> VitalityReport:
        """Assess vitality for a batch of strokes.

        Parameters
        ----------
        strokes:
            List of stroke dicts, each with at least ``text`` and ``kind``.
        rate_per_hour:
            Observed production rate.  If ``None``, rate dimension scores 0.5.
        target_rate:
            Override the instance-level target rate for this call.
        """
        effective_target = target_rate or self.target_rate

        # Score each dimension
        rate_score = (
            _score_rate(rate_per_hour, effective_target)
            if rate_per_hour is not None
            else 0.5
        )
        novelty_score = _score_novelty(strokes, self.novelty_window)
        kind_score = _score_kind_balance(strokes)
        coherence_score = _score_coherence(strokes)

        breakdown = {
            "rate": round(rate_score, 4),
            "novelty": round(novelty_score, 4),
            "kind_balance": round(kind_score, 4),
            "coherence": round(coherence_score, 4),
        }

        # Weighted composite
        raw = sum(
            breakdown[dim] * WEIGHTS[dim] for dim in WEIGHTS
        )
        score = round(raw * 100, 1)

        # Verdict
        verdict = "stagnant"
        for threshold, label in VERDICT_THRESHOLDS:
            if score >= threshold:
                verdict = label
                break

        # Details
        from collections import Counter

        kind_counts = dict(Counter(s.get("kind", "thought") for s in strokes))
        details = {
            "stroke_count": len(strokes),
            "kind_counts": kind_counts,
            "novelty_window": self.novelty_window,
            "target_rate": effective_target,
            "observed_rate": rate_per_hour,
        }

        return VitalityReport(
            score=score,
            verdict=verdict,
            breakdown=breakdown,
            details=details,
        )

    def assess_from_strokes(
        self,
        strokes: Sequence[Dict[str, Any]],
        window: int = 200,
    ) -> VitalityReport:
        """Convenience: assess the last *window* strokes and infer rate.

        Extracts timestamps from stroke ``at`` fields to compute rate.
        """
        recent = list(strokes)[-window:]
        rate = _infer_rate(recent)
        return self.assess(recent, rate_per_hour=rate)


# ---------------------------------------------------------------------------
# Rate inference
# ---------------------------------------------------------------------------


def _infer_rate(strokes: Sequence[Dict[str, Any]]) -> Optional[float]:
    """Infer strokes/hour from stroke timestamps.

    Each stroke dict should have an ``at`` field (ISO 8601).
    Returns None if fewer than 2 strokes have parseable timestamps.
    """
    from datetime import datetime, timezone

    times: list[float] = []
    for s in strokes:
        at = s.get("at", "")
        if not at:
            continue
        try:
            dt = datetime.fromisoformat(at)
            times.append(dt.timestamp())
        except (ValueError, TypeError):
            continue

    if len(times) < 2:
        return None

    times.sort()
    span_hours = (times[-1] - times[0]) / 3600.0
    if span_hours <= 0:
        return None

    return len(times) / span_hours


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_report(report: VitalityReport) -> str:
    """Human-readable one-line summary."""
    b = report.breakdown
    parts = [
        f"{report.verdict}",
        f"score {report.score}/100",
        f"rate={b.get('rate', 0):.2f}",
        f"novelty={b.get('novelty', 0):.2f}",
        f"kind={b.get('kind_balance', 0):.2f}",
        f"coh={b.get('coherence', 0):.2f}",
    ]
    detail = report.details
    if detail.get("stroke_count"):
        parts.append(f"{detail['stroke_count']} strokes")
    if detail.get("observed_rate") is not None:
        parts.append(f"rate={detail['observed_rate']:.0f}/hr")
    return " | ".join(parts)
