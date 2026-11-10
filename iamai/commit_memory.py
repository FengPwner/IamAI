#!/usr/bin/env python3
"""commit_memory — measure how well a repo remembers its own past.

A codebase with amnesia keeps reinventing the same abstractions under
new names.  A codebase with eidetic memory builds layer upon layer,
each commit standing on the shoulders of earlier ones.

This module answers one question: **does the commit history show
institutional memory, or chronic amnesia?**

Memory dimensions
-----------------

====================  ======================================================
metric                meaning
====================  ======================================================
ancestry_depth        fraction of files in each commit that also appear in
                      at least one earlier commit (building on known ground)
echo_rate             fraction of commit messages sharing ≥ 1 meaningful
                      token with an earlier message (verbal memory)
reinvention_rate      fraction of files that debut within the window
                      (new species — exploration *or* reinvention)
continuity_score      composite 0.0–1.0: high = strong memory, low = amnesia
memory_class          eidetic | sharp | adequate | foggy | amnesiac
====================  ======================================================

Memory classes
--------------

============  ==============================================================
class         meaning
============  ==============================================================
eidetic       score ≥ 0.80 — nearly every commit extends prior work
sharp         0.60 ≤ score < 0.80 — good recall, occasional new territory
adequate      0.40 ≤ score < 0.60 — mix of recall and novelty
foggy         0.20 ≤ score < 0.40 — mostly new files, weak verbal echo
amnesiac      score < 0.20 — every commit looks like a fresh start
============  ==============================================================

Public API
----------
- ``CommitRecord`` — data class for one commit's metadata
- ``compute_memory(commits) -> MemoryResult``
- ``classify_memory(score) -> str``
- ``memory_report(result) -> str``
- ``memory_trend(results) -> MemoryTrend``

Usage::

    from iamai.commit_memory import CommitRecord, compute_memory

    commits = [
        CommitRecord(sha="aaa", message="add foo module",
                     files={"iamai/foo.py", "tests/test_foo.py"}),
        CommitRecord(sha="bbb", message="extend foo with bar",
                     files={"iamai/foo.py", "iamai/bar.py",
                            "tests/test_bar.py"}),
        CommitRecord(sha="ccc", message="refactor foo internals",
                     files={"iamai/foo.py", "tests/test_foo.py",
                            "docs/FOO.md"}),
    ]
    r = compute_memory(commits)
    print(r.memory_class)    # "sharp" or "eidetic"
    print(r.continuity_score) # 0.72
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Set


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
    "this", "that", "not", "no", "do", "so", "if", "up",
})


@dataclass
class CommitRecord:
    """Minimal commit metadata for memory analysis."""

    sha: str
    message: str
    files: Set[str] = field(default_factory=set)


@dataclass
class MemoryResult:
    """Outcome of a single memory analysis window."""

    ancestry_depth: float = 0.0
    echo_rate: float = 0.0
    reinvention_rate: float = 0.0
    continuity_score: float = 0.0
    memory_class: str = "amnesiac"
    commit_count: int = 0
    file_count: int = 0


@dataclass
class MemoryTrend:
    """Trend across multiple memory windows."""

    scores: List[float] = field(default_factory=list)
    trend: str = "stable"
    slope: float = 0.0
    mean: float = 0.0
    stddev: float = 0.0


# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------


def _meaningful_tokens(message: str) -> Set[str]:
    """Extract meaningful lowercase tokens from a commit message."""
    tokens = set(re.findall(r"[a-z][a-z0-9_\-]+", message.lower()))
    return tokens - _STOP_WORDS


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def _compute_ancestry_depth(commits: Sequence[CommitRecord]) -> float:
    """Fraction of file-touches that land on previously-seen files.

    The first commit contributes 0 (nothing is "known" yet).  For every
    subsequent commit, count how many of its files were touched by at
    least one earlier commit, divide by total files in that commit.
    Return the average across all commits (excluding the first).
    """
    if len(commits) < 2:
        return 0.0

    seen: Set[str] = set(commits[0].files)
    ratios: List[float] = []

    for c in commits[1:]:
        if not c.files:
            ratios.append(0.0)
            continue
        known = sum(1 for f in c.files if f in seen)
        ratios.append(known / len(c.files))
        seen |= c.files

    return sum(ratios) / len(ratios)


def _compute_echo_rate(commits: Sequence[CommitRecord]) -> float:
    """Fraction of commits whose message echoes an earlier message.

    "Echo" = sharing ≥ 1 meaningful token with any prior commit message.
    The first commit is excluded from the denominator.
    """
    if len(commits) < 2:
        return 0.0

    prior_tokens: Set[str] = set()
    prior_tokens |= _meaningful_tokens(commits[0].message)
    echoes = 0

    for c in commits[1:]:
        tokens = _meaningful_tokens(c.message)
        if tokens & prior_tokens:
            echoes += 1
        prior_tokens |= tokens

    return echoes / (len(commits) - 1)


def _compute_reinvention_rate(commits: Sequence[CommitRecord]) -> float:
    """Fraction of file-touches that introduce a brand-new file.

    High reinvention means lots of exploration (good early on) but may
    signal amnesia in a mature codebase (creating instead of extending).
    """
    if not commits:
        return 0.0

    seen: Set[str] = set()
    total_touches = 0
    new_touches = 0

    for c in commits:
        for f in c.files:
            total_touches += 1
            if f not in seen:
                new_touches += 1
                seen.add(f)

    if total_touches == 0:
        return 0.0
    return new_touches / total_touches


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _compute_continuity_score(
    ancestry: float, echo: float, reinvention: float
) -> float:
    """Combine dimensions into a single 0.0–1.0 continuity score.

    ancestry_depth   — weight 0.40  (building on known files is the
    echo_rate        — weight 0.30    strongest memory signal)
    1-reinvention    — weight 0.30  (low reinvention = strong memory)
    """
    return round(
        0.40 * ancestry + 0.30 * echo + 0.30 * (1.0 - reinvention), 4
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_THRESHOLDS = [
    (0.80, "eidetic"),
    (0.60, "sharp"),
    (0.40, "adequate"),
    (0.20, "foggy"),
    (0.00, "amnesiac"),
]


def classify_memory(score: float) -> str:
    """Map a continuity score to a memory class label."""
    for threshold, label in _THRESHOLDS:
        if score >= threshold:
            return label
    return "amnesiac"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute_memory(commits: Sequence[CommitRecord]) -> MemoryResult:
    """Analyse commit memory across a single window.

    Parameters
    ----------
    commits:
        Ordered sequence of CommitRecord objects (oldest first).

    Returns
    -------
    MemoryResult with all dimensions, score, and classification.
    """
    if not commits:
        return MemoryResult()

    ancestry = _compute_ancestry_depth(commits)
    echo = _compute_echo_rate(commits)
    reinvention = _compute_reinvention_rate(commits)
    score = _compute_continuity_score(ancestry, echo, reinvention)
    label = classify_memory(score)

    all_files: Set[str] = set()
    for c in commits:
        all_files |= c.files

    return MemoryResult(
        ancestry_depth=round(ancestry, 4),
        echo_rate=round(echo, 4),
        reinvention_rate=round(reinvention, 4),
        continuity_score=score,
        memory_class=label,
        commit_count=len(commits),
        file_count=len(all_files),
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


def memory_trend(results: Sequence[MemoryResult]) -> MemoryTrend:
    """Analyse the trend across multiple memory windows.

    Parameters
    ----------
    results:
        Ordered sequence of MemoryResult objects (oldest first).

    Returns
    -------
    MemoryTrend with slope, trend label, and summary stats.
    """
    if not results:
        return MemoryTrend()

    scores = [r.continuity_score for r in results]
    slope = _linear_slope(scores)
    mean = sum(scores) / len(scores)
    sd = _stddev(scores)

    if slope > 0.02:
        trend = "strengthening"
    elif slope < -0.02:
        trend = "fading"
    else:
        trend = "stable"

    return MemoryTrend(
        scores=scores,
        trend=trend,
        slope=round(slope, 4),
        mean=round(mean, 4),
        stddev=round(sd, 4),
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def memory_report(result: MemoryResult) -> str:
    """Human-readable summary of a memory analysis."""
    lines = [
        f"Memory: {result.memory_class} (score={result.continuity_score:.2f})",
        f"  commits analysed  : {result.commit_count}",
        f"  files (universe)  : {result.file_count}",
        f"  ancestry depth    : {result.ancestry_depth:.2f}",
        f"  echo rate         : {result.echo_rate:.2f}",
        f"  reinvention rate  : {result.reinvention_rate:.2f}",
    ]
    return "\n".join(lines)


def trend_report(trend: MemoryTrend) -> str:
    """Human-readable summary of a memory trend."""
    if not trend.scores:
        return "No memory data available."
    lines = [
        f"Memory trend: {trend.trend} (slope={trend.slope:+.4f})",
        f"  windows analysed : {len(trend.scores)}",
        f"  mean score       : {trend.mean:.2f}",
        f"  stddev           : {trend.stddev:.2f}",
        f"  recent scores    : {', '.join(f'{s:.2f}' for s in trend.scores[-5:])}",
    ]
    return "\n".join(lines)
