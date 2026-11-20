"""Stroke topic lifecycle tracker — follow concepts from birth to dormancy.

``stroke_resonance`` measures how far a single stroke's ideas propagate.
``stroke_concept_recurrence`` tracks dormancy gaps for known concepts.
``stroke_coherence`` scores continuity between neighbours.
None of these capture the *arc* of a topic: how it emerges, grows,
peaks, declines, and either revives or goes dormant.

Topic lifecycle analysis answers: **which ideas are gaining traction,
which are fading, and what is the overall health of the topic garden?**

Concepts
--------

==================  ====================================================
term                meaning
==================  ====================================================
**topic**           a significant word token (len >= 4, not a stopword)
**first_seen**      index of the first stroke mentioning the topic
**last_seen**       index of the most recent stroke mentioning it
**mentions**        total stroke count containing the topic
**momentum**        exponentially-weighted recency score (0–1)
**phase**           lifecycle stage of a topic
**topic_age**       strokes since first_seen
**recency**         strokes since last_seen
==================  ====================================================

Topic phases
------------

==============  ========================================================
phase            description
==============  ========================================================
**emerging**     seen <= 3 times, all within the last 20% of the window
**growing**      mentions increasing in recent half vs earlier half
**peaked**       high momentum, mentions spread across the window
**declining**    momentum falling — recent half has fewer mentions
**dormant**      not seen in the last 30% of the window
==============  ========================================================

Stream-level patterns
---------------------

==================  ====================================================
pattern              description
==================  ====================================================
**healthy_cycle**    topics emerge, peak, and retire naturally
**fixation**         few topics dominate > 50% of recent strokes
**shallow**          many topics emerge but few reach peaked phase
**graveyard**        > 40% of tracked topics are dormant
**steady_state**     balanced mix of phases, no dominant pattern
==================  ====================================================

Algorithm
---------
1. Tokenise each stroke into concept tokens.
2. Build per-topic mention timeline (list of stroke indices).
3. Compute momentum via exponential decay weighting.
4. Classify phase by comparing first-half vs second-half mention rates.
5. Aggregate phase counts to determine stream pattern.
6. Optionally compare two snapshots via *lifecycle_delta*.

Usage::

    from iamai import stroke_topic_lifecycle as tl
    report = tl.lifecycle_report(strokes_text, window=100)
    print(report["pattern"])         # "healthy_cycle" / "fixation" / ...
    for topic, info in report["topics"].items():
        print(f"{topic}: {info['phase']} (momentum={info['momentum']})")
"""

from __future__ import annotations

import math
from collections import defaultdict

# ---------------------------------------------------------------------------
# Stopwords
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    "that this these those from into with your have been will would "
    "could should their there they them than then what when where which "
    "about above after before between through during each other some such "
    "only same also very just more most much many few little".split()
)


def extract_tokens(text: str) -> set[str]:
    """Return significant word tokens from *text*."""
    words = text.lower().split()
    return {w.strip(".,;:!?\"'()-") for w in words if len(w) >= 4 and w not in _STOPWORDS}


def build_mention_map(
    token_sets: list[set[str]],
) -> dict[str, list[int]]:
    """Map each topic token to the list of stroke indices that mention it."""
    mentions: dict[str, list[int]] = defaultdict(list)
    for idx, tokens in enumerate(token_sets):
        for token in tokens:
            mentions[token].append(idx)
    return dict(mentions)


def compute_momentum(
    mention_indices: list[int],
    total_strokes: int,
    decay: float = 0.05,
) -> float:
    """Exponential-decay momentum score for a topic.

    Recent mentions score higher.  Returns a value in [0, 1].

    Parameters
    ----------
    mention_indices : list[int]
        Stroke indices where the topic appears.
    total_strokes : int
        Total number of strokes in the window.
    decay : float
        Decay constant; larger = faster falloff.
    """
    if not mention_indices or total_strokes == 0:
        return 0.0
    last = total_strokes - 1
    weighted = sum(math.exp(-decay * (last - i)) for i in mention_indices)
    # Normalise: max possible is if every stroke mentions it
    max_weighted = sum(math.exp(-decay * (last - i)) for i in range(total_strokes))
    if max_weighted == 0:
        return 0.0
    return round(weighted / max_weighted, 4)


def classify_phase(
    mention_indices: list[int],
    total_strokes: int,
    momentum: float,
) -> str:
    """Determine the lifecycle phase of a topic.

    Parameters
    ----------
    mention_indices : list[int]
        Stroke indices where the topic appears.
    total_strokes : int
        Number of strokes in the analysis window.
    momentum : float
        Pre-computed momentum value.
    """
    if not mention_indices:
        return "dormant"

    last_seen = max(mention_indices)
    recency = total_strokes - 1 - last_seen
    recency_frac = recency / total_strokes if total_strokes else 1.0

    # Dormant: not seen in the last 30% of the window
    if recency_frac > 0.3:
        return "dormant"

    mentions = len(mention_indices)

    # Emerging: few mentions, all recent
    if mentions <= 3:
        first_seen = min(mention_indices)
        span_frac = (last_seen - first_seen) / total_strokes if total_strokes else 0
        if span_frac <= 0.2 or mentions <= 1:
            return "emerging"

    # Compare first-half vs second-half mentions
    midpoint = total_strokes // 2
    early = sum(1 for i in mention_indices if i < midpoint)
    late = sum(1 for i in mention_indices if i >= midpoint)

    if late > early * 1.5 and late >= 2:
        return "growing"
    if early > late * 1.5 and early >= 2:
        return "declining"

    # High momentum and spread out -> peaked
    if momentum > 0.3 and mentions >= 4:
        return "peaked"

    # Default: declining if momentum is low, growing otherwise
    if momentum < 0.15:
        return "declining"
    return "growing"


def classify_stream_pattern(
    phase_counts: dict[str, int],
    total_topics: int,
    fixation_ratio: float,
) -> str:
    """Classify the overall stream pattern from phase distribution.

    Parameters
    ----------
    phase_counts : dict[str, int]
        Count of topics in each phase.
    total_topics : int
        Total number of tracked topics.
    fixation_ratio : float
        Fraction of recent strokes dominated by top-3 topics.
    """
    if total_topics == 0:
        return "steady_state"

    dormant_frac = phase_counts.get("dormant", 0) / total_topics
    emerging_frac = phase_counts.get("emerging", 0) / total_topics
    peaked_frac = phase_counts.get("peaked", 0) / total_topics

    # Fixation: few topics dominate
    if fixation_ratio > 0.5:
        return "fixation"

    # Graveyard: too many dormant topics
    if dormant_frac > 0.4:
        return "graveyard"

    # Shallow: many emerging but few reach peaked
    if emerging_frac > 0.4 and peaked_frac < 0.1:
        return "shallow"

    # Healthy cycle: balanced mix with some peaked and not too many dormant
    if peaked_frac > 0.05 and dormant_frac < 0.3:
        return "healthy_cycle"

    return "steady_state"


def compute_fixation_ratio(
    mention_map: dict[str, list[int]],
    total_strokes: int,
    recent_frac: float = 0.3,
    top_n: int = 3,
) -> float:
    """Fraction of recent strokes mentioning any of the top-N topics.

    Parameters
    ----------
    mention_map : dict[str, list[int]]
        Per-topic mention index lists.
    total_strokes : int
        Total strokes in window.
    recent_frac : float
        What fraction of the tail counts as "recent".
    top_n : int
        Number of top topics to consider.
    """
    if total_strokes == 0:
        return 0.0
    recent_start = int(total_strokes * (1 - recent_frac))
    recent_count = total_strokes - recent_start
    if recent_count == 0:
        return 0.0

    # Rank topics by mentions in the recent window
    recent_mentions: dict[str, int] = {}
    for topic, indices in mention_map.items():
        c = sum(1 for i in indices if i >= recent_start)
        if c > 0:
            recent_mentions[topic] = c

    top_topics = sorted(recent_mentions, key=recent_mentions.get, reverse=True)[:top_n]

    # Count distinct recent strokes mentioning any top topic
    covered: set[int] = set()
    for topic in top_topics:
        for i in mention_map[topic]:
            if i >= recent_start:
                covered.add(i)

    return round(len(covered) / recent_count, 4)


def lifecycle_report(
    texts: list[str],
    window: int | None = None,
    decay: float = 0.05,
) -> dict:
    """Compute topic lifecycle metrics over the stroke stream.

    Parameters
    ----------
    texts : list[str]
        Stroke text bodies in chronological order.
    window : int, optional
        If given, only the last *window* strokes are analysed.
    decay : float
        Exponential decay constant for momentum.

    Returns
    -------
    dict with keys:
        total_strokes, analysed_strokes, topic_count,
        topics (dict[topic] -> {mentions, momentum, phase, first_seen,
                               last_seen, recency}),
        phase_counts (dict[phase] -> int),
        fixation_ratio (float),
        pattern (str).
    """
    if window is not None:
        texts = texts[-window:]
    n = len(texts)

    if n == 0:
        return {
            "total_strokes": 0,
            "analysed_strokes": 0,
            "topic_count": 0,
            "topics": {},
            "phase_counts": {},
            "fixation_ratio": 0.0,
            "pattern": "steady_state",
        }

    token_sets = [extract_tokens(t) for t in texts]
    mention_map = build_mention_map(token_sets)

    topics: dict[str, dict] = {}
    phase_counts: dict[str, int] = defaultdict(int)

    for topic, indices in mention_map.items():
        mom = compute_momentum(indices, n, decay)
        phase = classify_phase(indices, n, mom)
        first_seen = min(indices)
        last_seen = max(indices)
        recency = n - 1 - last_seen

        topics[topic] = {
            "mentions": len(indices),
            "momentum": mom,
            "phase": phase,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "recency": recency,
        }
        phase_counts[phase] += 1

    fixation = compute_fixation_ratio(mention_map, n)
    pattern = classify_stream_pattern(dict(phase_counts), len(mention_map), fixation)

    return {
        "total_strokes": n,
        "analysed_strokes": n,
        "topic_count": len(mention_map),
        "topics": topics,
        "phase_counts": dict(phase_counts),
        "fixation_ratio": fixation,
        "pattern": pattern,
    }


def lifecycle_delta(before: dict, after: dict) -> dict:
    """Compare two lifecycle snapshots and return the changes.

    Parameters
    ----------
    before, after : dict
        Reports returned by :func:`lifecycle_report`.

    Returns
    -------
    dict with keys:
        topic_count_change (int),
        new_topics (list[str]),
        lost_topics (list[str]),
        phase_transitions (dict[topic] -> {from, to}),
        momentum_changes (dict[topic] -> float),
        pattern_before (str),
        pattern_after (str),
        pattern_shifted (bool),
        fixation_change (float).
    """
    before_topics = set(before.get("topics", {}).keys())
    after_topics = set(after.get("topics", {}).keys())

    new_topics = sorted(after_topics - before_topics)
    lost_topics = sorted(before_topics - after_topics)
    common = before_topics & after_topics

    phase_transitions: dict[str, dict[str, str]] = {}
    momentum_changes: dict[str, float] = {}

    for topic in common:
        b_info = before["topics"][topic]
        a_info = after["topics"][topic]

        if b_info["phase"] != a_info["phase"]:
            phase_transitions[topic] = {
                "from": b_info["phase"],
                "to": a_info["phase"],
            }

        mom_change = round(a_info["momentum"] - b_info["momentum"], 4)
        if abs(mom_change) > 0.001:
            momentum_changes[topic] = mom_change

    fixation_change = round(
        after.get("fixation_ratio", 0.0) - before.get("fixation_ratio", 0.0), 4
    )

    return {
        "topic_count_change": len(after_topics) - len(before_topics),
        "new_topics": new_topics,
        "lost_topics": lost_topics,
        "phase_transitions": phase_transitions,
        "momentum_changes": momentum_changes,
        "pattern_before": before.get("pattern", "steady_state"),
        "pattern_after": after.get("pattern", "steady_state"),
        "pattern_shifted": before.get("pattern") != after.get("pattern"),
        "fixation_change": fixation_change,
    }
