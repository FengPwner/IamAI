#!/usr/bin/env python3
"""repo_nutrition_label — a standardised "Nutrition Facts" panel for a repository.

Borrowed from food packaging: a compact, glanceable label that tells you
what is inside the repo at a given moment.  Not every metric is actionable,
but together they form a picture of *dietary balance* — is the repo getting
enough tests?  too much documentation sugar?  protein (source code) to
fibre (tests) ratio?

Metrics computed
~~~~~~~~~~~~~~~~

========================  ================================================
metric                    meaning
========================  ================================================
``serving_size``          tracked files in the working tree
``source_g``              "protein" — lines of Python source
``test_g``                "fibre" — lines of test code
``doc_g``                 "carbs" — lines of markdown / docs
``data_g``                "fat" — lines of JSON / JSONL / CSV data
``test_fibre_ratio``      test_g / max(source_g, 1); ≥1.0 is well-fibred
``doc_sugar_pct``         doc_g / total_lines × 100
``orphan_pct``            source modules with no matching test file
``freshness_days``        days since last commit
``commit_density``        commits per day of repo lifetime
``health_grade``          A / B / C / D / F composite
========================  ================================================

Health grade
~~~~~~~~~~~~

The composite is a weighted average of five sub-scores, each normalised
to 0–100:

========  ============================  =================================
weight    sub-score                     100 = best
========  ============================  =================================
30 %      test_fibre_ratio              ≥ 1.0
20 %      orphan-free                   0 % orphans
20 %      freshness                     committed within 1 day
15 %      doc balance                   10–30 % docs
15 %      commit density                ≥ 2 commits / day
========  ============================  =================================

Grade thresholds: A ≥ 85, B ≥ 70, C ≥ 55, D ≥ 40, F < 40.

Usage::

    from iamai.repo_nutrition_label import generate_label, format_label

    label = generate_label()
    print(format_label(label))
    print(label.health_grade)    # "B"
"""

from __future__ import annotations

import math
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class NutritionLabel:
    """Snapshot of repository health as a nutrition facts panel."""

    # serving
    serving_size: int = 0            # tracked files
    serving_date: str = ""           # ISO date of measurement

    # macronutrients (lines)
    source_g: int = 0                # Python source lines
    test_g: int = 0                  # test lines
    doc_g: int = 0                   # markdown / doc lines
    data_g: int = 0                  # data file lines
    total_lines: int = 0

    # derived ratios
    test_fibre_ratio: float = 0.0
    doc_sugar_pct: float = 0.0
    orphan_pct: float = 0.0
    freshness_days: float = 0.0
    commit_density: float = 0.0

    # sub-scores (0–100 each)
    fibre_score: float = 0.0
    orphan_score: float = 0.0
    freshness_score: float = 0.0
    doc_balance_score: float = 0.0
    density_score: float = 0.0

    # composite
    composite_score: float = 0.0
    health_grade: str = "F"

    # detail
    source_files: int = 0
    test_files: int = 0
    doc_files: int = 0
    data_files: int = 0
    orphan_modules: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# File counting helpers
# ---------------------------------------------------------------------------

def _run(cmd: Sequence[str], cwd: Optional[str] = None) -> str:
    """Run a command and return stdout; empty on failure."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, cwd=cwd
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _tracked_files(repo: Path) -> List[str]:
    """Return list of tracked files via git ls-files."""
    raw = _run(["git", "ls-files"], cwd=str(repo))
    if not raw:
        return []
    return [f for f in raw.splitlines() if f]


def _count_lines(repo: Path, paths: Sequence[str]) -> int:
    """Count total lines across the given relative paths."""
    total = 0
    for p in paths:
        fp = repo / p
        if fp.is_file():
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    total += sum(1 for _ in fh)
            except (OSError, UnicodeDecodeError):
                pass
    return total


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

def _classify_file(relpath: str) -> Optional[str]:
    """Classify a tracked file into source / test / doc / data / None."""
    rp = relpath.lower()
    if rp.endswith(".py"):
        if "test" in rp or rp.startswith("tests/") or "/test_" in rp:
            return "test"
        return "source"
    if rp.endswith((".md", ".rst", ".txt")) and "data/" not in rp:
        return "doc"
    if rp.endswith((".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml")):
        return "data"
    return None


def _source_module_name(relpath: str) -> str:
    """Extract the Python module stem from a relative path."""
    return Path(relpath).stem


def _find_orphans(source_files: Sequence[str], test_files: Sequence[str]) -> List[str]:
    """Return source module stems that have no matching test file."""
    test_stems = {_source_module_name(t) for t in test_files}
    # also match test_xxx for xxx.py
    test_stems |= {
        s.replace("test_", "", 1) for s in test_stems if s.startswith("test_")
    }
    orphans = []
    for sf in source_files:
        stem = _source_module_name(sf)
        if stem not in test_stems and f"test_{stem}" not in test_stems:
            orphans.append(stem)
    return sorted(set(orphans))


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

def _fibre_score(ratio: float) -> float:
    """0–100: peaks at ratio ≥ 1.0."""
    return min(100.0, ratio * 100.0)


def _orphan_score(orphan_pct: float) -> float:
    """0–100: 100 when no orphans.  orphan_pct is a percentage (0–100)."""
    return max(0.0, 100.0 - orphan_pct)


def _freshness_score(days: float) -> float:
    """0–100: 100 if committed today, decays logarithmically."""
    if days <= 0:
        return 100.0
    return max(0.0, 100.0 - 20.0 * math.log2(1.0 + days))


def _doc_balance_score(doc_pct: float) -> float:
    """0–100: best when docs are 10–30 % of total."""
    if doc_pct < 0:
        return 0.0
    if 10.0 <= doc_pct <= 30.0:
        return 100.0
    if doc_pct < 10.0:
        return max(0.0, doc_pct / 10.0 * 100.0)
    # doc_pct > 30: penalise excess
    excess = doc_pct - 30.0
    return max(0.0, 100.0 - excess * 2.0)


def _density_score(commits_per_day: float) -> float:
    """0–100: peaks at ≥ 2 commits/day."""
    return min(100.0, commits_per_day / 2.0 * 100.0)


def _grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _days_since_last_commit(repo: Path) -> float:
    """Days since the most recent commit."""
    ts = _run(
        ["git", "log", "-1", "--format=%at"],
        cwd=str(repo),
    )
    if not ts:
        return 999.0
    try:
        last = int(ts)
        now = datetime.now(timezone.utc).timestamp()
        return max(0.0, (now - last) / 86400.0)
    except (ValueError, OSError):
        return 999.0


def _repo_age_days(repo: Path) -> float:
    """Days since the first commit."""
    ts = _run(
        ["git", "log", "--reverse", "--format=%at", "-1"],
        cwd=str(repo),
    )
    if not ts:
        return 1.0
    try:
        first = int(ts)
        now = datetime.now(timezone.utc).timestamp()
        return max(1.0, (now - first) / 86400.0)
    except (ValueError, OSError):
        return 1.0


def _commit_count(repo: Path) -> int:
    raw = _run(["git", "rev-list", "--count", "HEAD"], cwd=str(repo))
    try:
        return int(raw)
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_label(repo_path: Optional[str] = None) -> NutritionLabel:
    """Generate a full nutrition label for the repository.

    Parameters
    ----------
    repo_path : str, optional
        Path to the git repository root.  Defaults to the repo containing
        this module.

    Returns
    -------
    NutritionLabel
    """
    if repo_path is None:
        repo = Path(__file__).resolve().parent.parent
    else:
        repo = Path(repo_path).resolve()

    label = NutritionLabel()
    label.serving_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    tracked = _tracked_files(repo)
    label.serving_size = len(tracked)

    # classify
    source_files: List[str] = []
    test_files: List[str] = []
    doc_files: List[str] = []
    data_files: List[str] = []
    for f in tracked:
        kind = _classify_file(f)
        if kind == "source":
            source_files.append(f)
        elif kind == "test":
            test_files.append(f)
        elif kind == "doc":
            doc_files.append(f)
        elif kind == "data":
            data_files.append(f)

    label.source_files = len(source_files)
    label.test_files = len(test_files)
    label.doc_files = len(doc_files)
    label.data_files = len(data_files)

    # count lines
    label.source_g = _count_lines(repo, source_files)
    label.test_g = _count_lines(repo, test_files)
    label.doc_g = _count_lines(repo, doc_files)
    label.data_g = _count_lines(repo, data_files)
    label.total_lines = label.source_g + label.test_g + label.doc_g + label.data_g

    # ratios
    label.test_fibre_ratio = (
        label.test_g / max(label.source_g, 1)
    )
    label.doc_sugar_pct = (
        label.doc_g / max(label.total_lines, 1) * 100.0
    )

    orphans = _find_orphans(source_files, test_files)
    label.orphan_modules = orphans[:50]  # cap for readability
    label.orphan_pct = (
        len(orphans) / max(label.source_files, 1) * 100.0
    )

    # temporal
    label.freshness_days = _days_since_last_commit(repo)
    commits = _commit_count(repo)
    age = _repo_age_days(repo)
    label.commit_density = commits / max(age, 1.0)

    # sub-scores
    label.fibre_score = _fibre_score(label.test_fibre_ratio)
    label.orphan_score = _orphan_score(label.orphan_pct)
    label.freshness_score = _freshness_score(label.freshness_days)
    label.doc_balance_score = _doc_balance_score(label.doc_sugar_pct)
    label.density_score = _density_score(label.commit_density)

    # composite (weighted)
    label.composite_score = (
        0.30 * label.fibre_score
        + 0.20 * label.orphan_score
        + 0.20 * label.freshness_score
        + 0.15 * label.doc_balance_score
        + 0.15 * label.density_score
    )
    label.health_grade = _grade(label.composite_score)

    return label


def format_label(label: NutritionLabel) -> str:
    """Render a NutritionLabel as an ASCII nutrition facts panel."""
    bar = "=" * 40
    thin = "-" * 40
    lines = [
        bar,
        "  Repository Nutrition Facts",
        bar,
        f"  Serving Size       {label.serving_size} files",
        f"  Serving Date       {label.serving_date}",
        thin,
        f"  Source (protein)   {label.source_g:>8,} lines  ({label.source_files} files)",
        f"  Tests  (fibre)     {label.test_g:>8,} lines  ({label.test_files} files)",
        f"  Docs   (carbs)     {label.doc_g:>8,} lines  ({label.doc_files} files)",
        f"  Data   (fat)       {label.data_g:>8,} lines  ({label.data_files} files)",
        thin,
        f"  Test Fibre Ratio   {label.test_fibre_ratio:>6.2f}x   [{label.fibre_score:.0f}/100]",
        f"  Orphan Modules     {label.orphan_pct:>5.1f}%    [{label.orphan_score:.0f}/100]",
        f"  Freshness          {label.freshness_days:>5.1f}d    [{label.freshness_score:.0f}/100]",
        f"  Doc Balance        {label.doc_sugar_pct:>5.1f}%    [{label.doc_balance_score:.0f}/100]",
        f"  Commit Density     {label.commit_density:>5.1f}/d   [{label.density_score:.0f}/100]",
        thin,
        f"  COMPOSITE SCORE    {label.composite_score:>5.1f} / 100",
        f"  HEALTH GRADE       {label.health_grade:>3s}",
        bar,
    ]
    return "\n".join(lines)


def quick_label(repo_path: Optional[str] = None) -> str:
    """One-call convenience: generate and format a label."""
    return format_label(generate_label(repo_path))
