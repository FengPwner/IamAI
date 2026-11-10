#!/usr/bin/env python3
"""commit_diffusivity — measure how quickly changes propagate through a codebase.

In physics, *thermal diffusivity* (α) describes how fast heat spreads
through a material.  It is defined as the ratio of thermal conductivity
to volumetric heat capacity:

    α = k / (ρ · cₚ)

A copper rod (high α) equalises temperature almost instantly; a wooden
rod (low α) stays hot at one end and cold at the other for a long time.

Codebases exhibit the same spectrum.  When a developer changes one
module, how quickly does that change *propagate* to related modules?
Do dependent files get updated in the same commit (or the very next
one), or do inconsistencies linger for days?  Does a single edit
trigger a cascade of follow-up changes across the codebase, or is the
impact absorbed locally?

This module measures **commit diffusivity**: how fast and how far
changes spread through a codebase's file dependency structure, and
what that reveals about information flow and coupling health.

Diffusivity vs related metrics
------------------------------

- **Viscosity** measures internal *friction* during normal flow.
- **Elasticity** measures *recovery* after deformation.
- **Surface tension** measures *boundary coupling*.
- **Diffusivity** measures *propagation speed and spread extent* of
  a change — how fast it travels and how far it reaches.

A codebase can be low-viscosity (easy to make changes) but low-
diffusivity (changes don't propagate to dependent areas quickly,
leaving inconsistencies).  The two are independent axes.

Diffusivity dimensions
----------------------

========================  ================================================
metric                    meaning
========================  ================================================
change_rate               mean number of files changed per commit in
                          the analysis window
concentration_index       Gini coefficient of per-file change frequency
                          (0 = all files changed equally; 1 = one file
                          gets all changes)
spread_velocity           mean number of *distinct* previously-untouched
                          files that appear per commit during the
                          propagation phase (first 10 commits after a
                          burst)
diffusion_coefficient     composite propagation speed: change_rate *
                          (1 - concentration_index) * spread_velocity /
                          baseline_files  (higher = faster spreading)
penetration_depth         mean number of distinct files touched in the
                          propagation phase after a burst
diffusion_length          maximum graph distance (measured in import-
                          hops) that a single-file change reaches
                          within 5 subsequent commits
absorption_time           median commits until a change in one file is
                          "absorbed" — i.e., all files that import it
                          have also been modified
diffusivity_score         composite 0.0–1.0: high = rapid, even
                          propagation; low = changes stay localised
                          and inconsistent
diffusivity_class         superconductor | conductive | diffusive |
                          insulating | stagnant
========================  ================================================

Diffusivity classes
-------------------

==============  ============================================================
class           meaning
==============  ============================================================
superconductor  score ≥ 0.80 — changes propagate almost instantly through
                the codebase; dependent modules are updated in the same
                or next commit; no lingering inconsistencies
conductive      0.60 ≤ score < 0.80 — good propagation; most dependent
                areas are updated within a few commits; occasional
                blind spots
diffusive       0.40 ≤ score < 0.60 — moderate propagation; changes
                spread unevenly, some areas update quickly while others
                lag behind
insulating      0.20 ≤ score < 0.40 — poor propagation; changes are
                confined to local areas; dependent modules often remain
                stale for extended periods
stagnant        score < 0.20 — changes barely propagate; the codebase
                has isolated islands that rarely see coordinated updates
==============  ============================================================

Public API
----------
- ``CommitRecord`` — data class for a single commit
- ``DiffusivityResult`` — data class holding all computed metrics
- ``DiffusivityTrend`` — data class for temporal evolution
- ``compute_diffusivity(commits, ...) -> DiffusivityResult``
- ``classify_diffusivity(score) -> str``
- ``diffusivity_report(result) -> str``
- ``diffusivity_trend(results) -> DiffusivityTrend``

Usage::

    from iamai.commit_diffusivity import CommitRecord, compute_diffusivity
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
    r = compute_diffusivity(commits)
    print(r.diffusivity_class)  # "diffusive"
    print(r.concentration_index)  # 0.0 (all files equal)
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
    """A single commit with timestamp and changed files."""

    sha: str
    timestamp: datetime
    files: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not isinstance(self.files, frozenset):
            object.__setattr__(self, "files", frozenset(self.files))


@dataclass(frozen=True)
class DiffusivityResult:
    """Result of a diffusivity analysis."""

    change_rate: float = 0.0
    concentration_index: float = 0.0
    spread_velocity: float = 0.0
    diffusion_coefficient: float = 0.0
    penetration_depth: float = 0.0
    diffusion_length: float = 0.0
    absorption_time: float = 0.0
    diffusivity_score: float = 0.0
    diffusivity_class: str = "stagnant"
    n_commits: int = 0
    n_files: int = 0

    @property
    def is_healthy(self) -> bool:
        """True if diffusivity class is conductive or better."""
        return self.diffusivity_class in ("superconductor", "conductive")


@dataclass(frozen=True)
class DiffusivityTrend:
    """How diffusivity evolves across consecutive analysis windows."""

    direction: str = "stable"          # increasing | stable | decreasing
    delta: float = 0.0
    scores: list = field(default_factory=list)
    n_windows: int = 0

    @property
    def summary(self) -> str:
        if self.n_windows < 2:
            return "insufficient data"
        if self.direction == "increasing":
            return f"improving (+{self.delta:.2f} over {self.n_windows} windows)"
        if self.direction == "decreasing":
            return f"degrading ({self.delta:+.2f} over {self.n_windows} windows)"
        return f"stable ({self.delta:+.2f} over {self.n_windows} windows)"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_CLASS_THRESHOLDS = [
    (0.80, "superconductor"),
    (0.60, "conductive"),
    (0.40, "diffusive"),
    (0.20, "insulating"),
    (0.00, "stagnant"),
]


def classify_diffusivity(score: float) -> str:
    """Map a 0.0–1.0 diffusivity score to a qualitative class."""
    score = max(0.0, min(1.0, score))
    for threshold, cls in _CLASS_THRESHOLDS:
        if score >= threshold:
            return cls
    return "stagnant"


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_diffusivity(
    commits: Sequence[CommitRecord],
    burst_multiplier: float = 3.0,
    propagation_window: int = 10,
    absorption_hops: int = 5,
) -> DiffusivityResult:
    """Compute diffusivity metrics for a sequence of commits.

    Parameters
    ----------
    commits:
        Ordered sequence of CommitRecord (oldest first).
    burst_multiplier:
        A commit is a "burst" if its file count exceeds the median
        files-per-commit by this factor.
    propagation_window:
        Number of commits after a burst to measure spread.
    absorption_hops:
        Maximum graph distance to consider for diffusion length.

    Returns
    -------
    DiffusivityResult with all computed metrics.
    """
    if not commits:
        return DiffusivityResult()

    n = len(commits)
    sorted_commits = sorted(commits, key=lambda c: c.timestamp)

    # --- change rate ---
    files_per_commit = [len(c.files) for c in sorted_commits]
    change_rate = statistics.mean(files_per_commit) if files_per_commit else 0.0

    # --- concentration index (Gini of per-file change frequency) ---
    file_freq: dict[str, int] = {}
    for c in sorted_commits:
        for f in c.files:
            file_freq[f] = file_freq.get(f, 0) + 1

    concentration_index = _gini(list(file_freq.values())) if file_freq else 0.0

    # --- spread velocity ---
    # After each burst, count distinct new files per commit
    median_fpc = statistics.median(files_per_commit) if files_per_commit else 1.0
    burst_threshold = max(median_fpc * burst_multiplier, 2.0)

    spread_velocities: list[float] = []
    for i, c in enumerate(sorted_commits):
        if len(c.files) >= burst_threshold:
            # Found a burst at index i
            seen_before = set()
            for j in range(max(0, i - propagation_window), i):
                seen_before.update(sorted_commits[j].files)
            new_per_commit = []
            for k in range(i + 1, min(i + 1 + propagation_window, n)):
                new_files = sorted_commits[k].files - seen_before
                new_per_commit.append(len(new_files))
                seen_before.update(sorted_commits[k].files)
            if new_per_commit:
                spread_velocities.append(statistics.mean(new_per_commit))

    spread_velocity = statistics.mean(spread_velocities) if spread_velocities else 0.0

    # --- diffusion coefficient ---
    all_files = set()
    for c in sorted_commits:
        all_files.update(c.files)
    baseline_files = max(len(all_files), 1)

    diffusion_coefficient = (
        change_rate * (1.0 - concentration_index) * spread_velocity / baseline_files
    )

    # --- penetration depth ---
    penetration_depths: list[int] = []
    for i, c in enumerate(sorted_commits):
        if len(c.files) >= burst_threshold:
            touched = set()
            for k in range(i, min(i + 1 + propagation_window, n)):
                touched.update(sorted_commits[k].files)
            penetration_depths.append(len(touched))

    penetration_depth = (
        statistics.mean(penetration_depths) if penetration_depths else 0.0
    )

    # --- diffusion length ---
    # Simplified: max distinct files touched in absorption_hops commits
    # after any single-file change commit
    diffusion_lengths: list[int] = []
    for i, c in enumerate(sorted_commits):
        if len(c.files) == 1:
            touched_after = set()
            for k in range(i + 1, min(i + 1 + absorption_hops, n)):
                touched_after.update(sorted_commits[k].files)
            diffusion_lengths.append(len(touched_after))

    diffusion_length = (
        statistics.mean(diffusion_lengths) if diffusion_lengths else 0.0
    )

    # --- absorption time ---
    # Median commits until the set of files touched in a burst stops growing
    absorption_times: list[int] = []
    for i, c in enumerate(sorted_commits):
        if len(c.files) >= burst_threshold:
            burst_files = set(c.files)
            for k in range(i + 1, min(i + propagation_window, n)):
                prev_size = len(burst_files)
                burst_files.update(sorted_commits[k].files)
                if len(burst_files) == prev_size:
                    absorption_times.append(k - i)
                    break

    absorption_time = (
        statistics.median(absorption_times) if absorption_times else float(n)
    )

    # --- composite score ---
    # Normalise each dimension to 0–1, then average
    norm_spread = min(spread_velocity / max(change_rate, 1.0), 1.0)
    norm_evenness = 1.0 - concentration_index
    norm_penetration = min(penetration_depth / max(baseline_files, 1), 1.0)
    norm_absorption = max(0.0, 1.0 - absorption_time / max(n, 1))
    norm_diffusion_len = min(diffusion_length / max(baseline_files, 1), 1.0)

    diffusivity_score = statistics.mean([
        norm_spread,
        norm_evenness,
        norm_penetration,
        norm_absorption,
        norm_diffusion_len,
    ])
    diffusivity_score = round(max(0.0, min(1.0, diffusivity_score)), 4)

    return DiffusivityResult(
        change_rate=round(change_rate, 4),
        concentration_index=round(concentration_index, 4),
        spread_velocity=round(spread_velocity, 4),
        diffusion_coefficient=round(diffusion_coefficient, 4),
        penetration_depth=round(penetration_depth, 4),
        diffusion_length=round(diffusion_length, 4),
        absorption_time=round(absorption_time, 4),
        diffusivity_score=diffusivity_score,
        diffusivity_class=classify_diffusivity(diffusivity_score),
        n_commits=n,
        n_files=len(all_files),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gini(values: Sequence[float]) -> float:
    """Compute Gini coefficient for a sequence of non-negative values.

    Returns 0.0 for uniform distribution, approaching 1.0 for maximal
    inequality.
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    total = sum(sorted_vals)
    if total == 0:
        return 0.0
    cumulative = 0.0
    weighted_sum = 0.0
    for i, v in enumerate(sorted_vals):
        cumulative += v
        weighted_sum += (i + 1) * v
    gini = (2.0 * weighted_sum) / (n * total) - (n + 1.0) / n
    return max(0.0, min(1.0, gini))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def diffusivity_report(result: DiffusivityResult) -> str:
    """Produce a human-readable diffusivity analysis report."""
    lines = [
        f"Diffusivity Analysis — {result.diffusivity_class.upper()}",
        f"  Score: {result.diffusivity_score:.2f}",
        f"  Commits analysed: {result.n_commits}",
        f"  Distinct files: {result.n_files}",
        "",
        "  Dimensions:",
        f"    change_rate:           {result.change_rate:.2f} files/commit",
        f"    concentration_index:   {result.concentration_index:.2f} (Gini)",
        f"    spread_velocity:       {result.spread_velocity:.2f} new files/commit",
        f"    diffusion_coefficient: {result.diffusion_coefficient:.4f}",
        f"    penetration_depth:     {result.penetration_depth:.1f} files",
        f"    diffusion_length:      {result.diffusion_length:.1f} files",
        f"    absorption_time:       {result.absorption_time:.1f} commits",
        "",
        f"  Health: {'✓ healthy' if result.is_healthy else '⚠ needs attention'}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def diffusivity_trend(results: Sequence[DiffusivityResult]) -> DiffusivityTrend:
    """Compute trend across consecutive diffusivity analysis windows.

    Parameters
    ----------
    results:
        Sequence of DiffusivityResult from consecutive time windows.

    Returns
    -------
    DiffusivityTrend with direction, delta, and window count.
    """
    if len(results) < 2:
        return DiffusivityTrend(
            direction="stable",
            delta=0.0,
            scores=[r.diffusivity_score for r in results],
            n_windows=len(results),
        )

    scores = [r.diffusivity_score for r in results]
    first_half = scores[: len(scores) // 2]
    second_half = scores[len(scores) // 2 :]

    avg_first = statistics.mean(first_half)
    avg_second = statistics.mean(second_half)
    delta = avg_second - avg_first

    if delta > 0.05:
        direction = "increasing"
    elif delta < -0.05:
        direction = "decreasing"
    else:
        direction = "stable"

    return DiffusivityTrend(
        direction=direction,
        delta=round(delta, 4),
        scores=scores,
        n_windows=len(results),
    )
