#!/usr/bin/env python3
"""commit_inertia — measure how much lasting momentum changes carry in a codebase.

Newton's first law of motion states that an object at rest stays at rest,
and an object in motion stays in motion with the same speed and direction,
unless acted upon by a net external force.  The resistance to change in
velocity is **inertia**, and it scales with mass.

Codebases exhibit inertia too.  Some repos are *massive* — every change
requires ten follow-up fixes, reviewers push back, CI fails, and the
original commit is eventually reverted or rewritten beyond recognition.
Other repos are *light* — a single commit triggers a cascade of related
improvements, tests pass first try, and the change compounds into
something larger than its origin.

This module measures **commit inertia**: the tendency of changes to
either sustain their momentum (building on prior work, expanding scope,
attracting follow-up) or to stall (overwritten, abandoned, or isolated).

Inertia vs related metrics
--------------------------

- **Turbulence** measures *erraticism* — is the commit flow smooth or
  chaotic?
- **Refraction** measures *intent fidelity* — does purpose survive
  boundary crossings?
- **Inertia** measures *momentum persistence* — do changes build on
  each other or evaporate?

A codebase can be low-turbulence (steady rhythm) yet low-inertia (each
commit is an isolated event that nothing builds upon).  Conversely, a
high-turbulence burst can carry enormous inertia if every commit in the
burst amplifies the last.

Inertia dimensions
------------------

========================  ================================================
metric                    meaning
========================  ================================================
change_persistence        fraction of commits whose changes survive
                          (are not substantially reverted or overwritten)
                          within the next ``overwrite_window`` commits
                          (higher = changes stick)
follow_up_rate            fraction of commits that touch at least one file
                          previously touched by the immediately preceding
                          commit
                          (higher = sequential commits build on each other)
amplification             mean ratio of "files also touched by prior
                          commit" to "total files in this commit" for
                          commits that share ≥1 file with their
                          predecessor
                          (higher = changes expand from a shared core)
decay_half_life           median number of commits before a file modified
                          in commit N is modified again.  Longer = changes
                          settle; shorter = constant churn
                          (normalized to 0–1 for scoring)
momentum_score            composite 0.0–1.0: high = changes persist and
                          build; low = changes evaporate or churn
inertia_class             ballistic | driven | cruising | drifting |
                          stalled
========================  ================================================

Inertia classes
---------------

==============  ============================================================
class           meaning
==============  ============================================================
ballistic       score ≥ 0.80 — changes compound rapidly, each commit
                builds on the last, very little rework
driven          0.60 ≤ score < 0.80 — strong forward momentum with
                occasional rework
cruising        0.40 ≤ score < 0.60 — moderate momentum; changes persist
                but follow-ups are inconsistent
drifting        0.20 ≤ score < 0.40 — changes often don't stick or don't
                build; the codebase moves sideways
stalled         score < 0.20 — changes are frequently overwritten, little
                sequential building
==============  ============================================================

Public API
----------
- ``CommitRecord`` — data class for one commit's metadata
- ``compute_inertia(commits, ...) -> InertiaResult``
- ``inertia_report(result) -> str`` — human-readable summary
- ``inertia_trend(results) -> InertiaTrend`` — direction of change
  across a series of measurements
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CommitRecord:
    """Metadata for a single commit."""

    hash: str
    author: str
    timestamp: datetime
    message: str
    files_changed: List[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0

    def areas(self) -> set:
        """Extract top-level directory areas from changed files."""
        result = set()
        for f in self.files_changed:
            parts = f.split("/")
            area = parts[0] if len(parts) > 1 else "__root__"
            result.add(area)
        return result


@dataclass
class InertiaResult:
    """Results of an inertia analysis."""

    window_commits: int
    window_hours: float
    change_persistence: float
    follow_up_rate: float
    amplification: float
    decay_half_life: float
    momentum_score: float
    inertia_class: str


@dataclass
class InertiaTrend:
    """How inertia scores change across a time series."""

    direction: str  # increasing | stable | decreasing
    score_delta: float
    earliest_score: float
    latest_score: float
    sample_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REVERT_RE = re.compile(
    r"(^revert\b|^rollback\b|^undo\b|rolls?\s?back|undoes\b|undid\b)",
    re.IGNORECASE,
)


def _is_revert(message: str) -> bool:
    """Return True if the commit message looks like a revert."""
    return bool(_REVERT_RE.search(message))


def _file_overlap(a: Sequence[str], b: Sequence[str]) -> int:
    """Count files appearing in both lists."""
    set_b = set(b)
    return sum(1 for f in a if f in set_b)


# ---------------------------------------------------------------------------
# Metric computations
# ---------------------------------------------------------------------------

def change_persistence(
    commits: Sequence[CommitRecord],
    overwrite_window: int = 5,
) -> float:
    """Fraction of commits whose changes survive the next *overwrite_window*
    commits without being substantially overwritten.

    A commit is "overwritten" if a later commit (within the window) touches
    more than half of the same files AND is a revert or has >60% deletions
    relative to insertions.
    """
    if not commits:
        return 0.0

    n = len(commits)
    survived = 0

    for i, commit in enumerate(commits):
        if not commit.files_changed:
            survived += 1
            continue

        overwritten = False
        my_files = set(commit.files_changed)
        threshold = len(my_files) * 0.5

        for j in range(i + 1, min(i + 1 + overwrite_window, n)):
            later = commits[j]
            overlap = len(my_files & set(later.files_changed))

            if overlap < threshold:
                continue

            # Check if it's a revert or a heavy-deletion overwrite
            if _is_revert(later.message):
                overwritten = True
                break
            if later.insertions > 0 and later.deletions > 0:
                del_ratio = later.deletions / (later.insertions + later.deletions)
                if del_ratio > 0.60:
                    overwritten = True
                    break

        if not overwritten:
            survived += 1

    return survived / n if n else 0.0


def follow_up_rate(commits: Sequence[CommitRecord]) -> float:
    """Fraction of consecutive commit pairs where the later commit touches
    at least one file from the earlier commit."""
    if len(commits) < 2:
        return 0.0

    follow_ups = 0
    pairs = 0

    for i in range(len(commits) - 1):
        a_files = set(commits[i].files_changed)
        b_files = set(commits[i + 1].files_changed)
        if not a_files or not b_files:
            continue
        pairs += 1
        if a_files & b_files:
            follow_ups += 1

    return follow_ups / pairs if pairs else 0.0


def amplification(commits: Sequence[CommitRecord]) -> float:
    """For commits sharing files with their predecessor, the mean ratio of
    shared files to total files in the current commit.

    A high ratio means the commit *expands* from a shared core rather than
    touching mostly new territory.
    """
    if len(commits) < 2:
        return 0.0

    ratios: list[float] = []
    for i in range(1, len(commits)):
        prev_files = set(commits[i - 1].files_changed)
        curr_files = commits[i].files_changed
        if not curr_files:
            continue
        overlap = _file_overlap(curr_files, list(prev_files))
        if overlap == 0:
            continue
        ratios.append(overlap / len(curr_files))

    return statistics.mean(ratios) if ratios else 0.0


def decay_half_life(commits: Sequence[CommitRecord]) -> float:
    """Median number of commits before a modified file is touched again.

    Longer half-life means changes *settle* — files are modified and left
    alone.  Shorter half-life means constant churn.

    Returns the raw median (in commit-count units).  Normalization to 0–1
    for scoring happens in ``compute_inertia``.
    """
    if len(commits) < 2:
        return 0.0

    # Track last-seen commit index for each file
    last_seen: dict[str, int] = {}
    gaps: list[int] = []

    for idx, commit in enumerate(commits):
        for f in commit.files_changed:
            if f in last_seen:
                gaps.append(idx - last_seen[f])
            last_seen[f] = idx

    if not gaps:
        return 0.0

    return float(statistics.median(gaps))


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_inertia(score: float) -> str:
    """Map a momentum_score to an inertia class."""
    if score >= 0.80:
        return "ballistic"
    elif score >= 0.60:
        return "driven"
    elif score >= 0.40:
        return "cruising"
    elif score >= 0.20:
        return "drifting"
    else:
        return "stalled"


# ---------------------------------------------------------------------------
# Composite computation
# ---------------------------------------------------------------------------

def compute_inertia(
    commits: Sequence[CommitRecord],
    window_hours: float = 168.0,
    overwrite_window: int = 5,
    ideal_half_life: float = 20.0,
) -> InertiaResult:
    """Compute inertia metrics for a sequence of commits.

    Parameters
    ----------
    commits : sequence of CommitRecord
        Commits ordered oldest-first.
    window_hours : float
        Time span the window covers (for reporting only).
    overwrite_window : int
        How many subsequent commits to check for overwrites.
    ideal_half_life : float
        The "ideal" decay half-life in commit counts.  Actual values at
        or above this map to 1.0; shorter values scale linearly.

    Returns
    -------
    InertiaResult
    """
    n = len(commits)
    if n == 0:
        return InertiaResult(
            window_commits=0,
            window_hours=window_hours,
            change_persistence=0.0,
            follow_up_rate=0.0,
            amplification=0.0,
            decay_half_life=0.0,
            momentum_score=0.0,
            inertia_class="stalled",
        )

    cp = change_persistence(commits, overwrite_window=overwrite_window)
    fur = follow_up_rate(commits)
    amp = amplification(commits)
    dhl_raw = decay_half_life(commits)

    # Normalize half-life: longer is better (changes settle)
    # Cap at ideal_half_life → 1.0; 0 → 0.0
    dhl_score = min(dhl_raw / ideal_half_life, 1.0) if ideal_half_life > 0 else 0.0

    # Composite: persistence 35%, follow-up 25%, amplification 20%, half-life 20%
    momentum_score = round(
        0.35 * cp
        + 0.25 * fur
        + 0.20 * amp
        + 0.20 * dhl_score,
        4,
    )

    inertia_class = classify_inertia(momentum_score)

    return InertiaResult(
        window_commits=n,
        window_hours=window_hours,
        change_persistence=round(cp, 4),
        follow_up_rate=round(fur, 4),
        amplification=round(amp, 4),
        decay_half_life=round(dhl_raw, 4),
        momentum_score=momentum_score,
        inertia_class=inertia_class,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def inertia_report(result: InertiaResult) -> str:
    """Human-readable summary of an inertia analysis."""
    lines = [
        f"Inertia analysis ({result.window_commits} commits over {result.window_hours:.1f}h)",
        f"  class:                {result.inertia_class}",
        f"  momentum score:       {result.momentum_score:.2f}",
        f"  change persistence:   {result.change_persistence:.2%}",
        f"  follow-up rate:       {result.follow_up_rate:.2%}",
        f"  amplification:        {result.amplification:.2f}",
        f"  decay half-life:      {result.decay_half_life:.1f} commits",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def inertia_trend(results: Sequence[InertiaResult]) -> InertiaTrend:
    """Classify how inertia scores evolve across a series of measurements."""
    if not results:
        return InertiaTrend(
            direction="stable",
            score_delta=0.0,
            earliest_score=0.0,
            latest_score=0.0,
            sample_count=0,
        )

    scores = [r.momentum_score for r in results]
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

    return InertiaTrend(
        direction=direction,
        score_delta=round(delta, 4),
        earliest_score=earliest,
        latest_score=latest,
        sample_count=len(results),
    )
