"""category_momentum — which areas is the repo paying more or less attention to?

``commit_breadth`` measures how many categories a single commit spans.
``repo_churn`` measures which files are touched most often.  Neither tells
you the *direction* of change: is the repo's attention shifting toward
tests and away from notes, or vice versa?

This module splits the last *n* commits into an **old half** and a
**new half**, counts which file categories appear in each half, and
computes a momentum score per category.

A positive momentum means the category is receiving *more* attention
recently; negative means *less*.  The magnitude reflects the size of
the shift relative to total commit activity.

Categories reuse the same definitions as ``commit_breadth``::

    core      iamai/
    tests     tests/
    tools     tools/
    docs      docs/
    notes     notes/
    data      data/
    snippets  snippets/
    scripts   scripts/
    infra     Makefile, pytest.ini, requirements*, .github/, .gitignore
    root      everything else

Scoring
-------

For each category::

    old_share = old_count / max(old_total, 1)
    new_share = new_count / max(new_total, 1)
    momentum  = (new_share - old_share) * 100

Values range roughly from -50 to +50.  A momentum of +15 means the
category's share of recent attention grew by 15 percentage points
compared to the older half.

Grades per category:

===================  =================================================
grade                meaning
===================  =================================================
``accelerating``     momentum > +10 — clearly gaining attention
``steady``           -10 ≤ momentum ≤ +10 — stable share
``decelerating``     momentum < -10 — clearly losing attention
===================  =================================================

Summary grade for the whole report:

===================  =================================================
summary              meaning
===================  =================================================
``concentrating``    top-1 category holds > 50 % of new-half attention
``shifting``         at least one category has |momentum| > 15
``balanced``         all momenta within ±10
===================  =================================================

Usage::

    from iamai.category_momentum import momentum_report

    report = momentum_report(repo_path="/path/to/IamAI", commits=20)
    for cat in report.categories:
        print(f"{cat.name:10s}  momentum={cat.momentum:+.1f}  {cat.grade}")
    print(f"summary: {report.summary}")
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Category definitions (mirrors commit_breadth)
# ---------------------------------------------------------------------------

CATEGORIES: dict[str, list[str]] = {
    "core":     ["iamai/"],
    "tests":    ["tests/"],
    "tools":    ["tools/"],
    "docs":     ["docs/"],
    "notes":    ["notes/"],
    "data":     ["data/"],
    "snippets": ["snippets/"],
    "scripts":  ["scripts/"],
    "infra":    [
        "Makefile", "pytest.ini", "requirements",
        ".github/", ".gitignore", ".gitattributes",
    ],
}
# "root" is implicit: anything that doesn't match the above.

ALL_CATEGORIES: list[str] = list(CATEGORIES.keys()) + ["root"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout, or empty on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def classify_file(filepath: str) -> str:
    """Return the category name for a given file path."""
    for cat, prefixes in CATEGORIES.items():
        for prefix in prefixes:
            if filepath.startswith(prefix):
                return cat
    return "root"


def classify_files(files: Sequence[str]) -> dict[str, int]:
    """Count files per category."""
    counts: dict[str, int] = {cat: 0 for cat in ALL_CATEGORIES}
    for f in files:
        counts[classify_file(f)] += 1
    return counts


def _get_commit_files(cwd: Path, commit_hash: str) -> list[str]:
    """Return list of files changed in a single commit."""
    raw = _git(
        ["diff-tree", "--no-commit-id", "-r", "--name-only", commit_hash],
        cwd,
    )
    return [line for line in raw.splitlines() if line] if raw else []


def _get_recent_commits(cwd: Path, n: int) -> list[str]:
    """Return up to n commit hashes, newest first."""
    raw = _git(["log", "--format=%H", f"-{n}"], cwd)
    return raw.splitlines() if raw else []


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CategoryMomentum:
    """Momentum data for a single category."""
    name: str
    old_count: int = 0
    new_count: int = 0
    momentum: float = 0.0

    @property
    def grade(self) -> str:
        if self.momentum > 10:
            return "accelerating"
        elif self.momentum < -10:
            return "decelerating"
        return "steady"


@dataclass
class MomentumReport:
    """Full momentum analysis report."""
    categories: list[CategoryMomentum] = field(default_factory=list)
    commits_analyzed: int = 0
    old_half_count: int = 0
    new_half_count: int = 0
    summary: str = "balanced"

    def to_dict(self) -> dict:
        return {
            "commits_analyzed": self.commits_analyzed,
            "old_half_files": self.old_half_count,
            "new_half_files": self.new_half_count,
            "summary": self.summary,
            "categories": [
                {
                    "name": c.name,
                    "old_count": c.old_count,
                    "new_count": c.new_count,
                    "momentum": round(c.momentum, 2),
                    "grade": c.grade,
                }
                for c in self.categories
            ],
        }


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def compute_momentum(
    old_categories: dict[str, int],
    new_categories: dict[str, int],
    old_total: int,
    new_total: int,
) -> list[CategoryMomentum]:
    """Compute per-category momentum from old/new file counts.

    Parameters
    ----------
    old_categories : dict mapping category name to file count (old half)
    new_categories : dict mapping category name to file count (new half)
    old_total : total files changed in old half
    new_total : total files changed in new half

    Returns
    -------
    list of CategoryMomentum, one per category, sorted by momentum descending.
    """
    results: list[CategoryMomentum] = []

    for cat in ALL_CATEGORIES:
        oc = old_categories.get(cat, 0)
        nc = new_categories.get(cat, 0)
        old_share = oc / max(old_total, 1)
        new_share = nc / max(new_total, 1)
        mom = (new_share - old_share) * 100
        results.append(CategoryMomentum(
            name=cat,
            old_count=oc,
            new_count=nc,
            momentum=round(mom, 2),
        ))

    results.sort(key=lambda c: c.momentum, reverse=True)
    return results


def _compute_summary(categories: list[CategoryMomentum], new_total: int) -> str:
    """Determine the summary grade for the report."""
    if not categories or new_total == 0:
        return "balanced"

    # Check concentrating: top-1 holds >50% of new-half attention
    top_new = max(c.new_count for c in categories)
    if top_new / max(new_total, 1) > 0.5:
        return "concentrating"

    # Check shifting: any category has |momentum| > 15
    if any(abs(c.momentum) > 15 for c in categories):
        return "shifting"

    return "balanced"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def momentum_report(
    repo_path: str | Path = ".",
    commits: int = 20,
) -> MomentumReport:
    """Analyse category momentum over the last *commits* commits.

    Parameters
    ----------
    repo_path : path to the git repository
    commits : number of commits to analyse (split into old/new halves)

    Returns
    -------
    MomentumReport with per-category momentum and summary grade.
    """
    cwd = Path(repo_path).resolve()

    hashes = _get_recent_commits(cwd, commits)
    if not hashes:
        return MomentumReport()

    # Split: first half is "new" (recent), second half is "old"
    mid = len(hashes) // 2
    new_hashes = hashes[:mid] if mid > 0 else hashes
    old_hashes = hashes[mid:] if mid > 0 else []

    # Collect file lists
    old_cats: dict[str, int] = {cat: 0 for cat in ALL_CATEGORIES}
    new_cats: dict[str, int] = {cat: 0 for cat in ALL_CATEGORIES}
    old_total = 0
    new_total = 0

    for h in old_hashes:
        files = _get_commit_files(cwd, h)
        for f in files:
            old_cats[classify_file(f)] += 1
            old_total += 1

    for h in new_hashes:
        files = _get_commit_files(cwd, h)
        for f in files:
            new_cats[classify_file(f)] += 1
            new_total += 1

    categories = compute_momentum(old_cats, new_cats, old_total, new_total)
    summary = _compute_summary(categories, new_total)

    return MomentumReport(
        categories=categories,
        commits_analyzed=len(hashes),
        old_half_count=old_total,
        new_half_count=new_total,
        summary=summary,
    )


def momentum_summary(repo_path: str | Path = ".", commits: int = 20) -> str:
    """One-line summary of category momentum."""
    report = momentum_report(repo_path, commits)
    if not report.categories:
        return "no commits to analyse"

    accel = [c for c in report.categories if c.grade == "accelerating"]
    decel = [c for c in report.categories if c.grade == "decelerating"]

    parts = [f"momentum over {report.commits_analyzed} commits: {report.summary}"]
    if accel:
        parts.append("gaining: " + ", ".join(
            f"{c.name} ({c.momentum:+.1f})" for c in accel
        ))
    if decel:
        parts.append("losing: " + ", ".join(
            f"{c.name} ({c.momentum:+.1f})" for c in decel
        ))
    return "; ".join(parts)
