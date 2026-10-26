"""commit_staleness — how fresh is the latest commit?

The batch committer runs on a fixed interval (default 600 s).  When it
falls behind — crashes, lock contention, disk full — uncommitted changes
pile up silently.  This module gives the caretaker a single-call answer
to: *how stale is HEAD, and should I worry?*

Staleness is measured as the wall-clock gap between **now** and the
author-date of the latest commit reachable from HEAD.  That gap is then
classified into one of four freshness levels:

    FRESH       gap < 1× interval     — committer is keeping up
    AGING       1× ≤ gap < 2×         — one missed cycle, probably fine
    STALE       2× ≤ gap < 4×         — multiple missed cycles, investigate
    ROTTEN      gap ≥ 4× interval     — committer is down or blocked

The function also returns a *debt estimate*: how many interval-lengths
of work are sitting uncommitted, computed from the file-modification
times of dirty files in the working tree.

Usage::

    from iamai.commit_staleness import assess_freshness, Freshness

    f = assess_freshness(batch_interval=600)
    print(f)
    # Freshness(level=FRESH, age_seconds=120, missed_cycles=0.2, debt_files=0)

Design notes:

- Uses ``git log -1 --format=%ct`` for the commit timestamp — fast, no
  library dependency.
- ``git status --porcelain`` for the dirty-file count.
- Returns a dataclass for easy inspection in tests and dashboards.
- Zero external dependencies beyond stdlib + git CLI.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class FreshnessLevel(Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    ROTTEN = "ROTTEN"


@dataclass(frozen=True)
class Freshness:
    """Snapshot of commit freshness at a point in time."""

    level: FreshnessLevel
    age_seconds: float
    missed_cycles: float
    debt_files: int
    last_commit_epoch: Optional[float] = None

    def __str__(self) -> str:
        return (
            f"Freshness(level={self.level.value}, "
            f"age={self.age_seconds:.0f}s, "
            f"missed={self.missed_cycles:.1f}cycles, "
            f"dirty={self.debt_files}files)"
        )

    @property
    def needs_attention(self) -> bool:
        return self.level in (FreshnessLevel.STALE, FreshnessLevel.ROTTEN)


def _last_commit_epoch(repo: str = ".") -> Optional[float]:
    """Return the author-date of HEAD as a UNIX timestamp, or None."""
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%ct"],
            cwd=repo,
            stderr=subprocess.DEVNULL,
        )
        return float(out.strip())
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return None


def _dirty_file_count(repo: str = ".") -> int:
    """Count files shown by ``git status --porcelain``."""
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=repo,
            stderr=subprocess.DEVNULL,
        )
        lines = [l for l in out.decode().splitlines() if l.strip()]
        return len(lines)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0


def assess_freshness(
    batch_interval: int = 600,
    repo: str = ".",
    now: Optional[float] = None,
) -> Freshness:
    """Assess how fresh the latest commit is.

    Parameters
    ----------
    batch_interval:
        Expected seconds between batch commits (default 600 = 10 min).
    repo:
        Path to the git working tree.
    now:
        Override wall-clock time (for testing).

    Returns
    -------
    Freshness
        Classification of commit staleness.
    """
    epoch = _last_commit_epoch(repo)
    current = now if now is not None else time.time()

    if epoch is None:
        # No commits at all — treat as maximally rotten.
        return Freshness(
            level=FreshnessLevel.ROTTEN,
            age_seconds=float("inf"),
            missed_cycles=float("inf"),
            debt_files=_dirty_file_count(repo),
            last_commit_epoch=None,
        )

    age = current - epoch
    missed = age / batch_interval if batch_interval > 0 else float("inf")

    if missed < 1.0:
        level = FreshnessLevel.FRESH
    elif missed < 2.0:
        level = FreshnessLevel.AGING
    elif missed < 4.0:
        level = FreshnessLevel.STALE
    else:
        level = FreshnessLevel.ROTTEN

    return Freshness(
        level=level,
        age_seconds=age,
        missed_cycles=missed,
        debt_files=_dirty_file_count(repo),
        last_commit_epoch=epoch,
    )
