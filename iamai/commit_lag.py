"""Commit-lag meter — how evenly spaced are recent commits?

The batch committer is supposed to push every *N* minutes.  When it
drifts or stalls the gap between consecutive commits grows.  This
module reads the last *k* commits via ``git log`` and reports:

* ``median_gap_s``  — median seconds between consecutive commits
* ``max_gap_s``     — worst single gap
* ``gaps``          — list of individual gaps (newest first)
* ``healthy``       — bool, True when median < threshold

Usage::

    from iamai.commit_lag import commit_lag, commit_lag_report

    info = commit_lag(repo, count=10)
    print(info["median_gap_s"])  # 612.4
    print(info["healthy"])       # True

    print(commit_lag_report(repo))
    # "healthy — median gap 612s across 10 commits (threshold 900s)"
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _recent_commit_times(repo: Path, count: int = 10) -> list[datetime]:
    """Return up to *count* commit timestamps, newest first."""
    try:
        out = subprocess.check_output(
            ["git", "log", f"-{count}", "--format=%aI"],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
        ).decode("utf-8").strip()
    except subprocess.CalledProcessError:
        return []
    if not out:
        return []
    return [datetime.fromisoformat(line) for line in out.split("\n") if line]


def commit_lag(
    repo: Path,
    count: int = 10,
    threshold_seconds: float = 900.0,
) -> dict:
    """Measure commit spacing for the last *count* commits.

    Parameters
    ----------
    repo:
        Repository root.
    count:
        How many commits to inspect (default 10).
    threshold_seconds:
        Median gap above this is considered unhealthy (default 900 s = 15 min).

    Returns
    -------
    dict with keys: ``median_gap_s``, ``max_gap_s``, ``gaps``,
    ``healthy``, ``commit_count``.
    """
    times = _recent_commit_times(repo, count + 1)  # need count+1 for count gaps
    if len(times) < 2:
        return {
            "median_gap_s": float("inf"),
            "max_gap_s": float("inf"),
            "gaps": [],
            "healthy": False,
            "commit_count": len(times),
        }

    gaps = [
        (times[i] - times[i + 1]).total_seconds()
        for i in range(len(times) - 1)
    ]
    sorted_gaps = sorted(gaps)
    mid = len(sorted_gaps) // 2
    if len(sorted_gaps) % 2 == 0:
        median = (sorted_gaps[mid - 1] + sorted_gaps[mid]) / 2.0
    else:
        median = sorted_gaps[mid]

    return {
        "median_gap_s": round(median, 1),
        "max_gap_s": round(max(gaps), 1),
        "gaps": [round(g, 1) for g in gaps],
        "healthy": median < threshold_seconds,
        "commit_count": len(times),
    }


def commit_lag_report(
    repo: Path,
    count: int = 10,
    threshold_seconds: float = 900.0,
) -> str:
    """One-line human-readable commit-lag summary.

    Example: ``"healthy — median gap 612s across 10 commits (threshold 900s)"``
    """
    info = commit_lag(repo, count=count, threshold_seconds=threshold_seconds)
    verdict = "healthy" if info["healthy"] else "lagging"
    if info["median_gap_s"] == float("inf"):
        return f"{verdict} — not enough commits to measure ({info['commit_count']} found)"
    return (
        f"{verdict} — median gap {info['median_gap_s']:.0f}s "
        f"across {info['commit_count']} commits "
        f"(threshold {threshold_seconds:.0f}s)"
    )
