"""Commit focus — is each commit about one thing, or a jumble?

``commit_age`` measures *staleness*; ``commit_velocity`` measures *speed*;
this module measures *cohesion*.  A commit that touches twelve files across
six directories is harder to review and harder to revert than one that touches
three files in one directory.  The caretaker can use the focus score to flag
sprawl before it accumulates.

Three public functions:

- ``commit_file_spread(repo, n)`` — how many files and directories the last
  *n* commits touched, returned as a list of per-commit dicts.
- ``focus_score(files, dirs)`` — numeric score from 0 (sprawling) to 1
  (perfectly focused).  Formula: ``1 / (1 + log2(files) + log2(max(dirs,1)))``.
- ``focus_verdict(score)`` — label: ``"focused"`` (≥ 0.5), ``"broad"``
  (≥ 0.3), or ``"sprawling"`` (< 0.3).

Edge cases:

- Empty repo or no commits → returns empty list / score 1.0.
- A commit with 0 changed files (e.g. merge commit) gets score 1.0.
- Paths with no directory separator are treated as living in root.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _parse_commit_files(cwd: Path, commit_hash: str) -> list[str]:
    """Return the list of files changed in a single commit."""
    raw = _git(
        ["diff-tree", "--no-commit-id", "-r", "--name-only", commit_hash],
        cwd,
    )
    if not raw:
        return []
    return [line for line in raw.splitlines() if line.strip()]


def _dirs_from_paths(files: list[str]) -> set[str]:
    """Extract the set of parent directories from a list of file paths."""
    dirs: set[str] = set()
    for f in files:
        parent = str(Path(f).parent)
        dirs.add(parent if parent != "." else "")
    return dirs


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def focus_score(files: int, dirs: int) -> float:
    """Compute a focus score from file count and directory count.

    Returns a float in [0, 1].  Higher means more focused.

    A commit touching 1 file in 1 directory scores 1.0.
    A commit touching 10 files in 5 directories scores ≈ 0.17.
    A commit with 0 files (merge) scores 1.0.
    """
    if files <= 0:
        return 1.0
    return round(1.0 / (1.0 + math.log2(max(files, 1)) + math.log2(max(dirs, 1))), 4)


def focus_verdict(score: float) -> str:
    """Label a focus score.

    ==========  ============================================
    verdict     range
    ==========  ============================================
    focused     score ≥ 0.5
    broad       0.3 ≤ score < 0.5
    sprawling   score < 0.3
    ==========  ============================================
    """
    if score >= 0.5:
        return "focused"
    if score >= 0.3:
        return "broad"
    return "sprawling"


def commit_file_spread(
    repo: Path | str | None = None,
    n: int = 10,
) -> list[dict]:
    """Analyse the last *n* commits for file/directory spread.

    Returns a list of dicts, newest first::

        [
            {
                "hash": "abc1234",
                "files": 3,
                "dirs": 2,
                "score": 0.45,
                "verdict": "broad",
            },
            ...
        ]

    Returns an empty list when no commits exist or git is unavailable.
    """
    if repo is None:
        repo = REPO
    repo = Path(repo)

    raw = _git(["log", "--format=%H", f"-{n}"], repo)
    if not raw:
        return []

    results: list[dict] = []
    for line in raw.splitlines():
        h = line.strip()
        if not h:
            continue
        files = _parse_commit_files(repo, h)
        dirs = _dirs_from_paths(files)
        file_count = len(files)
        dir_count = len(dirs) if dirs else (1 if file_count > 0 else 0)
        score = focus_score(file_count, dir_count)
        results.append({
            "hash": h[:7],
            "files": file_count,
            "dirs": dir_count,
            "score": score,
            "verdict": focus_verdict(score),
        })

    return results


def focus_report(
    repo: Path | str | None = None,
    n: int = 10,
) -> str:
    """One-liner summarising recent commit focus for caretaker logs.

    Example output::

        last 10 commits: 7 focused, 2 broad, 1 sprawling — avg score 0.62
    """
    if repo is None:
        repo = REPO
    repo = Path(repo)

    spread = commit_file_spread(repo, n)
    if not spread:
        return "no commits — cannot measure focus"

    counts = {"focused": 0, "broad": 0, "sprawling": 0}
    total = 0.0
    for entry in spread:
        counts[entry["verdict"]] += 1
        total += entry["score"]

    avg = round(total / len(spread), 2)
    parts = [f"{v} {k}" for k, v in counts.items() if v > 0]
    return f"last {len(spread)} commits: {', '.join(parts)} — avg score {avg}"
