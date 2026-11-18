"""restart_amnesia_detector — detect creative-context loss after writer restart.

When the automated writer restarts, it may lose the creative thread it
was following before the stop.  This module compares a window of strokes
produced *before* the restart with a window *after* the restart to
detect "amnesia" — when post-restart output regresses to patterns the
writer had already moved past.

Signals used:

- **vocabulary_overlap**: fraction of unique tokens in the post-window
  that also appear in the pre-window.  Very high overlap suggests the
  writer is re-treading old ground rather than advancing.
- **topic_drift**: cosine distance between TF vectors of the two
  windows.  Near-zero drift means the writer hasn't shifted topic at
  all, which is suspicious after a cold restart.
- **cadence_similarity**: how closely the inter-stroke intervals match.
  Identical cadence may indicate mechanical replay rather than fresh
  writing.

These three signals are combined into a composite ``amnesia_score``
in [0.0, 1.0] where 0.0 means "clearly fresh" and 1.0 means "almost
certainly amnesiac".

Usage::

    from iamai.restart_amnesia_detector import AmnesiaDetector

    det = AmnesiaDetector()
    verdict = det.check(pre_strokes, post_strokes)
    print(verdict.score)       # 0.0 – 1.0
    print(verdict.has_amnesia) # bool
    print(verdict.signals)     # dict of individual signal values

Thresholds are configurable.  The defaults are conservative — they
flag only strong amnesia to avoid false positives during normal
restarts where the writer legitimately continues a similar topic.

Written by Qwen during caretaker visit 705, 2026-11-18.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


# ─── Data classes ───────────────────────────────────────────────────


@dataclass(frozen=True)
class AmnesiaSignals:
    """Individual signal values from an amnesia check."""

    vocabulary_overlap: float = 0.0
    topic_drift: float = 0.0
    cadence_similarity: float = 0.0

    def as_dict(self) -> Dict[str, float]:
        return {
            "vocabulary_overlap": round(self.vocabulary_overlap, 4),
            "topic_drift": round(self.topic_drift, 4),
            "cadence_similarity": round(self.cadence_similarity, 4),
        }


@dataclass(frozen=True)
class AmnesiaVerdict:
    """Result of an amnesia check."""

    score: float = 0.0
    has_amnesia: bool = False
    signals: AmnesiaSignals = field(default_factory=AmnesiaSignals)

    def summary(self) -> str:
        tag = "AMNESIA" if self.has_amnesia else "fresh"
        return f"{tag} (score={self.score:.3f})"


# ─── Tokeniser ──────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-zA-Z\u4e00-\u9fff]+|[0-9]+")


def _tokenise(text: str) -> List[str]:
    """Lowercase tokeniser: splits on whitespace and punctuation."""
    return [t.lower() for t in _TOKEN_RE.findall(text)]


# ─── Signal functions ───────────────────────────────────────────────


def vocabulary_overlap(pre_tokens: Sequence[str],
                       post_tokens: Sequence[str]) -> float:
    """Fraction of post-window unique tokens present in pre-window.

    Returns 0.0 when post_tokens is empty (no overlap possible).
    Returns 1.0 when every post token also appears in pre.
    """
    if not post_tokens:
        return 0.0
    pre_set = set(pre_tokens)
    post_set = set(post_tokens)
    if not post_set:
        return 0.0
    overlap = post_set & pre_set
    return len(overlap) / len(post_set)


def topic_drift(pre_tokens: Sequence[str],
                post_tokens: Sequence[str]) -> float:
    """Cosine distance between TF vectors of two token lists.

    Returns 0.0 (identical distributions) to 1.0 (orthogonal).
    Returns 0.0 when either list is empty (no signal).
    """
    if not pre_tokens or not post_tokens:
        return 0.0

    pre_counts = Counter(pre_tokens)
    post_counts = Counter(post_tokens)
    all_terms = set(pre_counts) | set(post_counts)

    dot = 0.0
    mag_pre = 0.0
    mag_post = 0.0
    for t in all_terms:
        a = pre_counts.get(t, 0)
        b = post_counts.get(t, 0)
        dot += a * b
        mag_pre += a * a
        mag_post += b * b

    if mag_pre == 0.0 or mag_post == 0.0:
        return 0.0

    cosine = dot / (math.sqrt(mag_pre) * math.sqrt(mag_post))
    # Clamp for floating-point safety
    cosine = max(0.0, min(1.0, cosine))
    return 1.0 - cosine


def cadence_similarity(pre_intervals: Sequence[float],
                       post_intervals: Sequence[float]) -> float:
    """Similarity of inter-stroke interval distributions.

    Compares the coefficient of variation (CV) of both windows.
    Returns 0.0 (very different CVs) to 1.0 (identical CVs).
    Returns 0.0 when either window has fewer than 2 intervals.
    """
    if len(pre_intervals) < 2 or len(post_intervals) < 2:
        return 0.0

    def _cv(vals: Sequence[float]) -> float:
        n = len(vals)
        mean = sum(vals) / n
        if mean == 0.0:
            return 0.0
        variance = sum((v - mean) ** 2 for v in vals) / n
        return math.sqrt(variance) / mean

    cv_pre = _cv(pre_intervals)
    cv_post = _cv(post_intervals)

    if cv_pre == 0.0 and cv_post == 0.0:
        return 1.0

    max_cv = max(cv_pre, cv_post)
    if max_cv == 0.0:
        return 1.0

    # Normalised absolute difference
    diff = abs(cv_pre - cv_post) / max_cv
    return max(0.0, 1.0 - diff)


# ─── Detector ───────────────────────────────────────────────────────


@dataclass
class AmnesiaDetector:
    """Stateless detector that checks for post-restart amnesia.

    Parameters
    ----------
    overlap_weight : float
        Weight for vocabulary_overlap in the composite score.
    drift_weight : float
        Weight for (1 - topic_drift) — low drift contributes to amnesia.
    cadence_weight : float
        Weight for cadence_similarity.
    threshold : float
        Composite score at or above which has_amnesia is True.
    """

    overlap_weight: float = 0.40
    drift_weight: float = 0.35
    cadence_weight: float = 0.25
    threshold: float = 0.70

    def _compute_score(self, signals: AmnesiaSignals) -> float:
        """Weighted combination of signals.

        High overlap + low drift + high cadence similarity → amnesia.
        """
        overlap_component = signals.vocabulary_overlap
        drift_component = 1.0 - signals.topic_drift  # low drift = bad
        cadence_component = signals.cadence_similarity

        total_weight = self.overlap_weight + self.drift_weight + self.cadence_weight
        if total_weight == 0.0:
            return 0.0

        raw = (
            self.overlap_weight * overlap_component
            + self.drift_weight * drift_component
            + self.cadence_weight * cadence_component
        )
        return min(1.0, max(0.0, raw / total_weight))

    def check_from_tokens(
        self,
        pre_tokens: Sequence[str],
        post_tokens: Sequence[str],
        pre_intervals: Sequence[float] = (),
        post_intervals: Sequence[float] = (),
    ) -> AmnesiaVerdict:
        """Run the amnesia check from pre-tokenised stroke lists.

        Parameters
        ----------
        pre_tokens : tokens from strokes before restart
        post_tokens : tokens from strokes after restart
        pre_intervals : inter-stroke intervals before restart (seconds)
        post_intervals : inter-stroke intervals after restart (seconds)
        """
        # No signal possible when either window is empty
        if not pre_tokens or not post_tokens:
            return AmnesiaVerdict(score=0.0, has_amnesia=False)

        overlap = vocabulary_overlap(pre_tokens, post_tokens)
        drift = topic_drift(pre_tokens, post_tokens)
        cadence = cadence_similarity(pre_intervals, post_intervals)

        signals = AmnesiaSignals(
            vocabulary_overlap=overlap,
            topic_drift=drift,
            cadence_similarity=cadence,
        )
        score = self._compute_score(signals)
        return AmnesiaVerdict(
            score=round(score, 4),
            has_amnesia=score >= self.threshold,
            signals=signals,
        )

    def check(
        self,
        pre_strokes: Sequence[str],
        post_strokes: Sequence[str],
        pre_timestamps: Sequence[float] = (),
        post_timestamps: Sequence[float] = (),
    ) -> AmnesiaVerdict:
        """Run the amnesia check from raw stroke texts and timestamps.

        Parameters
        ----------
        pre_strokes : list of stroke text strings before restart
        post_strokes : list of stroke text strings after restart
        pre_timestamps : unix timestamps for pre_strokes (same length)
        post_timestamps : unix timestamps for post_strokes (same length)
        """
        pre_tokens: List[str] = []
        for s in pre_strokes:
            pre_tokens.extend(_tokenise(s))

        post_tokens: List[str] = []
        for s in post_strokes:
            post_tokens.extend(_tokenise(s))

        pre_intervals: List[float] = []
        if len(pre_timestamps) >= 2:
            for i in range(1, len(pre_timestamps)):
                pre_intervals.append(pre_timestamps[i] - pre_timestamps[i - 1])

        post_intervals: List[float] = []
        if len(post_timestamps) >= 2:
            for i in range(1, len(post_timestamps)):
                post_intervals.append(
                    post_timestamps[i] - post_timestamps[i - 1]
                )

        return self.check_from_tokens(
            pre_tokens, post_tokens, pre_intervals, post_intervals
        )
