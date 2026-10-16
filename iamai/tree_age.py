"""Tree age — when was each directory last touched?

A self-writing repository grows unevenly. The writer rotates through six
stroke kinds, but tests, tools, and infrastructure directories evolve at
their own pace — some getting commits every hour, others going stale for
days. Staleness is not always a problem (stable code does not need
churn), but *unintended* staleness is a risk: a directory nobody has
touched in a week may contain broken imports or outdated assumptions.

This module answers two questions:

1. **How old is each directory?** — measured as seconds since the most
   recent commit that modified a file in that directory.
2. **Which directories are stale?** — those exceeding a configurable
   threshold (default: 24 hours).

Implementation uses ``git log`` with a pathspec per directory. This is
cheap for the ~30 top-level directories in IamAI and avoids scanning
every file individually.

Usage::

    from iamai.tree_age import directory_ages, stale_directories, tree_age_summary

    ages = directory_ages()
    # {"iamai": 45.2, "tests": 120.7, "docs": 600.3, "notes": 30.1, ...}

    stale = stale_directories(threshold_hours=24)
    # ["legacy", "archive"]

    print(tree_age_summary())
    # "23 directories tracked, 21 fresh (<24h), 2 stale: legacy (3d), archive (5d)"

Design choices:

- Pure reads; does not modify any files.
- Uses ``git log -1 --format=%ct -- <path>`` per directory, which is O(1)
  per directory regardless of history depth.
- Ignores ``.git`` and ``__pycache__`` directories.
- Returns ``None`` for directories with no git history (untracked).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories that are noise in an age report.
_IGNORE = {".git", "__pycache__", ".pytest_cache", "node_modules", ".mypy_cache"}


def _git_last_modified(directory: Path, root: Path) -> Optional[float]:
    """Return the epoch timestamp of the most recent commit touching *directory*.

    Returns ``None`` when git has no record for the path (empty directory,
    entirely untracked, or git is unavailable).
    """
    try:
        rel = directory.relative_to(root)
    except ValueError:
        return None

    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", str(rel)],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(root),
        )
        if result.returncode != 0:
            return None
        text = result.stdout.strip()
        if not text:
            return None
        return float(text)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None


def directory_ages(
    root: Optional[Path | str] = None,
    depth: int = 1,
    now: Optional[float] = None,
) -> dict[str, float]:
    """Map each directory to seconds since its last commit.

    Parameters
    ----------
    root : Path or str, optional
        Repository root. Defaults to the IamAI repo.
    depth : int
        How many levels deep to scan. Default 1 (top-level only).
    now : float, optional
        Current epoch time. Defaults to ``time.time()``. Override in tests
        for deterministic results.

    Returns
    -------
    dict[str, float]
        Directory name → age in seconds. Directories with no git history
        are excluded.
    """
    if root is None:
        root = REPO_ROOT
    root = Path(root)
    if now is None:
        now = time.time()

    ages: dict[str, float] = {}

    for dirpath, dirnames, filenames in root.walk():
        # Prune ignored directories.
        dirnames[:] = [d for d in dirnames if d not in _IGNORE]

        current = Path(dirpath)
        # Check depth constraint.
        try:
            rel_depth = len(current.relative_to(root).parts)
        except ValueError:
            continue
        if rel_depth > depth:
            dirnames.clear()
            continue

        # Skip empty directories.
        if not filenames and not dirnames:
            continue

        # Skip the root itself (we report subdirectories).
        if current == root:
            continue

        last_modified = _git_last_modified(current, root)
        if last_modified is not None:
            rel_name = str(current.relative_to(root))
            ages[rel_name] = round(now - last_modified, 1)

    return ages


def stale_directories(
    root: Optional[Path | str] = None,
    threshold_hours: float = 24.0,
    now: Optional[float] = None,
) -> list[dict[str, float]]:
    """List directories older than the threshold.

    Returns a list of dicts with ``name`` and ``age_seconds`` keys,
    sorted from oldest to newest.
    """
    ages = directory_ages(root=root, now=now)
    threshold_seconds = threshold_hours * 3600

    stale = [
        {"name": name, "age_seconds": age}
        for name, age in ages.items()
        if age > threshold_seconds
    ]
    stale.sort(key=lambda d: d["age_seconds"], reverse=True)
    return stale


def tree_age_summary(
    root: Optional[Path | str] = None,
    threshold_hours: float = 24.0,
    now: Optional[float] = None,
) -> str:
    """One-liner for caretaker status reports.

    Example::

        "23 directories tracked, 21 fresh (<24h), 2 stale: legacy (3d 4h), archive (5d 12h)"
    """
    ages = directory_ages(root=root, now=now)
    if not ages:
        return "no directories found"

    total = len(ages)
    threshold_seconds = threshold_hours * 3600

    stale = [
        (name, age)
        for name, age in ages.items()
        if age > threshold_seconds
    ]
    stale.sort(key=lambda x: x[1], reverse=True)

    fresh_count = total - len(stale)

    def _human_age(seconds: float) -> str:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        if days > 0:
            return f"{days}d {hours}h"
        minutes = int((seconds % 3600) // 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    threshold_label = f"{threshold_hours:g}h"
    if stale:
        stale_detail = ", ".join(
            f"{name} ({_human_age(age)})" for name, age in stale[:5]
        )
        if len(stale) > 5:
            stale_detail += f", +{len(stale) - 5} more"
        return (
            f"{total} directories tracked, "
            f"{fresh_count} fresh (<{threshold_label}), "
            f"{len(stale)} stale: {stale_detail}"
        )

    return f"{total} directories tracked, all fresh (<{threshold_label})"
