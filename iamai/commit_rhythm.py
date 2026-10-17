"""Commit rhythm: is the batch committer keeping its promise?

The batch committer pledges to commit every ``--interval`` seconds (default 600).
When it misses a beat the caretaker needs to know: was it a one-off slip,
or has the rhythm broken entirely?

This module reads the last N commit timestamps from ``git log``, computes
the gaps between consecutive commits, and classifies the current rhythm:

* **steady** — all recent gaps are within ±30 % of the target interval
* **drifting** — at least one gap exceeds 1.3× but none exceed 2×
* **broken** — at least one gap exceeds 2× the target interval
* **silent** — no commits found in the observation window

Usage::

    from iamai.commit_rhythm import CommitRhythm, rhythm_status

    cr = CommitRhythm(target_interval=600, window=5)
    verdict = cr.classify(gaps_seconds=[610, 595, 620, 580, 605])
    # -> "steady"

    print(rhythm_status())
    # "steady: 5/5 gaps within ±30% of 600s target"
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class CommitRhythm:
    """Configuration and classifier for commit cadence health.

    >>> cr = CommitRhythm(target_interval=600, window=5)
    >>> cr.classify([600, 600, 600, 600, 600])
    'steady'
    >>> cr.classify([600, 600, 1300, 600, 600])
    'broken'
    >>> cr.classify([600, 600, 800, 600, 600])
    'drifting'
    >>> cr.classify([])
    'silent'
    """

    target_interval: int = 600  # seconds (default batch interval)
    window: int = 5  # number of recent gaps to examine

    @property
    def drift_threshold(self) -> float:
        """Upper bound for 'steady': 1.3× the target."""
        return self.target_interval * 1.3

    @property
    def broken_threshold(self) -> float:
        """Upper bound before 'broken': 2× the target."""
        return self.target_interval * 2.0

    def classify(self, gaps_seconds: List[float]) -> str:
        """Classify commit rhythm from a list of inter-commit gaps.

        Parameters
        ----------
        gaps_seconds : list of float
            Seconds between consecutive commits, oldest-first.
            Length should be >= 1; empty list returns 'silent'.

        Returns
        -------
        str
            One of: steady, drifting, broken, silent.
        """
        if not gaps_seconds:
            return "silent"

        recent = gaps_seconds[-self.window:]
        if any(g >= self.broken_threshold for g in recent):
            return "broken"
        if any(g >= self.drift_threshold for g in recent):
            return "drifting"
        return "steady"

    def describe(self, gaps_seconds: List[float]) -> str:
        """Human-readable summary of the rhythm classification.

        >>> cr = CommitRhythm(target_interval=600, window=3)
        >>> cr.describe([610, 590, 605])
        'steady: 3/3 gaps within ±30% of 600s target'
        >>> cr.describe([])
        'silent: no commits in observation window'
        """
        verdict = self.classify(gaps_seconds)
        if verdict == "silent":
            return "silent: no commits in observation window"
        recent = gaps_seconds[-self.window:]
        in_range = sum(1 for g in recent if g < self.drift_threshold)
        return f"{verdict}: {in_range}/{len(recent)} gaps within ±30% of {self.target_interval}s target"


def git_commit_gaps(repo_root: Path = REPO_ROOT, count: int = 10) -> List[float]:
    """Return inter-commit gaps in seconds from the last ``count+1`` commits.

    Reads ``git log`` timestamps and computes consecutive gaps.
    Returns an empty list if the repo has fewer than 2 commits.
    """
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={count + 1}", "--format=%at"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        timestamps = [int(t) for t in result.stdout.strip().split("\n") if t.strip()]
        if len(timestamps) < 2:
            return []
        # git log outputs newest-first; reverse for chronological order
        timestamps.reverse()
        return [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return []


def rhythm_status(
    target_interval: int = 600,
    window: int = 5,
    repo_root: Path = REPO_ROOT,
) -> str:
    """One-liner status for caretaker dashboards.

    >>> # doctest: +SKIP
    >>> print(rhythm_status())
    steady: 5/5 gaps within ±30% of 600s target
    """
    gaps = git_commit_gaps(repo_root=repo_root, count=max(window + 1, 10))
    cr = CommitRhythm(target_interval=target_interval, window=window)
    return cr.describe(gaps)
