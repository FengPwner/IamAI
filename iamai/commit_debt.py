"""commit_debt — quantify the repository's uncommitted and unpushed backlog.

A repo with nine modified files and no commits is not the same as a repo
with nine modified files and a fresh commit behind them, even though
``git status`` looks identical.  The difference is *debt*: work that has
been done but not yet recorded in the commit graph.

This module measures two kinds of debt:

=====================  =================================================
kind                   what it measures
=====================  =================================================
``write_debt``         modified / added / deleted files not yet committed
``push_debt``          local commits not yet on the remote
=====================  =================================================

Each is scored on a 0–100 scale, then blended into a single
``debt_score`` where **higher is worse** (more debt, more risk).

Scoring
-------

Write debt (modified-file count → 0–100)::

    0 files       →  0   (clean tree)
    1–3 files     →  10  (trivial)
    4–9 files     →  30  (noticeable)
    10–25 files   →  60  (concerning)
    26–99 files   →  85  (dangerous)
    100+ files    → 100  (critical)

Push debt (unpushed commits → 0–100)::

    0 commits     →  0
    1–2 commits   →  15
    3–5 commits   →  40
    6–15 commits  →  70
    16+ commits   → 100

The composite::

    debt_score = 0.6 * write_debt + 0.4 * push_debt

Grades
------

=====================  =================================================
grade                  meaning
=====================  =================================================
``clear``              score < 15 — tree is clean, push is current
``tidy``               score 15–39 — small backlog, normal cadence
``owing``              score 40–69 — significant backlog, commit soon
``overdue``            score 70–89 — large backlog, intervene now
``critical``           score ≥ 90 — data-loss risk, drop everything
=====================  =================================================

Usage::

    from iamai.commit_debt import debt_report

    report = debt_report(repo_path="/path/to/repo")
    print(report.debt_score, report.grade)
    print(report.write_debt, report.push_debt)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# thresholds
# ---------------------------------------------------------------------------

_WRITE_TIERS: list[tuple[int, int]] = [
    (0, 0),
    (3, 10),
    (9, 30),
    (25, 60),
    (99, 85),
]
_WRITE_CRITICAL = 100

_PUSH_TIERS: list[tuple[int, int]] = [
    (0, 0),
    (2, 15),
    (5, 40),
    (15, 70),
]
_PUSH_CRITICAL = 100

_GRADE_THRESHOLDS: list[tuple[int, str]] = [
    (15, "clear"),
    (40, "tidy"),
    (70, "owing"),
    (90, "overdue"),
]


def _score_from_tiers(value: int, tiers: list[tuple[int, int]], critical: int) -> int:
    """Map an integer value to a 0–100 score using step tiers."""
    for ceiling, score in tiers:
        if value <= ceiling:
            return score
    return critical


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

@dataclass
class DebtReport:
    """Snapshot of a repository's commit and push debt."""

    write_debt: int = 0
    push_debt: int = 0
    debt_score: float = 0.0
    grade: str = "clear"

    modified_files: List[str] = field(default_factory=list)
    unpushed_commits: int = 0

    def to_dict(self) -> dict:
        return {
            "write_debt": self.write_debt,
            "push_debt": self.push_debt,
            "debt_score": round(self.debt_score, 1),
            "grade": self.grade,
            "modified_count": len(self.modified_files),
            "unpushed_commits": self.unpushed_commits,
        }


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------

def _run_git(repo: Path, *args: str) -> str:
    """Run a git command in the given repo and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _count_modified(repo: Path) -> tuple[int, List[str]]:
    """Return (count, file_list) of modified/untracked files."""
    output = _run_git(repo, "status", "--porcelain")
    if not output:
        return 0, []
    files = [line.strip() for line in output.splitlines() if line.strip()]
    return len(files), files


def _count_unpushed(repo: Path, branch: str = "main") -> int:
    """Return the number of local commits ahead of the remote."""
    try:
        output = _run_git(repo, "rev-list", "--count", f"origin/{branch}..HEAD")
        return int(output) if output else 0
    except (ValueError, subprocess.SubprocessError):
        return 0


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def debt_report(
    repo_path: str | Path = ".",
    branch: str = "main",
) -> DebtReport:
    """Compute the commit-debt report for *repo_path*.

    Parameters
    ----------
    repo_path : str or Path
        Path to a git repository.
    branch : str
        Branch to compare against its remote tracking branch.

    Returns
    -------
    DebtReport
    """
    repo = Path(repo_path).resolve()

    mod_count, mod_files = _count_modified(repo)
    unpushed = _count_unpushed(repo, branch)

    w = _score_from_tiers(mod_count, _WRITE_TIERS, _WRITE_CRITICAL)
    p = _score_from_tiers(unpushed, _PUSH_TIERS, _PUSH_CRITICAL)
    score = 0.6 * w + 0.4 * p

    grade = "critical"
    for threshold, label in _GRADE_THRESHOLDS:
        if score < threshold:
            grade = label
            break

    return DebtReport(
        write_debt=w,
        push_debt=p,
        debt_score=score,
        grade=grade,
        modified_files=mod_files,
        unpushed_commits=unpushed,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description="Measure commit debt.")
    parser.add_argument("--repo", default=".", help="Path to git repo")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = debt_report(repo_path=args.repo, branch=args.branch)

    if args.json:
        print(_json.dumps(report.to_dict(), indent=2))
    else:
        print(f"debt_score: {report.debt_score:.1f}  grade: {report.grade}")
        print(f"  write_debt: {report.write_debt}  ({len(report.modified_files)} files)")
        print(f"  push_debt:  {report.push_debt}  ({report.unpushed_commits} unpushed)")
