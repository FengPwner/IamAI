"""Stroke persistence tracker — measure how ideas persist, recur, and fade.

``stroke_diversity`` captures how *varied* the output mix is.
``stroke_transition_tracker`` captures how ideas *connect* between
consecutive strokes.  Neither captures a subtler temporal dimension:
**how long do ideas stay alive, and do they come back?**

Persistence is not repetition — a persistent idea may be explored from
different angles across many strokes, while a repetitive one just copies
the same phrase.  Tracking persistence reveals the *lifecycle of
concepts* in the writer's stream:

* **Persistent** concepts appear across many consecutive strokes — the
  writer is deeply engaged with one thread.
* **Fleeting** concepts appear once or twice then vanish — the writer
  samples broadly but doesn't dwell.
* **Recurring** concepts appear, disappear, then reappear — the writer
  circles back to unfinished threads.
* **Decaying** concepts appear frequently at first then taper off — the
  writer is moving past a topic.

Data model
----------

A **ConceptTrace** records one concept's journey through the stream:

================  =====================================================
field             meaning
================  =====================================================
``concept``       the keyword or phrase being tracked
``appearances``   list of stroke indices where the concept appears
``first_seen``    earliest stroke index
``last_seen``     latest stroke index
``span``          last_seen − first_seen (0 for single-appearance)
``frequency``     len(appearances) / (span + 1) — density within span
``recurrences``   number of gaps > 1 stroke between consecutive appearances
``fade_curve``    list of gap lengths between consecutive appearances
================  =====================================================

Algorithm
---------
1. For each stroke, extract a set of **concept tokens** — significant
   words (length >= 4, not in a stoplist) from the stroke text.
2. Build a mapping: concept → sorted list of stroke indices.
3. For each concept with >= 2 appearances, compute:

   - ``span`` = last index − first index
   - ``frequency`` = count / (span + 1)
   - ``recurrences`` = number of gaps > ``gap_threshold`` between
     consecutive appearances
   - ``fade_curve`` = list of inter-appearance gaps

4. Classify each concept's lifecycle:

=============  ========================================================
lifecycle      description
=============  ========================================================
**persistent** span >= 5 and frequency >= 0.6 — present throughout
**recurring**  recurrences >= 2 — appears, vanishes, returns
**decaying**   gap lengths are increasing (positive trend in fade_curve)
**fleeting**   span <= 2 or only 1 appearance — here and gone
**anchored**   frequency >= 0.8 and recurrences == 0 — in nearly every
               stroke of its span, never missing a beat
=============  ========================================================

5. Aggregate into stream-level metrics:

   - ``persistence_score`` — mean span of all multi-appearance concepts,
     normalized by stream length.  Range [0, 1].
   - ``recurrence_rate`` — fraction of concepts that recur (>= 2 gaps).
   - ``anchor_ratio`` — fraction of concepts classified as anchored.
   - ``fade_ratio`` — fraction classified as decaying.

6. Classify the overall writing pattern:

===================  =================================================
pattern              description
===================  =================================================
**deep-dive**        persistence_score > 0.5, low recurrence_rate —
                     the writer sticks with topics
**scattershot**      persistence_score < 0.2, mostly fleeting —
                     the writer samples widely
**boomerang**        recurrence_rate > 0.3 — ideas keep coming back
**focused-sprint**   high anchor_ratio, short spans — intense but brief
                     engagement with each topic
===================  =================================================

Zero dependencies.  stdlib only.

>>> texts = [
...     "alpha beta gamma delta",
...     "alpha beta gamma delta",
...     "something completely different here now",
...     "another passage with no overlap whatsoever",
...     "alpha beta gamma delta",
...     "alpha beta gamma delta",
...     "nothing shared with earlier passages here",
...     "fresh topics only in this final stroke",
...     "alpha beta gamma delta",
...     "alpha beta gamma delta",
... ]
>>> report = persistence_report(texts)
>>> report["stream_pattern"]
'boomerang'
>>> report["total_concepts"] >= 4
True
>>> report["recurrence_rate"] > 0.0
True
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Sequence, Tuple


# ---------------------------------------------------------------------------
# Stopwords — common words that carry little conceptual weight
# ---------------------------------------------------------------------------

_STOPWORDS: frozenset[str] = frozenset({
    "able", "also", "been", "both", "come", "could", "each", "even",
    "every", "find", "found", "from", "give", "given", "going", "have",
    "here", "into", "just", "keep", "kind", "know", "known", "last",
    "like", "long", "look", "made", "make", "many", "more", "most",
    "much", "must", "need", "next", "only", "other", "over", "part",
    "same", "said", "seen", "seem", "show", "side", "some", "such",
    "sure", "take", "tell", "than", "that", "their", "them", "then",
    "there", "these", "they", "thing", "think", "this", "those",
    "through", "time", "turn", "upon", "used", "very", "want", "well",
    "what", "when", "where", "which", "while", "will", "with", "word",
    "work", "would", "year",
})

_MIN_WORD_LEN = 4
_GAP_THRESHOLD = 2  # gaps larger than this count as recurrences


# ---------------------------------------------------------------------------
# Concept extraction
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z][a-z'_-]{3,}", re.IGNORECASE)


def extract_concepts(text: str) -> set[str]:
    """Extract significant concept tokens from a text string.

    Args:
        text: free-form text from a stroke.

    Returns:
        Set of lowercase concept words, filtered by length and stoplist.

    >>> sorted(extract_concepts("The quick brown fox is very quick"))
    ['brown', 'quick']
    >>> extract_concepts("a b c")
    set()
    >>> extract_concepts("")
    set()
    """
    words = _WORD_RE.findall(text.lower())
    return {
        w for w in words
        if len(w) >= _MIN_WORD_LEN and w not in _STOPWORDS
    }


# ---------------------------------------------------------------------------
# Concept trace computation
# ---------------------------------------------------------------------------

def _compute_trace(concept: str, appearances: list[int]) -> dict[str, Any]:
    """Compute the full trace for one concept.

    Args:
        concept: the concept keyword.
        appearances: sorted list of stroke indices where it appears.

    Returns:
        Dict with all ConceptTrace fields.
    """
    count = len(appearances)
    first = appearances[0]
    last = appearances[-1]
    span = last - first

    if count < 2:
        return {
            "concept": concept,
            "appearances": appearances,
            "first_seen": first,
            "last_seen": last,
            "span": 0,
            "frequency": 1.0,
            "recurrences": 0,
            "fade_curve": [],
            "lifecycle": "fleeting",
        }

    gaps = [
        appearances[i + 1] - appearances[i]
        for i in range(count - 1)
    ]
    frequency = count / (span + 1)
    recurrences = sum(1 for g in gaps if g > _GAP_THRESHOLD)

    # Classify lifecycle
    lifecycle = _classify_lifecycle(span, frequency, recurrences, gaps)

    return {
        "concept": concept,
        "appearances": appearances,
        "first_seen": first,
        "last_seen": last,
        "span": span,
        "frequency": round(frequency, 4),
        "recurrences": recurrences,
        "fade_curve": gaps,
        "lifecycle": lifecycle,
    }


def _classify_lifecycle(
    span: int,
    frequency: float,
    recurrences: int,
    gaps: list[int],
) -> str:
    """Classify a concept's lifecycle pattern.

    Args:
        span: index range (last − first).
        frequency: appearances / (span + 1).
        recurrences: number of gaps exceeding threshold.
        gaps: list of inter-appearance gap lengths.

    Returns:
        One of: 'persistent', 'recurring', 'decaying', 'fleeting', 'anchored'.
    """
    # Anchored: nearly every stroke in span, no recurrences
    if frequency >= 0.8 and recurrences == 0 and span >= 2:
        return "anchored"

    # Recurring: appears, vanishes, comes back (checked before persistent
    # because recurrence is a stronger signal than mere span coverage)
    if recurrences >= 2:
        return "recurring"

    # Persistent: present throughout a wide span without major gaps
    if span >= 5 and frequency >= 0.6:
        return "persistent"

    # Decaying: gaps are getting longer over time
    if len(gaps) >= 3:
        increasing = sum(
            1 for i in range(1, len(gaps)) if gaps[i] > gaps[i - 1]
        )
        if increasing >= len(gaps) - 1:
            return "decaying"

    # Fleeting: short span or few appearances
    return "fleeting"


# ---------------------------------------------------------------------------
# Trend detection for gap sequences
# ---------------------------------------------------------------------------

def gap_trend(gaps: list[int]) -> str:
    """Determine whether gaps are increasing, decreasing, or stable.

    Args:
        gaps: list of inter-appearance gap lengths.

    Returns:
        'increasing', 'decreasing', or 'stable'.

    >>> gap_trend([1, 2, 4, 7])
    'increasing'
    >>> gap_trend([5, 3, 2, 1])
    'decreasing'
    >>> gap_trend([2, 2, 2])
    'stable'
    >>> gap_trend([])
    'stable'
    >>> gap_trend([3])
    'stable'
    """
    if len(gaps) < 2:
        return "stable"

    diffs = [gaps[i + 1] - gaps[i] for i in range(len(gaps) - 1)]
    positive = sum(1 for d in diffs if d > 0)
    negative = sum(1 for d in diffs if d < 0)
    threshold = len(diffs) * 0.5

    if positive > threshold:
        return "increasing"
    if negative > threshold:
        return "decreasing"
    return "stable"


# ---------------------------------------------------------------------------
# Stream-level classification
# ---------------------------------------------------------------------------

def _classify_stream(
    persistence_score: float,
    recurrence_rate: float,
    anchor_ratio: float,
    lifecycle_counts: Counter,
    total_concepts: int,
) -> str:
    """Classify the overall writing pattern from stream metrics.

    Args:
        persistence_score: normalized mean span.
        recurrence_rate: fraction of concepts that recur.
        anchor_ratio: fraction classified as anchored.
        lifecycle_counts: Counter of lifecycle labels.
        total_concepts: total number of tracked concepts.

    Returns:
        One of: 'deep-dive', 'scattershot', 'boomerang', 'focused-sprint'.
    """
    if total_concepts == 0:
        return "scattershot"

    # Boomerang: ideas keep coming back
    if recurrence_rate > 0.3:
        return "boomerang"

    # Focused sprint: anchored concepts with short spans
    if anchor_ratio > 0.3:
        return "focused-sprint"

    # Deep dive: persistent concepts
    if persistence_score > 0.5:
        return "deep-dive"

    # Default: scattershot
    return "scattershot"


# ---------------------------------------------------------------------------
# Main report function
# ---------------------------------------------------------------------------

def persistence_report(
    stroke_texts: Sequence[str],
    *,
    min_appearances: int = 2,
    gap_threshold: int = _GAP_THRESHOLD,
) -> dict[str, Any]:
    """Generate a persistence report for a stream of strokes.

    Args:
        stroke_texts: ordered sequence of stroke text strings.
        min_appearances: minimum appearances to track a concept (default 2).
        gap_threshold: gap size above which a recurrence is counted.

    Returns:
        Dict with keys:

        - ``total_concepts``: number of unique concepts found.
        - ``tracked_concepts``: number meeting min_appearances threshold.
        - ``traces``: list of ConceptTrace dicts for tracked concepts.
        - ``persistence_score``: mean normalized span, range [0, 1].
        - ``recurrence_rate``: fraction of tracked concepts that recur.
        - ``anchor_ratio``: fraction classified as anchored.
        - ``fade_ratio``: fraction classified as decaying.
        - ``lifecycle_counts``: Counter of lifecycle labels.
        - ``stream_pattern``: overall writing pattern classification.
        - ``top_persistent``: top 5 concepts by span.
        - ``top_recurring``: top 5 concepts by recurrence count.

    >>> texts = ["alpha beta gamma delta"] * 6
    >>> r = persistence_report(texts)
    >>> r["stream_pattern"]
    'focused-sprint'
    >>> r["persistence_score"]
    1.0
    """
    stream_len = len(stroke_texts)
    if stream_len == 0:
        return {
            "total_concepts": 0,
            "tracked_concepts": 0,
            "traces": [],
            "persistence_score": 0.0,
            "recurrence_rate": 0.0,
            "anchor_ratio": 0.0,
            "fade_ratio": 0.0,
            "lifecycle_counts": Counter(),
            "stream_pattern": "scattershot",
            "top_persistent": [],
            "top_recurring": [],
        }

    # Step 1: extract concepts per stroke
    concept_map: dict[str, list[int]] = defaultdict(list)
    all_concepts: set[str] = set()

    for idx, text in enumerate(stroke_texts):
        concepts = extract_concepts(text)
        all_concepts.update(concepts)
        for c in concepts:
            concept_map[c].append(idx)

    # Step 2: build traces for concepts meeting threshold
    traces: list[dict[str, Any]] = []
    for concept, appearances in concept_map.items():
        if len(appearances) >= min_appearances:
            trace = _compute_trace(concept, appearances)
            # Override gap_threshold if caller changed it
            if gap_threshold != _GAP_THRESHOLD:
                trace["recurrences"] = sum(
                    1 for g in trace["fade_curve"] if g > gap_threshold
                )
                trace["lifecycle"] = _classify_lifecycle(
                    trace["span"],
                    trace["frequency"],
                    trace["recurrences"],
                    trace["fade_curve"],
                )
            traces.append(trace)

    # Step 3: compute stream metrics
    tracked = len(traces)
    lifecycle_counts: Counter = Counter(t["lifecycle"] for t in traces)

    if tracked > 0 and stream_len > 1:
        spans = [t["span"] for t in traces]
        persistence_score = sum(spans) / (len(spans) * (stream_len - 1))
        persistence_score = min(persistence_score, 1.0)
        recurrence_rate = lifecycle_counts.get("recurring", 0) / tracked
        anchor_ratio = lifecycle_counts.get("anchored", 0) / tracked
        fade_ratio = lifecycle_counts.get("decaying", 0) / tracked
    else:
        persistence_score = 0.0
        recurrence_rate = 0.0
        anchor_ratio = 0.0
        fade_ratio = 0.0

    # Step 4: classify stream pattern
    stream_pattern = _classify_stream(
        persistence_score,
        recurrence_rate,
        anchor_ratio,
        lifecycle_counts,
        len(all_concepts),
    )

    # Step 5: top concepts
    top_persistent = sorted(traces, key=lambda t: t["span"], reverse=True)[:5]
    top_recurring = sorted(
        traces, key=lambda t: t["recurrences"], reverse=True
    )[:5]

    return {
        "total_concepts": len(all_concepts),
        "tracked_concepts": tracked,
        "traces": traces,
        "persistence_score": round(persistence_score, 4),
        "recurrence_rate": round(recurrence_rate, 4),
        "anchor_ratio": round(anchor_ratio, 4),
        "fade_ratio": round(fade_ratio, 4),
        "lifecycle_counts": dict(lifecycle_counts),
        "stream_pattern": stream_pattern,
        "top_persistent": [
            {"concept": t["concept"], "span": t["span"], "lifecycle": t["lifecycle"]}
            for t in top_persistent
        ],
        "top_recurring": [
            {
                "concept": t["concept"],
                "recurrences": t["recurrences"],
                "lifecycle": t["lifecycle"],
            }
            for t in top_recurring
        ],
    }


# ---------------------------------------------------------------------------
# Convenience: quick health check
# ---------------------------------------------------------------------------

def persistence_health(report: dict[str, Any]) -> str:
    """Return a one-word health assessment from a persistence report.

    Args:
        report: output of :func:`persistence_report`.

    Returns:
        One of: 'healthy', 'shallow', 'stale', 'mixed'.

    >>> persistence_health({"stream_pattern": "deep-dive", "persistence_score": 0.7})
    'healthy'
    >>> persistence_health({"stream_pattern": "scattershot", "persistence_score": 0.1})
    'shallow'
    >>> persistence_health({"stream_pattern": "boomerang", "persistence_score": 0.3})
    'mixed'
    """
    pattern = report.get("stream_pattern", "scattershot")
    score = report.get("persistence_score", 0.0)

    if pattern == "deep-dive" and score > 0.5:
        return "healthy"
    if pattern == "scattershot" and score < 0.2:
        return "shallow"
    if pattern == "boomerang":
        return "mixed"
    if pattern == "focused-sprint":
        return "healthy"
    return "mixed"


if __name__ == "__main__":
    import doctest
    doctest.testmod()
