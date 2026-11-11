#!/usr/bin/env python3
"""commit_turbulence — measure how erratic or predictable commit flow is.

Fluid dynamics distinguishes **laminar** flow (smooth, predictable,
layered) from **turbulent** flow (chaotic, mixing, eddies).  Codebases
have the same spectrum.  A laminar repo sees steady, well-spaced commits
that touch coherent areas.  A turbulent repo sees bursts of commits at
3 AM touching unrelated files, interleaved with long silences.

This module quantifies that spectrum.

Turbulence is *not* bad per se.  A burst of commits during a hackathon
is turbulent but productive.  Chronic turbulence, however, signals
context-switching debt, firefighting, or lack of architectural
coherence.  Measuring it lets you notice the shift from "we shipped
a lot this week" to "we shipped chaotically this week."

Turbulence dimensions
---------------------

========================  ================================================
metric                    meaning
========================  ================================================
burstiness                max commits in a single time-window ÷ mean
                          commits per window.  1.0 = perfectly uniform;
                          higher = bursty
interval_cv               coefficient of variation (σ/μ) of inter-commit
                          intervals.  Low = clock-like; high = erratic
direction_entropy         Shannon entropy of per-file-area change
                          frequencies across consecutive commits.
                          Low = focused; high = scattered
author_churn              fraction of consecutive commit pairs with
                          different authors.  1.0 = every commit is by
                          a different person
size_volatility           coefficient of variation of commit sizes
                          (lines changed).  High = wild swings
revert_ratio              fraction of commits whose message matches a
                          revert pattern.  High = oscillating direction
turbulence_score          composite 0.0–1.0: weighted blend of the above
flow_regime               laminar | transitional | turbulent
========================  ================================================

Flow regimes
------------

==============  ============================================================
regime          meaning
==============  ============================================================
laminar         score < 0.30 — commits flow smoothly, focused areas,
                consistent tempo
transitional    0.30 ≤ score < 0.65 — mixed signals; some bursts or
                scatter but not chronic
turbulent       score ≥ 0.65 — erratic timing, scattered touches,
                frequent direction changes
==============  ============================================================

Public API
----------
- ``CommitRecord`` — data class for one commit's metadata
- ``compute_turbulence(commits, ...) -> TurbulenceResult``
- ``classify_turbulence(score) -> str``
- ``turbulence_report(result) -> str``
- ``area_turbulence(commits_by_area) -> dict[str, TurbulenceResult]``
- ``turbulence_trend(snapshots) -> TurbulenceTrend``

Usage::

    from iamai.commit_turbulence import CommitRecord, compute_turbulence
    from datetime import datetime

    commits = [
        CommitRecord(
            sha="abc123",
            timestamp=datetime(2026, 11, 10, 9, 0),
            author="qwen",
            files_changed=["iamai/commit_inertia.py", "tests/test_commit_inertia.py"],
            lines_changed=526,
            message="add commit_inertia module",
        ),
        # ...
    ]
    result = compute_turbulence(commits, window_minutes=60)
    print(result.flow_regime)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CommitRecord:
    """Minimal commit metadata for turbulence analysis."""

    sha: str
    timestamp: datetime
    author: str
    files_changed: List[str]
    lines_changed: int
    message: str

    @property
    def areas(self) -> List[str]:
        """Extract top-level directory names from changed files."""
        dirs = set()
        for f in self.files_changed:
            parts = f.split("/")
            dirs.add(parts[0] if len(parts) > 1 else ".")
        return sorted(dirs)


@dataclass
class TurbulenceResult:
    """Full turbulence analysis for a sequence of commits."""

    burstiness: float = 0.0
    interval_cv: float = 0.0
    direction_entropy: float = 0.0
    author_churn: float = 0.0
    size_volatility: float = 0.0
    revert_ratio: float = 0.0
    turbulence_score: float = 0.0
    flow_regime: str = "laminar"
    commit_count: int = 0
    window_minutes: int = 60
    details: dict = field(default_factory=dict)


@dataclass
class TurbulenceTrend:
    """Trend across multiple turbulence snapshots."""

    direction: str = "stable"
    slope: float = 0.0
    first_mean: float = 0.0
    last_mean: float = 0.0
    delta: float = 0.0
    measurements: int = 0
    interpretation: str = ""


# ---------------------------------------------------------------------------
# Revert pattern
# ---------------------------------------------------------------------------

_REVERT_RE = re.compile(
    r"^(revert|Revert|REVERT|rollback|Rollback|undo|Undo)",
    re.MULTILINE,
)


def _is_revert(message: str) -> bool:
    """Check whether a commit message looks like a revert."""
    return bool(_REVERT_RE.search(message))


# ---------------------------------------------------------------------------
# Individual metrics
# ---------------------------------------------------------------------------

def _burstiness(commits: Sequence[CommitRecord], window_minutes: int) -> float:
    """Ratio of max-window-count to mean-window-count.

    Returns 1.0 for perfectly uniform flow; higher for burstier patterns.
    Returns 1.0 when there are too few commits to measure.
    """
    if len(commits) < 2:
        return 1.0

    timestamps = sorted(c.timestamp for c in commits)
    t_min = timestamps[0]
    t_max = timestamps[-1]

    span_minutes = (t_max - t_min).total_seconds() / 60.0
    if span_minutes <= 0:
        return 1.0

    window_count = max(1, int(math.ceil(span_minutes / window_minutes)))
    buckets: Counter = Counter()
    for ts in timestamps:
        bucket_idx = int((ts - t_min).total_seconds() / 60.0 / window_minutes)
        bucket_idx = min(bucket_idx, window_count - 1)
        buckets[bucket_idx] += 1

    # Include empty buckets
    counts = [buckets.get(i, 0) for i in range(window_count)]
    mean_count = sum(counts) / len(counts) if counts else 0
    if mean_count == 0:
        return 1.0

    max_count = max(counts)
    return max_count / mean_count


def _interval_cv(commits: Sequence[CommitRecord]) -> float:
    """Coefficient of variation of inter-commit intervals (in seconds).

    Low CV = clock-like regularity; high CV = erratic timing.
    Returns 0.0 when there are fewer than 3 commits.
    """
    if len(commits) < 3:
        return 0.0

    timestamps = sorted(c.timestamp for c in commits)
    intervals = [
        (timestamps[i + 1] - timestamps[i]).total_seconds()
        for i in range(len(timestamps) - 1)
    ]

    n = len(intervals)
    mean = sum(intervals) / n
    if mean == 0:
        return 0.0

    variance = sum((x - mean) ** 2 for x in intervals) / n
    std = math.sqrt(variance)
    return std / mean


def _direction_entropy(commits: Sequence[CommitRecord]) -> float:
    """Shannon entropy of area-level change distribution.

    Measures how scattered commits are across codebase areas.
    Returns 0.0 when all commits touch the same area.
    """
    if len(commits) < 2:
        return 0.0

    area_counts: Counter = Counter()
    for c in commits:
        for area in c.areas:
            area_counts[area] += 1

    total = sum(area_counts.values())
    if total == 0:
        return 0.0

    entropy = 0.0
    for count in area_counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)

    # Normalize by max possible entropy (log2 of number of areas)
    n_areas = len(area_counts)
    if n_areas <= 1:
        return 0.0

    max_entropy = math.log2(n_areas)
    return entropy / max_entropy if max_entropy > 0 else 0.0


def _author_churn(commits: Sequence[CommitRecord]) -> float:
    """Fraction of consecutive commit pairs with different authors.

    Returns 0.0 when all commits are by the same author (no churn).
    """
    if len(commits) < 2:
        return 0.0

    sorted_commits = sorted(commits, key=lambda c: c.timestamp)
    transitions = 0
    total_pairs = len(sorted_commits) - 1

    for i in range(total_pairs):
        if sorted_commits[i].author != sorted_commits[i + 1].author:
            transitions += 1

    return transitions / total_pairs


def _size_volatility(commits: Sequence[CommitRecord]) -> float:
    """Coefficient of variation of commit sizes (lines changed).

    High volatility = wild swings in how much changes per commit.
    Returns 0.0 when all commits change the same number of lines.
    """
    if len(commits) < 2:
        return 0.0

    sizes = [max(1, abs(c.lines_changed)) for c in commits]
    n = len(sizes)
    mean = sum(sizes) / n
    if mean == 0:
        return 0.0

    variance = sum((s - mean) ** 2 for s in sizes) / n
    std = math.sqrt(variance)
    cv = std / mean

    # Cap at 5.0 for scoring purposes (raw value can be much higher)
    return min(cv, 5.0)


def _revert_ratio(commits: Sequence[CommitRecord]) -> float:
    """Fraction of commits that appear to be reverts."""
    if not commits:
        return 0.0

    reverts = sum(1 for c in commits if _is_revert(c.message))
    return reverts / len(commits)


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

# Weights for the composite score (sum to 1.0)
_WEIGHTS = {
    "burstiness": 0.20,
    "interval_cv": 0.25,
    "direction_entropy": 0.15,
    "author_churn": 0.10,
    "size_volatility": 0.20,
    "revert_ratio": 0.10,
}


def _normalize_metric(name: str, value: float) -> float:
    """Normalize a raw metric to 0.0–1.0 for scoring."""
    if name == "burstiness":
        # 1.0 = uniform (low turbulence), map to 0
        # Higher = more bursty.  Score = (burstiness - 1) / (burstiness)
        # Clamped.  burstiness=1 → 0, burstiness=3 → 0.67, burstiness=10 → 0.9
        return min(1.0, max(0.0, (value - 1.0) / value)) if value > 1.0 else 0.0
    elif name == "interval_cv":
        # CV of 0 = perfectly regular.  CV of 2+ = very erratic.
        return min(1.0, value / 2.0)
    elif name == "direction_entropy":
        # Already 0.0–1.0
        return min(1.0, max(0.0, value))
    elif name == "author_churn":
        # Already 0.0–1.0
        return min(1.0, max(0.0, value))
    elif name == "size_volatility":
        # Normalized CV, capped at 5.0 → 1.0
        return min(1.0, value / 3.0)
    elif name == "revert_ratio":
        # 0.0–1.0, but even 0.3 is very high in practice
        return min(1.0, value / 0.3)
    return min(1.0, max(0.0, value))


def _composite_score(metrics: dict) -> float:
    """Compute weighted turbulence score from normalized metrics."""
    score = 0.0
    for name, weight in _WEIGHTS.items():
        raw = metrics.get(name, 0.0)
        normalized = _normalize_metric(name, raw)
        score += weight * normalized
    return round(min(1.0, max(0.0, score)), 4)


def classify_turbulence(score: float) -> str:
    """Classify a turbulence score into a flow regime."""
    if score < 0.30:
        return "laminar"
    elif score < 0.65:
        return "transitional"
    else:
        return "turbulent"


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_turbulence(
    commits: Sequence[CommitRecord],
    window_minutes: int = 60,
) -> TurbulenceResult:
    """Compute turbulence metrics for a sequence of commits.

    Parameters
    ----------
    commits : sequence of CommitRecord
        The commits to analyze.  Should be at least 3 for meaningful results.
    window_minutes : int
        Size of the time window for burstiness calculation.

    Returns
    -------
    TurbulenceResult
        Complete turbulence analysis.
    """
    if not commits:
        return TurbulenceResult(
            turbulence_score=0.0,
            flow_regime="laminar",
            commit_count=0,
            window_minutes=window_minutes,
            details={"note": "no commits to analyze"},
        )

    burst = _burstiness(commits, window_minutes)
    interval = _interval_cv(commits)
    entropy = _direction_entropy(commits)
    churn = _author_churn(commits)
    volatility = _size_volatility(commits)
    reverts = _revert_ratio(commits)

    metrics = {
        "burstiness": burst,
        "interval_cv": interval,
        "direction_entropy": entropy,
        "author_churn": churn,
        "size_volatility": volatility,
        "revert_ratio": reverts,
    }

    score = _composite_score(metrics)
    regime = classify_turbulence(score)

    return TurbulenceResult(
        burstiness=round(burst, 4),
        interval_cv=round(interval, 4),
        direction_entropy=round(entropy, 4),
        author_churn=round(churn, 4),
        size_volatility=round(volatility, 4),
        revert_ratio=round(reverts, 4),
        turbulence_score=score,
        flow_regime=regime,
        commit_count=len(commits),
        window_minutes=window_minutes,
        details={
            "normalized_metrics": {
                k: round(_normalize_metric(k, v), 4) for k, v in metrics.items()
            },
            "weights": dict(_WEIGHTS),
        },
    )


# ---------------------------------------------------------------------------
# Area-level turbulence
# ---------------------------------------------------------------------------

def area_turbulence(
    commits_by_area: dict[str, Sequence[CommitRecord]],
    window_minutes: int = 60,
) -> dict[str, TurbulenceResult]:
    """Compute turbulence for each codebase area independently.

    Parameters
    ----------
    commits_by_area : dict mapping area name to its commits
    window_minutes : int

    Returns
    -------
    dict mapping area name to TurbulenceResult
    """
    return {
        area: compute_turbulence(commits, window_minutes)
        for area, commits in commits_by_area.items()
    }


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def turbulence_trend(snapshots: Sequence[float]) -> TurbulenceTrend:
    """Analyze turbulence scores over time using linear regression.

    Parameters
    ----------
    snapshots : sequence of float
        Turbulence scores from successive time windows, in chronological order.

    Returns
    -------
    TurbulenceTrend
    """
    n = len(snapshots)
    if n < 2:
        return TurbulenceTrend(
            direction="stable",
            slope=0.0,
            first_mean=snapshots[0] if snapshots else 0.0,
            last_mean=snapshots[-1] if snapshots else 0.0,
            delta=0.0,
            measurements=n,
            interpretation="insufficient data for trend analysis",
        )

    x_mean = (n - 1) / 2.0
    y_mean = sum(snapshots) / n
    num = sum((i - x_mean) * (snapshots[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    slope = num / den if den > 0 else 0.0

    first = snapshots[0]
    last = snapshots[-1]
    delta = last - first

    if slope > 0.02:
        direction = "increasing"
        interp = (
            "commit flow is becoming more erratic over time — "
            "bursts, scatter, or timing irregularity are growing"
        )
    elif slope < -0.02:
        direction = "decreasing"
        interp = (
            "commit flow is stabilizing — the repo is moving toward "
            "more predictable, laminar development patterns"
        )
    else:
        direction = "stable"
        interp = "turbulence level is holding steady"

    return TurbulenceTrend(
        direction=direction,
        slope=round(slope, 6),
        first_mean=round(first, 4),
        last_mean=round(last, 4),
        delta=round(delta, 4),
        measurements=n,
        interpretation=interp,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def turbulence_report(result: TurbulenceResult) -> str:
    """Generate a human-readable turbulence report."""
    lines = [
        f"Commits analyzed: {result.commit_count}",
        f"Window: {result.window_minutes} min",
        f"Turbulence: {result.turbulence_score:.3f} ({result.flow_regime})",
        f"  Burstiness:     {result.burstiness:.3f}",
        f"  Interval CV:    {result.interval_cv:.3f}",
        f"  Direction entropy: {result.direction_entropy:.3f}",
        f"  Author churn:   {result.author_churn:.3f}",
        f"  Size volatility: {result.size_volatility:.3f}",
        f"  Revert ratio:    {result.revert_ratio:.3f}",
    ]
    return "\n".join(lines)
