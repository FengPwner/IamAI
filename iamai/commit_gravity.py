#!/usr/bin/env python3
"""commit_gravity — measure how much a commit pulls on its neighbours.

Newton taught us that every mass bends the space around it.  A commit
does the same to a codebase: it creates a gravitational field that
either draws nearby files into its orbit (callers need updating, tests
need adjusting, docs need catching up) or leaves the surrounding code
indifferent.

The *heavier* a commit — the more structural change it carries — the
larger its sphere of influence.  A one-line typo fix exerts almost no
gravity.  An API redesign pulls in dozens of callers across the next
dozen commits.

This module measures **commit gravity**: how much influence a commit
exerts on the commits that follow, and what the shape of that influence
reveals about the codebase's architecture.

Gravity dimensions
------------------

========================  ================================================
metric                    meaning
========================  ================================================
pull_count                number of subsequent commits (within the
                          analysis window) that touch at least one file
                          *co-located* with a file the source commit
                          touched (same top-level directory)
pull_ratio                pull_count / total subsequent commits
affected_areas            number of distinct top-level directories that
                          subsequent commits touched *because* they
                          overlap with the source's areas
reach_depth               maximum directory-depth overlap between source
                          files and subsequent-commit files (deeper =
                          more localised influence)
influence_hours           hours between source commit and the last
                          "pulled" commit (the edge of the gravity well)
gravity_score             composite 0.0–1.0: high = healthy pull (the
                          commit mattered and the codebase responded);
                          low = either zero pull (the commit was
                          inconsequential) or runaway pull (the commit
                          destabilised the codebase and spawned endless
                          fix-ups)
gravity_class             massive | strong | moderate | weak | negligible
========================  ================================================

Gravity classes
---------------

==============  ============================================================
class           meaning
==============  ============================================================
massive         score ≥ 0.80 — a structural change that reshaped nearby
                code; the codebase absorbed it across multiple commits
strong          0.60 ≤ score < 0.80 — significant influence, healthy
                follow-up
moderate        0.40 ≤ score < 0.60 — moderate pull, some areas responded
weak            0.20 ≤ score < 0.40 — minimal influence, codebase largely
                indifferent
negligible      score < 0.20 — no measurable pull; the commit landed
                without disturbing anything
==============  ============================================================

Public API
----------
- ``CommitInfo`` — data class for one commit's metadata
- ``GravityResult`` — data class holding all computed metrics
- ``GravityTrend`` — data class for how gravity evolves over time
- ``compute_gravity(source, subsequent, ...) -> GravityResult``
- ``classify_gravity(score) -> str``
- ``gravity_report(result) -> str``
- ``gravity_trend(results) -> GravityTrend``

Usage::

    from iamai.commit_gravity import CommitInfo, compute_gravity
    from datetime import datetime

    source = CommitInfo(
        sha="abc123",
        timestamp=datetime(2026, 11, 10, 10, 0),
        files={"iamai/foo.py", "tests/test_foo.py"},
    )
    subsequent = [
        CommitInfo(sha="def456",
                   timestamp=datetime(2026, 11, 10, 10, 15),
                   files={"iamai/foo.py", "iamai/bar.py"}),
        CommitInfo(sha="ghi789",
                   timestamp=datetime(2026, 11, 10, 11, 0),
                   files={"tests/test_bar.py", "docs/CHANGELOG.md"}),
        CommitInfo(sha="jkl012",
                   timestamp=datetime(2026, 11, 10, 12, 0),
                   files={"iamai/baz.py"}),
    ]
    r = compute_gravity(source, subsequent)
    print(r.gravity_class)  # "strong"
    print(r.pull_count)     # 3
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import FrozenSet, Optional, Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommitInfo:
    """Lightweight commit metadata for gravity analysis."""

    sha: str
    timestamp: datetime
    files: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not isinstance(self.files, frozenset):
            object.__setattr__(self, "files", frozenset(self.files))


@dataclass(frozen=True)
class GravityResult:
    """Computed gravity metrics for one source commit."""

    source_sha: str
    window_commits: int
    pull_count: int
    pull_ratio: float
    affected_areas: int
    reach_depth: int
    influence_hours: Optional[float]
    gravity_score: float
    gravity_class: str


@dataclass(frozen=True)
class GravityTrend:
    """How gravity scores evolve across a series of measurements."""

    direction: str          # increasing | stable | declining
    score_delta: float
    earliest_score: float
    latest_score: float
    sample_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _top_area(path: str) -> str:
    """Return the top-level directory of a file path."""
    parts = path.replace("\\", "/").split("/")
    return parts[0] if len(parts) > 1 else "."


def _area_set(files: FrozenSet[str]) -> FrozenSet[str]:
    """Return the set of top-level areas touched by a set of files."""
    return frozenset(_top_area(f) for f in files)


def _dir_depth(path: str) -> int:
    """Return the directory depth of a file path."""
    return path.replace("\\", "/").count("/")


def _max_depth_overlap(source_files: FrozenSet[str],
                       other_files: FrozenSet[str]) -> int:
    """Maximum directory-depth where source and other share a common prefix."""
    source_prefixes: set[str] = set()
    for f in source_files:
        parts = f.replace("\\", "/").split("/")
        for i in range(1, len(parts)):
            source_prefixes.add("/".join(parts[:i]))

    best = 0
    for f in other_files:
        parts = f.replace("\\", "/").split("/")
        for i in range(1, len(parts)):
            prefix = "/".join(parts[:i])
            if prefix in source_prefixes:
                best = max(best, i)
    return best


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_gravity(score: float) -> str:
    """Map a 0.0–1.0 score to a gravity class label."""
    if score >= 0.80:
        return "massive"
    if score >= 0.60:
        return "strong"
    if score >= 0.40:
        return "moderate"
    if score >= 0.20:
        return "weak"
    return "negligible"


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_gravity(
    source: CommitInfo,
    subsequent: Sequence[CommitInfo],
    window_hours: float = 72.0,
) -> GravityResult:
    """Compute the gravitational influence of *source* on later commits.

    Parameters
    ----------
    source:
        The commit whose gravity we are measuring.
    subsequent:
        Commits that came *after* the source (sorted ascending by time).
    window_hours:
        How far forward to look for pulled commits (default 72 h).
    """
    source_areas = _area_set(source.files)
    window_end = source.timestamp.timestamp() + window_hours * 3600

    # Filter to commits inside the analysis window
    in_window = [
        c for c in subsequent
        if source.timestamp < c.timestamp
        and c.timestamp.timestamp() <= window_end
    ]

    # "Pulled" commits: those touching at least one area the source touched
    pulled = [
        c for c in in_window
        if _area_set(c.files) & source_areas
    ]

    pull_count = len(pulled)
    pull_ratio = pull_count / len(in_window) if in_window else 0.0

    # Affected areas: distinct top-level dirs in pulled commits that
    # overlap with source areas.
    pulled_areas: set[str] = set()
    for c in pulled:
        pulled_areas |= _area_set(c.files) & source_areas
    affected_areas = len(pulled_areas)

    # Reach depth: maximum directory-depth overlap across all pulled commits
    reach_depth = 0
    for c in pulled:
        reach_depth = max(reach_depth,
                          _max_depth_overlap(source.files, c.files))

    # Influence hours: time from source to last pulled commit
    if pulled:
        last_ts = max(c.timestamp.timestamp() for c in pulled)
        influence_hours = (last_ts - source.timestamp.timestamp()) / 3600.0
    else:
        influence_hours = None

    # --- Composite score ---
    # Three sub-scores, weighted:
    #
    # 1. Pull score (0–1): What fraction of subsequent commits were pulled?
    #    Optimal range: 0.2–0.6 (some pull, not everything).
    if pull_ratio <= 0.0:
        pull_score = 0.0
    elif pull_ratio <= 0.6:
        pull_score = pull_ratio / 0.6
    else:
        # Past 0.6 the pull is so strong it may indicate destabilisation.
        pull_score = max(0.4, 1.0 - (pull_ratio - 0.6) * 1.5)

    # 2. Spread score (0–1): How many distinct areas responded?
    #    More areas = broader structural influence.
    max_possible_areas = max(len(source_areas), 1)
    spread_score = min(1.0, affected_areas / max_possible_areas)

    # 3. Depth score (0–1): How deeply did the influence penetrate?
    #    Deeper overlap means the pull reached into specifics, not just
    #    surface-level directory membership.
    depth_score = min(1.0, reach_depth / 3.0)  # depth 3 = full score

    gravity_score = (pull_score * 0.4 + spread_score * 0.3 +
                     depth_score * 0.3)
    gravity_score = round(max(0.0, min(1.0, gravity_score)), 4)
    gravity_class = classify_gravity(gravity_score)

    return GravityResult(
        source_sha=source.sha,
        window_commits=len(in_window),
        pull_count=pull_count,
        pull_ratio=round(pull_ratio, 4),
        affected_areas=affected_areas,
        reach_depth=reach_depth,
        influence_hours=round(influence_hours, 2)
        if influence_hours is not None else None,
        gravity_score=gravity_score,
        gravity_class=gravity_class,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def gravity_report(result: GravityResult) -> str:
    """Human-readable summary of a gravity analysis."""
    lines = [
        f"Gravity analysis for {result.source_sha[:12]}",
        f"  class:             {result.gravity_class}",
        f"  score:             {result.gravity_score:.2f}",
        f"  window commits:    {result.window_commits}",
        f"  pull count:        {result.pull_count}",
        f"  pull ratio:        {result.pull_ratio:.2%}",
        f"  affected areas:    {result.affected_areas}",
        f"  reach depth:       {result.reach_depth}",
    ]
    if result.influence_hours is not None:
        lines.append(f"  influence span:    {result.influence_hours:.1f}h")
    else:
        lines.append("  influence span:    (none)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def gravity_trend(results: Sequence[GravityResult]) -> GravityTrend:
    """Classify how gravity scores evolve over a series of measurements."""
    if not results:
        return GravityTrend(
            direction="stable",
            score_delta=0.0,
            earliest_score=0.0,
            latest_score=0.0,
            sample_count=0,
        )

    scores = [r.gravity_score for r in results]
    earliest = scores[0]
    latest = scores[-1]
    delta = latest - earliest

    if len(scores) < 2:
        direction = "stable"
    elif delta > 0.05:
        direction = "increasing"
    elif delta < -0.05:
        direction = "declining"
    else:
        direction = "stable"

    return GravityTrend(
        direction=direction,
        score_delta=round(delta, 4),
        earliest_score=earliest,
        latest_score=latest,
        sample_count=len(scores),
    )
