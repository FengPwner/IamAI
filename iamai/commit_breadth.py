"""commit_breadth — how many distinct areas does each commit touch?

A self-writing repo like IamAI should produce commits that span several
areas at once: a new module in ``iamai/``, its tests in ``tests/``, a
CLI wrapper in ``tools/``, and updated docs in ``docs/`` or ``notes/``.
A commit that only touches one file in one directory is *narrow*; one
that touches five or more categories is *broad*.

This module measures the **category breadth** of each commit and scores
it on a 0–100 scale where higher means more diverse.

Categories
----------

=================  ===================================================
category           prefix / rule
=================  ===================================================
``core``           ``iamai/``
``tests``          ``tests/``
``tools``          ``tools/``
``docs``           ``docs/``
``notes``          ``notes/``
``data``           ``data/``
``snippets``       ``snippets/``
``scripts``        ``scripts/``
``infra``          ``Makefile``, ``pytest.ini``, ``requirements*.txt``,
                   ``.github/``, ``.gitignore``
``root``           everything else at the repo root
=================  ===================================================

Scoring
-------

``breadth_score = (categories_touched / TOTAL_CATEGORIES) * 100``

=====================  =================================================
grade                  meaning
=====================  =================================================
``excellent``          score ≥ 80 — commit spans most areas
``good``               score 60–79 — solid multi-area commit
``fair``               score 40–59 — moderate spread
``narrow``             score 20–39 — focused on one or two areas
``single``             score < 20 — only one area touched
=====================  =================================================

Usage::

    from iamai.commit_breadth import breadth_report

    report = breadth_report(repo_path="/path/to/IamAI", last=10)
    for entry in report.commits:
        print(entry.sha[:8], entry.breadth_score, entry.grade,
              entry.categories)
    print(report.avg_breadth, report.avg_grade)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Category definitions
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
        "pyproject.toml", "setup.cfg", "setup.py",
    ],
}

TOTAL_CATEGORIES = len(CATEGORIES) + 1  # +1 for "root"

# ---------------------------------------------------------------------------
# Grade thresholds (breadth_score >= threshold → grade)
# ---------------------------------------------------------------------------

_GRADE_THRESHOLDS: list[tuple[float, str]] = [
    (80.0, "excellent"),
    (60.0, "good"),
    (40.0, "fair"),
    (20.0, "narrow"),
]
_GRADE_SINGLE = "single"


def _classify_grade(score: float) -> str:
    """Return the grade string for a given breadth score."""
    for threshold, grade in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return _GRADE_SINGLE


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

def classify_file(filepath: str) -> str:
    """Classify a file path into a category.

    Parameters
    ----------
    filepath : str
        Relative path from the repo root (as returned by git).

    Returns
    -------
    str
        One of the known category names, or ``"root"`` for unclassified
        top-level files.
    """
    for category, prefixes in CATEGORIES.items():
        for prefix in prefixes:
            if filepath.startswith(prefix):
                return category
    return "root"


def classify_files(filepaths: Sequence[str]) -> set[str]:
    """Classify a list of file paths and return the set of categories."""
    return {classify_file(f) for f in filepaths if f}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommitBreadth:
    """Breadth measurement for a single commit."""

    sha: str
    files_changed: int
    categories: tuple[str, ...]
    breadth_score: float
    grade: str

    def to_dict(self) -> dict:
        return {
            "sha": self.sha,
            "files_changed": self.files_changed,
            "categories": list(self.categories),
            "breadth_score": round(self.breadth_score, 1),
            "grade": self.grade,
        }


@dataclass
class BreadthReport:
    """Aggregate breadth report over a range of commits."""

    commits: list[CommitBreadth] = field(default_factory=list)
    avg_breadth: float = 0.0
    avg_grade: str = "single"
    total_commits: int = 0
    broad_commits: int = 0    # score >= 60
    narrow_commits: int = 0   # score < 40

    def to_dict(self) -> dict:
        return {
            "total_commits": self.total_commits,
            "avg_breadth": round(self.avg_breadth, 1),
            "avg_grade": self.avg_grade,
            "broad_commits": self.broad_commits,
            "narrow_commits": self.narrow_commits,
            "commits": [c.to_dict() for c in self.commits],
        }


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(repo: Path, *args: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )
    return result.stdout.strip()


def _get_commit_files(repo: Path, sha: str) -> list[str]:
    """Return the list of files changed in a commit."""
    output = _run_git(repo, "diff-tree", "--no-commit-id", "-r", "--name-only", sha)
    return [f.strip() for f in output.splitlines() if f.strip()]


def _get_recent_shas(repo: Path, n: int = 20) -> list[str]:
    """Return the *n* most recent commit SHAs on the current branch."""
    output = _run_git(repo, "log", "--format=%H", f"-{n}")
    return [s.strip() for s in output.splitlines() if s.strip()]


# ---------------------------------------------------------------------------
# Core measurement
# ---------------------------------------------------------------------------

def measure_commit(
    repo: Path,
    sha: str,
) -> CommitBreadth:
    """Measure the breadth of a single commit.

    Parameters
    ----------
    repo : Path
        Path to the git repository.
    sha : str
        Full or abbreviated commit SHA.

    Returns
    -------
    CommitBreadth
    """
    files = _get_commit_files(repo, sha)
    cats = classify_files(files)

    score = (len(cats) / TOTAL_CATEGORIES) * 100
    grade = _classify_grade(score)

    return CommitBreadth(
        sha=sha,
        files_changed=len(files),
        categories=tuple(sorted(cats)),
        breadth_score=score,
        grade=grade,
    )


def breadth_report(
    repo_path: str | Path = ".",
    last: int = 20,
) -> BreadthReport:
    """Compute breadth for the *last* N commits.

    Parameters
    ----------
    repo_path : str or Path
        Path to the git repository.
    last : int
        Number of recent commits to analyse.

    Returns
    -------
    BreadthReport
    """
    repo = Path(repo_path).resolve()
    shas = _get_recent_shas(repo, last)

    entries: list[CommitBreadth] = []
    for sha in shas:
        try:
            entries.append(measure_commit(repo, sha))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue

    if not entries:
        return BreadthReport()

    scores = [e.breadth_score for e in entries]
    avg = sum(scores) / len(scores)

    return BreadthReport(
        commits=entries,
        avg_breadth=avg,
        avg_grade=_classify_grade(avg),
        total_commits=len(entries),
        broad_commits=sum(1 for s in scores if s >= 60),
        narrow_commits=sum(1 for s in scores if s < 40),
    )


# ---------------------------------------------------------------------------
# Summary formatter
# ---------------------------------------------------------------------------

def breadth_summary(report: BreadthReport) -> str:
    """Return a human-readable one-liner for the report."""
    if not report.commits:
        return "commit_breadth: no commits to analyse"
    return (
        f"commit_breadth: avg {report.avg_breadth:.1f}% ({report.avg_grade}) "
        f"over {report.total_commits} commits — "
        f"{report.broad_commits} broad, {report.narrow_commits} narrow"
    )
