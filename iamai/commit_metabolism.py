#!/usr/bin/env python3
"""commit_metabolism — measure how efficiently a codebase metabolizes changes.

A living organism takes in nutrients, absorbs the useful ones, and
excretes waste.  A codebase does the same: it takes in new files and
lines, absorbs the ones that become structural, and churns out the ones
that don't survive contact with reality.

This module answers one question: **is the codebase a healthy metabolism,
or a wasteful one that burns energy on code that never sticks?**

Metabolism dimensions
---------------------

========================  ================================================
metric                    meaning
========================  ================================================
absorption_rate           fraction of files introduced in the window
                          that are touched again by a later commit
                          (absorbed into the body, not excreted)
retention_score           fraction of added lines that survive to the
                          end of the window (not subsequently deleted)
rework_fraction           ratio of deletions to additions — how much
                          energy is spent undoing prior work
churn_index               fraction of total file-touches that result in
                          net deletion (shrinking files)
metabolic_efficiency      composite 0.0–1.0 score: high = efficient
                          metabolism, low = wasteful churn
metabolic_class           anabolic | balanced | catabolic | wasteful |
                          necrotic
========================  ================================================

Metabolic classes
-----------------

==============  ============================================================
class           meaning
==============  ============================================================
anabolic        score ≥ 0.80 — building efficiently, most code sticks
balanced        0.60 ≤ score < 0.80 — healthy mix of growth and pruning
catabolic       0.40 ≤ score < 0.60 — breaking down more than building
wasteful        0.20 ≤ score < 0.40 — lots of churn, little retention
necrotic        score < 0.20 — code dies faster than it's born
==============  ============================================================

Public API
----------
- ``MetabolicCommit`` — data class for one commit's metadata
- ``compute_metabolism(commits) -> MetabolismResult``
- ``classify_metabolism(score) -> str``
- ``metabolism_report(result) -> str``
- ``metabolism_trend(results) -> MetabolismTrend``

Usage::

    from iamai.commit_metabolism import MetabolicCommit, compute_metabolism

    commits = [
        MetabolicCommit(sha="aaa", files={"a.py", "b.py"},
                        additions=50, deletions=0),
        MetabolicCommit(sha="bbb", files={"a.py", "c.py"},
                        additions=30, deletions=10),
        MetabolicCommit(sha="ccc", files={"a.py", "b.py"},
                        additions=5, deletions=20),
    ]
    r = compute_metabolism(commits)
    print(r.metabolic_class)   # "balanced"
    print(r.metabolic_efficiency)  # 0.62
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Set


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MetabolicCommit:
    """Minimal commit metadata for metabolism analysis."""

    sha: str
    files: Set[str] = field(default_factory=set)
    additions: int = 0
    deletions: int = 0


@dataclass
class MetabolismResult:
    """Outcome of a single metabolism analysis window."""

    absorption_rate: float = 0.0
    retention_score: float = 0.0
    rework_fraction: float = 0.0
    churn_index: float = 0.0
    metabolic_efficiency: float = 0.0
    metabolic_class: str = "necrotic"
    commit_count: int = 0
    total_files: int = 0
    total_additions: int = 0
    total_deletions: int = 0


@dataclass
class MetabolismTrend:
    """Trend across multiple metabolism windows."""

    scores: List[float] = field(default_factory=list)
    trend: str = "stable"
    slope: float = 0.0
    mean: float = 0.0
    stddev: float = 0.0


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def _compute_absorption_rate(commits: Sequence[MetabolicCommit]) -> float:
    """Fraction of introduced files that are touched again later.

    For each commit (except the last), count how many of its *new* files
    (files not seen in any earlier commit) appear in at least one later
    commit.  Return the ratio across all introduced files.

    A file that debuts and is never touched again is "excreted" — the
    codebase didn't absorb it.
    """
    if len(commits) < 2:
        return 0.0

    seen: Set[str] = set()
    introduced: Dict[str, int] = {}  # file -> index of introduction

    for i, c in enumerate(commits):
        for f in c.files:
            if f not in seen:
                introduced[f] = i
                seen.add(f)

    if not introduced:
        return 0.0

    # Check which introduced files are touched again after introduction
    absorbed = 0
    for f, intro_idx in introduced.items():
        for j in range(intro_idx + 1, len(commits)):
            if f in commits[j].files:
                absorbed += 1
                break

    return absorbed / len(introduced)


def _compute_retention_score(commits: Sequence[MetabolicCommit]) -> float:
    """Fraction of added lines that survive (not subsequently deleted).

    Estimate: total_additions - total_deletions gives net lines added.
    retention = max(0, net) / total_additions.

    If total_additions is 0 (only deletions), retention is 0.0.
    """
    total_add = sum(c.additions for c in commits)
    total_del = sum(c.deletions for c in commits)

    if total_add == 0:
        return 0.0

    net = total_add - total_del
    return max(0.0, net) / total_add


def _compute_rework_fraction(commits: Sequence[MetabolicCommit]) -> float:
    """Ratio of deletions to additions — how much work is undone.

    Returns a value between 0.0 (no rework) and 1.0 (all work undone).
    Clamped to [0, 1] even if deletions exceed additions (possible when
    deleting legacy code not added in this window).
    """
    total_add = sum(c.additions for c in commits)
    total_del = sum(c.deletions for c in commits)

    if total_add == 0:
        return 1.0 if total_del > 0 else 0.0

    return min(1.0, total_del / total_add)


def _compute_churn_index(commits: Sequence[MetabolicCommit]) -> float:
    """Fraction of file-touches where the commit deletes more than adds.

    Each file-touch is one (commit, file) pair.  A "churning" touch is
    one where the commit has more deletions than additions.

    Note: this is a rough proxy since we don't have per-file line counts,
    so we use the commit-level ratio as a heuristic.
    """
    if not commits:
        return 0.0

    total_touches = sum(len(c.files) for c in commits)
    if total_touches == 0:
        return 0.0

    churning_touches = sum(
        len(c.files) for c in commits if c.deletions > c.additions
    )

    return churning_touches / total_touches


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _compute_efficiency(
    absorption: float,
    retention: float,
    rework: float,
    churn: float,
) -> float:
    """Combine dimensions into a single 0.0–1.0 metabolic efficiency score.

    absorption_rate   — weight 0.30  (absorbed code = healthy growth)
    retention_score   — weight 0.30  (surviving lines = efficient use)
    1 - rework        — weight 0.25  (low rework = focused effort)
    1 - churn         — weight 0.15  (low churn = stable direction)
    """
    return round(
        0.30 * absorption
        + 0.30 * retention
        + 0.25 * (1.0 - rework)
        + 0.15 * (1.0 - churn),
        4,
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_THRESHOLDS = [
    (0.80, "anabolic"),
    (0.60, "balanced"),
    (0.40, "catabolic"),
    (0.20, "wasteful"),
    (0.00, "necrotic"),
]


def classify_metabolism(score: float) -> str:
    """Map an efficiency score to a metabolic class label."""
    for threshold, label in _THRESHOLDS:
        if score >= threshold:
            return label
    return "necrotic"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute_metabolism(
    commits: Sequence[MetabolicCommit],
) -> MetabolismResult:
    """Analyse commit metabolism across a single window.

    Parameters
    ----------
    commits:
        Ordered sequence of MetabolicCommit objects (oldest first).

    Returns
    -------
    MetabolismResult with all dimensions, score, and classification.
    """
    if not commits:
        return MetabolismResult()

    absorption = _compute_absorption_rate(commits)
    retention = _compute_retention_score(commits)
    rework = _compute_rework_fraction(commits)
    churn = _compute_churn_index(commits)
    efficiency = _compute_efficiency(absorption, retention, rework, churn)
    label = classify_metabolism(efficiency)

    all_files: Set[str] = set()
    total_add = 0
    total_del = 0
    for c in commits:
        all_files |= c.files
        total_add += c.additions
        total_del += c.deletions

    return MetabolismResult(
        absorption_rate=round(absorption, 4),
        retention_score=round(retention, 4),
        rework_fraction=round(rework, 4),
        churn_index=round(churn, 4),
        metabolic_efficiency=efficiency,
        metabolic_class=label,
        commit_count=len(commits),
        total_files=len(all_files),
        total_additions=total_add,
        total_deletions=total_del,
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
    numerator = sum(
        (i - x_mean) * (v - y_mean) for i, v in enumerate(values)
    )
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


def metabolism_trend(
    results: Sequence[MetabolismResult],
) -> MetabolismTrend:
    """Analyse the trend across multiple metabolism windows.

    Parameters
    ----------
    results:
        Ordered sequence of MetabolismResult objects (oldest first).

    Returns
    -------
    MetabolismTrend with slope, trend label, and summary stats.
    """
    if not results:
        return MetabolismTrend()

    scores = [r.metabolic_efficiency for r in results]
    slope = _linear_slope(scores)
    mean = sum(scores) / len(scores)
    sd = _stddev(scores)

    if slope > 0.02:
        trend = "strengthening"
    elif slope < -0.02:
        trend = "declining"
    else:
        trend = "stable"

    return MetabolismTrend(
        scores=scores,
        trend=trend,
        slope=round(slope, 4),
        mean=round(mean, 4),
        stddev=round(sd, 4),
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def metabolism_report(result: MetabolismResult) -> str:
    """Human-readable summary of a metabolism analysis."""
    lines = [
        f"Metabolism: {result.metabolic_class} "
        f"(efficiency={result.metabolic_efficiency:.2f})",
        f"  commits analysed  : {result.commit_count}",
        f"  files (universe)  : {result.total_files}",
        f"  total additions   : {result.total_additions}",
        f"  total deletions   : {result.total_deletions}",
        f"  absorption rate   : {result.absorption_rate:.2f}",
        f"  retention score   : {result.retention_score:.2f}",
        f"  rework fraction   : {result.rework_fraction:.2f}",
        f"  churn index       : {result.churn_index:.2f}",
    ]
    return "\n".join(lines)


def trend_report(trend: MetabolismTrend) -> str:
    """Human-readable summary of a metabolism trend."""
    if not trend.scores:
        return "No metabolism data available."
    lines = [
        f"Metabolism trend: {trend.trend} (slope={trend.slope:+.4f})",
        f"  windows analysed : {len(trend.scores)}",
        f"  mean efficiency  : {trend.mean:.2f}",
        f"  stddev           : {trend.stddev:.2f}",
        f"  recent scores    : "
        f"{', '.join(f'{s:.2f}' for s in trend.scores[-5:])}",
    ]
    return "\n".join(lines)
