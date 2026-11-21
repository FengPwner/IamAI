"""repo_maturity_index — classify how mature a self-writing repository is.

A self-writing repo goes through recognisable phases.  Early on it
accumulates files faster than it produces insight.  Eventually the ratio
inverts: fewer new files, more refinement of existing ones.  When even
refinement stalls, the repo has reached its carrying capacity.

This module takes a handful of repo-level metrics and maps them to a
maturity stage::

    seedling   → first 50 commits, everything is new
    sapling    → 50–300 commits, modules proliferating
    canopy     → 300–800 commits, structure stabilising
    old_growth → 800+ commits, mostly maintenance
    petrified  → growth has stopped, only caretaker visits

The *maturity score* is a continuous 0.0–1.0 value derived from four
signals (each normalised to 0–1 and averaged):

    commit_depth_norm    — log-scaled commit count (ceiling at 2000)
    file_count_norm      — log-scaled tracked file count (ceiling at 5000)
    content_ratio        — fraction of non-test, non-doc files (code health)
    care_ratio           — caretaker notes per 100 commits (maintenance load)

A high score with a low ``care_ratio`` signals a healthy, self-sustaining
repo.  A high score with a high ``care_ratio`` signals a repo that needs
constant intervention to stay alive — which is exactly the situation this
repo has been in since around visit 700.

Public API
----------
- ``MaturityReport`` dataclass
- ``assess_maturity(...) -> MaturityReport``
- ``classify_stage(score) -> str``
- ``maturity_summary(report) -> str``

Usage::

    from iamai.repo_maturity_index import assess_maturity

    report = assess_maturity(
        commits=1100, files=2591, code_files=1770,
        caretaker_visits=779, stroke_count=6920,
    )
    print(report.stage)        # "old_growth"
    print(report.score)        # 0.82
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MaturityReport:
    """Snapshot of a repo's maturity at a point in time."""

    score: float               # 0.0–1.0 overall maturity
    stage: str                 # one of the STAGES keys
    commit_depth_norm: float   # normalised commit count
    file_count_norm: float     # normalised file count
    content_ratio: float       # code files / total files
    care_ratio: float          # caretaker visits per 100 commits
    strokes_per_commit: float  # average strokes between commits
    diagnosis: str             # one-sentence health summary


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

STAGES: dict[str, tuple[float, float]] = {
    "seedling":   (0.0, 0.15),
    "sapling":    (0.15, 0.35),
    "canopy":     (0.35, 0.60),
    "old_growth": (0.60, 0.85),
    "petrified":  (0.85, 1.01),  # slightly above 1.0 to catch edge
}

# Ceilings for normalisation (log-scale)
_COMMIT_CEIL = 2000
_FILE_CEIL   = 5000


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log_norm(value: float, ceiling: float) -> float:
    """Log-scale normalisation: 0 at value=1, 1 at value=ceiling."""
    if value <= 1:
        return 0.0
    return min(math.log(value) / math.log(ceiling), 1.0)


def _content_ratio(code_files: int, total_files: int) -> float:
    """Fraction of tracked files that are code (not tests/docs/notes)."""
    if total_files == 0:
        return 0.0
    return min(code_files / total_files, 1.0)


def _care_ratio(caretaker_visits: int, commits: int) -> float:
    """Caretaker visits per 100 commits, normalised to 0–1.

    0 visits / 100 commits → 0.0 (self-sustaining)
    50+ visits / 100 commits → 1.0 (heavily dependent)
    """
    if commits == 0:
        return 0.0
    ratio = (caretaker_visits / commits) * 100
    return min(ratio / 50.0, 1.0)


def _strokes_per_commit(stroke_count: int, commits: int) -> float:
    if commits == 0:
        return 0.0
    return stroke_count / commits


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_stage(score: float) -> str:
    """Map a 0.0–1.0 score to a stage label."""
    for name, (lo, hi) in STAGES.items():
        if lo <= score < hi:
            return name
    return "petrified"  # fallback for score >= 1.0


def assess_maturity(
    commits: int,
    files: int,
    code_files: int,
    caretaker_visits: int,
    stroke_count: int,
) -> MaturityReport:
    """Compute a maturity report from repo-level metrics.

    Parameters
    ----------
    commits : int
        Total number of commits.
    files : int
        Total tracked files.
    code_files : int
        Files that are source code (``*.py`` in the main package).
    caretaker_visits : int
        Total caretaker visit notes written.
    stroke_count : int
        Total strokes logged in ``data/strokes.jsonl``.
    """
    cdn = _log_norm(commits, _COMMIT_CEIL)
    fcn = _log_norm(files, _FILE_CEIL)
    cr = _content_ratio(code_files, files)
    car = _care_ratio(caretaker_visits, commits)
    spc = _strokes_per_commit(stroke_count, commits)

    # Weighted average: commit depth and file count carry more weight
    # because they are the strongest maturity signals.  The care_ratio
    # component rewards *low* dependency — but only when the repo is
    # actually active.  A dead repo with zero visits should not score
    # well just because care_ratio is zero.
    activity_floor = min(cdn + fcn, 0.1)  # tiny bonus for any activity
    care_component = (1 - car) * 0.25 if (cdn + fcn) > 0.05 else 0.0
    score = (cdn * 0.30 + fcn * 0.25 + care_component + cr * 0.20 + activity_floor)
    score = round(max(0.0, min(score, 1.0)), 4)

    stage = classify_stage(score)
    diagnosis = _diagnose(score, car, spc, stage)

    return MaturityReport(
        score=score,
        stage=stage,
        commit_depth_norm=round(cdn, 4),
        file_count_norm=round(fcn, 4),
        content_ratio=round(cr, 4),
        care_ratio=round(car, 4),
        strokes_per_commit=round(spc, 2),
        diagnosis=diagnosis,
    )


def maturity_summary(report: MaturityReport) -> str:
    """One-line human-readable summary."""
    return (
        f"{report.stage} (score={report.score:.2f}): "
        f"{report.diagnosis}"
    )


# ---------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------

def _diagnose(score: float, care_ratio: float, spc: float, stage: str) -> str:
    """Generate a one-sentence health diagnosis."""
    parts: list[str] = []

    if stage == "seedling":
        parts.append("repo is young and still finding its shape")
    elif stage == "sapling":
        parts.append("modules are multiplying faster than they are being pruned")
    elif stage == "canopy":
        parts.append("structure is stabilising but some areas are getting dense")
    elif stage == "old_growth":
        parts.append("the repo has outgrown its original design")
    elif stage == "petrified":
        parts.append("growth has plateaued; the repo is a museum of its own history")

    if care_ratio > 0.5:
        parts.append("caretaker dependency is high — the repo cannot sustain itself")
    elif care_ratio > 0.2:
        parts.append("moderate caretaker need — occasional intervention required")
    else:
        parts.append("low caretaker dependency — mostly self-sustaining")

    if spc > 10:
        parts.append("many strokes between commits suggests commit batching is too coarse")
    elif spc < 1:
        parts.append("more commits than strokes — the writer may be idle")

    return "; ".join(parts) + "."
