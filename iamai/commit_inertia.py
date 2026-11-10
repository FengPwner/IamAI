#!/usr/bin/env python3
"""commit_inertia — measure how resistant a codebase area is to change.

Newton's first law: a body at rest stays at rest.  A file that hasn't
been touched in months has *inertia* — not because it's perfect, but
because the cost of disturbing it (understanding context, running tests,
risking regressions) outweighs the perceived benefit of touching it.

Inertia is not the same as freshness.  Freshness asks "how recently was
this touched?"  Inertia asks "how much force would it take to change this
*now*?"  A freshly-touched file can have high inertia (a complex module
you just fixed but dread revisiting).  A stale file can have low inertia
(a trivial config that anyone could edit in seconds).

This module measures **commit inertia**: the resistance a codebase area
exerts against new changes, and what that resistance reveals about
architectural rigidity, knowledge concentration, and technical debt.

Inertia dimensions
-----------------

========================  ================================================
metric                    meaning
========================  ================================================
mass                      proxy for how "heavy" a file/area is: lines of
                          code × cyclomatic complexity × coupling degree
                          (more mass = harder to move)
velocity                  rate of recent changes: commits per day over
                          the analysis window (zero velocity = at rest
                          = maximum static friction)
friction_coefficient      how many other files must change when this one
                          does (high coupling = high friction)
momentum                  mass × velocity: a heavy file being actively
                          changed has momentum (easier to keep going
                          than to stop); a heavy file at rest has zero
                          momentum (hardest to start moving)
static_inertia            resistance to the *first* change after a quiet
                          period: combines staleness, mass, and coupling
                          into a 0.0–1.0 score
dynamic_inertia           resistance to *continued* change in an active
                          area: combines momentum decay, test coverage
                          gaps, and documentation staleness
inertia_score             composite 0.0–1.0: high = very resistant to
                          change (rigid, heavy, coupled); low = fluid
                          and easy to modify
inertia_class             frozen | rigid | stiff | flexible | fluid
========================  ================================================

Inertia classes
---------------

==============  ============================================================
class           meaning
==============  ============================================================
frozen          score ≥ 0.80 — area hasn't moved in ages and is too heavy
                or too coupled to change safely; approaching it requires
                significant effort and risk tolerance
rigid           0.60 ≤ score < 0.80 — area is resistant but not
                immovable; changes happen but are slow and cautious
stiff           0.40 ≤ score < 0.60 — moderate resistance; the area
                changes when needed but doesn't welcome change
flexible        0.20 ≤ score < 0.40 — low resistance; the area is
                actively maintained and easy to modify
fluid           score < 0.20 — very low resistance; the area is in
                active development and changes flow easily
==============  ============================================================

Public API
----------
- ``FileInfo`` — data class for one file's metadata
- ``compute_inertia(file_info, history, ...) -> InertiaResult``
- ``classify_inertia(score) -> str``
- ``inertia_report(result) -> str``
- ``area_inertia(files, history) -> AreaInertiaResult``
- ``inertia_trend(results) -> InertiaTrend``

Usage::

    from iamai.commit_inertia import FileInfo, compute_inertia
    from datetime import datetime

    info = FileInfo(
        path="iamai/commit_gravity.py",
        lines=320,
        complexity=12,
        coupling=5,
        test_coverage=0.85,
        last_changed=datetime(2026, 11, 10, 10, 0),
    )
    result = compute_inertia(info, commits_per_day=2.5)
    print(result.inertia_class)  # "flexible"
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INERTIA_CLASSES = ("frozen", "rigid", "stiff", "flexible", "fluid")

# Thresholds: score >= threshold → that class
_THRESHOLDS = [
    (0.80, "frozen"),
    (0.60, "rigid"),
    (0.40, "stiff"),
    (0.20, "flexible"),
    (0.00, "fluid"),
]

# Default analysis window
DEFAULT_WINDOW_DAYS = 30

# Mass normalisation constants (empirical, tuned for this repo's scale)
_MASS_LINES_REF = 500.0       # "reference" file size
_MASS_COMPLEXITY_REF = 20.0   # "reference" cyclomatic complexity
_MASS_COUPLING_REF = 10.0     # "reference" coupling count

# Friction threshold
_FRICTION_HIGH = 8
_FRICTION_LOW = 3

# Velocity thresholds (commits per day)
_VELOCITY_ACTIVE = 1.0
_VELOCITY_QUIET = 0.1


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FileInfo:
    """Metadata for a single file in the codebase."""

    path: str
    lines: int = 0
    complexity: int = 1          # cyclomatic complexity (1 = trivial)
    coupling: int = 0            # number of files this file imports / depends on
    test_coverage: float = 0.0   # 0.0–1.0
    last_changed: Optional[datetime] = None
    area: str = ""               # top-level directory (e.g. "iamai")

    def __post_init__(self):
        if not self.area and "/" in self.path:
            self.area = self.path.split("/")[0]
        self.test_coverage = max(0.0, min(1.0, self.test_coverage))


@dataclass
class InertiaResult:
    """Result of inertia computation for a single file."""

    path: str
    area: str
    mass: float
    velocity: float
    friction_coefficient: float
    momentum: float
    static_inertia: float
    dynamic_inertia: float
    inertia_score: float
    inertia_class: str
    staleness_days: float = 0.0
    details: Dict[str, float] = field(default_factory=dict)


@dataclass
class AreaInertiaResult:
    """Aggregated inertia for a codebase area (directory)."""

    area: str
    file_count: int
    mean_inertia: float
    max_inertia: float
    min_inertia: float
    frozen_count: int
    fluid_count: int
    area_class: str
    heaviest_file: str
    stillest_file: str
    details: Dict[str, float] = field(default_factory=dict)


@dataclass
class InertiaTrend:
    """Trend analysis over a series of inertia measurements."""

    direction: str               # "increasing" | "stable" | "decreasing"
    slope: float                 # change in mean inertia per measurement
    first_mean: float
    last_mean: float
    delta: float
    measurements: int
    interpretation: str


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_mass(lines: int, complexity: int, coupling: int) -> float:
    """Compute the 'mass' of a file — how heavy it is to change.

    mass = normalised(lines) × normalised(complexity) × (1 + normalised(coupling))

    Returns a value typically in [0, ~100], unbounded above.
    """
    norm_lines = lines / _MASS_LINES_REF
    norm_complexity = complexity / _MASS_COMPLEXITY_REF
    norm_coupling = coupling / _MASS_COUPLING_REF
    return norm_lines * norm_complexity * (1.0 + norm_coupling)


def compute_friction(coupling: int) -> float:
    """Compute friction coefficient from coupling count.

    Returns 0.0–1.0: higher = more files must change when this one does.
    """
    if coupling <= 0:
        return 0.0
    if coupling >= _FRICTION_HIGH:
        return 1.0
    if coupling <= _FRICTION_LOW:
        return coupling / (2.0 * _FRICTION_LOW)
    # Linear interpolation between low and high
    return 0.5 + 0.5 * (coupling - _FRICTION_LOW) / (_FRICTION_HIGH - _FRICTION_LOW)


def compute_velocity_score(commits_per_day: float) -> float:
    """Convert commit rate to a velocity score 0.0–1.0.

    Higher = more active.  Saturates at _VELOCITY_ACTIVE.
    """
    if commits_per_day <= 0:
        return 0.0
    if commits_per_day >= _VELOCITY_ACTIVE:
        return 1.0
    return commits_per_day / _VELOCITY_ACTIVE


def compute_static_inertia(
    staleness_days: float,
    mass: float,
    friction: float,
) -> float:
    """Compute static inertia — resistance to the first change after rest.

    Combines staleness (log-scaled), mass, and friction into 0.0–1.0.
    """
    # Log-scaled staleness: 1 day → ~0.0, 30 days → ~0.5, 365 days → ~0.85
    if staleness_days <= 0:
        stale_score = 0.0
    else:
        stale_score = min(1.0, math.log1p(staleness_days) / math.log1p(365))

    # Normalise mass to 0–1 (sigmoid-like)
    mass_score = 1.0 - math.exp(-mass / 5.0)

    # Weighted combination
    raw = 0.40 * stale_score + 0.35 * mass_score + 0.25 * friction
    return max(0.0, min(1.0, raw))


def compute_dynamic_inertia(
    mass: float,
    friction: float,
    test_coverage: float,
    momentum: float,
) -> float:
    """Compute dynamic inertia — resistance to continued change.

    High momentum + good tests = low dynamic inertia (keep going).
    High mass + low tests + high friction = high dynamic inertia (hard to sustain).
    """
    mass_score = 1.0 - math.exp(-mass / 5.0)
    momentum_bonus = min(1.0, momentum / 10.0)  # momentum helps
    test_gap = 1.0 - test_coverage               # untested = risky

    raw = 0.30 * mass_score + 0.25 * friction + 0.25 * test_gap - 0.20 * momentum_bonus
    return max(0.0, min(1.0, raw))


def compute_inertia(
    file_info: FileInfo,
    commits_per_day: float = 0.0,
    now: Optional[datetime] = None,
) -> InertiaResult:
    """Compute the inertia of a single file.

    Parameters
    ----------
    file_info : FileInfo
        File metadata (lines, complexity, coupling, coverage, last changed).
    commits_per_day : float
        Recent commit rate for this file (0 = no recent activity).
    now : datetime, optional
        Reference time for staleness computation (default: utcnow).

    Returns
    -------
    InertiaResult
    """
    if now is None:
        now = datetime.utcnow()

    # Staleness
    staleness_days = 0.0
    if file_info.last_changed is not None:
        delta = now - file_info.last_changed
        staleness_days = max(0.0, delta.total_seconds() / 86400.0)

    # Core metrics
    mass = compute_mass(file_info.lines, file_info.complexity, file_info.coupling)
    friction = compute_friction(file_info.coupling)
    velocity = compute_velocity_score(commits_per_day)
    momentum = mass * velocity

    # Inertia components
    static = compute_static_inertia(staleness_days, mass, friction)
    dynamic = compute_dynamic_inertia(mass, friction, file_info.test_coverage, momentum)

    # Composite: if velocity is zero, static dominates; otherwise blend
    if velocity < 0.01:
        score = static
    else:
        # Moving objects: blend static (barrier to entry) and dynamic (cost to continue)
        score = 0.40 * static + 0.60 * dynamic

    cls = classify_inertia(score)

    return InertiaResult(
        path=file_info.path,
        area=file_info.area,
        mass=round(mass, 4),
        velocity=round(velocity, 4),
        friction_coefficient=round(friction, 4),
        momentum=round(momentum, 4),
        static_inertia=round(static, 4),
        dynamic_inertia=round(dynamic, 4),
        inertia_score=round(score, 4),
        inertia_class=cls,
        staleness_days=round(staleness_days, 2),
        details={
            "lines": file_info.lines,
            "complexity": file_info.complexity,
            "coupling": file_info.coupling,
            "test_coverage": file_info.test_coverage,
            "commits_per_day": commits_per_day,
        },
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_inertia(score: float) -> str:
    """Classify an inertia score into a human-readable class.

    Returns one of: frozen, rigid, stiff, flexible, fluid.
    """
    score = max(0.0, min(1.0, score))
    for threshold, label in _THRESHOLDS:
        if score >= threshold:
            return label
    return "fluid"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def area_inertia(
    results: Sequence[InertiaResult],
    area: Optional[str] = None,
) -> AreaInertiaResult:
    """Aggregate inertia results for a codebase area.

    Parameters
    ----------
    results : sequence of InertiaResult
        Individual file results (should all belong to the same area).
    area : str, optional
        Override area label; if None, uses the first result's area.

    Returns
    -------
    AreaInertiaResult
    """
    if not results:
        raise ValueError("cannot compute area inertia from empty results")

    if area is None:
        area = results[0].area

    scores = [r.inertia_score for r in results]
    mean_score = sum(scores) / len(scores)
    frozen = sum(1 for s in scores if s >= 0.80)
    fluid = sum(1 for s in scores if s < 0.20)

    # Heaviest file (highest mass)
    heaviest = max(results, key=lambda r: r.mass)
    # Stillest file (most stale)
    stillest = max(results, key=lambda r: r.staleness_days)

    return AreaInertiaResult(
        area=area,
        file_count=len(results),
        mean_inertia=round(mean_score, 4),
        max_inertia=round(max(scores), 4),
        min_inertia=round(min(scores), 4),
        frozen_count=frozen,
        fluid_count=fluid,
        area_class=classify_inertia(mean_score),
        heaviest_file=heaviest.path,
        stillest_file=stillest.path,
        details={
            "median_inertia": round(sorted(scores)[len(scores) // 2], 4),
            "frozen_fraction": round(frozen / len(scores), 4),
            "fluid_fraction": round(fluid / len(scores), 4),
        },
    )


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def inertia_trend(
    snapshots: Sequence[float],
) -> InertiaTrend:
    """Analyse the trend of inertia scores over time.

    Parameters
    ----------
    snapshots : sequence of float
        Mean inertia scores from successive measurement windows.

    Returns
    -------
    InertiaTrend
    """
    n = len(snapshots)
    if n < 2:
        return InertiaTrend(
            direction="stable",
            slope=0.0,
            first_mean=snapshots[0] if snapshots else 0.0,
            last_mean=snapshots[-1] if snapshots else 0.0,
            delta=0.0,
            measurements=n,
            interpretation="insufficient data for trend analysis",
        )

    # Simple linear regression: y = a + b*x
    x_mean = (n - 1) / 2.0
    y_mean = sum(snapshots) / n
    num = sum((i - x_mean) * (snapshots[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    slope = num / den if den > 0 else 0.0

    first = snapshots[0]
    last = snapshots[-1]
    delta = last - first

    # Classify direction
    if slope > 0.01:
        direction = "increasing"
        interp = "codebase is becoming more resistant to change over time — rigidity is growing"
    elif slope < -0.01:
        direction = "decreasing"
        interp = "codebase is becoming easier to change — inertia is being reduced (refactoring, simplification)"
    else:
        direction = "stable"
        interp = "inertia is holding steady — no significant change in resistance to modification"

    return InertiaTrend(
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

def inertia_report(result: InertiaResult) -> str:
    """Generate a human-readable inertia report for a single file."""
    lines = [
        f"File: {result.path}",
        f"Area: {result.area}",
        f"Inertia: {result.inertia_score:.2f} ({result.inertia_class})",
        f"  Mass:       {result.mass:.3f}",
        f"  Velocity:   {result.velocity:.3f}",
        f"  Friction:   {result.friction_coefficient:.3f}",
        f"  Momentum:   {result.momentum:.3f}",
        f"  Static:     {result.static_inertia:.3f}",
        f"  Dynamic:    {result.dynamic_inertia:.3f}",
        f"  Staleness:  {result.staleness_days:.1f} days",
    ]
    return "\n".join(lines)


def area_report(result: AreaInertiaResult) -> str:
    """Generate a human-readable report for an area."""
    lines = [
        f"Area: {result.area}",
        f"Files: {result.file_count}",
        f"Mean inertia: {result.mean_inertia:.2f} ({result.area_class})",
        f"  Max: {result.max_inertia:.2f}  Min: {result.min_inertia:.2f}",
        f"  Frozen: {result.frozen_count}  Fluid: {result.fluid_count}",
        f"  Heaviest: {result.heaviest_file}",
        f"  Stillest: {result.stillest_file}",
    ]
    return "\n".join(lines)
