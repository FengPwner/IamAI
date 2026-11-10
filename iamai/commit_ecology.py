#!/usr/bin/env python3
"""commit_ecology — measure the health of the commit ecosystem.

A codebase is an ecosystem.  Files are species, commits are weather
events, and the overall health depends on diversity, balance, and
interconnection.  A thriving ecosystem has rich variety, even
distribution, and strong cross-pollination.  A barren one is a
monoculture where the same three files get edited on repeat.

This module answers one question: **is the commit history a healthy
ecosystem, or a fragile monoculture on the verge of collapse?**

Ecology dimensions
------------------

========================  ================================================
metric                    meaning
========================  ================================================
species_richness          number of distinct file paths touched across
                          all commits in the window
shannon_evenness          Shannon diversity index (H / ln(S)) — how
                          evenly changes distribute across files;
                          0 = all changes in one file, 1 = perfectly
                          even
simpson_diversity         1 - Σ(pi²) — probability that two randomly
                          chosen file-touches belong to different files
keystone_fraction         fraction of files touched ≥ 3 times (these
                          are structural keystones holding the ecosystem
                          together)
invasion_rate             fraction of files that first appear within
                          the window (new species entering)
extinction_rate           fraction of files touched exactly once
                          (vulnerable, no redundancy)
connectance               realised file-commit links / maximum possible
                          links in the bipartite graph
ecology_score             composite 0.0–1.0 score
ecology_class             thriving | healthy | fragile | barren |
                          monoculture
========================  ================================================

Ecology classes
---------------

==============  ============================================================
class           meaning
==============  ============================================================
thriving        score ≥ 0.80 — diverse, balanced, well-connected
healthy         0.60 ≤ score < 0.80 — good variety, minor imbalances
fragile         0.40 ≤ score < 0.60 — narrow focus or uneven distribution
barren          0.20 ≤ score < 0.40 — very few files, heavy concentration
monoculture     score < 0.20 — nearly all activity in one or two files
==============  ============================================================

Public API
----------
- ``CommitInfo`` — data class for one commit's metadata (shared with resonance)
- ``compute_ecology(commits) -> EcologyResult``
- ``classify_ecology(score) -> str``
- ``ecology_report(result) -> str``
- ``ecology_trend(results) -> EcologyTrend`` — across multiple windows

Usage::

    from iamai.commit_ecology import CommitInfo, compute_ecology

    commits = [
        CommitInfo(sha="aaa", files={"iamai/foo.py", "tests/test_foo.py",
                                     "docs/FOO.md"}, additions=200, deletions=0),
        CommitInfo(sha="bbb", files={"iamai/bar.py", "tests/test_bar.py"},
                   additions=150, deletions=5),
        CommitInfo(sha="ccc", files={"iamai/foo.py", "iamai/baz.py",
                                     "tests/test_baz.py", "docs/BAZ.md"},
                   additions=300, deletions=0),
    ]
    r = compute_ecology(commits)
    print(r.ecology_class)   # "thriving"
    print(r.ecology_score)   # 0.83
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CommitInfo:
    """Lightweight representation of one commit for ecology analysis."""

    sha: str
    message: str = ""
    files: set[str] = field(default_factory=set)
    additions: int = 0
    deletions: int = 0


@dataclass
class EcologyResult:
    """Ecology metrics for a window of commits."""

    species_richness: float = 0.0
    shannon_evenness: float = 0.0
    simpson_diversity: float = 0.0
    keystone_fraction: float = 0.0
    invasion_rate: float = 0.0
    extinction_rate: float = 0.0
    connectance: float = 0.0
    ecology_score: float = 0.0
    ecology_class: str = "monoculture"
    commit_count: int = 0
    file_count: int = 0


@dataclass
class EcologyTrend:
    """Trend across multiple ecology windows."""

    scores: list[float] = field(default_factory=list)
    trend: str = "stable"  # improving | stable | degrading
    slope: float = 0.0
    mean: float = 0.0
    stddev: float = 0.0


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_CLASS_THRESHOLDS = [
    (0.80, "thriving"),
    (0.60, "healthy"),
    (0.40, "fragile"),
    (0.20, "barren"),
    (0.00, "monoculture"),
]

# Composite weights (sum to 1.0)
_W_SHANNON = 0.20
_W_SIMPSON = 0.15
_W_KEYSTONE = 0.15
_W_INVASION = 0.10
_W_EXTINCTION = 0.10  # inverted: lower extinction is better
_W_CONNECTANCE = 0.15
_W_RICHNESS_NORM = 0.15  # normalised richness


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------


def _file_frequency(commits: Sequence[CommitInfo]) -> Counter:
    """Count how many commits touch each file."""
    freq: Counter = Counter()
    for c in commits:
        for f in c.files:
            freq[f] += 1
    return freq


def species_richness(commits: Sequence[CommitInfo]) -> int:
    """Number of distinct files across all commits."""
    all_files: set[str] = set()
    for c in commits:
        all_files |= c.files
    return len(all_files)


def shannon_evenness(commits: Sequence[CommitInfo]) -> float:
    """Shannon evenness J = H / ln(S).

    Returns 0.0 when S ≤ 1 (no diversity to measure).
    """
    freq = _file_frequency(commits)
    s = len(freq)
    if s <= 1:
        return 0.0

    total = sum(freq.values())
    if total == 0:
        return 0.0

    h = 0.0
    for count in freq.values():
        p = count / total
        if p > 0:
            h -= p * math.log(p)

    h_max = math.log(s)
    if h_max == 0:
        return 0.0
    return min(1.0, h / h_max)


def simpson_diversity(commits: Sequence[CommitInfo]) -> float:
    """Simpson's diversity index: 1 - Σ(pi²).

    Returns 0.0 when there are no file touches.
    """
    freq = _file_frequency(commits)
    total = sum(freq.values())
    if total <= 1:
        return 0.0

    sum_p2 = sum((c / total) ** 2 for c in freq.values())
    return max(0.0, 1.0 - sum_p2)


def keystone_fraction(commits: Sequence[CommitInfo], *, min_touches: int = 3) -> float:
    """Fraction of files touched ≥ ``min_touches`` times.

    These "keystone species" are structural elements that multiple
    commits depend on or interact with.
    """
    freq = _file_frequency(commits)
    if not freq:
        return 0.0
    keystone = sum(1 for c in freq.values() if c >= min_touches)
    return keystone / len(freq)


def invasion_rate(commits: Sequence[CommitInfo]) -> float:
    """Fraction of files that first appear in the later half of the window.

    New files entering the ecosystem = invasion.  A moderate invasion
    rate is healthy (growth); zero means stagnation; very high means
    instability.

    For this metric, "later half" means commits in the second half of
    the ordered sequence.
    """
    if len(commits) < 2:
        return 0.0

    mid = len(commits) // 2
    early_files: set[str] = set()
    for c in commits[:mid]:
        early_files |= c.files

    all_files: set[str] = set()
    for c in commits:
        all_files |= c.files

    if not all_files:
        return 0.0

    new_files = all_files - early_files
    return len(new_files) / len(all_files)


def extinction_rate(commits: Sequence[CommitInfo]) -> float:
    """Fraction of files touched exactly once.

    High extinction rate means most files are one-shots — no follow-up,
    no iteration.  This is fragile: those files have no redundancy.
    """
    freq = _file_frequency(commits)
    if not freq:
        return 0.0
    singletons = sum(1 for c in freq.values() if c == 1)
    return singletons / len(freq)


def connectance(commits: Sequence[CommitInfo]) -> float:
    """Realised links / possible links in the commit-file bipartite graph.

    A link exists when commit C touches file F.  Maximum possible
    links = |commits| × |files|.  Realised links = sum of unique
    file touches per commit.

    Higher connectance means denser interconnection.
    """
    if not commits:
        return 0.0

    all_files: set[str] = set()
    for c in commits:
        all_files |= c.files

    n_commits = len(commits)
    n_files = len(all_files)
    max_links = n_commits * n_files
    if max_links == 0:
        return 0.0

    realised = sum(len(c.files) for c in commits)
    return realised / max_links


def _normalised_richness(commits: Sequence[CommitInfo]) -> float:
    """Richness normalised against commit count.

    More files per commit = richer ecosystem.  Caps at 1.0 when
    files_per_commit >= 5 (a reasonable ceiling for focused work).
    """
    if not commits:
        return 0.0
    s = species_richness(commits)
    ratio = s / len(commits)
    return min(1.0, ratio / 5.0)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def classify_ecology(score: float) -> str:
    """Map an ecology score to its class label."""
    score = max(0.0, min(1.0, score))
    for threshold, label in _CLASS_THRESHOLDS:
        if score >= threshold:
            return label
    return "monoculture"


def compute_ecology(commits: Sequence[CommitInfo]) -> EcologyResult:
    """Compute ecology metrics for a sequence of commits.

    Parameters
    ----------
    commits:
        Ordered list of commits (oldest first).

    Returns
    -------
    EcologyResult with all dimensions populated.
    """
    if not commits:
        return EcologyResult()

    n = len(commits)
    s = species_richness(commits)
    shan = shannon_evenness(commits)
    simp = simpson_diversity(commits)
    keyst = keystone_fraction(commits)
    inv = invasion_rate(commits)
    ext = extinction_rate(commits)
    conn = connectance(commits)
    rich_norm = _normalised_richness(commits)

    # Composite: extinction is inverted (lower is better)
    score = (
        _W_SHANNON * shan
        + _W_SIMPSON * simp
        + _W_KEYSTONE * keyst
        + _W_INVASION * min(1.0, inv * 2)  # moderate invasion is best
        + _W_EXTINCTION * (1.0 - ext)  # invert: low extinction = high score
        + _W_CONNECTANCE * conn
        + _W_RICHNESS_NORM * rich_norm
    )
    score = round(max(0.0, min(1.0, score)), 4)

    return EcologyResult(
        species_richness=float(s),
        shannon_evenness=round(shan, 4),
        simpson_diversity=round(simp, 4),
        keystone_fraction=round(keyst, 4),
        invasion_rate=round(inv, 4),
        extinction_rate=round(ext, 4),
        connectance=round(conn, 4),
        ecology_score=score,
        ecology_class=classify_ecology(score),
        commit_count=n,
        file_count=s,
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


def ecology_trend(results: Sequence[EcologyResult]) -> EcologyTrend:
    """Analyse the trend across multiple ecology windows.

    Parameters
    ----------
    results:
        Ordered sequence of EcologyResult objects (oldest first).

    Returns
    -------
    EcologyTrend with slope, trend label, and summary stats.
    """
    if not results:
        return EcologyTrend()

    scores = [r.ecology_score for r in results]
    slope = _linear_slope(scores)
    mean = sum(scores) / len(scores)
    sd = _stddev(scores)

    if slope > 0.02:
        trend = "improving"
    elif slope < -0.02:
        trend = "degrading"
    else:
        trend = "stable"

    return EcologyTrend(
        scores=scores,
        trend=trend,
        slope=round(slope, 4),
        mean=round(mean, 4),
        stddev=round(sd, 4),
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def ecology_report(result: EcologyResult) -> str:
    """Human-readable summary of an ecology analysis."""
    lines = [
        f"Ecology: {result.ecology_class} (score={result.ecology_score:.2f})",
        f"  commits analysed : {result.commit_count}",
        f"  files (species)  : {result.file_count}",
        f"  shannon evenness : {result.shannon_evenness:.2f}",
        f"  simpson diversity: {result.simpson_diversity:.2f}",
        f"  keystone fraction: {result.keystone_fraction:.2f}",
        f"  invasion rate    : {result.invasion_rate:.2f}",
        f"  extinction rate  : {result.extinction_rate:.2f}",
        f"  connectance      : {result.connectance:.2f}",
    ]
    return "\n".join(lines)


def trend_report(trend: EcologyTrend) -> str:
    """Human-readable summary of an ecology trend."""
    if not trend.scores:
        return "No ecology data available."
    lines = [
        f"Ecology trend: {trend.trend} (slope={trend.slope:+.4f})",
        f"  windows analysed: {len(trend.scores)}",
        f"  mean score      : {trend.mean:.2f}",
        f"  stddev          : {trend.stddev:.2f}",
        f"  recent scores   : {', '.join(f'{s:.2f}' for s in trend.scores[-5:])}",
    ]
    return "\n".join(lines)
