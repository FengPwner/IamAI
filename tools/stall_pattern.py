#!/usr/bin/env python3
"""stall_pattern — classify writer stall behaviour from commit history.

The writer dies.  That's a fact, not a bug.  What matters is *how* it
dies: the same way every time (systematic), randomly (environmental),
or in a pattern that's getting worse (degrading).

This module pulls commit timestamps from ``git log`` and classifies
the stall pattern into one of four categories:

    ┌───────────────┬─────────────────────────────────────────────────┐
    │ Pattern       │ Meaning                                         │
    ├───────────────┼─────────────────────────────────────────────────┤
    │ regular       │ Stalls happen at ~fixed intervals.  Likely a    │
    │               │ resource limit (OOM killer, cgroup timeout).    │
    │ clustered     │ Stalls bunch in time windows.  Could be         │
    │               │ time-of-day (cron jobs stealing CPU) or         │
    │               │ load-dependent.                                 │
    │ accelerating  │ Gaps between stalls are shrinking.  The system  │
    │               │ is getting less stable over time.               │
    │ random        │ No discernible pattern.  Probably external —    │
    │               │ flaky network, shared-host noise.               │
    └───────────────┴─────────────────────────────────────────────────┘

Usage:
    python3 tools/stall_pattern.py [--commits 50] [--stall-gap 300]

``--stall-gap`` is the minimum seconds between commits to count as a
stall (default 300 = five minutes; the writer's cadence is 15 s, so
anything over 5 min means the writer was dead for a while).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import List, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def get_commit_timestamps(n: int = 50) -> list[datetime]:
    """Return the last *n* commit timestamps as timezone-aware datetimes."""
    result = subprocess.run(
        ["git", "log", f"-{n}", "--format=%aI"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    if result.returncode != 0:
        return []
    timestamps = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line:
            timestamps.append(datetime.fromisoformat(line))
    return timestamps


def compute_gaps(timestamps: list[datetime]) -> list[float]:
    """Seconds between consecutive commits (oldest-first order)."""
    if len(timestamps) < 2:
        return []
    ordered = sorted(timestamps)
    return [
        (b - a).total_seconds()
        for a, b in zip(ordered[:-1], ordered[1:])
    ]


def find_stalls(gaps: list[float], stall_gap: float = 300.0) -> list[int]:
    """Indices into *gaps* where the gap exceeds *stall_gap* seconds."""
    return [i for i, g in enumerate(gaps) if g >= stall_gap]


def classify_stalls(
    stall_indices: list[int],
    gaps: list[float],
    min_stalls: int = 3,
) -> dict:
    """Classify the stall pattern.

    Returns a dict with keys:
        pattern:  "regular" | "clustered" | "accelerating" | "random"
        confidence: 0.0–1.0
        stall_count: number of stalls detected
        mean_gap: average gap between stalls (in commit-index units)
        detail: human-readable explanation
    """
    n = len(stall_indices)
    if n < min_stalls:
        return {
            "pattern": "random",
            "confidence": 0.0,
            "stall_count": n,
            "mean_gap": 0.0,
            "detail": f"too few stalls ({n}) to classify reliably",
        }

    # gaps between consecutive stall positions
    stall_gaps = [
        stall_indices[i + 1] - stall_indices[i]
        for i in range(n - 1)
    ]
    mu = mean(stall_gaps)
    sd = stdev(stall_gaps) if len(stall_gaps) > 1 else 0.0
    cv = sd / mu if mu > 0 else float("inf")

    # --- regularity: low CV → regular intervals ---
    if cv < 0.3:
        return {
            "pattern": "regular",
            "confidence": max(0.0, 1.0 - cv),
            "stall_count": n,
            "mean_gap": mu,
            "detail": (
                f"stalls every ~{mu:.1f} commits (CV={cv:.2f}); "
                "likely a fixed resource limit"
            ),
        }

    # --- acceleration: are stalls getting closer together? ---
    first_half = stall_gaps[: len(stall_gaps) // 2]
    second_half = stall_gaps[len(stall_gaps) // 2 :]
    if first_half and second_half:
        mu1, mu2 = mean(first_half), mean(second_half)
        if mu1 > 0 and mu2 / mu1 < 0.7:
            return {
                "pattern": "accelerating",
                "confidence": min(1.0, 1.0 - mu2 / mu1),
                "stall_count": n,
                "mean_gap": mu,
                "detail": (
                    f"stall gap shrank from ~{mu1:.1f} to ~{mu2:.1f} commits; "
                    "system stability is degrading"
                ),
            }

    # --- clustering: high variance with some very small gaps ---
    small_gaps = [g for g in stall_gaps if g <= 2]
    if len(small_gaps) >= n // 3:
        return {
            "pattern": "clustered",
            "confidence": min(1.0, len(small_gaps) / n),
            "stall_count": n,
            "mean_gap": mu,
            "detail": (
                f"{len(small_gaps)}/{n - 1} stall-to-stall gaps ≤ 2 commits; "
                "stalls arrive in bursts"
            ),
        }

    # --- default: random ---
    return {
        "pattern": "random",
        "confidence": min(1.0, cv / 2.0) if cv < 2.0 else 0.5,
        "stall_count": n,
        "mean_gap": mu,
        "detail": (
            f"CV={cv:.2f}, no regularity, acceleration, or clustering detected"
        ),
    }


def analyse(
    n_commits: int = 50,
    stall_gap: float = 300.0,
) -> dict:
    """End-to-end: pull git log → find stalls → classify."""
    timestamps = get_commit_timestamps(n_commits)
    gaps = compute_gaps(timestamps)
    stall_indices = find_stalls(gaps, stall_gap)
    result = classify_stalls(stall_indices, gaps)
    result["total_commits"] = len(timestamps)
    result["total_gaps"] = len(gaps)
    result["stall_gap_threshold"] = stall_gap
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify writer stall patterns")
    parser.add_argument("--commits", type=int, default=50,
                        help="number of recent commits to analyse")
    parser.add_argument("--stall-gap", type=float, default=300.0,
                        help="minimum seconds to count as a stall")
    args = parser.parse_args()

    result = analyse(n_commits=args.commits, stall_gap=args.stall_gap)
    print(f"pattern:    {result['pattern']}")
    print(f"confidence: {result['confidence']:.2f}")
    print(f"stalls:     {result['stall_count']} in {result['total_commits']} commits")
    print(f"detail:     {result['detail']}")


if __name__ == "__main__":
    main()
