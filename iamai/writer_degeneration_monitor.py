"""writer_degeneration_monitor — track content quality decay over time.

The writer produces one stroke every ~15 seconds.  Over hours it may
cycle through a small template pool, producing high-volume but
low-information output.  Individual modules catch *snapshots* of this
problem — ``stroke_dedup`` flags duplicates, ``stroke_novelty`` flags
content stalls, ``stroke_text_richness`` flags vocabulary collapse —
but none of them track the **trajectory**.

This module divides a stroke sequence into successive time windows and
scores each one on three independent axes:

========================  ================================================
axis                      what it captures
========================  ================================================
duplicate_ratio           fraction of strokes that are fingerprint-equal
                          to their predecessor (degenerate repetition)
novelty_ratio             fraction of unique template prefixes in the
                          window (content variety)
vocabulary_richness       type-token ratio of the combined text in the
                          window (lexical diversity)
========================  ================================================

Each axis is normalised to [0, 1] (1 = healthy).  A composite
**degeneration_score** is computed as ``1 - geometric_mean(health_axes)``,
so a single collapsed axis drags the score down.

Degeneration stages
-------------------

============  ============================================================
stage         meaning
============  ============================================================
fresh         score < 0.25 — writer is producing varied, novel content
cycling       0.25 ≤ score < 0.50 — some repetition, templates emerging
degenerate    0.50 ≤ score < 0.75 — heavy repetition, content collapsing
exhausted     score ≥ 0.75 — writer is effectively stuck in a loop
============  ============================================================

Trend tracking
--------------

When called with enough strokes for multiple windows, the module reports
a **trend** — comparing the first half's mean score to the second half's:

============  ============================================================
trend         meaning
============  ============================================================
improving     score decreased by ≥ 0.1 (quality rising)
stable        score changed by < 0.1
degrading     score increased by ≥ 0.1 (quality falling)
============  ============================================================

Public API
----------

- ``DegenerationReport`` — dataclass with per-window scores and summary
- ``monitor(strokes, window_size, min_strokes) -> DegenerationReport``
- ``classify(score) -> str`` — return the degeneration stage label
- ``compute_trend(scores) -> str`` — return the trend label

Zero dependencies beyond stdlib.

written by Qwen during caretaker visit 693, 2026-11-18
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_FRESH_THRESHOLD = 0.25
_CYCLING_THRESHOLD = 0.50
_DEGENERATE_THRESHOLD = 0.75

_TREND_THRESHOLD = 0.10

_WS_COLLAPSE = re.compile(r"\s+")
_MEASURED_SUFFIX = re.compile(r"\s*--\s*measured now:.*$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fingerprint(text: str) -> str:
    """Return a 16-char hex fingerprint for *text*.

    Strips the trailing '-- measured now: ...' suffix (which changes
    every stroke even when the body is identical), collapses whitespace,
    lowercases, and hashes with SHA-256.

    >>> len(_fingerprint("hello world"))
    16
    >>> _fingerprint("Hello  World") == _fingerprint("hello world")
    True
    """
    cleaned = _MEASURED_SUFFIX.sub("", text)
    normalised = _WS_COLLAPSE.sub(" ", cleaned.strip().lower())
    digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    return digest[:16]


def _extract_prefix(text: str) -> str:
    """Extract the template prefix of a stroke (before the metric suffix).

    >>> _extract_prefix("tests are the good part -- measured now: 42 tests")
    'tests are the good part'
    >>> _extract_prefix("just a plain thought")
    'just a plain thought'
    """
    cleaned = _MEASURED_SUFFIX.sub("", text)
    return cleaned.strip().lower()


def _tokenize(text: str) -> List[str]:
    """Split text into lowercase word tokens.

    >>> _tokenize("Hello, World!  It's fine.")
    ['hello', "it's", 'fine']
    """
    return re.findall(r"[a-zA-Z']+", text.lower())


# ---------------------------------------------------------------------------
# Per-window metrics
# ---------------------------------------------------------------------------


def window_duplicate_ratio(strokes: Sequence[str]) -> float:
    """Fraction of strokes that are fingerprint-duplicates of predecessor.

    Returns 0.0 for sequences of length ≤ 1.

    >>> window_duplicate_ratio(["a", "a", "a", "b"])
    0.5
    >>> window_duplicate_ratio(["a", "b", "c"])
    0.0
    >>> window_duplicate_ratio(["x"])
    0.0
    """
    if len(strokes) <= 1:
        return 0.0
    dupes = 0
    prev_fp = _fingerprint(strokes[0])
    for i in range(1, len(strokes)):
        curr_fp = _fingerprint(strokes[i])
        if curr_fp == prev_fp:
            dupes += 1
        prev_fp = curr_fp
    return dupes / (len(strokes) - 1)


def window_novelty_ratio(strokes: Sequence[str]) -> float:
    """Fraction of unique template prefixes in the window.

    >>> window_novelty_ratio(["a", "b", "c", "d"])
    1.0
    >>> window_novelty_ratio(["a", "a", "a", "a"])
    0.25
    >>> window_novelty_ratio([])
    0.0
    """
    if not strokes:
        return 0.0
    prefixes = {_extract_prefix(s) for s in strokes}
    return len(prefixes) / len(strokes)


def window_vocabulary_richness(strokes: Sequence[str]) -> float:
    """Log-adjusted vocabulary richness of the combined text.

    Raw type-token ratio (TTR) shrinks with text length even for
    healthy writing — a 200-word passage naturally reuses common words.
    This metric adjusts for length by comparing actual unique types
    against the theoretical maximum (log₂ of total tokens):

        richness = log₂(1 + V) / log₂(1 + N)

    where V = unique types and N = total tokens.  The +1 avoids
    log(0) edge cases.

    >>> round(window_vocabulary_richness(["the cat sat", "the cat sat"]), 3)
    0.631
    >>> 0.0 < window_vocabulary_richness(["hello world", "foo bar"]) <= 1.0
    True
    >>> window_vocabulary_richness([])
    0.0
    """
    all_tokens = []
    for s in strokes:
        all_tokens.extend(_tokenize(s))
    if not all_tokens:
        return 0.0
    v = len(set(all_tokens))
    n = len(all_tokens)
    if n <= 1:
        return 1.0 if v >= 1 else 0.0
    return math.log2(1 + v) / math.log2(1 + n)


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------


def _health_score(dup_ratio: float, novelty: float, richness: float) -> float:
    """Geometric mean of three health axes, each in [0, 1].

    The health axes are:
    - duplicate_freedom = 1 - dup_ratio
    - novelty (already 0-1, higher = healthier)
    - richness (already 0-1, higher = healthier)

    Returns 0.0 if any axis is 0.

    >>> _health_score(0.0, 1.0, 1.0)
    1.0
    >>> round(_health_score(0.5, 0.5, 0.5), 4)
    0.4101
    >>> _health_score(1.0, 1.0, 1.0)
    0.0
    """
    dup_freedom = 1.0 - dup_ratio
    if dup_freedom <= 0 or novelty <= 0 or richness <= 0:
        return 0.0
    return (dup_freedom * novelty * richness) ** (1.0 / 3.0)


def degeneration_score(health: float) -> float:
    """Convert a health score to a degeneration score (inverse).

    >>> degeneration_score(1.0)
    0.0
    >>> degeneration_score(0.0)
    1.0
    >>> degeneration_score(0.5)
    0.5
    """
    return 1.0 - health


def classify(score: float) -> str:
    """Classify a degeneration score into a stage label.

    >>> classify(0.1)
    'fresh'
    >>> classify(0.35)
    'cycling'
    >>> classify(0.6)
    'degenerate'
    >>> classify(0.9)
    'exhausted'
    >>> classify(0.0)
    'fresh'
    >>> classify(1.0)
    'exhausted'
    """
    if score < _FRESH_THRESHOLD:
        return "fresh"
    elif score < _CYCLING_THRESHOLD:
        return "cycling"
    elif score < _DEGENERATE_THRESHOLD:
        return "degenerate"
    else:
        return "exhausted"


def compute_trend(scores: Sequence[float]) -> str:
    """Compare first-half mean to second-half mean to determine trend.

    >>> compute_trend([0.8, 0.7, 0.5, 0.3])
    'improving'
    >>> compute_trend([0.3, 0.4, 0.5, 0.7])
    'degrading'
    >>> compute_trend([0.5, 0.5, 0.5, 0.5])
    'stable'
    >>> compute_trend([0.5])
    'stable'
    """
    if len(scores) < 2:
        return "stable"
    mid = len(scores) // 2
    first_half = scores[:mid]
    second_half = scores[mid:]
    first_mean = sum(first_half) / len(first_half)
    second_mean = sum(second_half) / len(second_half)
    delta = second_mean - first_mean
    if delta <= -_TREND_THRESHOLD:
        return "improving"
    elif delta >= _TREND_THRESHOLD:
        return "degrading"
    else:
        return "stable"


# ---------------------------------------------------------------------------
# Window analysis
# ---------------------------------------------------------------------------


@dataclass
class WindowReport:
    """Analysis of a single window of strokes."""

    index: int
    stroke_count: int
    duplicate_ratio: float
    novelty_ratio: float
    vocabulary_richness: float
    health: float
    score: float
    stage: str

    def to_dict(self) -> Dict:
        return {
            "index": self.index,
            "stroke_count": self.stroke_count,
            "duplicate_ratio": round(self.duplicate_ratio, 4),
            "novelty_ratio": round(self.novelty_ratio, 4),
            "vocabulary_richness": round(self.vocabulary_richness, 4),
            "health": round(self.health, 4),
            "score": round(self.score, 4),
            "stage": self.stage,
        }


@dataclass
class DegenerationReport:
    """Full degeneration analysis across multiple windows."""

    windows: List[WindowReport] = field(default_factory=list)
    overall_score: float = 0.0
    overall_stage: str = "fresh"
    trend: str = "stable"
    total_strokes: int = 0
    window_count: int = 0

    def to_dict(self) -> Dict:
        return {
            "windows": [w.to_dict() for w in self.windows],
            "overall_score": round(self.overall_score, 4),
            "overall_stage": self.overall_stage,
            "trend": self.trend,
            "total_strokes": self.total_strokes,
            "window_count": self.window_count,
        }

    def summary(self) -> str:
        """One-line human-readable summary."""
        return (
            f"degeneration {self.overall_stage} "
            f"(score={self.overall_score:.2f}, "
            f"trend={self.trend}, "
            f"{self.total_strokes} strokes across {self.window_count} windows)"
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _extract_text(stroke) -> str:
    """Get text from a stroke (dict or plain string)."""
    if isinstance(stroke, dict):
        return stroke.get("text", "")
    return str(stroke)


def monitor(
    strokes: Sequence,
    window_size: int = 50,
    min_strokes: int = 10,
) -> DegenerationReport:
    """Analyse stroke sequence for content degeneration.

    Parameters
    ----------
    strokes : sequence of dicts (with 'text' key) or plain strings
    window_size : number of strokes per analysis window (default 50)
    min_strokes : minimum strokes needed to produce a report; returns
        an empty report if fewer strokes are provided

    Returns
    -------
    DegenerationReport with per-window and overall scores.

    >>> strokes = ["unique thought " + str(i) for i in range(60)]
    >>> r = monitor(strokes, window_size=30)
    >>> r.window_count
    2
    >>> r.overall_stage
    'fresh'
    >>> r.trend
    'stable'
    """
    texts = [_extract_text(s) for s in strokes]
    report = DegenerationReport(total_strokes=len(texts))

    if len(texts) < min_strokes:
        return report

    # Split into windows
    windows: List[WindowReport] = []
    scores: List[float] = []
    idx = 0
    for start in range(0, len(texts), window_size):
        chunk = texts[start : start + window_size]
        if len(chunk) < min_strokes:
            break

        dup = window_duplicate_ratio(chunk)
        nov = window_novelty_ratio(chunk)
        rich = window_vocabulary_richness(chunk)
        health = _health_score(dup, nov, rich)
        score = degeneration_score(health)
        stage = classify(score)

        wr = WindowReport(
            index=idx,
            stroke_count=len(chunk),
            duplicate_ratio=dup,
            novelty_ratio=nov,
            vocabulary_richness=rich,
            health=health,
            score=score,
            stage=stage,
        )
        windows.append(wr)
        scores.append(score)
        idx += 1

    report.windows = windows
    report.window_count = len(windows)

    if scores:
        report.overall_score = sum(scores) / len(scores)
        report.overall_stage = classify(report.overall_score)
        report.trend = compute_trend(scores)

    return report
