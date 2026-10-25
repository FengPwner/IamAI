"""Commit momentum — is the commit rate accelerating, steady, or slowing?

Most monitoring tools in this repo answer *snapshot* questions: "is the
writer alive right now?"  ``commit_momentum`` answers a *trend* question:
**compared to a few hours ago, are commits arriving faster or slower?**

Concept
-------

Pick a rolling window (default 12 h).  Split it into two equal halves:

* **older half** — from ``now - window`` to ``now - window/2``
* **newer half** — from ``now - window/2`` to ``now``

Count commits that fall in each half and compute a ratio::

    ratio  = newer_count / older_count   (clamped: 0 if both are zero)

Classification::

    accelerating  ratio >= 1.30   — picking up pace
    steady        0.70 <= ratio < 1.30
    decelerating  0.30 <= ratio < 0.70
    stalled       ratio < 0.30 OR newer_count == 0

Why this matters
----------------

A ``repo_pulse`` reading of "degraded" tells you something is off *now*.
Commit momentum tells you the *direction*: if momentum is decelerating
over several caretaker visits, the system is trending toward a stall even
if it hasn't stalled yet.  Conversely, accelerating momentum after a
restart is a positive signal that the system is recovering.

Usage::

    from iamai.commit_momentum import CommitMomentum, momentum_report

    cm = CommitMomentum(window_hours=12)
    result = cm.evaluate(commit_timestamps=[...])
    print(result.verdict)   # "accelerating" | "steady" | "decelerating" | "stalled"

    report = momentum_report()  # CLI one-liner
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommitMomentum:
    """Configuration for commit-momentum measurement.

    Parameters
    ----------
    window_hours:
        Total rolling window in hours (default 12).  The window is split
        in half: older half and newer half.
    accel_threshold:
        Ratio at or above which momentum is "accelerating" (default 1.30).
    decel_threshold:
        Ratio below which momentum is "decelerating" (default 0.70).
    stall_threshold:
        Ratio below which momentum is "stalled" (default 0.30).  Also
        triggered when newer_count is zero regardless of ratio.
    """

    window_hours: float = 12.0
    accel_threshold: float = 1.30
    decel_threshold: float = 0.70
    stall_threshold: float = 0.30

    @property
    def window_seconds(self) -> float:
        return self.window_hours * 3600

    @property
    def half_seconds(self) -> float:
        return self.window_seconds / 2

    def evaluate(
        self,
        commit_timestamps: Sequence[float],
        now: Optional[float] = None,
    ) -> "MomentumResult":
        """Compute momentum from a list of Unix epoch timestamps.

        Parameters
        ----------
        commit_timestamps:
            Unix epoch seconds for each commit (need not be sorted).
        now:
            Reference time (default: current time).

        Returns
        -------
        MomentumResult with counts, ratio, and verdict.
        """
        if now is None:
            now = time.time()

        window_start = now - self.window_seconds
        midpoint = now - self.half_seconds

        older_count = 0
        newer_count = 0

        for ts in commit_timestamps:
            if ts < window_start:
                continue  # outside window
            if ts < midpoint:
                older_count += 1
            else:
                newer_count += 1

        if older_count == 0 and newer_count == 0:
            ratio = 0.0
        elif older_count == 0:
            # No commits in the older half but some in the newer — treat
            # as maximum acceleration signal.
            ratio = float(newer_count)  # ratio is effectively infinite
        else:
            ratio = newer_count / older_count

        verdict = classify_momentum(
            ratio,
            newer_count,
            accel=self.accel_threshold,
            decel=self.decel_threshold,
            stall=self.stall_threshold,
        )

        return MomentumResult(
            older_count=older_count,
            newer_count=newer_count,
            ratio=round(ratio, 4),
            verdict=verdict,
            window_hours=self.window_hours,
        )


@dataclass(frozen=True)
class MomentumResult:
    """Outcome of a commit-momentum evaluation."""

    older_count: int
    newer_count: int
    ratio: float
    verdict: str  # "accelerating" | "steady" | "decelerating" | "stalled"
    window_hours: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "older_count": self.older_count,
            "newer_count": self.newer_count,
            "ratio": self.ratio,
            "verdict": self.verdict,
            "window_hours": self.window_hours,
        }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_momentum(
    ratio: float,
    newer_count: int,
    *,
    accel: float = 1.30,
    decel: float = 0.70,
    stall: float = 0.30,
) -> str:
    """Classify a momentum ratio into a verdict string.

    Parameters
    ----------
    ratio:
        newer_count / older_count (or 0 if both zero).
    newer_count:
        Absolute count in the newer half — used to force "stalled"
        when zero regardless of ratio.
    accel, decel, stall:
        Threshold boundaries.

    Returns
    -------
    One of "accelerating", "steady", "decelerating", "stalled".
    """
    if newer_count == 0:
        return "stalled"
    if ratio >= accel:
        return "accelerating"
    if ratio >= decel:
        return "steady"
    if ratio < stall:
        return "stalled"
    return "decelerating"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def fetch_commit_timestamps(
    repo: Path = REPO_ROOT,
    max_count: int = 5000,
) -> List[float]:
    """Read recent commit timestamps from git log.

    Returns a list of Unix epoch floats, newest first.
    """
    try:
        output = subprocess.check_output(
            ["git", "log", f"--max-count={max_count}", "--format=%at"],
            cwd=str(repo),
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return []

    timestamps: List[float] = []
    for line in output.strip().split("\n"):
        line = line.strip()
        if line:
            try:
                timestamps.append(float(line))
            except ValueError:
                continue
    return timestamps


# ---------------------------------------------------------------------------
# High-level report
# ---------------------------------------------------------------------------

def momentum_report(
    window_hours: float = 12.0,
    repo: Path = REPO_ROOT,
) -> MomentumResult:
    """One-liner: fetch commits and return a MomentumResult."""
    cm = CommitMomentum(window_hours=window_hours)
    timestamps = fetch_commit_timestamps(repo=repo)
    return cm.evaluate(timestamps)
