"""Commit compaction — detect commit density and recommend squash timing.

The IamAI writer commits every 600 seconds (10 minutes) via the batch
committer.  Over time the git log fills with small, incremental commits
that are individually meaningful but collectively noisy.  This module
measures commit density over a sliding window and classifies it so that
a caretaker or CI job can decide when to squash history.

Three public functions:

- ``commit_density(repo_path, window_minutes)`` — count commits in the
  recent window and return a density dict.
- ``classify_density(commits_per_hour)`` — map a rate to a verdict:
  ``sparse``, ``healthy``, ``dense``, or ``compact``.
- ``compaction_summary(repo_path, window_minutes)`` — one-liner for
  caretaker reports.

Scale (commits per hour of active writing):

==============  =================================================
verdict         meaning
==============  =================================================
``sparse``      < 2 cph — long gaps, nothing to squash
``healthy``     2–6 cph — normal batch-commit rhythm
``dense``       6–12 cph — consider squashing soon
``compact``     > 12 cph — squash recommended now
==============  =================================================

Edge cases:

- Empty repo (no commits) → density returns zero commits, ``sparse``.
- Window larger than repo history → counts all commits; the rate is
  still computed against the requested window (conservative).
- Shallow clones with truncated history → count is lower-bound.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

# Thresholds in commits per hour
_SPARSE = 2
_HEALTHY = 6
_DENSE = 12
# above _DENSE → compact


def _run_git(repo_path: Path, *args: str) -> Optional[str]:
    """Run a git command in the given repo, return stdout or None on error."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path)] + list(args),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _count_commits_in_window(repo_path: Path, window_minutes: int) -> int:
    """Count commits within the last ``window_minutes`` minutes."""
    since = f"{window_minutes} minutes ago"
    out = _run_git(repo_path, "rev-list", "--count", "--since", since, "HEAD")
    if out is None:
        return 0
    try:
        return int(out.strip())
    except ValueError:
        return 0


def _total_commits(repo_path: Path) -> int:
    """Total commit count on the current branch."""
    out = _run_git(repo_path, "rev-list", "--count", "HEAD")
    if out is None:
        return 0
    try:
        return int(out.strip())
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def commit_density(
    repo_path: Optional[str | Path] = None,
    window_minutes: int = 60,
) -> dict:
    """Measure commit density over a sliding window.

    Returns a dict::

        {
            "commits_in_window": 15,
            "window_minutes": 60,
            "commits_per_hour": 15.0,
            "total_commits": 1403,
            "verdict": "compact",
        }

    ``repo_path`` defaults to the current working directory.
    """
    if repo_path is None:
        repo_path = Path.cwd()
    repo_path = Path(repo_path)

    count = _count_commits_in_window(repo_path, window_minutes)
    total = _total_commits(repo_path)
    hours = max(window_minutes, 1) / 60.0
    rate = count / hours

    return {
        "commits_in_window": count,
        "window_minutes": window_minutes,
        "commits_per_hour": round(rate, 2),
        "total_commits": total,
        "verdict": classify_density(rate),
    }


def classify_density(commits_per_hour: float) -> str:
    """Map a commit rate to a density verdict.

    >>> classify_density(1.0)
    'sparse'
    >>> classify_density(4.0)
    'healthy'
    >>> classify_density(8.0)
    'dense'
    >>> classify_density(15.0)
    'compact'
    """
    if commits_per_hour < _SPARSE:
        return "sparse"
    if commits_per_hour < _HEALTHY:
        return "healthy"
    if commits_per_hour < _DENSE:
        return "dense"
    return "compact"


def compaction_summary(
    repo_path: Optional[str | Path] = None,
    window_minutes: int = 60,
) -> str:
    """One-liner for caretaker status reports.

    Example outputs::

        15 commits/hr (compact) — squash recommended, 1403 total
        4 commits/hr (healthy) — no action needed, 823 total
        0 commits/hr (sparse) — nothing to squash, 0 total
    """
    d = commit_density(repo_path, window_minutes)
    rate = d["commits_per_hour"]
    verdict = d["verdict"]
    total = d["total_commits"]

    if verdict == "compact":
        action = "squash recommended"
    elif verdict == "dense":
        action = "consider squashing"
    elif verdict == "healthy":
        action = "no action needed"
    else:
        action = "nothing to squash"

    return (
        f"{rate} commits/hr ({verdict}) — {action}, {total} total"
    )
