"""commit_age.py — measure how long uncommitted changes wait before being committed.

When the batch committer dies between caretaker visits, the writer keeps
producing strokes that accumulate as uncommitted modifications. These
changes are locally visible but invisible to anyone reading the remote.
The "age" of an uncommitted file (time since last modification) quantifies
how stale the remote's view of the repo has become.

This module provides:
  - file_age_seconds(path): seconds since a file was last modified
  - uncommitted_ages(repo_path): dict mapping modified file paths to their ages
  - commit_age_summary(repo_path): summary with min/max/mean/median ages

Usage:
    python3 -c "from iamai.commit_age import commit_age_summary; print(commit_age_summary())"
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent


def file_age_seconds(path: str | Path, now: Optional[float] = None) -> float:
    """Return seconds since `path` was last modified.

    Args:
        path: File path to check.
        now: Override for current time (for testing). Defaults to time.time().

    Returns:
        Seconds since last modification.

    Raises:
        FileNotFoundError: If path does not exist.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"path does not exist: {p}")
    if now is None:
        now = time.time()
    return now - p.stat().st_mtime


def _get_modified_files(repo_path: str | Path) -> list[str]:
    """Return list of modified file paths (staged + unstaged) relative to repo root."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "-uno"],
        capture_output=True,
        text=True,
        cwd=str(repo_path),
    )
    if result.returncode != 0:
        return []
    files = []
    for line in result.stdout.strip().splitlines():
        if len(line) >= 4:
            # porcelain format: "XY filename"
            filepath = line[3:].strip()
            # handle renames: "R  old -> new"
            if " -> " in filepath:
                filepath = filepath.split(" -> ")[1]
            files.append(filepath)
    return files


def uncommitted_ages(
    repo_path: str | Path | None = None,
    now: Optional[float] = None,
) -> dict[str, float]:
    """Return ages (seconds) of all uncommitted modified files.

    Args:
        repo_path: Path to the git repository root. Defaults to REPO.
        now: Override for current time (for testing).

    Returns:
        Dict mapping relative file paths to their age in seconds.
        Empty dict if repo is clean or not a git repo.
    """
    if repo_path is None:
        repo_path = REPO
    repo_path = Path(repo_path)
    if now is None:
        now = time.time()

    modified = _get_modified_files(repo_path)
    ages = {}
    for rel_path in modified:
        abs_path = repo_path / rel_path
        try:
            ages[rel_path] = now - abs_path.stat().st_mtime
        except (FileNotFoundError, OSError):
            # file may have been deleted between git status and stat
            continue
    return ages


def commit_age_summary(
    repo_path: str | Path | None = None,
    now: Optional[float] = None,
) -> dict:
    """Return summary statistics for uncommitted file ages.

    Returns:
        Dict with keys: count, min_seconds, max_seconds, mean_seconds,
        median_seconds, files (list of (path, age) sorted by age desc).
        If no uncommitted changes, count=0 and all stats are 0.
    """
    ages = uncommitted_ages(repo_path, now)
    if not ages:
        return {
            "count": 0,
            "min_seconds": 0,
            "max_seconds": 0,
            "mean_seconds": 0,
            "median_seconds": 0,
            "files": [],
        }

    values = list(ages.values())
    values_sorted = sorted(ages.items(), key=lambda x: x[1], reverse=True)

    n = len(values)
    mean_val = sum(values) / n
    # median
    sorted_vals = sorted(values)
    if n % 2 == 1:
        median_val = sorted_vals[n // 2]
    else:
        median_val = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2

    return {
        "count": n,
        "min_seconds": round(min(values), 2),
        "max_seconds": round(max(values), 2),
        "mean_seconds": round(mean_val, 2),
        "median_seconds": round(median_val, 2),
        "files": [(p, round(a, 2)) for p, a in values_sorted],
    }


if __name__ == "__main__":
    summary = commit_age_summary()
    if summary["count"] == 0:
        print("no uncommitted changes")
    else:
        print(f"{summary['count']} uncommitted files:")
        print(f"  youngest: {summary['min_seconds']:.0f}s")
        print(f"  oldest:   {summary['max_seconds']:.0f}s")
        print(f"  mean:     {summary['mean_seconds']:.0f}s")
        print(f"  median:   {summary['median_seconds']:.0f}s")
        for path, age in summary["files"]:
            print(f"  {age:7.0f}s  {path}")
