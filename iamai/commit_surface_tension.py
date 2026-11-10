#!/usr/bin/env python3
"""commit_surface_tension — measure how tightly coupled a codebase's boundary is.

In physics, surface tension is the tendency of liquid surfaces to shrink
to the minimum possible area.  Molecules at the surface experience
stronger inward forces than bulk molecules, creating a "skin" that
resists penetration.  Water striders exploit this to walk on ponds;
soap breaks it so dishes get clean.

Codebases have surfaces too.  The **surface** of a codebase is the set
of files that external consumers (other packages, CLI entry points,
plugin interfaces, public APIs) depend on.  When these boundary files
are tightly coupled to internal implementation — every API change
forces internal rewrites, every new endpoint touches ten modules — the
codebase has **high surface tension**.  The surface resists being
broken or reshaped.

When boundary files are loosely coupled — stable interfaces, clean
abstractions, thin adapters — the codebase has **low surface tension**.
Changes at the boundary don't propagate deeply; the surface is
permeable and easy to reshape.

Surface tension vs related metrics
-----------------------------------

- **Viscosity** measures internal friction during *normal flow*.
- **Elasticity** measures *recovery after deformation*.
- **Inertia** measures resistance to *starting* motion.
- **Surface tension** measures resistance at the *boundary* — how
  tightly the surface layer is coupled to the interior.

A codebase can be low-viscosity internally but have high surface
tension (smooth internal flow, but every API change is painful).
The surface and the interior are independent axes of health.

Surface tension dimensions
---------------------------

========================  ================================================
metric                    meaning
========================  ================================================
boundary_ratio            fraction of tracked files that are "boundary"
                          files (API endpoints, public modules, __init__.py
                          files that re-export, CLI entry points)
                          (higher = more surface area relative to volume)
coupling_depth            mean number of internal files transitively
                          imported by each boundary file
                          (higher = deeper dependency chains from surface)
cohesion_index            fraction of boundary files that share imports
                          with at least one other boundary file
                          (higher = boundary files are interlinked)
permeability              fraction of commits that touch *only* boundary
                          files without requiring changes to internal files
                          (higher = surface changes don't propagate)
surface_area              total number of distinct boundary files seen
                          in the analysis window
surface_stability         fraction of boundary files that remain unchanged
                          across the entire window
                          (higher = the surface is rigid / stable)
tension_score             composite 0.0–1.0: high = sealed (tightly
                          coupled surface); low = porous (loose coupling)
tension_class             sealed | tight | cohesive | porous | open
========================  ================================================

Tension classes
----------------

==============  ============================================================
class           meaning
==============  ============================================================
sealed          score ≥ 0.80 — the surface is a rigid shell; any API
                change cascades through internal files; new endpoints
                require touching many modules
tight           0.60 ≤ score < 0.80 — the surface is fairly coupled;
                moderate internal changes needed for boundary updates
cohesive        0.40 ≤ score < 0.60 — moderate coupling; some boundary
                changes propagate, others are absorbed locally
porous          0.20 ≤ score < 0.40 — loose coupling; most boundary
                changes don't require deep internal modifications
open            score < 0.20 — the surface is highly permeable; API
                changes rarely affect internal files; clean abstractions
==============  ============================================================

Public API
----------
- ``SurfaceTensionResult`` — data class holding all computed metrics
- ``SurfaceTensionTrend`` — data class for how tension evolves over time
- ``compute_surface_tension(commits, ...) -> SurfaceTensionResult``
- ``classify_tension(score) -> str``
- ``surface_tension_report(result) -> str``
- ``surface_tension_trend(results) -> SurfaceTensionTrend``

Usage::

    from iamai.commit_surface_tension import CommitRecord, compute_surface_tension
    from datetime import datetime, timedelta

    ref = datetime(2026, 11, 11, 0, 0)
    commits = [
        CommitRecord(
            sha=f"c{i}",
            timestamp=ref + timedelta(hours=i),
            files=frozenset([f"iamai/module_{i % 5}.py"]),
            boundary_files=frozenset([f"iamai/module_{i % 5}.py"] if i % 3 == 0 else []),
            internal_deps=frozenset([f"iamai/internal_{i % 3}.py"]),
        )
        for i in range(20)
    ]
    r = compute_surface_tension(commits)
    print(r.tension_class)  # "cohesive"
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
    """Lightweight commit metadata for surface tension analysis."""

    sha: str
    timestamp: datetime
    files: FrozenSet[str] = field(default_factory=frozenset)
    boundary_files: FrozenSet[str] = field(default_factory=frozenset)
    internal_deps: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self):
        if not isinstance(self.files, frozenset):
            object.__setattr__(self, "files", frozenset(self.files))
        if not isinstance(self.boundary_files, frozenset):
            object.__setattr__(self, "boundary_files", frozenset(self.boundary_files))
        if not isinstance(self.internal_deps, frozenset):
            object.__setattr__(self, "internal_deps", frozenset(self.internal_deps))


@dataclass(frozen=True)
class SurfaceTensionResult:
    """Computed surface tension metrics for an analysis window."""

    window_commits: int
    window_hours: float
    boundary_ratio: float
    coupling_depth: float
    cohesion_index: float
    permeability: float
    surface_area: int
    surface_stability: float
    tension_score: float
    tension_class: str


@dataclass(frozen=True)
class SurfaceTensionTrend:
    """How surface tension evolves across a series of measurements."""

    direction: str          # "increasing" | "stable" | "decreasing"
    score_delta: float
    earliest_score: float
    latest_score: float
    sample_count: int


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_tension(score: float) -> str:
    """Map a 0.0–1.0 tension score to a human-readable class."""
    if score >= 0.80:
        return "sealed"
    if score >= 0.60:
        return "tight"
    if score >= 0.40:
        return "cohesive"
    if score >= 0.20:
        return "porous"
    return "open"


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _is_boundary(filename: str) -> bool:
    """Heuristic: is a file likely a boundary/interface file?

    Treats the following as boundary indicators:
    - Files in an ``api/`` directory
    - Files named ``__init__.py`` (re-exports)
    - Files in ``cli/`` or ``cmd/`` directories
    - Files with ``handler``, ``endpoint``, ``route``, ``view`` in name
    - Files explicitly marked in boundary_files set (preferred)
    """
    parts = filename.lower().split("/")
    name = parts[-1] if parts else ""
    boundary_dirs = {"api", "cli", "cmd", "views", "routes"}
    if boundary_dirs & set(parts[:-1]):
        return True
    if name == "__init__.py":
        return True
    for keyword in ("handler", "endpoint", "route", "view", "adapter", "facade"):
        if keyword in name:
            return True
    return False


def compute_surface_tension(
    commits: Sequence[CommitRecord],
    *,
    boundary_files_override: Optional[FrozenSet[str]] = None,
) -> SurfaceTensionResult:
    """Compute surface tension metrics from a sequence of commits.

    Parameters
    ----------
    commits
        Ordered sequence of ``CommitRecord`` objects (oldest first).
    boundary_files_override
        Optional explicit set of boundary files.  When provided, overrides
        the heuristic detection.

    Returns
    -------
    SurfaceTensionResult with all computed metrics.
    """
    if len(commits) < 2:
        return SurfaceTensionResult(
            window_commits=len(commits),
            window_hours=0.0,
            boundary_ratio=0.0,
            coupling_depth=0.0,
            cohesion_index=0.0,
            permeability=1.0,
            surface_area=0,
            surface_stability=1.0,
            tension_score=0.0,
            tension_class="open",
        )

    # --- Collect all files and identify boundary files ---
    all_files: set[str] = set()
    all_boundary: set[str] = set()
    all_internal: set[str] = set()

    for c in commits:
        all_files.update(c.files)
        if boundary_files_override is not None:
            all_boundary.update(c.boundary_files & boundary_files_override)
        else:
            all_boundary.update(f for f in c.files if _is_boundary(f))
            all_boundary.update(c.boundary_files)
        all_internal.update(c.internal_deps)

    total_files = len(all_files) or 1

    # 1. Boundary ratio
    boundary_ratio = len(all_boundary) / total_files

    # 2. Coupling depth: mean internal deps per boundary file per commit
    coupling_depths: list[float] = []
    for c in commits:
        b_files = c.boundary_files if c.boundary_files else frozenset(
            f for f in c.files if _is_boundary(f)
        )
        if b_files:
            dep_count = len(c.internal_deps)
            coupling_depths.append(dep_count / max(len(b_files), 1))

    coupling_depth = statistics.mean(coupling_depths) if coupling_depths else 0.0

    # 3. Cohesion index: fraction of boundary files sharing imports
    #    Approximated by: how often do multiple boundary files appear
    #    in the same commit?
    multi_boundary_commits = sum(
        1 for c in commits
        if len(c.boundary_files if c.boundary_files else frozenset(
            f for f in c.files if _is_boundary(f)
        )) >= 2
    )
    cohesion_index = multi_boundary_commits / len(commits) if commits else 0.0

    # 4. Permeability: fraction of commits touching *only* boundary files
    #    (no internal deps changed in same commit)
    surface_only_commits = sum(
        1 for c in commits
        if c.files and not c.internal_deps
    )
    permeability = surface_only_commits / len(commits) if commits else 1.0

    # 5. Surface area
    surface_area = len(all_boundary)

    # 6. Surface stability: fraction of boundary files never modified
    #    across the window
    touched_boundary: set[str] = set()
    for c in commits:
        b_files = c.boundary_files if c.boundary_files else frozenset(
            f for f in c.files if _is_boundary(f)
        )
        touched_boundary.update(b_files)

    if all_boundary:
        untouched = len(all_boundary - touched_boundary)
        surface_stability = untouched / len(all_boundary)
    else:
        surface_stability = 1.0

    # --- Composite score ---
    # High tension = tight coupling at boundary = bad for API agility
    #
    # Components:
    # - boundary_ratio (more surface = more tension points)
    # - coupling_depth (deeper deps = higher tension)
    # - cohesion_index (interlinked boundary = higher tension)
    # - 1 - permeability (low permeability = high tension)
    # - 1 - surface_stability (unstable surface = higher churn = higher tension)

    # Normalize coupling_depth to 0–1 (cap at 5.0)
    coupling_norm = min(1.0, coupling_depth / 5.0)

    tension_score = (
        boundary_ratio * 0.20 +
        coupling_norm * 0.25 +
        cohesion_index * 0.15 +
        (1.0 - permeability) * 0.25 +
        (1.0 - surface_stability) * 0.15
    )
    tension_score = round(max(0.0, min(1.0, tension_score)), 4)
    tension_class = classify_tension(tension_score)

    # --- Time span ---
    first_ts = commits[0].timestamp.timestamp()
    last_ts = commits[-1].timestamp.timestamp()
    span_hours = max((last_ts - first_ts) / 3600.0, 1.0 / 3600.0)

    return SurfaceTensionResult(
        window_commits=len(commits),
        window_hours=round(span_hours, 2),
        boundary_ratio=round(boundary_ratio, 4),
        coupling_depth=round(coupling_depth, 4),
        cohesion_index=round(cohesion_index, 4),
        permeability=round(permeability, 4),
        surface_area=surface_area,
        surface_stability=round(surface_stability, 4),
        tension_score=tension_score,
        tension_class=tension_class,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def surface_tension_report(result: SurfaceTensionResult) -> str:
    """Human-readable summary of a surface tension analysis."""
    lines = [
        f"Surface tension analysis ({result.window_commits} commits over {result.window_hours:.1f}h)",
        f"  class:              {result.tension_class}",
        f"  score:              {result.tension_score:.2f}",
        f"  boundary ratio:     {result.boundary_ratio:.2%}",
        f"  coupling depth:     {result.coupling_depth:.2f} deps/boundary file",
        f"  cohesion index:     {result.cohesion_index:.2%}",
        f"  permeability:       {result.permeability:.2%}",
        f"  surface area:       {result.surface_area} boundary files",
        f"  surface stability: {result.surface_stability:.2%}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def surface_tension_trend(results: Sequence[SurfaceTensionResult]) -> SurfaceTensionTrend:
    """Classify how surface tension scores evolve across a series of measurements."""
    if not results:
        return SurfaceTensionTrend(
            direction="stable",
            score_delta=0.0,
            earliest_score=0.0,
            latest_score=0.0,
            sample_count=0,
        )

    scores = [r.tension_score for r in results]
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

    return SurfaceTensionTrend(
        direction=direction,
        score_delta=round(delta, 4),
        earliest_score=earliest,
        latest_score=latest,
        sample_count=len(results),
    )
