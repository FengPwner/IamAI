"""backlog_drain — how fast is the writer consuming its uncommitted backlog?

The IamAI writer produces strokes every 15 seconds, but the batch committer
only flushes every 600 seconds (10 minutes).  Between flushes the uncommitted
file count grows.  After a flush it drops.  The *drain rate* measures whether
the committer is keeping up.

Three public functions:

- ``snapshot(repo)`` — current uncommitted count + timestamp.
- ``drain_rate(snapshots)`` — files-per-minute change over a window of
  snapshots.  Negative means the backlog is shrinking (good); positive
  means it is growing (bad).
- ``drain_report(repo, snapshots)`` — one-liner for caretaker reports.

Drain-rate interpretation::

    rate < -1 fpm   →  draining   (committer outpacing writer)
    -1 ≤ rate ≤ 1   →  steady    (writer and committer balanced)
    rate > 1 fpm     →  growing   (backlog accumulating, investigate)

Edge cases:

- Zero or one snapshot → drain rate is 0.0 (insufficient data).
- All snapshots at the same timestamp → 0.0.
- Negative uncommitted count (git error) → excluded from calculation.

Usage::

    from iamai.backlog_drain import snapshot, drain_rate, drain_report

    s = snapshot(repo)          # {"count": 9, "at": 1729310400.0}
    history.append(s)
    rate = drain_rate(history)  # -1.5  (draining)
    print(drain_report(repo, history))
    # "draining at -1.5 fpm — 9 files pending"
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import TypedDict


class Snapshot(TypedDict):
    count: int
    at: float


def snapshot(repo: Path | str, at: float | None = None) -> Snapshot:
    """Capture the current uncommitted file count.

    Parameters
    ----------
    repo : path to the repository root.
    at : optional timestamp override (defaults to ``time.time()``).

    Returns
    -------
    Snapshot with ``count`` (int, may be -1 on git error) and ``at`` (float).
    """
    repo = Path(repo)
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            count = -1
        else:
            count = len([l for l in result.stdout.splitlines() if l.strip()])
    except (OSError, subprocess.SubprocessError):
        count = -1
    return {"count": count, "at": at if at is not None else time.time()}


def drain_rate(snapshots: list[Snapshot]) -> float:
    """Compute the backlog change rate in files per minute.

    Uses ordinary least-squares regression over the snapshot window so that
    noisy individual readings don't dominate.

    Parameters
    ----------
    snapshots : list of Snapshot dicts, ideally sorted by ``at`` ascending.

    Returns
    -------
    float — files per minute.  Negative = shrinking, positive = growing.
    Returns 0.0 when fewer than 2 valid snapshots exist.
    """
    valid = [s for s in snapshots if s["count"] >= 0]
    if len(valid) < 2:
        return 0.0

    # convert to (minutes_elapsed, count) pairs relative to first snapshot
    t0 = valid[0]["at"]
    points = [((s["at"] - t0) / 60.0, s["count"]) for s in valid]

    n = len(points)
    sum_x = sum(p[0] for p in points)
    sum_y = sum(p[1] for p in points)
    sum_xy = sum(p[0] * p[1] for p in points)
    sum_x2 = sum(p[0] ** 2 for p in points)

    denom = n * sum_x2 - sum_x ** 2
    if denom == 0:
        return 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denom
    return slope


def classify(rate: float) -> str:
    """Map a drain rate to a human-readable verdict."""
    if rate < -1.0:
        return "draining"
    elif rate > 1.0:
        return "growing"
    else:
        return "steady"


def drain_report(
    repo: Path | str,
    snapshots: list[Snapshot],
) -> str:
    """One-liner for caretaker reports."""
    current = snapshot(repo)
    rate = drain_rate(snapshots)
    verdict = classify(rate)
    pending = current["count"]
    return f"{verdict} at {rate:+.1f} fpm — {pending} files pending"
