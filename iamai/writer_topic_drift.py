#!/usr/bin/env python3
"""writer_topic_drift — measure how a writer's topic focus shifts over time.

A writer that never changes topic is stuck in a rut.  A writer that
changes topic every commit is skimming the surface.  Somewhere between
those extremes lies productive exploration: sustained dives into an area,
punctuated by deliberate moves to adjacent work.

This module quantifies that balance by classifying every file a commit
touches into a **topic area** and measuring how the distribution of those
areas evolves across successive time windows.

Topic areas are derived from file paths using a configurable prefix map.
The defaults reflect this repository's layout:

  - ``iamai/caretaker_*`` → caretaker
  - ``iamai/cadence_*``   → cadence
  - ``iamai/writer_*``    → writer-self
  - ``iamai/batch*``      → batch
  - ``iamai/commit_*``    → commit-analysis
  - ``tests/*``           → testing
  - ``docs/*``            → documentation
  - ``notes/*``           → reflection
  - ``tools/*``           → tooling
  - anything else         → other

A commit can belong to multiple areas (a refactor that touches both
``iamai/cadence_jitter.py`` and ``tests/test_cadence_jitter.py`` spans
cadence and testing).

Topic drift dimensions
----------------------

========================  ================================================
metric                    meaning
========================  ================================================
topic_entropy             Shannon entropy (base-2) of the area distribution
                          across all commits in the window; 0 = single
                          area, log2(N) = uniform spread over N areas
concentration_index       fraction of file-changes in the single most-
                          touched area (higher = more focused)
transition_rate           fraction of consecutive commit pairs where the
                          dominant (most-files) area changes
                          (higher = more topic switching)
topic_stability           mean Jaccard similarity of area sets between
                          consecutive window pairs (higher = less drift)
drift_score               composite 0.0–1.0: low = focused / stable;
                          high = scattered / erratic
focus_class               focused | exploring | drifting | scattered |
                          oscillating
========================  ================================================

Focus classes
-------------

==============  ============================================================
class           meaning
==============  ============================================================
focused         score < 0.25 — deep work in one or two areas; healthy
                sustained attention
exploring       0.25 ≤ score < 0.45 — deliberate movement across areas;
                productive breadth
drifting        0.45 ≤ score < 0.65 — no clear focus, topics shift without
                obvious intent
scattered       0.65 ≤ score < 0.85 — rapid topic changes, high entropy;
                likely context-thrashing
oscillating     score ≥ 0.85 — extreme instability; the writer bounces
                between unrelated areas with no sustained thread
==============  ============================================================

Usage
-----

::

    from iamai.writer_topic_drift import compute_drift, StrokeRecord

    strokes = [StrokeRecord(timestamp=..., files=[...]), ...]
    result = compute_drift(strokes, window_size=50)
    print(drift_report(result))
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StrokeRecord:
    """A single writing event (commit or stroke) with its affected files."""

    timestamp: datetime
    files: List[str] = field(default_factory=list)
    message: str = ""

    def topics(self, prefix_map: Optional[Dict[str, str]] = None) -> set:
        """Derive topic areas from file paths using *prefix_map*."""
        return {_classify_file(f, prefix_map) for f in self.files}

    def dominant_topic(self, prefix_map: Optional[Dict[str, str]] = None) -> str:
        """Return the topic area with the most files in this stroke."""
        if not self.files:
            return "other"
        counts: Counter = Counter()
        for f in self.files:
            counts[_classify_file(f, prefix_map)] += 1
        return counts.most_common(1)[0][0]


@dataclass
class DriftResult:
    """Results of a topic-drift analysis."""

    window_strokes: int
    topic_entropy: float
    concentration_index: float
    transition_rate: float
    topic_stability: float
    drift_score: float
    focus_class: str
    area_distribution: Dict[str, float] = field(default_factory=dict)


@dataclass
class DriftTrend:
    """How drift scores change across successive windows."""

    direction: str  # increasing | stable | decreasing
    score_delta: float
    earliest_score: float
    latest_score: float
    sample_count: int


# ---------------------------------------------------------------------------
# Default prefix map
# ---------------------------------------------------------------------------

_DEFAULT_PREFIX_MAP: Dict[str, str] = {
    "iamai/caretaker": "caretaker",
    "iamai/cadence": "cadence",
    "iamai/writer_": "writer-self",
    "iamai/batch": "batch",
    "iamai/commit_": "commit-analysis",
    "tests/": "testing",
    "docs/": "documentation",
    "notes/": "reflection",
    "tools/": "tooling",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify_file(path: str, prefix_map: Optional[Dict[str, str]] = None) -> str:
    """Map a file path to a topic area using the longest matching prefix."""
    pm = prefix_map if prefix_map is not None else _DEFAULT_PREFIX_MAP
    best_match = ""
    best_area = "other"
    for prefix, area in pm.items():
        if path.startswith(prefix) and len(prefix) > len(best_match):
            best_match = prefix
            best_area = area
    return best_area


def _shannon_entropy(dist: Counter) -> float:
    """Compute Shannon entropy (base-2) from a Counter of counts."""
    total = sum(dist.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in dist.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------

def topic_entropy(strokes: Sequence[StrokeRecord],
                  prefix_map: Optional[Dict[str, str]] = None) -> Tuple[float, Dict[str, float]]:
    """Compute topic entropy and area distribution across strokes.

    Returns
    -------
    tuple of (entropy, distribution_dict)
        entropy is in bits (log-base-2); distribution maps area → fraction.
    """
    counts: Counter = Counter()
    for s in strokes:
        for f in s.files:
            counts[_classify_file(f, prefix_map)] += 1

    total = sum(counts.values())
    if total == 0:
        return (0.0, {})

    dist = {area: count / total for area, count in counts.items()}
    entropy = _shannon_entropy(counts)
    return (round(entropy, 4), dist)


def concentration_index(strokes: Sequence[StrokeRecord],
                        prefix_map: Optional[Dict[str, str]] = None) -> float:
    """Fraction of file-changes in the most-touched area."""
    counts: Counter = Counter()
    for s in strokes:
        for f in s.files:
            counts[_classify_file(f, prefix_map)] += 1

    total = sum(counts.values())
    if total == 0:
        return 0.0
    return round(counts.most_common(1)[0][1] / total, 4)


def transition_rate(strokes: Sequence[StrokeRecord],
                    prefix_map: Optional[Dict[str, str]] = None) -> float:
    """Fraction of consecutive stroke pairs where dominant topic changes."""
    if len(strokes) < 2:
        return 0.0

    transitions = 0
    comparisons = 0
    prev_dominant = strokes[0].dominant_topic(prefix_map)
    for s in strokes[1:]:
        curr_dominant = s.dominant_topic(prefix_map)
        comparisons += 1
        if curr_dominant != prev_dominant:
            transitions += 1
        prev_dominant = curr_dominant

    return round(transitions / comparisons, 4) if comparisons > 0 else 0.0


def topic_stability(strokes: Sequence[StrokeRecord],
                    window_size: int = 10,
                    prefix_map: Optional[Dict[str, str]] = None) -> float:
    """Mean Jaccard similarity of topic-area sets between consecutive sub-windows.

    The stroke list is split into chunks of *window_size*; similarity is
    measured between each pair of adjacent chunks.
    """
    if len(strokes) < 2 * window_size:
        # Not enough data for two windows — compare first half vs second half
        mid = len(strokes) // 2
        if mid == 0:
            return 1.0
        a_areas: set = set()
        b_areas: set = set()
        for s in strokes[:mid]:
            a_areas |= s.topics(prefix_map)
        for s in strokes[mid:]:
            b_areas |= s.topics(prefix_map)
        return round(_jaccard(a_areas, b_areas), 4)

    # Split into chunks
    chunks = []
    for i in range(0, len(strokes), window_size):
        chunk = strokes[i:i + window_size]
        if len(chunk) >= window_size // 2:  # skip tiny tail chunks
            areas: set = set()
            for s in chunk:
                areas |= s.topics(prefix_map)
            chunks.append(areas)

    if len(chunks) < 2:
        return 1.0

    sims = [_jaccard(chunks[i], chunks[i + 1]) for i in range(len(chunks) - 1)]
    return round(sum(sims) / len(sims), 4)


def classify_focus(score: float) -> str:
    """Classify focus from a composite drift score."""
    if score < 0.25:
        return "focused"
    elif score < 0.45:
        return "exploring"
    elif score < 0.65:
        return "drifting"
    elif score < 0.85:
        return "scattered"
    else:
        return "oscillating"


def compute_drift(strokes: Sequence[StrokeRecord],
                  window_size: int = 50,
                  prefix_map: Optional[Dict[str, str]] = None) -> DriftResult:
    """Compute topic-drift metrics for a sequence of strokes.

    Parameters
    ----------
    strokes : sequence of StrokeRecord
        Strokes ordered oldest-first.
    window_size : int
        Number of strokes per analysis window.
    prefix_map : dict, optional
        Custom prefix → area mapping.  Uses defaults when *None*.

    Returns
    -------
    DriftResult
    """
    n = len(strokes)
    if n == 0:
        return DriftResult(
            window_strokes=0,
            topic_entropy=0.0,
            concentration_index=0.0,
            transition_rate=0.0,
            topic_stability=1.0,
            drift_score=0.0,
            focus_class="focused",
            area_distribution={},
        )

    # Use the last `window_size` strokes for the primary window
    window = strokes[-window_size:] if n > window_size else list(strokes)

    ent, dist = topic_entropy(window, prefix_map)
    conc = concentration_index(window, prefix_map)
    trans = transition_rate(window, prefix_map)
    stab = topic_stability(window, window_size=max(5, window_size // 5), prefix_map=prefix_map)

    # Normalize entropy: 0 is most focused, 1.0 is maximum spread
    # For a typical repo with ~8 topic areas, max entropy ≈ 3.0 bits
    # Normalize against a practical ceiling of 3.5 bits
    max_entropy = 3.5
    norm_entropy = min(ent / max_entropy, 1.0)

    # Composite score:
    #   high entropy       → more drift       (weight 0.30)
    #   low concentration  → more drift       (weight 0.20)
    #   high transitions   → more drift       (weight 0.30)
    #   low stability      → more drift       (weight 0.20)
    drift_score = round(
        0.30 * norm_entropy
        + 0.20 * (1.0 - conc)
        + 0.30 * trans
        + 0.20 * (1.0 - stab),
        4,
    )

    focus_class = classify_focus(drift_score)

    return DriftResult(
        window_strokes=len(window),
        topic_entropy=ent,
        concentration_index=conc,
        transition_rate=trans,
        topic_stability=stab,
        drift_score=drift_score,
        focus_class=focus_class,
        area_distribution=dist,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def drift_report(result: DriftResult) -> str:
    """Human-readable summary of a topic-drift analysis."""
    lines = [
        f"Topic drift analysis ({result.window_strokes} strokes)",
        f"  class:                {result.focus_class}",
        f"  drift score:          {result.drift_score:.2f}",
        f"  topic entropy:        {result.topic_entropy:.2f} bits",
        f"  concentration index:  {result.concentration_index:.2%}",
        f"  transition rate:      {result.transition_rate:.2%}",
        f"  topic stability:      {result.topic_stability:.2f}",
    ]
    if result.area_distribution:
        lines.append("  area distribution:")
        for area, frac in sorted(result.area_distribution.items(),
                                  key=lambda x: -x[1]):
            lines.append(f"    {area:20s} {frac:.1%}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def drift_trend(results: Sequence[DriftResult]) -> DriftTrend:
    """Classify how drift scores evolve across a series of measurements."""
    if not results:
        return DriftTrend(
            direction="stable",
            score_delta=0.0,
            earliest_score=0.0,
            latest_score=0.0,
            sample_count=0,
        )

    scores = [r.drift_score for r in results]
    earliest = scores[0]
    latest = scores[-1]
    delta = round(latest - earliest, 4)

    if len(scores) < 2:
        direction = "stable"
    elif delta > 0.05:
        direction = "increasing"
    elif delta < -0.05:
        direction = "decreasing"
    else:
        direction = "stable"

    return DriftTrend(
        direction=direction,
        score_delta=delta,
        earliest_score=earliest,
        latest_score=latest,
        sample_count=len(results),
    )
