"""Stroke drift tracker — measure how much writing topics shift over time.

``stroke_persistence`` tracks *which* concepts survive across the stream.
``stroke_resonance`` measures *forward projection* of a single stroke's
ideas.  ``stroke_thematic_coherence`` evaluates *overall* consistency.
None of these captures a simpler, more visual question: **how far has
the writing drifted from where it started?**

Drift is the *cumulative directional shift* in topic space.  A writer
might produce coherent, resonant strokes and still drift steadily away
from the opening themes — like a conversation that naturally evolves.
Conversely, a writer might bounce between unrelated topics but always
return to a home base, resulting in low net drift despite high
stroke-to-stroke volatility.

Concepts
--------

==================  ====================================================
term                meaning
==================  ====================================================
**step_drift**      1 − Jaccard(concepts_i, concepts_{i+1}) — how much
                    one stroke differs from the next
**cumulative_drift** running sum of step_drifts, normalized by count
**window_drift**    1 − Jaccard(concepts_start, concepts_end) within a
                    sliding window — direct start-to-end distance
**drift_velocity**  rate of drift change: is the writer accelerating
                    away from origin or settling back?
**drift_pattern**   classification of the drift curve shape
==================  ====================================================

Drift patterns
--------------

===================  =================================================
pattern              description
===================  =================================================
**stable**           drift stays low — writer stays on topic
**gradual**          drift increases steadily — natural evolution
**oscillating**      drift goes up and down — writer explores then
                     returns
**pivoting**         sudden jump in drift — topic change mid-stream
**wandering**        high variance, no clear direction — unfocused
===================  =================================================

Zero dependencies.  stdlib only.

>>> texts = [
...     "alpha beta gamma delta epsilon",
...     "alpha beta gamma delta zeta",
...     "alpha beta gamma eta theta",
...     "alpha beta iota kappa lambda",
...     "alpha mu nu xi omicron",
... ]
>>> report = drift_report(texts)
>>> report["drift_pattern"] in ("gradual", "stable", "oscillating", "pivoting", "wandering")
True
>>> 0.0 <= report["cumulative_drift"] <= 1.0
True
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple


# ---------------------------------------------------------------------------
# Stopwords
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


# ---------------------------------------------------------------------------
# Concept extraction
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z][a-z'_-]{3,}", re.IGNORECASE)


def extract_concepts(text: str) -> set[str]:
    """Extract significant concept tokens from text.

    Args:
        text: free-form stroke text.

    Returns:
        Set of lowercase concept words.

    >>> sorted(extract_concepts("The quick brown fox is very quick"))
    ['brown', 'quick']
    >>> extract_concepts("a b c")
    set()
    """
    words = _WORD_RE.findall(text.lower())
    return {w for w in words if len(w) >= _MIN_WORD_LEN and w not in _STOPWORDS}


# ---------------------------------------------------------------------------
# Distance metrics
# ---------------------------------------------------------------------------

def jaccard_distance(a: set[str], b: set[str]) -> float:
    """Compute Jaccard distance between two sets.

    Args:
        a: first concept set.
        b: second concept set.

    Returns:
        1 − |a ∩ b| / |a ∪ b|.  Returns 0.0 for two empty sets.

    >>> round(jaccard_distance({"a", "b"}, {"b", "c"}), 4)
    0.6667
    >>> jaccard_distance(set(), set())
    0.0
    >>> jaccard_distance({"a"}, {"b"})
    1.0
    """
    if not a and not b:
        return 0.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return 1.0 - len(a & b) / union


def step_drift(concept_sets: list[set[str]]) -> list[float]:
    """Compute per-step drift between consecutive concept sets.

    Args:
        concept_sets: ordered list of concept sets per stroke.

    Returns:
        List of Jaccard distances, length = len(concept_sets) − 1.

    >>> [round(x, 4) for x in step_drift([{"a", "b"}, {"b", "c"}, {"c", "d"}])]
    [0.6667, 0.6667]
    >>> step_drift([{"a"}])
    []
    """
    return [
        jaccard_distance(concept_sets[i], concept_sets[i + 1])
        for i in range(len(concept_sets) - 1)
    ]


def window_drift(
    concept_sets: list[set[str]],
    window: int = 5,
) -> list[float]:
    """Compute sliding-window drift (start-to-end distance per window).

    Args:
        concept_sets: ordered list of concept sets.
        window: number of strokes per window (must be >= 2).

    Returns:
        List of window drift values.

    >>> window_drift([{"a", "b", "c"}, {"b", "c", "d"}, {"c", "d", "e"}, {"d", "e", "f"}, {"e", "f", "g"}], window=3)
    [0.8, 0.8, 0.8]
    """
    if window < 2:
        window = 2
    results = []
    for i in range(len(concept_sets) - window + 1):
        start = concept_sets[i]
        end = concept_sets[i + window - 1]
        results.append(jaccard_distance(start, end))
    return results


# ---------------------------------------------------------------------------
# Drift velocity
# ---------------------------------------------------------------------------

def drift_velocity(step_drifts: list[float]) -> list[float]:
    """Compute drift velocity — the rate of change in step drift.

    Positive velocity means the writer is accelerating away from the
    previous stroke's topic; negative means settling closer.

    Args:
        step_drifts: list of per-step drift values.

    Returns:
        List of velocity values (differences), length = len(step_drifts) − 1.

    >>> drift_velocity([0.2, 0.4, 0.3, 0.6])
    [0.2, -0.1, 0.3]
    >>> drift_velocity([0.5])
    []
    """
    return [
        round(step_drifts[i + 1] - step_drifts[i], 4)
        for i in range(len(step_drifts) - 1)
    ]


# ---------------------------------------------------------------------------
# Pattern classification
# ---------------------------------------------------------------------------

def _classify_drift_pattern(
    step_drifts: list[float],
    cumulative: float,
    velocities: list[float],
) -> str:
    """Classify the overall drift pattern.

    Args:
        step_drifts: per-step Jaccard distances.
        cumulative: normalized cumulative drift.
        velocities: rate-of-change values.

    Returns:
        One of: 'stable', 'gradual', 'oscillating', 'pivoting', 'wandering'.
    """
    if not step_drifts:
        return "stable"

    mean_drift = sum(step_drifts) / len(step_drifts)

    # Stable: very low average drift
    if mean_drift < 0.2:
        return "stable"

    # Check for pivoting: any single step with drift > 0.8
    max_step = max(step_drifts)
    if max_step > 0.8 and len(step_drifts) >= 3:
        return "pivoting"

    # Oscillating: high variance in velocities (sign changes)
    if len(velocities) >= 2:
        sign_changes = sum(
            1 for i in range(len(velocities) - 1)
            if (velocities[i] > 0 and velocities[i + 1] < 0)
            or (velocities[i] < 0 and velocities[i + 1] > 0)
        )
        change_ratio = sign_changes / len(velocities)
        if change_ratio > 0.5:
            return "oscillating"

    # Wandering: high variance, no clear trend
    if len(velocities) >= 2:
        var = sum(v ** 2 for v in velocities) / len(velocities)
        if var > 0.05:
            return "wandering"

    # Gradual: steady increase or consistent drift
    if cumulative > 0.3 and mean_drift >= 0.2:
        return "gradual"

    return "stable"


# ---------------------------------------------------------------------------
# Cumulative drift
# ---------------------------------------------------------------------------

def cumulative_drift(step_drifts: list[float]) -> float:
    """Compute normalized cumulative drift.

    Average of all step drifts, representing overall topic shift.
    Range [0, 1].

    Args:
        step_drifts: per-step Jaccard distances.

    Returns:
        Mean step drift, clamped to [0, 1].

    >>> cumulative_drift([0.5, 0.5, 0.5])
    0.5
    >>> cumulative_drift([])
    0.0
    """
    if not step_drifts:
        return 0.0
    return min(sum(step_drifts) / len(step_drifts), 1.0)


# ---------------------------------------------------------------------------
# Drift health
# ---------------------------------------------------------------------------

def drift_health(pattern: str, cumulative: float) -> str:
    """One-word health assessment from drift metrics.

    Args:
        pattern: drift pattern classification.
        cumulative: normalized cumulative drift value.

    Returns:
        One of: 'focused', 'evolving', 'scattered', 'mixed'.

    >>> drift_health("stable", 0.1)
    'focused'
    >>> drift_health("gradual", 0.5)
    'evolving'
    >>> drift_health("wandering", 0.7)
    'scattered'
    >>> drift_health("oscillating", 0.4)
    'mixed'
    """
    if pattern == "stable" and cumulative < 0.3:
        return "focused"
    if pattern == "gradual":
        return "evolving"
    if pattern in ("wandering", "pivoting") and cumulative > 0.5:
        return "scattered"
    return "mixed"


# ---------------------------------------------------------------------------
# Main report
# ---------------------------------------------------------------------------

def drift_report(
    stroke_texts: Sequence[str],
    *,
    window: int = 5,
) -> dict[str, Any]:
    """Generate a drift report for a stream of strokes.

    Args:
        stroke_texts: ordered sequence of stroke text strings.
        window: window size for window_drift calculation (default 5).

    Returns:
        Dict with keys:

        - ``total_strokes``: number of strokes analyzed.
        - ``step_drifts``: per-step Jaccard distances.
        - ``cumulative_drift``: normalized mean step drift.
        - ``window_drifts``: sliding-window drift values.
        - ``mean_window_drift``: average window drift.
        - ``velocities``: drift velocity values.
        - ``mean_velocity``: average velocity.
        - ``drift_pattern``: pattern classification.
        - ``drift_health``: health assessment.
        - ``max_step_drift``: highest single-step drift.
        - ``min_step_drift``: lowest single-step drift.
    """
    n = len(stroke_texts)
    if n < 2:
        return {
            "total_strokes": n,
            "step_drifts": [],
            "cumulative_drift": 0.0,
            "window_drifts": [],
            "mean_window_drift": 0.0,
            "velocities": [],
            "mean_velocity": 0.0,
            "drift_pattern": "stable",
            "drift_health": "focused",
            "max_step_drift": 0.0,
            "min_step_drift": 0.0,
        }

    # Extract concepts
    concept_sets = [extract_concepts(t) for t in stroke_texts]

    # Step drifts
    steps = step_drift(concept_sets)
    cum = round(cumulative_drift(steps), 4)

    # Window drifts
    w_drifts = window_drift(concept_sets, window=window)
    mean_w = round(sum(w_drifts) / len(w_drifts), 4) if w_drifts else 0.0

    # Velocities
    vels = drift_velocity(steps)
    mean_v = round(sum(vels) / len(vels), 4) if vels else 0.0

    # Classify
    pattern = _classify_drift_pattern(steps, cum, vels)
    health = drift_health(pattern, cum)

    return {
        "total_strokes": n,
        "step_drifts": [round(s, 4) for s in steps],
        "cumulative_drift": cum,
        "window_drifts": [round(w, 4) for w in w_drifts],
        "mean_window_drift": mean_w,
        "velocities": vels,
        "mean_velocity": mean_v,
        "drift_pattern": pattern,
        "drift_health": health,
        "max_step_drift": round(max(steps), 4) if steps else 0.0,
        "min_step_drift": round(min(steps), 4) if steps else 0.0,
    }


# ---------------------------------------------------------------------------
# Delta: compare two drift reports
# ---------------------------------------------------------------------------

def drift_delta(
    earlier: dict[str, Any],
    later: dict[str, Any],
) -> dict[str, Any]:
    """Compare two drift reports to track drift evolution.

    Args:
        earlier: drift report from an earlier stream snapshot.
        later: drift report from a later snapshot.

    Returns:
        Dict with drift changes between snapshots.

    >>> e = {"cumulative_drift": 0.3, "drift_pattern": "stable", "drift_health": "focused"}
    >>> l = {"cumulative_drift": 0.5, "drift_pattern": "gradual", "drift_health": "evolving"}
    >>> d = drift_delta(e, l)
    >>> d["cumulative_drift_change"]
    0.2
    >>> d["pattern_changed"]
    True
    """
    cum_change = round(
        later.get("cumulative_drift", 0.0) - earlier.get("cumulative_drift", 0.0),
        4,
    )
    return {
        "cumulative_drift_change": cum_change,
        "pattern_changed": earlier.get("drift_pattern") != later.get("drift_pattern"),
        "health_changed": earlier.get("drift_health") != later.get("drift_health"),
        "earlier_pattern": earlier.get("drift_pattern"),
        "later_pattern": later.get("drift_pattern"),
        "drift_direction": (
            "increasing" if cum_change > 0.05
            else "decreasing" if cum_change < -0.05
            else "steady"
        ),
    }


if __name__ == "__main__":
    import doctest
    doctest.testmod()
