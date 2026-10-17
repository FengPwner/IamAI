"""Commit stability — is the commit cadence holding steady?

Existing modules answer *what* is in a commit (``commit_dispersion``),
*how long since* the last one (``commit_gap``), and *whether the writer
is producing* (``writer_pulse``).  None of them tell the caretaker
whether commits arrive at a **regular rhythm** or in erratic bursts.

This module reads recent commit timestamps via ``git log --format=%ct``
and computes:

* ``intervals``       — list of inter-commit gaps (seconds), newest first
* ``mean_interval``   — average gap
* ``cv``              — coefficient of variation (std / mean)
* ``jitter``          — mean absolute deviation from the mean
* ``stability``       — float 0–1, where 1 = perfectly regular
* ``verdict``         — ``"steady"``, ``"wobbly"``, or ``"erratic"``

Verdict thresholds::

    cv ≤ 0.3   →  steady
    cv ≤ 0.7   →  wobbly
    cv > 0.7   →  erratic

Stability score formula::

    stability = max(0, 1 - cv)

This gives 1.0 for a perfectly regular cadence and approaches 0 as
intervals become highly variable.

Usage::

    from iamai.commit_stability import commit_stability, stability_report

    info = commit_stability(repo, count=15)
    print(info["cv"])          # 0.42
    print(info["verdict"])     # "wobbly"

    print(stability_report(repo))
    # "wobbly — cv 0.42, mean gap 612s across 15 commits"
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path


def _commit_timestamps(repo: Path, count: int = 15) -> list[float]:
    """Return Unix timestamps of the last *count* commits, newest first."""
    try:
        out = subprocess.check_output(
            ["git", "log", f"-{count}", "--format=%ct"],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="replace").strip()
    except subprocess.CalledProcessError:
        return []

    timestamps: list[float] = []
    for line in out.split("\n"):
        line = line.strip()
        if line and line.isdigit():
            timestamps.append(float(line))
    return timestamps


def _intervals(timestamps: list[float]) -> list[float]:
    """Compute inter-commit gaps (seconds) from newest-first timestamps."""
    if len(timestamps) < 2:
        return []
    return [timestamps[i] - timestamps[i + 1] for i in range(len(timestamps) - 1)]


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def commit_stability(
    repo: Path,
    count: int = 15,
) -> dict:
    """Measure commit cadence regularity over the last *count* commits.

    Parameters
    ----------
    repo:
        Repository root.
    count:
        How many commits to inspect (default 15).

    Returns
    -------
    dict with keys:
        ``intervals``, ``mean_interval``, ``cv``, ``jitter``,
        ``stability``, ``verdict``, ``commits_inspected``.
    """
    ts = _commit_timestamps(repo, count=count)
    if len(ts) < 2:
        return {
            "intervals": [],
            "mean_interval": 0.0,
            "cv": 0.0,
            "jitter": 0.0,
            "stability": 0.0,
            "verdict": "unknown",
            "commits_inspected": len(ts),
        }

    ivs = _intervals(ts)
    mu = _mean(ivs)
    sigma = _std(ivs, mu)

    cv = sigma / mu if mu > 0 else 0.0
    jitter = _mean([abs(v - mu) for v in ivs])
    stability = max(0.0, 1.0 - cv)

    if cv <= 0.3:
        verdict = "steady"
    elif cv <= 0.7:
        verdict = "wobbly"
    else:
        verdict = "erratic"

    return {
        "intervals": ivs,
        "mean_interval": round(mu, 1),
        "cv": round(cv, 3),
        "jitter": round(jitter, 1),
        "stability": round(stability, 3),
        "verdict": verdict,
        "commits_inspected": len(ts),
    }


def stability_report(repo: Path, count: int = 15) -> str:
    """One-line human-readable stability summary."""
    info = commit_stability(repo, count=count)
    if info["commits_inspected"] < 2:
        return "insufficient data (need ≥ 2 commits)"
    return (
        f"{info['verdict']} — cv {info['cv']}, "
        f"mean gap {info['mean_interval']}s "
        f"across {info['commits_inspected']} commits "
        f"(stability {info['stability']})"
    )
