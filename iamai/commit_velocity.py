"""Commit velocity — is the repo accelerating or slowing down?

While ``cadence_drift`` measures how far actual stroke intervals wander
from the configured target, and ``stroke_entropy`` measures variety,
this module captures *momentum*: whether commits are arriving faster or
slower compared to the previous observation window.

Model
-----
Split the last ``2 × window`` commits into two halves — *recent* and
*previous*.  Compute commits-per-hour for each half, then derive:

==============  =================================================
verdict         meaning
==============  =================================================
``accelerating``  recent rate > 1.2× previous rate
``steady``        recent rate within ±20% of previous rate
``decelerating``  recent rate < 0.8× previous rate
``stalled``       zero commits in the recent window
==============  =================================================

``velocity_report`` returns a one-liner for caretaker logs::

    from iamai.commit_velocity import velocity, velocity_report
    info = velocity(repo, window_hours=1)
    print(info["verdict"])       # "steady"
    print(info["recent_rate"])   # 6.2
    print(velocity_report(repo))
    # "steady — 6.2 commits/hr (prev 5.8), ratio 1.07"
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _recent_commit_timestamps(repo: Path, n: int) -> list[float]:
    """Return the last *n* commit timestamps as Unix epoch floats.

    Uses ``git log`` so we never touch .git internals.
    """
    try:
        out = subprocess.check_output(
            ["git", "log", f"--max-count={n}", "--format=%ct"],
            cwd=repo,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    timestamps: list[float] = []
    for line in out.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.isdigit():
            timestamps.append(float(line))
    return timestamps


def velocity(
    repo: Path | str | None = None,
    window_hours: float = 1.0,
) -> dict:
    """Measure commit velocity over two consecutive windows.

    Parameters
    ----------
    repo:
        Path to the repository root.  Defaults to this project's root.
    window_hours:
        Size of each observation window in hours.  The function looks
        back ``2 × window_hours`` from the latest commit.

    Returns
    -------
    dict with keys: ``recent_rate``, ``previous_rate``, ``ratio``,
    ``verdict``, ``window_hours``, ``recent_count``, ``previous_count``.
    """
    if repo is None:
        repo = Path(__file__).resolve().parent.parent
    repo = Path(repo)

    window_secs = window_hours * 3600
    # Fetch enough commits to cover two windows.  Even at 1 commit/min,
    # 2 hours = 120 commits; triple for safety margin.
    max_commits = int(window_hours * 2 * 120) + 50
    timestamps = _recent_commit_timestamps(repo, max_commits)

    if not timestamps:
        return {
            "recent_rate": 0.0,
            "previous_rate": 0.0,
            "ratio": 0.0,
            "verdict": "stalled",
            "window_hours": window_hours,
            "recent_count": 0,
            "previous_count": 0,
        }

    now = timestamps[0]  # most recent commit
    recent_cutoff = now - window_secs
    previous_cutoff = recent_cutoff - window_secs

    recent_count = sum(1 for t in timestamps if t > recent_cutoff)
    previous_count = sum(1 for t in timestamps if previous_cutoff < t <= recent_cutoff)

    recent_rate = recent_count / window_hours if window_hours > 0 else 0.0
    previous_rate = previous_count / window_hours if window_hours > 0 else 0.0

    if previous_rate > 0:
        ratio = recent_rate / previous_rate
    elif recent_rate > 0:
        ratio = float("inf")
    else:
        ratio = 0.0

    # Classify
    if recent_count == 0:
        verdict = "stalled"
    elif ratio > 1.2:
        verdict = "accelerating"
    elif ratio < 0.8:
        verdict = "decelerating"
    else:
        verdict = "steady"

    return {
        "recent_rate": round(recent_rate, 2),
        "previous_rate": round(previous_rate, 2),
        "ratio": round(ratio, 3) if ratio != float("inf") else float("inf"),
        "verdict": verdict,
        "window_hours": window_hours,
        "recent_count": recent_count,
        "previous_count": previous_count,
    }


def velocity_report(
    repo: Path | str | None = None,
    window_hours: float = 1.0,
) -> str:
    """One-line human-readable summary."""
    info = velocity(repo, window_hours)
    if info["verdict"] == "stalled":
        return f"stalled — no commits in the last {info['window_hours']}h"
    return (
        f"{info['verdict']} — {info['recent_rate']} commits/hr "
        f"(prev {info['previous_rate']}), ratio {info['ratio']}"
    )
