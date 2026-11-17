"""unpushed_age — measure how old the oldest unpushed local commit is.

complements ``unpushed_count``: count tells you *how many* commits are
sitting unpushed; age tells you *how long* the oldest one has been
waiting.  a single unpushed commit that is forty minutes old is a
bigger problem than ten unpushed commits that are thirty seconds old.

the caretaker uses this to decide whether a push failure is "just
bad timing, self-heals next cycle" or "the deploy key has been broken
since the last container rebuild and a human needs to intervene."

thresholds (seconds)
--------------------
    fresh    < 600     (one batch cycle — normal jitter)
    aging    < 1800    (three cycles — something is off)
    stale    < 3600    (six cycles — push pipeline is broken)
    critical >= 3600   (an hour+ — data-loss risk on container recycle)

exit codes
----------
    0 — synced (no unpushed commits)
    1 — fresh
    2 — aging
    3 — stale
    4 — critical
    5 — cannot determine
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

THRESHOLDS = [
    (600, "fresh"),
    (1800, "aging"),
    (3600, "stale"),
]
CRITICAL_LABEL = "critical"

# exit codes
EXIT_SYNCED = 0
EXIT_FRESH = 1
EXIT_AGING = 2
EXIT_STALE = 3
EXIT_CRITICAL = 4
EXIT_UNKNOWN = 5


@dataclass
class AgeResult:
    """result of an unpushed-age check.

    Attributes
    ----------
    age_seconds : float or None
        age of the oldest unpushed commit in seconds; ``None`` when
        there are no unpushed commits or the check failed.
    unpushed_count : int
        number of local commits not yet on ``origin/main``.
    label : str
        one of ``synced``, ``fresh``, ``aging``, ``stale``, ``critical``,
        or ``unknown``.
    exit_code : int
        recommended process exit code (see module docstring).
    oldest_hash : str or None
        short hash of the oldest unpushed commit, or ``None``.
    error : str or None
        error message when the check could not be performed.
    """

    age_seconds: Optional[float]
    unpushed_count: int
    label: str
    exit_code: int
    oldest_hash: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "age_seconds": self.age_seconds,
            "unpushed_count": self.unpushed_count,
            "label": self.label,
            "exit_code": self.exit_code,
            "oldest_hash": self.oldest_hash,
            "error": self.error,
        }

    def summary(self) -> str:
        if self.label == "synced":
            return "synced: no unpushed commits"
        if self.error:
            return f"unknown: {self.error}"
        mins = self.age_seconds / 60
        return (
            f"{self.label}: oldest unpushed commit {self.oldest_hash} "
            f"is {mins:.1f} min old ({self.unpushed_count} unpushed)"
        )


def classify(age_seconds: Optional[float], unpushed_count: int) -> Tuple[str, int]:
    """return (label, exit_code) for a given age and count."""
    if unpushed_count == 0:
        return "synced", EXIT_SYNCED
    if age_seconds is None:
        return "unknown", EXIT_UNKNOWN
    for threshold, label in THRESHOLDS:
        if age_seconds < threshold:
            return label, [EXIT_FRESH, EXIT_AGING, EXIT_STALE][
                [t for t, _ in THRESHOLDS].index(threshold)
            ]
    return CRITICAL_LABEL, EXIT_CRITICAL


def _run(cmd: list[str], repo: Path, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(repo), timeout=timeout
    )


def measure_unpushed_age(repo: Path | str = ".") -> AgeResult:
    """measure the age of the oldest unpushed local commit.

    Parameters
    ----------
    repo : Path or str
        path to the git working tree.

    Returns
    -------
    AgeResult
        structured result with age, count, label, and exit code.
    """
    repo = Path(repo).resolve()

    # step 1: count unpushed commits
    count_proc = _run(
        ["git", "rev-list", "--count", "origin/main..HEAD"], repo
    )
    if count_proc.returncode != 0:
        return AgeResult(
            age_seconds=None,
            unpushed_count=0,
            label="unknown",
            exit_code=EXIT_UNKNOWN,
            error=count_proc.stderr.strip() or "git rev-list failed",
        )

    try:
        unpushed_count = int(count_proc.stdout.strip())
    except ValueError:
        return AgeResult(
            age_seconds=None,
            unpushed_count=0,
            label="unknown",
            exit_code=EXIT_UNKNOWN,
            error=f"non-integer rev-list output: {count_proc.stdout.strip()!r}",
        )

    if unpushed_count == 0:
        return AgeResult(
            age_seconds=None,
            unpushed_count=0,
            label="synced",
            exit_code=EXIT_SYNCED,
        )

    # step 2: find the oldest unpushed commit (last in the list)
    log_proc = _run(
        ["git", "rev-list", "origin/main..HEAD", "--reverse"], repo
    )
    if log_proc.returncode != 0:
        return AgeResult(
            age_seconds=None,
            unpushed_count=unpushed_count,
            label="unknown",
            exit_code=EXIT_UNKNOWN,
            error=log_proc.stderr.strip(),
        )

    lines = log_proc.stdout.strip().splitlines()
    if not lines:
        return AgeResult(
            age_seconds=None,
            unpushed_count=unpushed_count,
            label="unknown",
            exit_code=EXIT_UNKNOWN,
            error="rev-list returned no commits despite nonzero count",
        )

    oldest_hash = lines[0][:8]

    # step 3: get the timestamp of the oldest unpushed commit
    ts_proc = _run(
        ["git", "show", "-s", "--format=%ct", lines[0]], repo
    )
    if ts_proc.returncode != 0:
        return AgeResult(
            age_seconds=None,
            unpushed_count=unpushed_count,
            label="unknown",
            exit_code=EXIT_UNKNOWN,
            error=ts_proc.stderr.strip(),
        )

    try:
        commit_ts = int(ts_proc.stdout.strip())
    except ValueError:
        return AgeResult(
            age_seconds=None,
            unpushed_count=unpushed_count,
            label="unknown",
            exit_code=EXIT_UNKNOWN,
            error=f"non-integer timestamp: {ts_proc.stdout.strip()!r}",
        )

    age_seconds = time.time() - commit_ts
    label, exit_code = classify(age_seconds, unpushed_count)

    return AgeResult(
        age_seconds=age_seconds,
        unpushed_count=unpushed_count,
        label=label,
        exit_code=exit_code,
        oldest_hash=oldest_hash,
    )
