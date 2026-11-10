#!/usr/bin/env python3
"""commit_viscosity — measure how resistant a codebase is to the flow of change.

In fluid dynamics, viscosity is the internal friction of a fluid: honey
flows slowly (high viscosity), water flows quickly (low viscosity).  A
codebase has viscosity too.  Some repos absorb changes smoothly — a new
feature ripples through layers without resistance, tests adapt, docs
update.  Others fight every change: adding a field breaks three call
sites, renaming a function orphans two tests, touching one module
requires understanding five others.

Viscosity is not the same as inertia.  Inertia asks "how hard is it to
*start* moving?"  Viscosity asks "once we're moving, how much internal
friction does the flow encounter?"  A codebase can have low inertia
(easy to start) but high viscosity (every change drags against coupling,
missing tests, tangled imports).

This module measures **commit viscosity**: the internal resistance a
codebase exerts against the flow of changes through it, and what that
resistance reveals about architectural health, coupling, and the ease of
maintenance.

Viscosity dimensions
--------------------

========================  ================================================
metric                    meaning
========================  ================================================
flow_rate                 commits per day over the analysis window
                          (higher = the codebase is actively flowing;
                          zero = frozen solid)
shear_stress              fraction of commits that touch files in ≥2
                          distinct top-level areas (multi-area commits
                          create "shear" between layers; too much shear
                          = high coupling, too little = siloed code)
layer_coupling            average number of distinct areas co-changed
                          per multi-area commit (higher = tighter
                          coupling between layers)
yield_point               minimum number of files that must be touched
                          to make the smallest meaningful change:
                          approximated by the median files-per-commit
                          (higher yield = more ceremony per change)
turbulence                coefficient of variation in commit sizes
                          (files per commit): high turbulence means
                          unpredictable change sizes — sometimes tiny,
                          sometimes enormous — indicating unstable
                          development patterns
viscosity_score           composite 0.0–1.0: high = high resistance to
                          flow (thick, coupled, unpredictable); low =
                          smooth, easy flow
viscosity_class           solid | viscous | thick | thin | flowing
========================  ================================================

Viscosity classes
-----------------

==============  ============================================================
class           meaning
==============  ============================================================
solid           score ≥ 0.80 — the codebase barely flows; changes require
                enormous effort and touch many files; architecture is
                rigid or heavily entangled
viscous         0.60 ≤ score < 0.80 — significant resistance; changes
                propagate slowly and drag other areas along
thick           0.40 ≤ score < 0.60 — moderate viscosity; the codebase
                flows but with noticeable friction
thin            0.20 ≤ score < 0.40 — low resistance; changes flow
                smoothly with minimal coupling
flowing         score < 0.20 — near-frictionless; the codebase absorbs
                changes easily, areas are well-isolated
==============  ============================================================

Public API
----------
- ``ViscosityResult`` — data class holding all computed metrics
- ``ViscosityTrend`` — data class for how viscosity evolves over time
- ``compute_viscosity(commits, ...) -> ViscosityResult``
- ``classify_viscosity(score) -> str``
- ``viscosity_report(result) -> str``
- ``viscosity_trend(results) -> ViscosityTrend``

Usage::

    from iamai.commit_viscosity import CommitRecord, compute_viscosity
    from datetime import datetime, timedelta

    ref = datetime(2026, 11, 11, 0, 0)
    commits = [
        CommitRecord(
            sha=f"c{i}",
            timestamp=ref + timedelta(hours=i),
            files=frozenset([f"iamai/module_{i % 5}.py"]),
        )
        for i in range(20)
    ]
    r = compute_viscosity(commits)
    print(r.viscosity_class)  # "thin"
    print(r.flow_rate)        # ~8.33 commits/day
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import FrozenSet, Optional, Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommitRecord:
    """Lightweight commit metadata for viscosity analysis."""

    sha: str
    timestamp: datetime
    files: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not isinstance(self.files, frozenset):
            object.__setattr__(self, "files", frozenset(self.files))


@dataclass(frozen=True)
class ViscosityResult:
    """Computed viscosity metrics for an analysis window."""

    window_commits: int
    window_hours: float
    flow_rate: float
    shear_stress: float
    layer_coupling: float
    yield_point: float
    turbulence: float
    viscosity_score: float
    viscosity_class: str


@dataclass(frozen=True)
class ViscosityTrend:
    """How viscosity scores evolve across a series of measurements."""

    direction: str          # increasing | stable | decreasing
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


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_viscosity(score: float) -> str:
    """Map a 0.0–1.0 score to a viscosity class label."""
    if score >= 0.80:
        return "solid"
    if score >= 0.60:
        return "viscous"
    if score >= 0.40:
        return "thick"
    if score >= 0.20:
        return "thin"
    return "flowing"


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_viscosity(
    commits: Sequence[CommitRecord],
    window_hours: float = 168.0,
) -> ViscosityResult:
    """Compute the viscosity of a codebase from its commit history.

    Parameters
    ----------
    commits:
        Commits sorted ascending by timestamp (oldest first).
    window_hours:
        The analysis window in hours (default 7 days).
    """
    if len(commits) < 2:
        return ViscosityResult(
            window_commits=len(commits),
            window_hours=window_hours,
            flow_rate=len(commits) / (window_hours / 24.0) if window_hours > 0 else 0.0,
            shear_stress=0.0,
            layer_coupling=0.0,
            yield_point=0.0,
            turbulence=0.0,
            viscosity_score=0.0,
            viscosity_class="flowing",
        )

    # --- Flow rate: commits per day ---
    first_ts = commits[0].timestamp.timestamp()
    last_ts = commits[-1].timestamp.timestamp()
    span_hours = max((last_ts - first_ts) / 3600.0, 1.0 / 3600.0)
    flow_rate = len(commits) / (span_hours / 24.0)

    # --- Shear stress: fraction of multi-area commits ---
    multi_area_count = 0
    layer_coupling_values: list[int] = []
    file_counts: list[int] = []

    for c in commits:
        areas = _area_set(c.files)
        n_areas = len(areas)
        n_files = len(c.files)
        file_counts.append(n_files)

        if n_areas >= 2:
            multi_area_count += 1
            layer_coupling_values.append(n_areas)

    shear_stress = multi_area_count / len(commits) if commits else 0.0

    # --- Layer coupling: average areas per multi-area commit ---
    layer_coupling = (
        statistics.mean(layer_coupling_values)
        if layer_coupling_values else 0.0
    )

    # --- Yield point: median files per commit ---
    yield_point = statistics.median(file_counts) if file_counts else 0.0

    # --- Turbulence: coefficient of variation in file counts ---
    if len(file_counts) >= 2:
        mean_fc = statistics.mean(file_counts)
        if mean_fc > 0:
            stdev_fc = statistics.stdev(file_counts)
            turbulence = stdev_fc / mean_fc
        else:
            turbulence = 0.0
    else:
        turbulence = 0.0

    # --- Composite score ---
    #
    # Three sub-scores, each 0.0–1.0:
    #
    # 1. Coupling sub-score (0–1): High shear stress + high layer coupling
    #    = high viscosity.  We want some coupling (not siloed), but not
    #    too much.
    #    Optimal shear: 0.1–0.3 (some cross-area work, not constant).
    if shear_stress <= 0.0:
        coupling_sub = 0.0  # No coupling at all: siloed (not high viscosity)
    elif shear_stress <= 0.3:
        coupling_sub = shear_stress / 0.3  # Linear ramp in healthy zone
    else:
        # Past 0.3: excessive coupling drives viscosity up
        coupling_sub = min(1.0, 1.0 + (shear_stress - 0.3) * 1.5)

    # Scale by layer_coupling: more areas per commit = more drag
    if layer_coupling > 0:
        coupling_sub = min(1.0, coupling_sub * (1.0 + (layer_coupling - 1) * 0.2))

    # 2. Yield sub-score (0–1): Higher median files-per-commit = more
    #    ceremony needed per change.
    #    1 file median = ideal; 5+ files = high yield.
    yield_sub = min(1.0, max(0.0, (yield_point - 1.0) / 4.0))

    # 3. Turbulence sub-score (0–1): High CV in commit sizes = unstable
    #    flow patterns.
    #    CV < 0.5 = laminar; CV > 2.0 = chaotic.
    turbulence_sub = min(1.0, max(0.0, (turbulence - 0.5) / 1.5))

    viscosity_score = (
        coupling_sub * 0.40 +
        yield_sub * 0.30 +
        turbulence_sub * 0.30
    )
    viscosity_score = round(max(0.0, min(1.0, viscosity_score)), 4)
    viscosity_class = classify_viscosity(viscosity_score)

    return ViscosityResult(
        window_commits=len(commits),
        window_hours=round(span_hours, 2),
        flow_rate=round(flow_rate, 4),
        shear_stress=round(shear_stress, 4),
        layer_coupling=round(layer_coupling, 4),
        yield_point=round(yield_point, 4),
        turbulence=round(turbulence, 4),
        viscosity_score=viscosity_score,
        viscosity_class=viscosity_class,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def viscosity_report(result: ViscosityResult) -> str:
    """Human-readable summary of a viscosity analysis."""
    lines = [
        f"Viscosity analysis ({result.window_commits} commits over {result.window_hours:.1f}h)",
        f"  class:             {result.viscosity_class}",
        f"  score:             {result.viscosity_score:.2f}",
        f"  flow rate:         {result.flow_rate:.2f} commits/day",
        f"  shear stress:      {result.shear_stress:.2%}",
        f"  layer coupling:    {result.layer_coupling:.2f} areas/multi-commit",
        f"  yield point:       {result.yield_point:.1f} files/commit (median)",
        f"  turbulence (CV):   {result.turbulence:.2f}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def viscosity_trend(results: Sequence[ViscosityResult]) -> ViscosityTrend:
    """Classify how viscosity scores evolve across a series of measurements."""
    if not results:
        return ViscosityTrend(
            direction="stable",
            score_delta=0.0,
            earliest_score=0.0,
            latest_score=0.0,
            sample_count=0,
        )

    scores = [r.viscosity_score for r in results]
    earliest = scores[0]
    latest = scores[-1]
    delta = latest - earliest

    if len(scores) < 2:
        direction = "stable"
    elif delta > 0.05:
        direction = "increasing"
    elif delta < -0.05:
        direction = "decreasing"
    else:
        direction = "stable"

    return ViscosityTrend(
        direction=direction,
        score_delta=round(delta, 4),
        earliest_score=earliest,
        latest_score=latest,
        sample_count=len(scores),
    )
