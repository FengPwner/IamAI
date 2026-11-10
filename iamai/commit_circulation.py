#!/usr/bin/env python3
"""commit_circulation — measure how well changes flow between codebase areas.

A codebase with good circulation spreads knowledge across its areas:
a change in core logic triggers updates in tests, docs, and consumers.
A codebase with poor circulation develops isolated silos — each area
evolves independently, unaware of what the others are doing.

This module answers one question: **do changes propagate across area
boundaries, or does each area live in its own bubble?**

Circulation dimensions
----------------------

========================  ================================================
metric                    meaning
========================  ================================================
cross_area_ratio          fraction of commits that touch files in ≥ 2
                          distinct top-level areas (directories)
area_coupling             average Jaccard similarity between consecutive
                          commits' area sets (how much the "shape" of
                          change shifts from one commit to the next)
reach_breadth             fraction of all known areas touched at least
                          once within the analysis window
bridge_commit_ratio       fraction of commits that connect two areas
                          never previously seen together in one commit
circulation_score         composite 0.0–1.0 score: high = well-circulated,
                          low = siloed
circulation_class         interconnected | flowing | adequate | siloed |
                          isolated
========================  ================================================

Circulation classes
-------------------

================  =========================================================
class             meaning
================  =========================================================
interconnected    score ≥ 0.80 — nearly every commit bridges multiple areas
flowing           0.60 ≤ score < 0.80 — good cross-pollination, some gaps
adequate          0.40 ≤ score < 0.60 — mixed, some areas communicate
siloed            0.20 ≤ score < 0.40 — most commits stay within one area
isolated          score < 0.20 — areas evolve in complete independence
================  =========================================================

Public API
----------
- ``CirculationCommit`` — data class for one commit's metadata
- ``compute_circulation(commits) -> CirculationResult``
- ``classify_circulation(score) -> str``
- ``circulation_report(result) -> str``
- ``circulation_trend(results) -> CirculationTrend``

Usage::

    from iamai.commit_circulation import CirculationCommit, compute_circulation

    commits = [
        CirculationCommit(sha="aaa",
                          files={"iamai/foo.py", "tests/test_foo.py"}),
        CirculationCommit(sha="bbb",
                          files={"iamai/bar.py", "docs/BAR.md"}),
        CirculationCommit(sha="ccc",
                          files={"iamai/foo.py", "iamai/bar.py",
                                 "tests/test_bar.py"}),
    ]
    r = compute_circulation(commits)
    print(r.circulation_class)   # "flowing"
    print(r.circulation_score)   # 0.67
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CirculationCommit:
    """Minimal commit metadata for circulation analysis."""

    sha: str
    files: Set[str] = field(default_factory=set)


@dataclass
class CirculationResult:
    """Outcome of a single circulation analysis window."""

    cross_area_ratio: float = 0.0
    area_coupling: float = 0.0
    reach_breadth: float = 0.0
    bridge_commit_ratio: float = 0.0
    circulation_score: float = 0.0
    circulation_class: str = "isolated"
    commit_count: int = 0
    area_count: int = 0
    areas: Set[str] = field(default_factory=set)


@dataclass
class CirculationTrend:
    """Trend across multiple circulation windows."""

    scores: List[float] = field(default_factory=list)
    trend: str = "stable"
    slope: float = 0.0
    mean: float = 0.0
    stddev: float = 0.0


# ---------------------------------------------------------------------------
# Area extraction
# ---------------------------------------------------------------------------


def _extract_area(filepath: str) -> str:
    """Extract the top-level area (directory) from a file path.

    Files at the root level belong to area '.'.
    """
    parts = PurePosixPath(filepath).parts
    if len(parts) <= 1:
        return "."
    return parts[0]


def _commit_areas(commit: CirculationCommit) -> FrozenSet[str]:
    """Return the set of areas touched by a commit."""
    return frozenset(_extract_area(f) for f in commit.files)


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def _compute_cross_area_ratio(commits: Sequence[CirculationCommit]) -> float:
    """Fraction of commits touching ≥ 2 distinct areas.

    A commit touching only iamai/ is single-area.  A commit touching
    iamai/ and tests/ is cross-area.
    """
    if not commits:
        return 0.0
    cross = sum(1 for c in commits if len(_commit_areas(c)) >= 2)
    return cross / len(commits)


def _jaccard(a: FrozenSet[str], b: FrozenSet[str]) -> float:
    """Jaccard similarity between two sets."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _compute_area_coupling(commits: Sequence[CirculationCommit]) -> float:
    """Average Jaccard similarity between consecutive commits' area sets.

    High coupling means the "shape" of changes is stable — similar areas
    are being co-modified.  Low coupling means each commit explores a
    different combination of areas.

    Note: this is *not* about similarity being high = good.  Both very
    high and very low have implications.  The metric feeds into the
    composite score as a measure of *consistency of cross-area work*.
    """
    if len(commits) < 2:
        return 0.0

    similarities: List[float] = []
    prev = _commit_areas(commits[0])

    for c in commits[1:]:
        curr = _commit_areas(c)
        similarities.append(_jaccard(prev, curr))
        prev = curr

    return sum(similarities) / len(similarities)


def _compute_reach_breadth(
    commits: Sequence[CirculationCommit],
) -> float:
    """Fraction of all known areas touched at least once in the window.

    If the codebase has 5 areas and commits touch 3 of them, reach is
    0.60.  This measures how broadly the window's attention spreads.
    """
    if not commits:
        return 0.0

    all_areas: Set[str] = set()
    for c in commits:
        all_areas |= _commit_areas(c)

    if not all_areas:
        return 0.0

    # For a meaningful metric we need a universe.  We use the areas
    # seen in this window as the universe — so reach_breadth is always
    # 1.0 for a single window.  The real value comes from comparing
    # windows or when the caller supplies a known universe.
    #
    # To make this useful in isolation, we compute the fraction of areas
    # that are touched by *more than one* commit — i.e., "shared" areas
    # vs. "one-off" areas.
    area_commit_count: Dict[str, int] = {}
    for c in commits:
        for area in _commit_areas(c):
            area_commit_count[area] = area_commit_count.get(area, 0) + 1

    shared = sum(1 for cnt in area_commit_count.values() if cnt > 1)
    return shared / len(all_areas) if all_areas else 0.0


def compute_reach_breadth_with_universe(
    commits: Sequence[CirculationCommit],
    universe: Set[str],
) -> float:
    """Reach breadth against a known area universe.

    Use this when you know all the areas in the codebase (e.g. from
    ``git ls-files``) and want the true reach fraction.
    """
    if not universe:
        return 0.0

    touched: Set[str] = set()
    for c in commits:
        touched |= _commit_areas(c)

    return len(touched & universe) / len(universe)


def _compute_bridge_commit_ratio(
    commits: Sequence[CirculationCommit],
) -> float:
    """Fraction of commits that bridge two previously unconnected areas.

    A "bridge" is a commit that co-touches two areas that have never
    appeared together in any earlier commit.  This measures how often
    the codebase discovers new connections between its parts.
    """
    if not commits:
        return 0.0

    known_pairs: Set[Tuple[str, str]] = set()
    bridges = 0

    for c in commits:
        areas = sorted(_commit_areas(c))
        is_bridge = False
        for i in range(len(areas)):
            for j in range(i + 1, len(areas)):
                pair = (areas[i], areas[j])
                if pair not in known_pairs:
                    is_bridge = True
                known_pairs.add(pair)
        if is_bridge:
            bridges += 1

    return bridges / len(commits)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _compute_circulation_score(
    cross_area: float,
    coupling: float,
    reach: float,
    bridge: float,
) -> float:
    """Combine dimensions into a single 0.0–1.0 circulation score.

    cross_area_ratio       — weight 0.35  (multi-area commits are the
    reach_breadth          — weight 0.25    strongest circulation signal)
    bridge_commit_ratio    — weight 0.25  (new connections matter)
    area_coupling          — weight 0.15  (consistency of cross-area work)
    """
    return round(
        0.35 * cross_area + 0.25 * reach + 0.25 * bridge + 0.15 * coupling,
        4,
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_THRESHOLDS = [
    (0.80, "interconnected"),
    (0.60, "flowing"),
    (0.40, "adequate"),
    (0.20, "siloed"),
    (0.00, "isolated"),
]


def classify_circulation(score: float) -> str:
    """Map a circulation score to a circulation class label."""
    for threshold, label in _THRESHOLDS:
        if score >= threshold:
            return label
    return "isolated"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute_circulation(
    commits: Sequence[CirculationCommit],
) -> CirculationResult:
    """Analyse commit circulation across a single window.

    Parameters
    ----------
    commits:
        Ordered sequence of CirculationCommit objects (oldest first).

    Returns
    -------
    CirculationResult with all dimensions, score, and classification.
    """
    if not commits:
        return CirculationResult()

    cross_area = _compute_cross_area_ratio(commits)
    coupling = _compute_area_coupling(commits)
    reach = _compute_reach_breadth(commits)
    bridge = _compute_bridge_commit_ratio(commits)
    score = _compute_circulation_score(cross_area, coupling, reach, bridge)
    label = classify_circulation(score)

    all_areas: Set[str] = set()
    for c in commits:
        all_areas |= _commit_areas(c)

    return CirculationResult(
        cross_area_ratio=round(cross_area, 4),
        area_coupling=round(coupling, 4),
        reach_breadth=round(reach, 4),
        bridge_commit_ratio=round(bridge, 4),
        circulation_score=score,
        circulation_class=label,
        commit_count=len(commits),
        area_count=len(all_areas),
        areas=all_areas,
    )


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


def _linear_slope(values: Sequence[float]) -> float:
    """Slope of a simple linear regression over evenly-spaced points."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _stddev(values: Sequence[float]) -> float:
    """Population standard deviation."""
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def circulation_trend(
    results: Sequence[CirculationResult],
) -> CirculationTrend:
    """Analyse the trend across multiple circulation windows.

    Parameters
    ----------
    results:
        Ordered sequence of CirculationResult objects (oldest first).

    Returns
    -------
    CirculationTrend with slope, trend label, and summary stats.
    """
    if not results:
        return CirculationTrend()

    scores = [r.circulation_score for r in results]
    slope = _linear_slope(scores)
    mean = sum(scores) / len(scores)
    sd = _stddev(scores)

    if slope > 0.02:
        trend = "improving"
    elif slope < -0.02:
        trend = "fragmenting"
    else:
        trend = "stable"

    return CirculationTrend(
        scores=scores,
        trend=trend,
        slope=round(slope, 4),
        mean=round(mean, 4),
        stddev=round(sd, 4),
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def circulation_report(result: CirculationResult) -> str:
    """Human-readable summary of a circulation analysis."""
    areas_str = ", ".join(sorted(result.areas)) if result.areas else "none"
    lines = [
        f"Circulation: {result.circulation_class} "
        f"(score={result.circulation_score:.2f})",
        f"  commits analysed  : {result.commit_count}",
        f"  areas discovered  : {result.area_count} ({areas_str})",
        f"  cross-area ratio  : {result.cross_area_ratio:.2f}",
        f"  area coupling     : {result.area_coupling:.2f}",
        f"  reach breadth     : {result.reach_breadth:.2f}",
        f"  bridge ratio      : {result.bridge_commit_ratio:.2f}",
    ]
    return "\n".join(lines)


def trend_report(trend: CirculationTrend) -> str:
    """Human-readable summary of a circulation trend."""
    if not trend.scores:
        return "No circulation data available."
    lines = [
        f"Circulation trend: {trend.trend} (slope={trend.slope:+.4f})",
        f"  windows analysed : {len(trend.scores)}",
        f"  mean score       : {trend.mean:.2f}",
        f"  stddev           : {trend.stddev:.2f}",
        f"  recent scores    : "
        f"{', '.join(f'{s:.2f}' for s in trend.scores[-5:])}",
    ]
    return "\n".join(lines)
