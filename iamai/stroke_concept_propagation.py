"""stroke_concept_propagation — track how ideas spread through the stroke stream.

While ``stroke_repetition_detector`` flags near-duplicate *content* and
``stroke_thematic_coherence`` measures whether a batch stays on topic,
neither answers: *when the writer introduces a concept, does it stick?*

A self-writing repo that constantly invents new vocabulary without
revisiting old ideas is a diary, not a knowledge base.  A repo that
reuses the same words forever is a parrot.  The sweet spot is
**propagation**: new ideas surface, some take root and propagate,
others die off naturally.

This module quantifies three dimensions of concept propagation:

1. **Concept echo rate** — when a distinctive word first appears,
   how many subsequent strokes echo it within a horizon?
2. **Concept half-life** — how many strokes does a concept survive
   before its usage drops below half its peak frequency?
3. **Idea adoption curve** — classify each concept's trajectory as
   *viral* (rapid adoption), *steady* (consistent reuse), *flash*
   (brief spike then silence), or *stillborn* (never reused).

Algorithm
---------
We extract **content words** (lowercase tokens ≥ 4 chars, excluding
stopwords) from each stroke, then track each word's *usage timeline*:
the sequence of stroke indices where it appears.

    echo_rate(w)      = |{i : w ∈ stroke_i, i ∈ (first(w), first(w)+H]}|
                        / H
    half_life(w)      = smallest d such that count(w, first(w)+d .. ∞)
                        < peak_window_count(w) / 2
    adoption_class(w) = classify(echo_rate, half_life, total_uses)

Regime classification for the overall stream:

==================  =====================================================
avg_echo_rate       regime
==================  =====================================================
≥ 0.40              **sticky** — ideas propagate strongly
0.25 – 0.40         **cultivating** — ideas are revisited moderately
0.12 – 0.25         **ephemeral** — ideas surface and fade quickly
< 0.12              **scattershot** — no concept persistence
==================  =====================================================

Edge cases
----------
* Empty input -> zeroed report.
* Single stroke -> no propagation possible.
* All strokes identical -> echo_rate = 1.0 for all concepts.
* Very short strokes (no content words) -> skipped.

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 728, 2026-11-19.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

# ---------------------------------------------------------------------------
# Common English stopwords (minimal set; keeps proper nouns and rare words)
# ---------------------------------------------------------------------------

_STOPWORDS: Set[str] = {
    "about", "above", "after", "again", "against", "all", "also", "another",
    "any", "because", "been", "before", "below", "between", "both", "came",
    "come", "could", "does", "done", "down", "each", "even", "every", "first",
    "from", "give", "given", "gives", "going", "gone", "great", "great",
    "have", "having", "here", "high", "however", "into", "itself", "just",
    "keep", "kept", "kind", "last", "like", "little", "long", "look", "made",
    "make", "many", "more", "most", "much", "must", "name", "never", "next",
    "nothing", "number", "off", "often", "once", "only", "other", "over",
    "part", "place", "point", "right", "same", "second", "seem", "seems",
    "shall", "show", "side", "since", "small", "some", "such", "take",
    "than", "that", "their", "them", "then", "there", "these", "they",
    "thing", "think", "this", "those", "through", "time", "together",
    "under", "upon", "very", "want", "well", "were", "what", "when",
    "where", "which", "while", "will", "with", "without", "word", "work",
    "world", "would", "year", "your",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ConceptTimeline:
    """Usage timeline for a single concept (word) across the stroke stream."""

    word: str
    first_seen: int  # stroke index (0-based) where first appears
    appearances: List[int]  # sorted list of stroke indices where it appears
    total_uses: int  # total number of strokes containing this word
    peak_window_count: int  # max uses in any window of size ``peak_window``
    peak_window_start: int  # start index of the peak window

    @property
    def span(self) -> int:
        """Distance from first to last appearance."""
        if len(self.appearances) < 2:
            return 0
        return self.appearances[-1] - self.appearances[0]


@dataclass
class ConceptReport:
    """Propagation metrics for a single concept."""

    word: str
    echo_rate: float  # fraction of horizon strokes that reuse the concept
    half_life: int  # strokes until usage drops below half peak
    adoption_class: str  # viral / steady / flash / stillborn
    total_uses: int
    span: int  # first-to-last distance


@dataclass
class PropagationReport:
    """Overall propagation health of the stroke stream."""

    total_strokes: int
    total_concepts: int  # unique content words seen
    concepts_tracked: int  # concepts with enough data to analyse
    avg_echo_rate: float
    median_half_life: float
    adoption_distribution: Dict[str, int]  # class -> count
    regime: str  # sticky / cultivating / ephemeral / scattershot
    top_concepts: List[ConceptReport]  # top N by echo_rate
    concept_timelines: Dict[str, ConceptTimeline] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tokenisation helpers
# ---------------------------------------------------------------------------


def extract_content_words(text: str, min_len: int = 4) -> List[str]:
    """Extract lowercase content words from text.

    Content words are alphabetic tokens of at least ``min_len`` characters,
    excluding stopwords.
    """
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    return [t for t in tokens if len(t) >= min_len and t not in _STOPWORDS]


def build_word_timelines(
    texts: Sequence[str], min_len: int = 4
) -> Dict[str, List[int]]:
    """Map each content word to the sorted list of stroke indices it appears in."""
    timelines: Dict[str, List[int]] = defaultdict(list)
    for idx, text in enumerate(texts):
        words = set(extract_content_words(text, min_len=min_len))
        for w in words:
            timelines[w].append(idx)
    return dict(timelines)


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------


def compute_echo_rate(
    appearances: List[int],
    total_strokes: int,
    horizon: Optional[int] = None,
) -> float:
    """Fraction of strokes after first appearance that reuse the concept.

    Parameters
    ----------
    appearances : sorted list of stroke indices where concept appears
    total_strokes : total number of strokes in the stream
    horizon : how many strokes after first_seen to consider
              (None = all remaining strokes)
    """
    if len(appearances) < 2 or total_strokes < 2:
        return 0.0
    first = appearances[0]
    if horizon is None:
        horizon = total_strokes - first - 1
    if horizon <= 0:
        return 0.0
    # Count appearances in (first, first + horizon]
    echoes = sum(1 for a in appearances if first < a <= first + horizon)
    return min(echoes / horizon, 1.0)


def compute_half_life(
    appearances: List[int],
    total_strokes: int,
    window_size: int = 10,
) -> int:
    """Number of strokes until usage drops below half of peak window count.

    Uses a sliding window of ``window_size`` strokes starting from
    first appearance.  Returns the distance from first appearance to
    the start of the first window whose count < peak/2.  If usage
    never drops below half peak, returns the full span.
    """
    if len(appearances) < 2:
        return 0
    first = appearances[0]
    last = appearances[-1]

    # Build window counts
    best_count = 0
    best_start = first
    window_counts: List[Tuple[int, int]] = []  # (start, count)

    for start in range(first, last + 1):
        count = sum(1 for a in appearances if start <= a < start + window_size)
        window_counts.append((start, count))
        if count > best_count:
            best_count = count
            best_start = start

    if best_count == 0:
        return 0

    threshold = best_count / 2.0
    for start, count in window_counts:
        if start > best_start and count < threshold:
            return start - first

    return last - first


def classify_adoption(
    echo_rate: float,
    half_life: int,
    total_uses: int,
    echo_high: float = 0.30,
    echo_low: float = 0.10,
    hl_long: int = 20,
    hl_short: int = 5,
) -> str:
    """Classify a concept's adoption trajectory.

    Returns one of: viral, steady, flash, stillborn.
    """
    if total_uses <= 1:
        return "stillborn"
    if echo_rate >= echo_high and half_life <= hl_short:
        return "viral"  # high echo, burns out fast
    if echo_rate >= echo_high and half_life > hl_long:
        return "steady"  # high echo, persists long
    if echo_rate < echo_low:
        return "stillborn"  # barely reused
    return "flash"  # moderate echo, moderate life


def _classify_regime(avg_echo_rate: float) -> str:
    """Classify overall stream propagation regime."""
    if avg_echo_rate >= 0.40:
        return "sticky"
    if avg_echo_rate >= 0.25:
        return "cultivating"
    if avg_echo_rate >= 0.12:
        return "ephemeral"
    return "scattershot"


# ---------------------------------------------------------------------------
# Concept timeline builder
# ---------------------------------------------------------------------------


def build_concept_timeline(
    word: str,
    appearances: List[int],
    total_strokes: int,
    peak_window: int = 10,
) -> ConceptTimeline:
    """Build a ConceptTimeline for a single word."""
    # Find peak window
    best_count = 0
    best_start = appearances[0] if appearances else 0
    first = appearances[0] if appearances else 0
    last = appearances[-1] if appearances else 0

    for start in range(first, last + 1):
        count = sum(1 for a in appearances if start <= a < start + peak_window)
        if count > best_count:
            best_count = count
            best_start = start

    return ConceptTimeline(
        word=word,
        first_seen=first,
        appearances=list(appearances),
        total_uses=len(appearances),
        peak_window_count=best_count,
        peak_window_start=best_start,
    )


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def analyse_propagation(
    texts: Sequence[str],
    horizon: Optional[int] = 50,
    min_uses: int = 2,
    min_len: int = 4,
    peak_window: int = 10,
    top_n: int = 10,
) -> PropagationReport:
    """Analyse concept propagation across the stroke stream.

    Parameters
    ----------
    texts : sequence of raw stroke texts
    horizon : how many strokes after first appearance to track echo
    min_uses : minimum appearances to include a concept in analysis
    min_len : minimum word length for content words
    peak_window : window size for half-life calculation
    top_n : number of top concepts to include in report

    Returns
    -------
    PropagationReport with overall stream metrics and per-concept details.
    """
    n = len(texts)
    if n == 0:
        return PropagationReport(
            total_strokes=0,
            total_concepts=0,
            concepts_tracked=0,
            avg_echo_rate=0.0,
            median_half_life=0.0,
            adoption_distribution={"viral": 0, "steady": 0, "flash": 0, "stillborn": 0},
            regime="scattershot",
            top_concepts=[],
        )

    timelines = build_word_timelines(texts, min_len=min_len)
    total_concepts = len(timelines)

    # Filter to concepts with enough data
    eligible = {w: apps for w, apps in timelines.items() if len(apps) >= min_uses}

    reports: List[ConceptReport] = []
    concept_timelines: Dict[str, ConceptTimeline] = {}

    for word, apps in eligible.items():
        er = compute_echo_rate(apps, n, horizon=horizon)
        hl = compute_half_life(apps, n, window_size=peak_window)
        ac = classify_adoption(er, hl, len(apps))
        ct = build_concept_timeline(word, apps, n, peak_window=peak_window)

        concept_timelines[word] = ct
        reports.append(
            ConceptReport(
                word=word,
                echo_rate=round(er, 4),
                half_life=hl,
                adoption_class=ac,
                total_uses=len(apps),
                span=ct.span,
            )
        )

    # Aggregate
    if reports:
        avg_er = sum(r.echo_rate for r in reports) / len(reports)
        half_lives = sorted(r.half_life for r in reports)
        median_hl = half_lives[len(half_lives) // 2]
    else:
        avg_er = 0.0
        median_hl = 0.0

    adoption_dist = {"viral": 0, "steady": 0, "flash": 0, "stillborn": 0}
    for r in reports:
        adoption_dist[r.adoption_class] += 1

    # Top concepts by echo rate
    reports.sort(key=lambda r: r.echo_rate, reverse=True)
    top = reports[:top_n]

    return PropagationReport(
        total_strokes=n,
        total_concepts=total_concepts,
        concepts_tracked=len(eligible),
        avg_echo_rate=round(avg_er, 4),
        median_half_life=round(median_hl, 1),
        adoption_distribution=adoption_dist,
        regime=_classify_regime(avg_er),
        top_concepts=top,
        concept_timelines=concept_timelines,
    )


# ---------------------------------------------------------------------------
# Sliding-window analysis
# ---------------------------------------------------------------------------


def analyse_propagation_windows(
    texts: Sequence[str],
    window_size: int = 100,
    step: int = 50,
    horizon: Optional[int] = 30,
    min_uses: int = 2,
) -> List[PropagationReport]:
    """Sliding-window propagation analysis to track idea persistence over time.

    Parameters
    ----------
    texts : sequence of raw stroke texts
    window_size : number of strokes per window
    step : stride between windows
    horizon : echo horizon within each window
    min_uses : minimum appearances per concept

    Returns
    -------
    List of PropagationReport, one per window.
    """
    if window_size < 2 or step < 1:
        raise ValueError("window_size must be >= 2 and step must be >= 1")

    reports: List[PropagationReport] = []
    for start in range(0, len(texts) - window_size + 1, step):
        window = texts[start : start + window_size]
        reports.append(
            analyse_propagation(window, horizon=horizon, min_uses=min_uses)
        )
    return reports
