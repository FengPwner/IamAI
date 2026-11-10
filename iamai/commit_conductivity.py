#!/usr/bin/env python3
"""commit_conductivity — measure how efficiently changes flow through a codebase's dependency graph.

In physics, **thermal conductivity** (k) measures how easily heat flows
through a material's lattice structure.  Copper (k ≈ 400 W/m·K) conducts
brilliantly because its free electrons carry energy without impedance.
Styrofoam (k ≈ 0.03 W/m·K) insulates because its trapped air pockets
block energy transfer at every pore boundary.

Codebases have conductivity too.  When a developer changes module A,
how efficiently does that change propagate to modules B, C, and D that
depend on it?  In a high-conductivity codebase, callers get updated in
the same commit or the next one, tests follow the code, and the
dependency graph carries change like copper carries current.  In a
low-conductivity codebase, changes stall at module boundaries: callers
break silently, tests go stale, and the information that "this API
changed" dissipates before reaching the modules that need it.

This module measures **commit conductivity**: how efficiently changes
flow through a codebase's file dependency structure, and what that
reveals about information transport health.

Conductivity vs related metrics
-------------------------------

- **Viscosity** measures internal *friction* during normal flow.
- **Diffusivity** measures *propagation speed* — how fast changes spread.
- **Surface tension** measures *boundary coupling*.
- **Elasticity** measures *recovery after deformation*.
- **Inertia** measures resistance to *starting* motion.
- **Conductivity** measures *transport efficiency* — not just how fast
  changes spread, but how completely and faithfully they reach every
  dependent module.  A codebase can be high-diffusivity (changes spread
  fast) but low-conductivity (changes lose fidelity — tests don't update,
  callers break).  Speed and completeness are independent axes.

Conductivity dimensions
-----------------------

========================  ================================================
metric                    meaning
========================  ================================================
pathway_efficiency        fraction of known dependents that get updated in
                          the same commit or the immediately next commit
                          when their dependency changes
                          (higher = changes reach consumers efficiently)
coverage_conductance      fraction of commits where test files for modified
                          source files are updated in the same commit or
                          the next one
                          (higher = tests follow code faithfully)
bottleneck_ratio          fraction of frequently-changed files whose
                          dependents are rarely co-modified
                          (higher = more change bottlenecks where
                          information stalls)
signal_fidelity           for changes that *do* propagate, how much of the
                          original change scope survives: ratio of
                          dependent files updated within 3 commits to
                          total known dependents
                          (higher = change intent is preserved)
contact_resistance        median hours between a file change and the first
                          update to any of its dependents
                          (lower = faster boundary crossing)
conductivity_score        composite 0.0–1.0: high = efficient, faithful
                          change transport; low = changes stall and
                          degrade at boundaries
conductivity_class        superconductor | conductive | resistive |
                          insulating | dielectric
========================  ================================================

Conductivity classes
--------------------

==============  ============================================================
class           meaning
==============  ============================================================
superconductor  score ≥ 0.80 — changes flow with near-zero loss; every
                API change reaches callers and tests in the same or next
                commit; the dependency graph is a copper bus
conductive      0.60 ≤ score < 0.80 — good transport; most dependents
                update within a few commits; occasional stalls but
                information generally reaches its destination
resistive       0.40 ≤ score < 0.60 — moderate loss; some changes
                propagate well while others stall at module boundaries;
                tests sometimes lag behind code changes
insulating      0.20 ≤ score < 0.40 — poor transport; many changes never
                reach their dependents; callers break silently and tests
                go stale for extended periods
dielectric      score < 0.20 — near-total blockage; changes rarely
                propagate beyond the original file; the codebase is
                effectively a collection of disconnected islands
==============  ============================================================

Public API
----------
- ``CommitRecord`` — data class holding per-commit metadata
- ``ConductivityResult`` — data class holding all computed metrics
- ``ConductivityTrend`` — data class for how conductivity evolves
- ``compute_conductivity(commits, ...) -> ConductivityResult``
- ``classify_conductivity(score) -> str``
- ``conductivity_report(result) -> str``
- ``conductivity_trend(results) -> ConductivityTrend``

Usage::

    from iamai.commit_conductivity import CommitRecord, compute_conductivity
    from datetime import datetime, timedelta

    ref = datetime(2026, 11, 11, 0, 0)
    commits = [
        CommitRecord(
            sha=f"c{i}",
            timestamp=ref + timedelta(hours=i),
            files=frozenset([f"iamai/module_{i % 5}.py"]),
            tests=frozenset([f"tests/test_module_{i % 5}.py"]),
            dependents=frozenset([f"iamai/caller_{(i+1) % 3}.py"]),
        )
        for i in range(20)
    ]
    r = compute_conductivity(commits)
    print(r.conductivity_class)  # "conductive"
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
    """Lightweight commit metadata for conductivity analysis."""

    sha: str
    timestamp: datetime
    files: FrozenSet[str] = field(default_factory=frozenset)
    tests: FrozenSet[str] = field(default_factory=frozenset)
    dependents: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self):
        if not isinstance(self.files, frozenset):
            object.__setattr__(self, "files", frozenset(self.files))
        if not isinstance(self.tests, frozenset):
            object.__setattr__(self, "tests", frozenset(self.tests))
        if not isinstance(self.dependents, frozenset):
            object.__setattr__(self, "dependents", frozenset(self.dependents))


@dataclass(frozen=True)
class ConductivityResult:
    """Computed conductivity metrics for an analysis window."""

    window_commits: int
    window_hours: float
    pathway_efficiency: float
    coverage_conductance: float
    bottleneck_ratio: float
    signal_fidelity: float
    contact_resistance: float
    conductivity_score: float
    conductivity_class: str


@dataclass(frozen=True)
class ConductivityTrend:
    """How conductivity evolves across a series of measurements."""

    direction: str          # "increasing" | "stable" | "decreasing"
    score_delta: float
    earliest_score: float
    latest_score: float
    sample_count: int


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_conductivity(score: float) -> str:
    """Map a 0.0–1.0 conductivity score to a human-readable class."""
    if score >= 0.80:
        return "superconductor"
    if score >= 0.60:
        return "conductive"
    if score >= 0.40:
        return "resistive"
    if score >= 0.20:
        return "insulating"
    return "dielectric"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_test_file(filename: str) -> bool:
    """Heuristic: is this file likely a test file?"""
    parts = filename.lower().split("/")
    name = parts[-1] if parts else ""
    if "test" in parts[:-1] or "tests" in parts[:-1]:
        return True
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return False


def _source_to_test_key(filename: str) -> str:
    """Derive a canonical test key from a source filename.

    ``iamai/module_a.py`` → ``module_a``
    ``tools/foo_bar.py`` → ``foo_bar``
    """
    name = filename.rsplit("/", 1)[-1]
    if name.endswith(".py"):
        name = name[:-3]
    return name


def _test_to_source_key(filename: str) -> str:
    """Derive a canonical source key from a test filename.

    ``tests/test_module_a.py`` → ``module_a``
    ``tests/test_foo_bar.py`` → ``foo_bar``
    """
    name = filename.rsplit("/", 1)[-1]
    if name.endswith(".py"):
        name = name[:-3]
    for prefix in ("test_",):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_conductivity(
    commits: Sequence[CommitRecord],
    *,
    propagation_window: int = 3,
    frequent_change_threshold: Optional[int] = None,
) -> ConductivityResult:
    """Compute conductivity metrics from a sequence of commits.

    Parameters
    ----------
    commits
        Ordered sequence of ``CommitRecord`` objects (oldest first).
    propagation_window
        Number of subsequent commits within which a dependent update is
        considered "propagated".  Default 3.
    frequent_change_threshold
        Minimum change count to classify a file as "frequently changed"
        for bottleneck detection.  Defaults to max(2, len(commits) // 10).

    Returns
    -------
    ConductivityResult with all computed metrics.
    """
    if len(commits) < 2:
        return ConductivityResult(
            window_commits=len(commits),
            window_hours=0.0,
            pathway_efficiency=0.0,
            coverage_conductance=0.0,
            bottleneck_ratio=0.0,
            signal_fidelity=0.0,
            contact_resistance=0.0,
            conductivity_score=0.0,
            conductivity_class="dielectric",
        )

    if frequent_change_threshold is None:
        frequent_change_threshold = max(2, len(commits) // 10)

    # --- Build per-file change timeline ---
    # file → list of (index, timestamp) when it was changed
    file_changes: dict[str, list[tuple[int, datetime]]] = {}
    # file → set of dependents observed across all commits
    file_dependents: dict[str, set[str]] = {}
    # file → set of associated test files observed
    file_tests: dict[str, set[str]] = {}

    for idx, c in enumerate(commits):
        for f in c.files:
            file_changes.setdefault(f, []).append((idx, c.timestamp))
        for d in c.dependents:
            # Each file in c.files is a dependency of d
            for f in c.files:
                file_dependents.setdefault(f, set()).add(d)
        for t in c.tests:
            for f in c.files:
                file_tests.setdefault(f, set()).add(t)

    # All changed files and all commits' file/test/dependent sets for lookup
    all_files: set[str] = set()
    for c in commits:
        all_files.update(c.files)
        all_files.update(c.tests)
        all_files.update(c.dependents)

    # ------------------------------------------------------------------
    # 1. Pathway efficiency
    #    When file F changes at commit i, what fraction of F's known
    #    dependents are updated in commit i or commit i+1?
    # ------------------------------------------------------------------
    pathway_hits = 0
    pathway_total = 0

    for f, changes in file_changes.items():
        deps = file_dependents.get(f, set())
        if not deps:
            continue
        for idx, ts in changes:
            # Check commits idx and idx+1 for dependent updates
            next_commits = commits[idx: idx + 2]
            updated_deps: set[str] = set()
            for nc in next_commits:
                updated_deps.update(nc.files & deps)
            pathway_hits += len(updated_deps)
            pathway_total += len(deps)

    pathway_efficiency = (
        pathway_hits / pathway_total if pathway_total > 0 else 1.0
    )

    # ------------------------------------------------------------------
    # 2. Coverage conductance
    #    When source file S changes, are its test files updated in the
    #    same commit or the next one?
    # ------------------------------------------------------------------
    coverage_hits = 0
    coverage_total = 0

    for f, changes in file_changes.items():
        tests = file_tests.get(f, set())
        if not tests:
            # Check heuristic: is there a test file that matches?
            key = _source_to_test_key(f)
            tests = {
                af for af in all_files
                if _is_test_file(af) and _test_to_source_key(af) == key
            }
        if not tests:
            continue
        for idx, ts in changes:
            next_commits = commits[idx: idx + 2]
            updated_tests: set[str] = set()
            for nc in next_commits:
                updated_tests.update(nc.tests & tests)
                # Also check files set for test filenames
                updated_tests.update(nc.files & tests)
            coverage_hits += min(len(updated_tests), len(tests))
            coverage_total += len(tests)

    coverage_conductance = (
        coverage_hits / coverage_total if coverage_total > 0 else 1.0
    )

    # ------------------------------------------------------------------
    # 3. Bottleneck ratio
    #    Fraction of frequently-changed files whose dependents are
    #    rarely co-modified (< 25% of dependent updates within window).
    # ------------------------------------------------------------------
    bottleneck_count = 0
    frequent_count = 0

    for f, changes in file_changes.items():
        if len(changes) < frequent_change_threshold:
            continue
        frequent_count += 1
        deps = file_dependents.get(f, set())
        if not deps:
            # No dependents means it's a leaf — not a bottleneck
            continue
        # How often do dependents get updated within propagation window?
        co_updates = 0
        total_opportunities = 0
        for idx, ts in changes:
            window_commits = commits[idx: idx + propagation_window + 1]
            for dep in deps:
                total_opportunities += 1
                for wc in window_commits:
                    if dep in wc.files:
                        co_updates += 1
                        break
        co_rate = co_updates / total_opportunities if total_opportunities > 0 else 1.0
        if co_rate < 0.25:
            bottleneck_count += 1

    bottleneck_ratio = (
        bottleneck_count / frequent_count if frequent_count > 0 else 0.0
    )

    # ------------------------------------------------------------------
    # 4. Signal fidelity
    #    For changes that propagate at all, what fraction of total
    #    dependents are reached within propagation_window commits?
    # ------------------------------------------------------------------
    fidelity_hits = 0
    fidelity_total = 0

    for f, changes in file_changes.items():
        deps = file_dependents.get(f, set())
        if not deps:
            continue
        for idx, ts in changes:
            window_commits = commits[idx: idx + propagation_window + 1]
            reached: set[str] = set()
            for wc in window_commits:
                reached.update(wc.files & deps)
            fidelity_hits += len(reached)
            fidelity_total += len(deps)

    signal_fidelity = (
        fidelity_hits / fidelity_total if fidelity_total > 0 else 1.0
    )

    # ------------------------------------------------------------------
    # 5. Contact resistance
    #    Median hours between a file change and the first update to any
    #    of its dependents.
    # ------------------------------------------------------------------
    resistance_hours: list[float] = []

    for f, changes in file_changes.items():
        deps = file_dependents.get(f, set())
        if not deps:
            continue
        for idx, ts in changes:
            # Find the earliest subsequent commit that touches a dependent
            for j in range(idx + 1, len(commits)):
                c = commits[j]
                if c.files & deps:
                    delta_hours = (c.timestamp - ts).total_seconds() / 3600.0
                    resistance_hours.append(max(delta_hours, 0.0))
                    break
            # If no dependent was ever updated, record a penalty
            # (capped at window duration)

    if resistance_hours:
        contact_resistance = statistics.median(resistance_hours)
    else:
        # No dependents ever — perfect or meaningless; default to 0
        contact_resistance = 0.0

    # ------------------------------------------------------------------
    # Composite score
    # ------------------------------------------------------------------
    # High conductivity = efficient transport
    #
    # Components (weighted):
    # - pathway_efficiency  (30%) — do dependents update promptly?
    # - coverage_conductance (25%) — do tests follow code?
    # - 1 - bottleneck_ratio (20%) — few bottlenecks = good
    # - signal_fidelity      (15%) — do changes reach all dependents?
    # - contact_resistance   (10%) — lower resistance = better
    #   (normalize: cap at 48h, invert)

    resistance_norm = min(1.0, contact_resistance / 48.0) if contact_resistance > 0 else 0.0

    conductivity_score = (
        pathway_efficiency * 0.30 +
        coverage_conductance * 0.25 +
        (1.0 - bottleneck_ratio) * 0.20 +
        signal_fidelity * 0.15 +
        (1.0 - resistance_norm) * 0.10
    )
    conductivity_score = round(max(0.0, min(1.0, conductivity_score)), 4)
    conductivity_class = classify_conductivity(conductivity_score)

    # --- Time span ---
    first_ts = commits[0].timestamp.timestamp()
    last_ts = commits[-1].timestamp.timestamp()
    span_hours = max((last_ts - first_ts) / 3600.0, 1.0 / 3600.0)

    return ConductivityResult(
        window_commits=len(commits),
        window_hours=round(span_hours, 2),
        pathway_efficiency=round(pathway_efficiency, 4),
        coverage_conductance=round(coverage_conductance, 4),
        bottleneck_ratio=round(bottleneck_ratio, 4),
        signal_fidelity=round(signal_fidelity, 4),
        contact_resistance=round(contact_resistance, 4),
        conductivity_score=conductivity_score,
        conductivity_class=conductivity_class,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def conductivity_report(result: ConductivityResult) -> str:
    """Human-readable summary of a conductivity analysis."""
    lines = [
        f"Conductivity analysis ({result.window_commits} commits over {result.window_hours:.1f}h)",
        f"  class:                {result.conductivity_class}",
        f"  score:                {result.conductivity_score:.2f}",
        f"  pathway efficiency:   {result.pathway_efficiency:.2%}",
        f"  coverage conductance: {result.coverage_conductance:.2%}",
        f"  bottleneck ratio:     {result.bottleneck_ratio:.2%}",
        f"  signal fidelity:      {result.signal_fidelity:.2%}",
        f"  contact resistance:   {result.contact_resistance:.2f}h",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def conductivity_trend(results: Sequence[ConductivityResult]) -> ConductivityTrend:
    """Classify how conductivity scores evolve across a series of measurements."""
    if not results:
        return ConductivityTrend(
            direction="stable",
            score_delta=0.0,
            earliest_score=0.0,
            latest_score=0.0,
            sample_count=0,
        )

    scores = [r.conductivity_score for r in results]
    earliest = scores[0]
    latest = scores[-1]
    delta = round(latest - earliest, 4)

    if len(scores) < 2:
        direction = "stable"
    elif delta > 0.05:
        direction = "increasing"
    elif delta < -0.05:
        direction = "decreasing"
    else:
        direction = "stable"

    return ConductivityTrend(
        direction=direction,
        score_delta=round(delta, 4),
        earliest_score=earliest,
        latest_score=latest,
        sample_count=len(results),
    )
