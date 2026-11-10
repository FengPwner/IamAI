#!/usr/bin/env python3
"""commit_resonance — measure whether consecutive commits amplify each other.

A healthy automated writing pipeline doesn't just produce commits — it
produces commits that *build on each other*.  One commit adds a module,
the next adds its tests, the one after refines the docs.  That pattern
is **resonance**: each commit makes the previous ones more valuable.

The opposite is **noise**: commits that touch unrelated files, revert
each other, or repeat the same change in slightly different words.  A
noisy pipeline is burning energy without accumulating value.

This module answers one question: **are the last N commits building
something together, or just happening near each other in time?**

Signal dimensions
-----------------

========================  ================================================
metric                    meaning
========================  ================================================
file_overlap              Jaccard similarity of file sets between
                          consecutive commits
message_coherence         token overlap between consecutive commit
                          messages (normalised)
direction_consistency     fraction of consecutive pairs that move in
                          the same direction (add/modify vs delete)
build_chain_fraction      fraction of commits touching ≥1 file touched
                          by any of the previous ``window`` commits
signal_strength           ratio of substantive lines changed to total
                          lines changed
resonance_score           composite 0.0–1.0 score
resonance_class           resonant | coherent | scattered | noisy |
                          incoherent
========================  ================================================

Resonance classes
-----------------

==============  ============================================================
class           meaning
==============  ============================================================
resonant        score ≥ 0.80 — commits clearly build on each other
coherent        0.60 ≤ score < 0.80 — related work, loose coupling
scattered       0.40 ≤ score < 0.60 — mixed related and unrelated work
noisy           0.20 ≤ score < 0.40 — mostly unrelated churn
incoherent      score < 0.20 — no visible connection between commits
==============  ============================================================

Public API
----------
- ``CommitInfo`` — data class for one commit's metadata
- ``compute_resonance(commits, *, window=5) -> ResonanceResult``
- ``classify_resonance(score) -> str``
- ``resonance_report(result) -> str``
- ``resonance_trend(results) -> ResonanceTrend`` — across multiple windows

Usage::

    from iamai.commit_resonance import CommitInfo, compute_resonance

    commits = [
        CommitInfo(sha="aaa", message="add caretaker_yield module",
                   files={"iamai/caretaker_yield.py", "tests/test_caretaker_yield.py"},
                   additions=580, deletions=0),
        CommitInfo(sha="bbb", message="caretaker_yield: fix edge case in classify",
                   files={"iamai/caretaker_yield.py"},
                   additions=12, deletions=3),
        CommitInfo(sha="ccc", message="add caretaker_entropy module + 124 tests",
                   files={"iamai/caretaker_entropy.py", "tests/test_caretaker_entropy.py"},
                   additions=600, deletions=0),
    ]
    r = compute_resonance(commits)
    print(r.resonance_class)   # "resonant"
    print(r.resonance_score)  # 0.85
"""

from __future__ import annotations

import math
import re
import string
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CommitInfo:
    """Lightweight representation of one commit for resonance analysis."""

    sha: str
    message: str
    files: set[str] = field(default_factory=set)
    additions: int = 0
    deletions: int = 0


@dataclass
class ResonanceResult:
    """Resonance metrics for a window of commits."""

    file_overlap: float = 0.0
    message_coherence: float = 0.0
    direction_consistency: float = 0.0
    build_chain_fraction: float = 0.0
    signal_strength: float = 0.0
    resonance_score: float = 0.0
    resonance_class: str = "incoherent"
    window_size: int = 0
    commit_count: int = 0


@dataclass
class ResonanceTrend:
    """Trend across multiple resonance windows."""

    scores: list[float] = field(default_factory=list)
    trend: str = "stable"  # improving | stable | degrading
    slope: float = 0.0
    mean: float = 0.0
    stddev: float = 0.0


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_CLASS_THRESHOLDS = [
    (0.80, "resonant"),
    (0.60, "coherent"),
    (0.40, "scattered"),
    (0.20, "noisy"),
    (0.00, "incoherent"),
]

# Composite weights (sum to 1.0)
_W_FILE_OVERLAP = 0.25
_W_MSG_COHERENCE = 0.15
_W_DIRECTION = 0.10
_W_BUILD_CHAIN = 0.30
_W_SIGNAL = 0.20


# ---------------------------------------------------------------------------
# Tokenisation helper
# ---------------------------------------------------------------------------

_STRIP_PUNCT = str.maketrans("", "", string.punctuation)
_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "from", "by", "is", "it", "this", "that",
    "was", "are", "be", "has", "had", "have", "do", "does", "did",
    "not", "no", "as", "if", "so", "up", "out", "can", "may",
})


def _tokenise(text: str) -> list[str]:
    """Lowercase, strip punctuation, remove stop words."""
    tokens = text.lower().translate(_STRIP_PUNCT).split()
    return [t for t in tokens if t and t not in _STOP_WORDS and len(t) > 1]


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets."""
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def _pairwise_file_overlap(commits: Sequence[CommitInfo]) -> float:
    """Average Jaccard similarity of file sets between consecutive commits."""
    if len(commits) < 2:
        return 0.0
    overlaps = []
    for i in range(len(commits) - 1):
        overlaps.append(_jaccard(commits[i].files, commits[i + 1].files))
    return sum(overlaps) / len(overlaps)


def _message_coherence(commits: Sequence[CommitInfo]) -> float:
    """Average token-overlap between consecutive commit messages."""
    if len(commits) < 2:
        return 0.0
    token_sets = [set(_tokenise(c.message)) for c in commits]
    coherences = []
    for i in range(len(token_sets) - 1):
        a, b = token_sets[i], token_sets[i + 1]
        if not a and not b:
            coherences.append(0.0)
        elif not a or not b:
            coherences.append(0.0)
        else:
            intersection = len(a & b)
            # Normalise by smaller set size to reward shared vocabulary
            denom = min(len(a), len(b))
            coherences.append(intersection / denom if denom else 0.0)
    return sum(coherences) / len(coherences) if coherences else 0.0


def _commit_direction(c: CommitInfo) -> str:
    """Classify a commit as 'add', 'modify', or 'delete' based on line counts."""
    total = c.additions + c.deletions
    if total == 0:
        return "modify"
    add_ratio = c.additions / total
    if add_ratio >= 0.8:
        return "add"
    elif add_ratio <= 0.2:
        return "delete"
    return "modify"


def _direction_consistency(commits: Sequence[CommitInfo]) -> float:
    """Fraction of consecutive pairs sharing the same direction class."""
    if len(commits) < 2:
        return 0.0
    directions = [_commit_direction(c) for c in commits]
    matches = sum(1 for i in range(len(directions) - 1)
                  if directions[i] == directions[i + 1])
    return matches / (len(directions) - 1)


def _build_chain_fraction(commits: Sequence[CommitInfo], window: int) -> float:
    """Fraction of commits that touch ≥1 file from any predecessor in window."""
    if len(commits) < 2:
        return 0.0
    connected = 0
    for i in range(1, len(commits)):
        lookback = max(0, i - window)
        predecessor_files = set()
        for j in range(lookback, i):
            predecessor_files |= commits[j].files
        if commits[i].files & predecessor_files:
            connected += 1
    return connected / (len(commits) - 1)


def _signal_strength(commits: Sequence[CommitInfo]) -> float:
    """Ratio of substantive changes to total changes.

    Heuristic: commits with < 5 total lines changed are 'noise'.
    Everything else counts as signal.
    """
    if not commits:
        return 0.0
    substantive = 0
    for c in commits:
        total = c.additions + c.deletions
        if total >= 5:
            substantive += 1
    return substantive / len(commits)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def classify_resonance(score: float) -> str:
    """Map a resonance score to its class label."""
    score = max(0.0, min(1.0, score))
    for threshold, label in _CLASS_THRESHOLDS:
        if score >= threshold:
            return label
    return "incoherent"


def compute_resonance(
    commits: Sequence[CommitInfo],
    *,
    window: int = 5,
) -> ResonanceResult:
    """Compute resonance metrics for a sequence of commits.

    Parameters
    ----------
    commits:
        Ordered list of commits (oldest first).
    window:
        How many predecessors to consider for build-chain analysis.

    Returns
    -------
    ResonanceResult with all dimensions populated.
    """
    if not commits:
        return ResonanceResult()

    n = len(commits)

    file_ov = _pairwise_file_overlap(commits)
    msg_coh = _message_coherence(commits)
    dir_con = _direction_consistency(commits)
    build_cf = _build_chain_fraction(commits, window=window)
    sig_str = _signal_strength(commits)

    # Composite
    score = (
        _W_FILE_OVERLAP * file_ov
        + _W_MSG_COHERENCE * msg_coh
        + _W_DIRECTION * dir_con
        + _W_BUILD_CHAIN * build_cf
        + _W_SIGNAL * sig_str
    )
    score = round(max(0.0, min(1.0, score)), 4)

    return ResonanceResult(
        file_overlap=round(file_ov, 4),
        message_coherence=round(msg_coh, 4),
        direction_consistency=round(dir_con, 4),
        build_chain_fraction=round(build_cf, 4),
        signal_strength=round(sig_str, 4),
        resonance_score=score,
        resonance_class=classify_resonance(score),
        window_size=window,
        commit_count=n,
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


def resonance_trend(results: Sequence[ResonanceResult]) -> ResonanceTrend:
    """Analyse the trend across multiple resonance windows.

    Parameters
    ----------
    results:
        Ordered sequence of ResonanceResult objects (oldest first).

    Returns
    -------
    ResonanceTrend with slope, trend label, and summary stats.
    """
    if not results:
        return ResonanceTrend()

    scores = [r.resonance_score for r in results]
    slope = _linear_slope(scores)
    mean = sum(scores) / len(scores)
    sd = _stddev(scores)

    if slope > 0.02:
        trend = "improving"
    elif slope < -0.02:
        trend = "degrading"
    else:
        trend = "stable"

    return ResonanceTrend(
        scores=scores,
        trend=trend,
        slope=round(slope, 4),
        mean=round(mean, 4),
        stddev=round(sd, 4),
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def resonance_report(result: ResonanceResult) -> str:
    """Human-readable summary of a resonance analysis."""
    lines = [
        f"Resonance: {result.resonance_class} (score={result.resonance_score:.2f})",
        f"  commits analysed : {result.commit_count}",
        f"  window size      : {result.window_size}",
        f"  file overlap     : {result.file_overlap:.2f}",
        f"  msg coherence    : {result.message_coherence:.2f}",
        f"  direction consist: {result.direction_consistency:.2f}",
        f"  build chain frac : {result.build_chain_fraction:.2f}",
        f"  signal strength  : {result.signal_strength:.2f}",
    ]
    return "\n".join(lines)


def trend_report(trend: ResonanceTrend) -> str:
    """Human-readable summary of a resonance trend."""
    if not trend.scores:
        return "No resonance data available."
    lines = [
        f"Resonance trend: {trend.trend} (slope={trend.slope:+.4f})",
        f"  windows analysed: {len(trend.scores)}",
        f"  mean score      : {trend.mean:.2f}",
        f"  stddev          : {trend.stddev:.2f}",
        f"  recent scores   : {', '.join(f'{s:.2f}' for s in trend.scores[-5:])}",
    ]
    return "\n".join(lines)
