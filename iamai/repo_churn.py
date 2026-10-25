"""Repo churn — which files move the most, which gather dust?

A repo with 672 tracked files is large enough that manual oversight is
impossible.  Churn analysis makes the *activity landscape* visible:

- **Hot files** — modified in many commits — are either genuine hubs
  (the JSONL append target, the state file) or symptoms of a problem
  (a config file that shouldn't change every ten minutes).
- **Cold files** — committed once and never touched — are either
  stable and done, or abandoned and forgotten.
- **Churn ratio** — what fraction of the tree has been touched in
  the last N commits — tells you how concentrated or diffuse the
  recent work has been.

This module walks ``git log`` with ``--name-only`` and tallies per-file
modification counts.  No external dependencies, no state files.

Usage::

    from iamai.repo_churn import repo_churn, churn_report

    info = repo_churn(repo=Path("."))
    hot = info["hot"]          # top 10 most-modified files
    cold = info["cold"]        # files never touched since initial commit
    ratio = info["churn_ratio"]  # 0.0 – 1.0

    print(churn_report(Path(".")))
    # "churn 0.12 (80/672 touched in last 50 commits); hot: data/strokes.jsonl (341), ..."
"""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _tracked_files(repo: Path) -> set[str]:
    """Return the set of all currently tracked file paths."""
    result = _run(["git", "ls-files"], repo)
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _file_mod_counts(repo: Path, max_commits: int = 200) -> Counter:
    """Count how many commits touched each file.

    Walks up to ``max_commits`` recent commits and tallies per-file
    modification counts using ``git log --name-only``.
    """
    result = _run(
        ["git", "log", f"--max-count={max_commits}", "--name-only", "--pretty=format:"],
        repo,
    )
    if result.returncode != 0:
        return Counter()

    counter: Counter = Counter()
    for line in result.stdout.splitlines():
        path = line.strip()
        if path:
            counter[path] += 1
    return counter


def _recent_touched(repo: Path, n_commits: int = 50) -> set[str]:
    """Return the set of files touched in the last N commits."""
    result = _run(
        ["git", "log", f"--max-count={n_commits}", "--name-only", "--pretty=format:"],
        repo,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def repo_churn(
    repo: Path,
    hot_n: int = 10,
    recent_commits: int = 50,
    max_commits: int = 200,
) -> dict[str, Any]:
    """Compute churn statistics for a repository.

    Args:
        repo: path to the git repository.
        hot_n: how many top-churned files to include in ``hot``.
        recent_commits: window for ``churn_ratio`` calculation.
        max_commits: how far back to walk for modification counts.

    Returns:
        Dictionary with keys:

        - ``tracked``: total number of tracked files.
        - ``hot``: list of ``(path, count)`` tuples, most-modified first.
        - ``cold``: list of files never touched in ``max_commits`` window.
        - ``churn_ratio``: fraction of tracked files touched in ``recent_commits``.
        - ``recent_touched_count``: absolute count of recently touched files.
        - ``mod_counts``: full Counter of modification counts.
    """
    tracked = _tracked_files(repo)
    mod_counts = _file_mod_counts(repo, max_commits=max_commits)
    recent = _recent_touched(repo, n_commits=recent_commits)

    # cold = tracked but never appeared in the mod_counts window
    touched_ever = set(mod_counts.keys())
    cold = sorted(tracked - touched_ever)

    # hot = top N by modification count
    hot = mod_counts.most_common(hot_n)

    churn_ratio = len(recent) / len(tracked) if tracked else 0.0

    return {
        "tracked": len(tracked),
        "hot": hot,
        "cold": cold,
        "churn_ratio": round(churn_ratio, 4),
        "recent_touched_count": len(recent),
        "mod_counts": mod_counts,
    }


def churn_report(repo: Path, recent_commits: int = 50) -> str:
    """One-liner for caretaker logs.

    Examples:
        >>> churn_report(Path("."))
        'churn 0.12 (80/672 touched in last 50 commits); hot: data/strokes.jsonl (341), docs/DEVLOG.md (128)'
        >>> churn_report(Path("."))
        'churn 0.00 (0/0 touched); empty repo?'
    """
    info = repo_churn(repo, hot_n=3, recent_commits=recent_commits)

    if info["tracked"] == 0:
        return "churn 0.00 (0/0 touched); empty repo?"

    hot_str = ", ".join(f"{path} ({count})" for path, count in info["hot"])
    return (
        f"churn {info['churn_ratio']:.2f} "
        f"({info['recent_touched_count']}/{info['tracked']} touched "
        f"in last {recent_commits} commits); "
        f"hot: {hot_str}"
    )
