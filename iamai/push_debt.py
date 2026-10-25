"""Push debt — how far behind the remote are we?

Unpushed commits accumulate like technical debt: each one increases the
chance of a painful merge conflict on the next push.  ``commit_lag``
counts them; this module scores the *risk* and tells the caretaker what
to do about it.

Risk model
----------
Three signals feed the score:

==============  =================================================
signal          source
==============  =================================================
``count``       number of unpushed commits (``git log @{u}..HEAD``)
``age_hours``   hours since the oldest unpushed commit
``conflict``    whether a dry-run rebase onto the remote tip fails
==============  =================================================

Score is 0–100, computed as::

    score = min(100, count * 10 + age_hours * 5 + conflict_penalty)

where ``conflict_penalty`` is 30 if a dry-run rebase fails, else 0.

==============  =================================================
verdict         meaning
==============  =================================================
``clean``       score 0 — nothing to push
``low``         score 1–30 — push when convenient
``medium``      score 31–60 — push soon, conflicts likely growing
``high``        score 61+ — push now, expect resolution work
==============  =================================================

Usage::

    from iamai.push_debt import push_debt, push_debt_report

    info = push_debt(repo=Path("."))
    print(info["score"])    # 45
    print(info["verdict"])  # "medium"
    print(push_debt_report(Path(".")))
    # "medium (45/100): 4 unpushed commits, oldest 2.3h ago"
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _unpushed_commits(repo: Path) -> list[dict[str, str]]:
    """Return list of unpushed commits with hash and timestamp.

    Uses ``git log @{u}..HEAD`` so we only see commits not yet on the
    remote tracking branch.  Falls back to comparing with origin/main
    if @{u} is not set.
    """
    result = _run(
        ["git", "log", "@{u}..HEAD", "--format=%H %ct"],
        repo,
    )
    if result.returncode != 0:
        # fallback: compare with origin/main
        result = _run(
            ["git", "log", "origin/main..HEAD", "--format=%H %ct"],
            repo,
        )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    commits = []
    for line in result.stdout.strip().splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            commits.append({"hash": parts[0], "timestamp": parts[1]})
    return commits


def _oldest_unpushed_age_hours(commits: list[dict[str, str]]) -> float:
    """Hours since the oldest unpushed commit."""
    if not commits:
        return 0.0
    oldest_ts = min(float(c["timestamp"]) for c in commits)
    now = datetime.now(timezone.utc).timestamp()
    return (now - oldest_ts) / 3600.0


def _would_conflict(repo: Path) -> bool:
    """Check if rebasing onto the remote tip would produce conflicts.

    Performs a dry-run: fetches, then attempts ``git merge-tree``
    between HEAD and the remote tip.  Falls back to False on any error
    (we'd rather under-report than crash).
    """
    # fetch first to make sure origin/main is fresh
    _run(["git", "fetch", "origin", "--quiet"], repo)

    # find the merge base
    base_result = _run(
        ["git", "merge-base", "HEAD", "origin/main"],
        repo,
    )
    if base_result.returncode != 0:
        return False

    # use merge-tree to simulate
    merge_result = _run(
        ["git", "merge-tree", base_result.stdout.strip(), "HEAD", "origin/main"],
        repo,
    )
    if merge_result.returncode != 0:
        return False

    # merge-tree outputs conflict markers if there are conflicts
    return "changed in both" in merge_result.stdout


def push_debt(repo: Path) -> dict[str, Any]:
    """Compute push debt score and verdict.

    Args:
        repo: path to the git repository.

    Returns:
        Dictionary with keys: ``count``, ``age_hours``, ``conflict``,
        ``score``, ``verdict``.
    """
    commits = _unpushed_commits(repo)
    count = len(commits)
    age_hours = round(_oldest_unpushed_age_hours(commits), 2)
    conflict = _would_conflict(repo) if count > 0 else False

    conflict_penalty = 30 if conflict else 0
    score = min(100, count * 10 + int(age_hours * 5) + conflict_penalty)

    if score == 0:
        verdict = "clean"
    elif score <= 30:
        verdict = "low"
    elif score <= 60:
        verdict = "medium"
    else:
        verdict = "high"

    return {
        "count": count,
        "age_hours": age_hours,
        "conflict": conflict,
        "score": score,
        "verdict": verdict,
    }


def push_debt_report(repo: Path) -> str:
    """One-liner for caretaker logs.

    Examples:
        >>> push_debt_report(Path("."))
        'clean (0/100): all pushed'
        >>> push_debt_report(Path("."))
        'medium (45/100): 4 unpushed commits, oldest 2.3h ago'
    """
    info = push_debt(repo)
    if info["verdict"] == "clean":
        return "clean (0/100): all pushed"
    return (
        f'{info["verdict"]} ({info["score"]}/100): '
        f'{info["count"]} unpushed commits, oldest {info["age_hours"]}h ago'
        + (", conflict likely" if info["conflict"] else "")
    )
