"""Stroke concept recurrence tracker — measure how ideas resurface.

``stroke_persistence`` tracks which concepts survive across the stream.
``stroke_drift`` measures cumulative topic shift.  ``stroke_resonance``
captures forward projection of a single stroke.  None of these answers
a subtler question: **when a concept disappears, does it come back, and
if so, on what schedule?**

Recurrence is the *return* of a concept after dormancy.  A concept that
appears, vanishes for five strokes, then reappears has a dormancy period
of 5.  Tracking these dormancy gaps across the stream reveals whether
the writer circles back on a regular cadence (periodic), in clusters
(bursty), after long absences (revival), or never (one-shot).

Concepts
--------

==================  ====================================================
term                meaning
==================  ====================================================
**concept**         a significant word (len >= 4, not a stopword)
**dormancy**        number of strokes between consecutive appearances
                    of the same concept
**revival**         a concept absent for >= revival_threshold strokes
                    that reappears
**recurrence_rhythm** classification of how a concept's dormancy gaps
                    are distributed
==================  ====================================================

Recurrence rhythms
------------------

===================  =================================================
rhythm               description
===================  =================================================
**periodic**         dormancy gaps are tightly clustered (CV < 0.3) —
                     the writer revisits on a regular schedule
**bursty**           many short gaps punctuated by occasional long ones —
                     the writer obsesses, drifts, obsesses again
**revival**          at least one gap exceeds revival_threshold —
                     the writer brought back a dormant thread
**one_shot**         concept appeared once and never returned
**steady**           concept appears in nearly every stroke —
                     no real dormancy to speak of
===================  =================================================

Algorithm
---------
1. Extract concept tokens from each stroke (same function as
   ``stroke_persistence.extract_concepts``).
2. Build a mapping: concept → sorted list of stroke indices.
3. For each concept with >= 2 appearances, compute:

   - ``dormancy_gaps`` = list of inter-appearance gaps
   - ``mean_dormancy`` = mean gap length
   - ``max_dormancy`` = longest gap
   - ``gap_cv`` = coefficient of variation of gaps (std / mean)
   - ``revivals`` = count of gaps >= revival_threshold
   - ``rhythm`` = classification from gap distribution

4. Aggregate into stream-level profile:

   - ``total_concepts`` — number of unique concepts extracted
   - ``recurring_concepts`` — concepts with >= 2 appearances
   - ``revival_concepts`` — concepts with >= 1 revival
   - ``rhythm_distribution`` — Counter of rhythm classifications
   - ``mean_dormancy`` — mean of all concepts' mean_dormancy values
   - ``longest_revival`` — max dormancy gap across all concepts
   - ``recurrence_score`` — recurring_concepts / total_concepts [0, 1]
   - ``revival_rate`` — revival_concepts / recurring_concepts [0, 1]

5. Classify stream recurrence pattern:

=====================  ==================================================
pattern                description
=====================  ==================================================
**cyclical**           high recurrence_score, many periodic concepts
**episodic**           moderate recurrence, revival-heavy — ideas return
                       after long absences
**transient**          low recurrence_score, mostly one-shot concepts
**anchored**           many steady concepts — the writer always returns
                       to core themes
=====================  ==================================================

6. Compute delta between two snapshots:

   - ``recurrence_score_delta`` — how recurrence changed
   - ``revival_rate_delta`` — how revival frequency changed
   - ``new_revivals`` — concepts that gained a revival between snapshots

Zero dependencies.  stdlib only.

>>> texts = [
...     "alpha beta gamma delta epsilon",
...     "something completely different here now",
...     "another passage with no overlap whatsoever",
...     "alpha beta gamma delta epsilon",
...     "nothing shared with earlier passages here",
...     "fresh topics only in this middle stroke",
...     "alpha beta gamma delta epsilon",
...     "completely unrelated material in this one",
...     "alpha beta gamma delta epsilon",
...     "alpha beta gamma delta epsilon",
... ]
>>> report = recurrence_report(texts)
>>> report["stream_pattern"] in ("cyclical", "episodic", "transient", "anchored")
True
>>> 0.0 <= report["recurrence_score"] <= 1.0
True
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

# ---------------------------------------------------------------------------
# Stopwords (same set as stroke_persistence)
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    "about", "above", "after", "again", "against", "also", "among",
    "another", "because", "been", "before", "below", "between", "both",
    "came", "come", "could", "does", "done", "down", "each", "even",
    "from", "gets", "going", "gone", "great", "have", "here", "high",
    "into", "just", "keep", "know", "last", "less", "like", "long",
    "look", "made", "make", "many", "most", "much", "must", "need",
    "next", "none", "only", "open", "other", "over", "part", "pass",
    "past", "pick", "pull", "push", "read", "real", "rest", "same",
    "seen", "show", "side", "some", "such", "sure", "take", "tell",
    "than", "that", "them", "then", "there", "these", "they", "this",
    "those", "time", "upon", "used", "very", "want", "well", "were",
    "what", "when", "where", "which", "while", "will", "with", "word",
    "work", "would", "your",
})

_MIN_TOKEN_LEN = 4


# ---------------------------------------------------------------------------
# Concept extraction
# ---------------------------------------------------------------------------

def extract_concepts(text: str) -> set[str]:
    """Extract significant concept tokens from *text*.

    Words are lowercased, stripped of non-alpha characters, and filtered
    by minimum length and stopword membership.
    """
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return {w for w in words if len(w) >= _MIN_TOKEN_LEN and w not in _STOPWORDS}


def build_concept_map(texts: list[str]) -> dict[str, list[int]]:
    """Map each concept to its sorted list of stroke indices."""
    cmap: dict[str, list[int]] = {}
    for idx, text in enumerate(texts):
        for concept in extract_concepts(text):
            cmap.setdefault(concept, []).append(idx)
    return cmap


# ---------------------------------------------------------------------------
# Per-concept metrics
# ---------------------------------------------------------------------------

def _coefficient_of_variation(values: list[float]) -> float:
    """Return CV = std / mean.  Returns 0.0 for degenerate inputs."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    if mean == 0.0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(variance) / mean


def concept_dormancy(indices: list[int]) -> list[int]:
    """Return sorted list of gaps between consecutive appearances."""
    if len(indices) < 2:
        return []
    return [indices[i + 1] - indices[i] for i in range(len(indices) - 1)]


def classify_rhythm(
    gaps: list[int],
    revival_threshold: int = 5,
) -> str:
    """Classify the recurrence rhythm of one concept from its gap list.

    Parameters
    ----------
    gaps
        Inter-appearance gap lengths (sorted ascending by construction).
    revival_threshold
        Gap length at or above which a gap counts as a revival.

    Returns
    -------
    str
        One of ``periodic``, ``bursty``, ``revival``, ``one_shot``,
        ``steady``.
    """
    if not gaps:
        return "one_shot"

    # All gaps are 1 → the concept is in every stroke of its span
    if all(g == 1 for g in gaps):
        return "steady"

    revivals = sum(1 for g in gaps if g >= revival_threshold)
    if revivals > 0:
        return "revival"

    cv = _coefficient_of_variation([float(g) for g in gaps])
    if cv < 0.3:
        return "periodic"

    return "bursty"


def concept_recurrence_metrics(
    indices: list[int],
    revival_threshold: int = 5,
) -> dict[str, Any]:
    """Compute full recurrence metrics for one concept.

    Parameters
    ----------
    indices
        Sorted list of stroke indices where the concept appears.
    revival_threshold
        Gap length at or above which a gap counts as a revival.

    Returns
    -------
    dict
        Keys: ``appearances``, ``dormancy_gaps``, ``mean_dormancy``,
        ``max_dormancy``, ``min_dormancy``, ``gap_cv``, ``revivals``,
        ``rhythm``.
    """
    gaps = concept_dormancy(indices)
    revivals = sum(1 for g in gaps if g >= revival_threshold)
    rhythm = classify_rhythm(gaps, revival_threshold)

    mean_d = sum(gaps) / len(gaps) if gaps else 0.0
    max_d = max(gaps) if gaps else 0
    min_d = min(gaps) if gaps else 0
    cv = _coefficient_of_variation([float(g) for g in gaps]) if gaps else 0.0

    return {
        "appearances": len(indices),
        "dormancy_gaps": gaps,
        "mean_dormancy": round(mean_d, 4),
        "max_dormancy": max_d,
        "min_dormancy": min_d,
        "gap_cv": round(cv, 4),
        "revivals": revivals,
        "rhythm": rhythm,
    }


# ---------------------------------------------------------------------------
# Stream-level report
# ---------------------------------------------------------------------------

def _classify_stream_pattern(
    recurrence_score: float,
    rhythm_dist: Counter,
    revival_rate: float,
    steady_ratio: float,
) -> str:
    """Classify the overall stream recurrence pattern."""
    # Anchored: many steady concepts dominate
    if steady_ratio > 0.4:
        return "anchored"
    # Cyclical: high recurrence, periodic-heavy
    if recurrence_score > 0.4 and rhythm_dist.get("periodic", 0) > rhythm_dist.get("revival", 0):
        return "cyclical"
    # Episodic: moderate recurrence, revival-heavy
    if revival_rate > 0.2:
        return "episodic"
    # Transient: low recurrence, mostly one-shot
    return "transient"


def recurrence_report(
    texts: list[str],
    revival_threshold: int = 5,
) -> dict[str, Any]:
    """Produce a full recurrence report for a stream of texts.

    Parameters
    ----------
    texts
        List of stroke texts in chronological order.
    revival_threshold
        Gap length at or above which a gap counts as a revival.

    Returns
    -------
    dict
        Stream-level report with keys: ``total_concepts``,
        ``recurring_concepts``, ``revival_concepts``,
        ``rhythm_distribution``, ``mean_dormancy``, ``longest_revival``,
        ``recurrence_score``, ``revival_rate``, ``stream_pattern``,
        ``concept_details``.
    """
    if not texts:
        return {
            "total_concepts": 0,
            "recurring_concepts": 0,
            "revival_concepts": 0,
            "rhythm_distribution": {},
            "mean_dormancy": 0.0,
            "longest_revival": 0,
            "recurrence_score": 0.0,
            "revival_rate": 0.0,
            "stream_pattern": "transient",
            "concept_details": {},
        }

    cmap = build_concept_map(texts)
    total = len(cmap)
    if total == 0:
        return {
            "total_concepts": 0,
            "recurring_concepts": 0,
            "revival_concepts": 0,
            "rhythm_distribution": {},
            "mean_dormancy": 0.0,
            "longest_revival": 0,
            "recurrence_score": 0.0,
            "revival_rate": 0.0,
            "stream_pattern": "transient",
            "concept_details": {},
        }

    rhythm_dist: Counter = Counter()
    concept_details: dict[str, dict[str, Any]] = {}
    recurring_count = 0
    revival_count = 0
    all_mean_dormancies: list[float] = []
    longest_rev = 0
    steady_count = 0

    for concept, indices in sorted(cmap.items()):
        metrics = concept_recurrence_metrics(indices, revival_threshold)
        concept_details[concept] = metrics

        rhythm_dist[metrics["rhythm"]] += 1

        if len(indices) >= 2:
            recurring_count += 1
            all_mean_dormancies.append(metrics["mean_dormancy"])

        if metrics["revivals"] > 0:
            revival_count += 1

        if metrics["rhythm"] == "steady":
            steady_count += 1

        if metrics["max_dormancy"] > longest_rev and metrics["revivals"] > 0:
            longest_rev = metrics["max_dormancy"]

    recurrence_score = recurring_count / total if total > 0 else 0.0
    revival_rate = revival_count / recurring_count if recurring_count > 0 else 0.0
    steady_ratio = steady_count / total if total > 0 else 0.0
    mean_dormancy = (
        sum(all_mean_dormancies) / len(all_mean_dormancies)
        if all_mean_dormancies
        else 0.0
    )

    stream_pattern = _classify_stream_pattern(
        recurrence_score, rhythm_dist, revival_rate, steady_ratio
    )

    return {
        "total_concepts": total,
        "recurring_concepts": recurring_count,
        "revival_concepts": revival_count,
        "rhythm_distribution": dict(rhythm_dist),
        "mean_dormancy": round(mean_dormancy, 4),
        "longest_revival": longest_rev,
        "recurrence_score": round(recurrence_score, 4),
        "revival_rate": round(revival_rate, 4),
        "stream_pattern": stream_pattern,
        "concept_details": concept_details,
    }


# ---------------------------------------------------------------------------
# Snapshot delta
# ---------------------------------------------------------------------------

def recurrence_delta(
    report_before: dict[str, Any],
    report_after: dict[str, Any],
) -> dict[str, Any]:
    """Compare two recurrence reports and return the deltas.

    Parameters
    ----------
    report_before
        Earlier recurrence_report output.
    report_after
        Later recurrence_report output.

    Returns
    -------
    dict
        Keys: ``recurrence_score_delta``, ``revival_rate_delta``,
        ``new_revivals`` (list of concepts that gained a revival),
        ``rhythm_shifts`` (dict of concept → (old_rhythm, new_rhythm)
        for concepts whose rhythm changed).
    """
    before_details = report_before.get("concept_details", {})
    after_details = report_after.get("concept_details", {})

    new_revivals: list[str] = []
    rhythm_shifts: dict[str, tuple[str, str]] = {}

    for concept, after_m in after_details.items():
        before_m = before_details.get(concept)
        if before_m is None:
            # Brand new concept — if it has revivals already, count it
            if after_m.get("revivals", 0) > 0:
                new_revivals.append(concept)
            continue

        before_rev = before_m.get("revivals", 0)
        after_rev = after_m.get("revivals", 0)
        if after_rev > before_rev:
            new_revivals.append(concept)

        before_rhythm = before_m.get("rhythm", "")
        after_rhythm = after_m.get("rhythm", "")
        if before_rhythm != after_rhythm:
            rhythm_shifts[concept] = (before_rhythm, after_rhythm)

    return {
        "recurrence_score_delta": round(
            report_after.get("recurrence_score", 0.0)
            - report_before.get("recurrence_score", 0.0),
            4,
        ),
        "revival_rate_delta": round(
            report_after.get("revival_rate", 0.0)
            - report_before.get("revival_rate", 0.0),
            4,
        ),
        "new_revivals": sorted(new_revivals),
        "rhythm_shifts": rhythm_shifts,
    }


# ---------------------------------------------------------------------------
# Doctest runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import doctest
    doctest.testmod(verbose=True)
