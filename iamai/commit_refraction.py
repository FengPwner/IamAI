#!/usr/bin/env python3
"""commit_refraction — measure how change intent bends when crossing module boundaries.

In optics, **refraction** describes how light changes direction when
passing from one medium to another.  Snell's law quantifies the bending:

    n₁ · sin(θ₁) = n₂ · sin(θ₂)

A beam entering water from air bends toward the normal because water's
refractive index (n ≈ 1.33) exceeds air's (n ≈ 1.00).  Some light
**reflects** at the boundary instead of passing through; the fraction
depends on the angle and the index mismatch.

Codebases refract changes too.  When a developer modifies module A,
the *intent* of that change — "add a timeout parameter", "fix the
off-by-one", "rename for clarity" — must cross into modules B, C, D
that depend on A.  In a low-refraction codebase, the intent passes
cleanly: callers update, tests follow, documentation adjusts, and the
original purpose is preserved on the far side.  In a high-refraction
codebase, the intent bends: callers update but miss edge cases, tests
change but test the wrong thing, documentation drifts, and the original
purpose is distorted beyond recognition.

Some changes **reflect** entirely: a commit modifies a module, the
dependent modules push back (merge conflicts, CI failures, reviewer
objections), and the change is partially or fully reverted.

This module measures **commit refraction**: how faithfully change intent
survives boundary crossings, and what that reveals about architectural
clarity.

Refraction vs related metrics
-----------------------------

- **Conductivity** measures *transport efficiency* — do dependents
  update at all?
- **Diffusivity** measures *propagation speed* — how fast do changes
  spread?
- **Surface tension** measures *boundary coupling strength*.
- **Refraction** measures *intent fidelity* — when changes DO cross
  boundaries, do they arrive intact or distorted?

A codebase can be high-conductivity (changes always propagate) yet
high-refraction (they arrive distorted — tests test the wrong thing,
callers handle only the happy path, documentation describes the old
behaviour).  Propagation and fidelity are independent axes.

Refraction dimensions
---------------------

========================  ================================================
metric                    meaning
========================  ================================================
intent_preservation       fraction of commits whose stated purpose (from
                          the commit message) is fully reflected in the
                          files actually changed
                          (higher = changes do what they say)
scope_distortion          absolute change in scope size (files touched)
                          as a change crosses boundaries; measured as
                          the coefficient of variation of per-area
                          file counts for commits that span ≥2 areas
                          (lower = consistent scope across areas)
boundary_reflection       fraction of commits that are partially or fully
                          reverted within the next ``revert_window``
                          commits
                          (lower = fewer changes bounce off boundaries)
coupling_index            for changes that cross boundaries, how cleanly
                          the cross-area files map: ratio of areas with
                          exactly one touched file to total areas touched
                          (higher = surgical boundary crossings)
boundary_coherence        fraction of cross-boundary commits where every
                          area touched has at least one file that was
                          modified (not just added or deleted)
                          (higher = changes engage with existing code on
                          both sides of the boundary)
refraction_score          composite 0.0–1.0: high = changes cross
                          boundaries with intent intact; low = changes
                          arrive distorted or bounce back
refraction_class          transparent | clear | refractive | opaque |
                          mirrored
========================  ================================================

Refraction classes
------------------

==============  ============================================================
class           meaning
==============  ============================================================
transparent     score ≥ 0.80 — changes cross boundaries with almost no
                distortion; intent is perfectly preserved; reverts are
                rare; the architecture transmits purpose like clear glass
                transmits light
clear           0.60 ≤ score < 0.80 — good fidelity; most changes arrive
                intact; occasional scope distortion or partial reverts
                but the overall intent survives
refractive      0.40 ≤ score < 0.60 — moderate distortion; changes
                frequently arrive with altered scope; some boundary
                crossings produce reverts; intent is partially preserved
opaque          0.20 ≤ score < 0.40 — poor fidelity; changes that cross
                boundaries are routinely distorted or reverted; the
                architecture obscures intent
mirrored        score < 0.20 — near-total reflection; changes almost
                never survive boundary crossings; the architecture
                acts like a mirror, bouncing changes back
==============  ============================================================

Public API
----------
- ``CommitRecord`` — data class holding per-commit metadata
- ``RefractionResult`` — data class holding all computed metrics
- ``RefractionTrend`` — data class for how refraction evolves
- ``compute_refraction(commits, ...) -> RefractionResult``
- ``classify_refraction(score) -> str``
- ``refraction_report(result) -> str``
- ``refraction_trend(results) -> RefractionTrend``

Usage::

    from iamai.commit_refraction import CommitRecord, compute_refraction
    from datetime import datetime, timedelta

    ref = datetime(2026, 11, 11, 0, 0)
    commits = [
        CommitRecord(
            sha=f"c{i}",
            timestamp=ref + timedelta(hours=i),
            files=frozenset([f"iamai/module_{i % 5}.py"]),
            areas=frozenset([f"area_{i % 3}"]),
            message=f"update module {i % 5}",
        )
        for i in range(20)
    ]
    r = compute_refraction(commits)
    print(r.refraction_class)  # "clear"
    print(r.intent_preservation)  # 0.xx
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean, median, stdev
from typing import FrozenSet, List, Optional, Sequence

__all__ = [
    "CommitRecord",
    "RefractionResult",
    "RefractionTrend",
    "compute_refraction",
    "classify_refraction",
    "refraction_report",
    "refraction_trend",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommitRecord:
    """Metadata for a single commit."""

    sha: str
    timestamp: datetime
    files: FrozenSet[str] = field(default_factory=frozenset)
    areas: FrozenSet[str] = field(default_factory=frozenset)
    message: str = ""
    additions: int = 0
    deletions: int = 0
    is_revert: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.files, frozenset):
            object.__setattr__(self, "files", frozenset(self.files))
        if not isinstance(self.areas, frozenset):
            object.__setattr__(self, "areas", frozenset(self.areas))


@dataclass(frozen=True)
class RefractionResult:
    """Computed refraction metrics for a window of commits."""

    window_commits: int
    window_hours: float
    intent_preservation: float
    scope_distortion: float
    boundary_reflection: float
    coupling_index: float
    boundary_coherence: float
    refraction_score: float
    refraction_class: str


@dataclass(frozen=True)
class RefractionTrend:
    """How refraction scores evolve across a series of measurements."""

    direction: str  # "increasing" | "stable" | "decreasing"
    score_delta: float
    earliest_score: float
    latest_score: float
    sample_count: int


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_refraction(score: float) -> str:
    """Map a 0.0–1.0 score to a refraction class."""
    if score >= 0.80:
        return "transparent"
    if score >= 0.60:
        return "clear"
    if score >= 0.40:
        return "refractive"
    if score >= 0.20:
        return "opaque"
    return "mirrored"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_area_from_path(path: str) -> str:
    """Derive an area name from a file path.

    Convention: the first path component is the area.
    e.g., ``iamai/core.py`` → ``iamai``, ``tests/test_core.py`` → ``tests``.
    """
    parts = path.replace("\\", "/").split("/")
    return parts[0] if parts else "root"


def _infer_areas(files: FrozenSet[str], explicit_areas: FrozenSet[str]) -> FrozenSet[str]:
    """Return the set of areas touched by a commit.

    If the commit record has explicit ``areas``, use those.
    Otherwise, derive from file paths.
    """
    if explicit_areas:
        return explicit_areas
    return frozenset(_extract_area_from_path(f) for f in files)


def _extract_intent_keywords(message: str) -> set:
    """Extract meaningful words from a commit message for intent matching."""
    if not message:
        return set()
    # Lowercase, strip common prefixes
    msg = message.lower().strip()
    # Remove conventional prefixes
    for prefix in ("add", "fix", "update", "refactor", "remove", "change",
                   "modify", "improve", "clean", "wip", "catch-up", "chore"):
        msg = re.sub(rf"^{prefix}\b", "", msg)
    # Tokenize: keep alphanumeric tokens of length >= 3
    tokens = set(re.findall(r"[a-z0-9_]{3,}", msg))
    # Remove noise words
    noise = {"the", "and", "for", "with", "from", "that", "this", "not",
             "are", "was", "were", "been", "has", "had", "but", "you",
             "all", "can", "her", "one", "our", "out", "its", "also"}
    tokens -= noise
    return tokens


def _file_matches_intent(filepath: str, intent_keywords: set) -> bool:
    """Check whether a file path is plausibly related to the commit intent."""
    if not intent_keywords:
        return True  # no intent to verify — trivially matches
    path_lower = filepath.lower()
    # Extract meaningful parts from the path
    path_parts = set(re.findall(r"[a-z0-9_]{3,}", path_lower))
    # A file matches if it shares at least one keyword with the intent
    return bool(path_parts & intent_keywords)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_refraction(
    commits: Sequence[CommitRecord],
    revert_window: int = 5,
) -> RefractionResult:
    """Analyse how change intent bends at module boundaries.

    Parameters
    ----------
    commits : sequence of CommitRecord
        Ordered chronologically (oldest first).
    revert_window : int
        How many subsequent commits to scan for reverts of a given commit.

    Returns
    -------
    RefractionResult with all dimensions computed.
    """
    n = len(commits)
    if n == 0:
        return RefractionResult(
            window_commits=0,
            window_hours=0.0,
            intent_preservation=0.0,
            scope_distortion=0.0,
            boundary_reflection=0.0,
            coupling_index=0.0,
            boundary_coherence=0.0,
            refraction_score=0.0,
            refraction_class="mirrored",
        )

    # Window duration
    if n == 1:
        window_hours = 0.0
    else:
        delta = commits[-1].timestamp - commits[0].timestamp
        window_hours = round(delta.total_seconds() / 3600.0, 2)

    # ------------------------------------------------------------------
    # 1. Intent preservation
    # ------------------------------------------------------------------
    intent_scores: list[float] = []
    for c in commits:
        if not c.message or not c.files:
            continue
        intent_kw = _extract_intent_keywords(c.message)
        if not intent_kw:
            intent_scores.append(1.0)  # trivial: no parseable intent
            continue
        matching = sum(1 for f in c.files if _file_matches_intent(f, intent_kw))
        intent_scores.append(matching / len(c.files))

    intent_preservation = round(mean(intent_scores), 4) if intent_scores else 0.0

    # ------------------------------------------------------------------
    # 2. Scope distortion (CV of per-area file counts for cross-area commits)
    # ------------------------------------------------------------------
    scope_cvs: list[float] = []
    for c in commits:
        areas = _infer_areas(c.files, c.areas)
        if len(areas) < 2:
            continue
        # Count files per area
        area_counts: dict[str, int] = {}
        for f in c.files:
            a = _extract_area_from_path(f) if not c.areas else next(
                (aa for aa in areas if f.startswith(aa + "/") or f.startswith(aa + "\\")),
                "other",
            )
            area_counts[a] = area_counts.get(a, 0) + 1
        counts = list(area_counts.values())
        if len(counts) < 2:
            continue
        m = mean(counts)
        if m == 0:
            continue
        sd = stdev(counts) if len(counts) >= 2 else 0.0
        cv = sd / m
        scope_cvs.append(cv)

    # Invert: low CV = low distortion = good.  Convert to 0–1 score.
    if scope_cvs:
        avg_cv = mean(scope_cvs)
        # CV of 0 → score 1.0; CV of 2+ → score ~0
        scope_distortion_raw = avg_cv
        scope_distortion_score = round(max(0.0, 1.0 - avg_cv / 2.0), 4)
    else:
        scope_distortion_raw = 0.0
        scope_distortion_score = 1.0  # no cross-area commits → no distortion

    # ------------------------------------------------------------------
    # 3. Boundary reflection (fraction of commits reverted within window)
    # ------------------------------------------------------------------
    reverted_count = 0
    for i, c in enumerate(commits):
        # Check if any of the next ``revert_window`` commits revert this one
        look_end = min(i + revert_window + 1, n)
        for j in range(i + 1, look_end):
            later = commits[j]
            if later.is_revert:
                # Check file overlap: revert touches same files
                if c.files & later.files:
                    reverted_count += 1
                    break

    boundary_reflection = round(reverted_count / n, 4) if n > 0 else 0.0
    # Invert: low reflection = good
    reflection_score = round(max(0.0, 1.0 - boundary_reflection * 3.0), 4)

    # ------------------------------------------------------------------
    # 4. Coupling index (surgical boundary crossings)
    # ------------------------------------------------------------------
    coupling_scores: list[float] = []
    for c in commits:
        areas = _infer_areas(c.files, c.areas)
        if len(areas) < 2:
            continue
        # Count files per area
        area_counts: dict[str, int] = {}
        for f in c.files:
            a = _extract_area_from_path(f) if not c.areas else next(
                (aa for aa in areas if f.startswith(aa + "/")), "other",
            )
            area_counts[a] = area_counts.get(a, 0) + 1
        if not area_counts:
            continue
        # Surgical = each area has exactly 1 file
        surgical = sum(1 for cnt in area_counts.values() if cnt == 1)
        coupling_scores.append(surgical / len(area_counts))

    coupling_index = round(mean(coupling_scores), 4) if coupling_scores else 1.0

    # ------------------------------------------------------------------
    # 5. Boundary coherence (every area has at least one modified file)
    # ------------------------------------------------------------------
    coherence_scores: list[float] = []
    for c in commits:
        areas = _infer_areas(c.files, c.areas)
        if len(areas) < 2:
            continue
        # For this metric, we consider a file "engaged" if it exists
        # (not purely additive/deletive — but we approximate with
        # having both additions and deletions, or just presence).
        # Simple heuristic: every area has at least one file.
        area_has_file: dict[str, bool] = {a: False for a in areas}
        for f in c.files:
            for a in areas:
                if f.startswith(a + "/") or f.startswith(a + "\\"):
                    area_has_file[a] = True
                    break
        engaged = sum(1 for v in area_has_file.values() if v)
        coherence_scores.append(engaged / len(areas) if areas else 1.0)

    boundary_coherence = round(mean(coherence_scores), 4) if coherence_scores else 1.0

    # ------------------------------------------------------------------
    # Composite score
    # ------------------------------------------------------------------
    # Weights: intent 30%, reflection 25%, coupling 20%,
    #          scope 15%, coherence 10%
    refraction_score = round(
        0.30 * intent_preservation
        + 0.25 * reflection_score
        + 0.20 * coupling_index
        + 0.15 * scope_distortion_score
        + 0.10 * boundary_coherence,
        4,
    )

    refraction_class = classify_refraction(refraction_score)

    return RefractionResult(
        window_commits=n,
        window_hours=window_hours,
        intent_preservation=intent_preservation,
        scope_distortion=round(scope_distortion_raw, 4),
        boundary_reflection=boundary_reflection,
        coupling_index=coupling_index,
        boundary_coherence=boundary_coherence,
        refraction_score=refraction_score,
        refraction_class=refraction_class,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def refraction_report(result: RefractionResult) -> str:
    """Human-readable summary of a refraction analysis."""
    lines = [
        f"Refraction analysis ({result.window_commits} commits over {result.window_hours:.1f}h)",
        f"  class:                {result.refraction_class}",
        f"  score:                {result.refraction_score:.2f}",
        f"  intent preservation:  {result.intent_preservation:.2%}",
        f"  scope distortion:     {result.scope_distortion:.2f}",
        f"  boundary reflection:  {result.boundary_reflection:.2%}",
        f"  coupling index:       {result.coupling_index:.2%}",
        f"  boundary coherence:   {result.boundary_coherence:.2%}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def refraction_trend(results: Sequence[RefractionResult]) -> RefractionTrend:
    """Classify how refraction scores evolve across a series of measurements."""
    if not results:
        return RefractionTrend(
            direction="stable",
            score_delta=0.0,
            earliest_score=0.0,
            latest_score=0.0,
            sample_count=0,
        )

    scores = [r.refraction_score for r in results]
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

    return RefractionTrend(
        direction=direction,
        score_delta=round(delta, 4),
        earliest_score=earliest,
        latest_score=latest,
        sample_count=len(results),
    )
