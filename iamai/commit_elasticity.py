#!/usr/bin/env python3
"""commit_elasticity — measure how well a codebase recovers from disruptive changes.

In physics, elasticity is the ability of a body to resist a distorting
influence and return to its original size and shape when the deforming
force is removed.  A rubber band snaps back instantly; a lump of clay
stays deformed forever.

Codebases experience the same spectrum.  A large refactor, a sudden
influx of new files, or a sweeping API rename is a *disruptive change*
— a force that deforms the normal commit pattern.  Some repos bounce
back within a few commits: follow-up fixes land, tests get updated,
docs catch up, and the rhythm returns to baseline.  Others stay
deformed: the disruption triggers weeks of cleanup commits, abandoned
test stubs linger, and the codebase never quite returns to its
pre-disruption equilibrium.

This module measures **commit elasticity**: the ability of a codebase
to absorb disruptive changes and return to steady-state commit patterns,
and what that recovery (or lack thereof) reveals about architectural
resilience.

Elasticity vs related metrics
-----------------------------

- **Viscosity** measures internal friction during normal flow.
- **Inertia** measures resistance to *starting* motion.
- **Elasticity** measures *recovery after deformation* — how quickly
  and completely the system returns to equilibrium after a shock.

A codebase can be low-viscosity (flows easily) but inelastic (doesn't
recover from shocks).  The two are independent axes of health.

Elasticity dimensions
---------------------

========================  ================================================
metric                    meaning
========================  ================================================
baseline_files            median files per commit during normal operation
                          (the equilibrium state)
disruption_threshold      files-per-commit value above which a commit is
                          considered disruptive (baseline * multiplier)
disruption_count          number of disruptive commits in the window
disruption_magnitude      mean ratio of files-in-disruption to baseline
                          (higher = bigger shocks relative to normal)
recovery_latency          median number of commits after a disruption
                          before files-per-commit returns to within
                          1.5x of baseline (lower = faster recovery)
rebound_ratio             fraction of disruptions after which the
                          codebase returns to baseline within
                          ``recovery_window`` commits
                          (1.0 = always recovers; 0.0 = never recovers)
plastic_deformation       fraction of file areas touched during
                          disruptions that continue to see elevated
                          activity (>2x baseline rate) for the
                          remainder of the window
damping_coefficient       how quickly post-disruption oscillations
                          decay: computed from the exponential decay
                          rate of files-per-commit after each
                          disruption (higher = faster settling)
elasticity_score          composite 0.0–1.0: high = elastic (fast,
                          complete recovery); low = plastic (slow or
                          no recovery, permanent deformation)
elasticity_class          rubbery | resilient | springy | stiff | brittle
========================  ================================================

Elasticity classes
------------------

==============  ============================================================
class           meaning
==============  ============================================================
rubbery         score ≥ 0.80 — the codebase snaps back almost immediately
                after disruptions; areas absorb shocks and stabilize
resilient       0.60 ≤ score < 0.80 — good recovery with minor lingering
                effects; disruptions are absorbed within a few commits
springy         0.40 ≤ score < 0.60 — moderate recovery; the codebase
                eventually stabilizes but oscillates for several commits
stiff           0.20 ≤ score < 0.40 — slow recovery; disruptions leave
                lasting deformation and trigger extended cleanup chains
brittle         score < 0.20 — the codebase fractures under disruption;
                areas never fully recover, accumulating permanent debt
==============  ============================================================

Public API
----------
- ``ElasticityResult`` — data class holding all computed metrics
- ``ElasticityTrend`` — data class for how elasticity evolves over time
- ``compute_elasticity(commits, ...) -> ElasticityResult``
- ``classify_elasticity(score) -> str``
- ``elasticity_report(result) -> str``
- ``elasticity_trend(results) -> ElasticityTrend``

Usage::

    from iamai.commit_elasticity import CommitRecord, compute_elasticity
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
    r = compute_elasticity(commits)
    print(r.elasticity_class)  # "springy"
    print(r.rebound_ratio)    # 0.5
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
    """Lightweight commit metadata for elasticity analysis."""

    sha: str
    timestamp: datetime
    files: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not isinstance(self.files, frozenset):
            object.__setattr__(self, "files", frozenset(self.files))


@dataclass(frozen=True)
class ElasticityResult:
    """Computed elasticity metrics for an analysis window."""

    window_commits: int
    window_hours: float
    baseline_files: float
    disruption_threshold: float
    disruption_count: int
    disruption_magnitude: float
    recovery_latency: float
    rebound_ratio: float
    plastic_deformation: float
    damping_coefficient: float
    elasticity_score: float
    elasticity_class: str


@dataclass(frozen=True)
class ElasticityTrend:
    """How elasticity scores evolve across a series of measurements."""

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

def classify_elasticity(score: float) -> str:
    """Map a 0.0–1.0 score to an elasticity class label."""
    if score >= 0.80:
        return "rubbery"
    if score >= 0.60:
        return "resilient"
    if score >= 0.40:
        return "springy"
    if score >= 0.20:
        return "stiff"
    return "brittle"


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_elasticity(
    commits: Sequence[CommitRecord],
    disruption_multiplier: float = 3.0,
    recovery_window: int = 10,
    window_hours: float = 168.0,
) -> ElasticityResult:
    """Compute the elasticity of a codebase from its commit history.

    Parameters
    ----------
    commits:
        Commits sorted ascending by timestamp (oldest first).
    disruption_multiplier:
        A commit is disruptive if its file count exceeds
        baseline * this multiplier.  Default 3x.
    recovery_window:
        Number of commits after a disruption within which recovery
        is expected.  Default 10.
    window_hours:
        The analysis window in hours (default 7 days).
    """
    if len(commits) < 2:
        return ElasticityResult(
            window_commits=len(commits),
            window_hours=window_hours,
            baseline_files=0.0,
            disruption_threshold=0.0,
            disruption_count=0,
            disruption_magnitude=0.0,
            recovery_latency=0.0,
            rebound_ratio=0.0,
            plastic_deformation=0.0,
            damping_coefficient=0.0,
            elasticity_score=0.0,
            elasticity_class="brittle",
        )

    # --- File counts per commit ---
    file_counts = [len(c.files) for c in commits]

    # --- Baseline: median files per commit ---
    baseline_files = statistics.median(file_counts)
    if baseline_files < 1:
        baseline_files = 1.0

    # --- Disruption threshold ---
    disruption_threshold = baseline_files * disruption_multiplier

    # --- Identify disruptions ---
    disruption_indices = [
        i for i, fc in enumerate(file_counts)
        if fc >= disruption_threshold
    ]
    disruption_count = len(disruption_indices)

    # --- Disruption magnitude ---
    if disruption_indices:
        disruption_magnitude = statistics.mean(
            file_counts[i] / baseline_files for i in disruption_indices
        )
    else:
        disruption_magnitude = 0.0

    # --- Recovery latency and rebound ratio ---
    recovery_latencies: list[int] = []
    rebounded = 0

    for di in disruption_indices:
        # Look at commits after this disruption
        recovered = False
        for offset in range(1, recovery_window + 1):
            idx = di + offset
            if idx >= len(file_counts):
                break
            if file_counts[idx] <= baseline_files * 1.5:
                recovery_latencies.append(offset)
                recovered = True
                break
        if recovered:
            rebounded += 1

    recovery_latency = (
        statistics.median(recovery_latencies)
        if recovery_latencies else 0.0
    )
    rebound_ratio = (
        rebounded / disruption_count
        if disruption_count > 0 else 0.0
    )

    # --- Plastic deformation ---
    # For each disruption, check if the areas it touched continue to
    # see elevated activity (>2x their baseline rate) for the rest
    # of the window.
    if disruption_count > 0 and len(commits) > 1:
        # Compute baseline area frequency (areas per commit)
        all_areas: dict[str, int] = {}
        for c in commits:
            for a in _area_set(c.files):
                all_areas[a] = all_areas.get(a, 0) + 1
        baseline_area_freq = {
            a: count / len(commits) for a, count in all_areas.items()
        }

        deformed_count = 0
        total_disruption_areas = 0

        for di in disruption_indices:
            disrupted_areas = _area_set(commits[di].files)
            remaining = commits[di + 1:]
            if not remaining:
                continue

            for area in disrupted_areas:
                total_disruption_areas += 1
                baseline_rate = baseline_area_freq.get(area, 0.0)
                if baseline_rate <= 0:
                    # New area introduced by disruption
                    post_count = sum(
                        1 for c in remaining if area in _area_set(c.files)
                    )
                    post_rate = post_count / len(remaining)
                    if post_rate > 0.3:
                        # Significant ongoing activity in a new area
                        deformed_count += 1
                else:
                    post_count = sum(
                        1 for c in remaining if area in _area_set(c.files)
                    )
                    post_rate = post_count / len(remaining)
                    if post_rate > baseline_rate * 2.0:
                        deformed_count += 1

        plastic_deformation = (
            deformed_count / total_disruption_areas
            if total_disruption_areas > 0 else 0.0
        )
    else:
        plastic_deformation = 0.0

    # --- Damping coefficient ---
    # After each disruption, measure how quickly file counts decay
    # back to baseline.  Model as exponential decay:
    #   files(t) = baseline + (peak - baseline) * e^(-lambda * t)
    # Solve for lambda (damping coefficient) via least-squares on
    # log-transformed residuals.
    damping_values: list[float] = []

    for di in disruption_indices:
        peak = file_counts[di]
        if peak <= baseline_files:
            continue

        residuals: list[float] = []
        for offset in range(1, min(recovery_window + 1, len(file_counts) - di)):
            idx = di + offset
            residual = max(0.0, file_counts[idx] - baseline_files)
            residuals.append(residual)

        if len(residuals) < 2:
            continue

        # Estimate decay rate from log of residuals
        initial_residual = max(residuals[0], 0.01)
        log_residuals = [
            math.log(max(r, 0.01) / initial_residual)
            for r in residuals
        ]

        # Simple linear regression: log(r) = -lambda * t
        n = len(log_residuals)
        t_values = list(range(1, n + 1))
        sum_t = sum(t_values)
        sum_log = sum(log_residuals)
        sum_t_log = sum(t * l for t, l in zip(t_values, log_residuals))
        sum_t2 = sum(t * t for t in t_values)

        denom = n * sum_t2 - sum_t * sum_t
        if abs(denom) > 1e-10:
            slope = (n * sum_t_log - sum_t * sum_log) / denom
            # slope should be negative for decay; lambda = -slope
            lam = max(0.0, -slope)
            damping_values.append(lam)

    damping_coefficient = (
        statistics.mean(damping_values)
        if damping_values else 0.0
    )

    # --- Composite score ---
    #
    # Four sub-scores, each 0.0–1.0:
    #
    # 1. Rebound sub-score: How often the codebase recovers.
    #    rebound_ratio directly maps to score.
    rebound_sub = rebound_ratio

    # 2. Latency sub-score: How fast recovery happens.
    #    1 commit = perfect; recovery_window commits = poor.
    if recovery_latencies:
        latency_sub = max(0.0, 1.0 - (recovery_latency - 1.0) / (recovery_window - 1.0))
    else:
        # No disruptions = no recovery needed = neutral
        latency_sub = 1.0 if disruption_count == 0 else 0.0

    # 3. Deformation sub-score: Lower plastic deformation = better.
    deformation_sub = 1.0 - plastic_deformation

    # 4. Damping sub-score: Higher damping = faster settling.
    #    lambda > 1.0 = fast decay; lambda < 0.1 = very slow.
    if damping_values:
        damping_sub = min(1.0, damping_coefficient / 1.0)
    else:
        damping_sub = 1.0 if disruption_count == 0 else 0.0

    elasticity_score = (
        rebound_sub * 0.30 +
        latency_sub * 0.25 +
        deformation_sub * 0.25 +
        damping_sub * 0.20
    )
    elasticity_score = round(max(0.0, min(1.0, elasticity_score)), 4)
    elasticity_class = classify_elasticity(elasticity_score)

    # --- Time span ---
    first_ts = commits[0].timestamp.timestamp()
    last_ts = commits[-1].timestamp.timestamp()
    span_hours = max((last_ts - first_ts) / 3600.0, 1.0 / 3600.0)

    return ElasticityResult(
        window_commits=len(commits),
        window_hours=round(span_hours, 2),
        baseline_files=round(baseline_files, 4),
        disruption_threshold=round(disruption_threshold, 4),
        disruption_count=disruption_count,
        disruption_magnitude=round(disruption_magnitude, 4),
        recovery_latency=round(recovery_latency, 4),
        rebound_ratio=round(rebound_ratio, 4),
        plastic_deformation=round(plastic_deformation, 4),
        damping_coefficient=round(damping_coefficient, 4),
        elasticity_score=elasticity_score,
        elasticity_class=elasticity_class,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def elasticity_report(result: ElasticityResult) -> str:
    """Human-readable summary of an elasticity analysis."""
    lines = [
        f"Elasticity analysis ({result.window_commits} commits over {result.window_hours:.1f}h)",
        f"  class:               {result.elasticity_class}",
        f"  score:               {result.elasticity_score:.2f}",
        f"  baseline files:      {result.baseline_files:.1f} files/commit (median)",
        f"  disruption threshold:{result.disruption_threshold:.1f} files",
        f"  disruptions found:   {result.disruption_count}",
        f"  disruption magnitude:{result.disruption_magnitude:.2f}x baseline",
        f"  recovery latency:    {result.recovery_latency:.1f} commits (median)",
        f"  rebound ratio:       {result.rebound_ratio:.2%}",
        f"  plastic deformation: {result.plastic_deformation:.2%}",
        f"  damping coefficient: {result.damping_coefficient:.3f}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def elasticity_trend(results: Sequence[ElasticityResult]) -> ElasticityTrend:
    """Classify how elasticity scores evolve across a series of measurements."""
    if not results:
        return ElasticityTrend(
            direction="stable",
            score_delta=0.0,
            earliest_score=0.0,
            latest_score=0.0,
            sample_count=0,
        )

    scores = [r.elasticity_score for r in results]
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

    return ElasticityTrend(
        direction=direction,
        score_delta=round(delta, 4),
        earliest_score=earliest,
        latest_score=latest,
        sample_count=len(scores),
    )
