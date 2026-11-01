#!/usr/bin/env python3
"""push_gap_analyzer.py — measure time gaps between successive pushes.

Frequent small pushes are healthy. Long gaps between pushes mean
either the batch committer is broken, or something is blocking the
pipeline. This tool quantifies push rhythm from git reflog.

Outputs:
  - push_count: number of push events in the window
  - gaps_s: list of seconds between consecutive pushes
  - min/max/mean/median gap in seconds
  - trend: 'increasing' | 'decreasing' | 'flat'
  - pattern: 'steady' | 'bursty' | 'erratic'
  - health_score: 0-100 composite

Usage:
    python3 tools/push_gap_analyzer.py
    python3 tools/push_gap_analyzer.py --window 48
    python3 tools/push_gap_analyzer.py --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median, mean

REPO = Path(__file__).resolve().parent.parent


def get_push_timestamps(repo: Path = REPO, hours: int = 24) -> list[float]:
    """Extract push event timestamps from git reflog for origin/main.

    Returns a sorted list of unix timestamps (oldest first).
    """
    try:
        result = subprocess.run(
            [
                "git",
                "reflog",
                "show",
                "origin/main",
                "--format=%gd|%gs|%ct",
                f"--since={hours} hours ago",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo),
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if result.returncode != 0:
        return []

    timestamps: list[float] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        # reflog lines look like: "0abc123 origin/main: push from ..."
        # or "0abc123 origin/main: update by push"
        lower = line.lower()
        if "push" not in lower and "update" not in lower:
            continue
        parts = line.split("|")
        if len(parts) < 3:
            continue
        try:
            ts = float(parts[-1])
            timestamps.append(ts)
        except ValueError:
            continue

    timestamps.sort()
    return timestamps


def compute_gaps(timestamps: list[float]) -> list[float]:
    """Compute seconds between consecutive push events."""
    if len(timestamps) < 2:
        return []
    gaps: list[float] = []
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        if gap > 0:
            gaps.append(gap)
    return gaps


def classify_trend(gaps: list[float]) -> str:
    """Classify whether gaps are increasing, decreasing, or flat.

    Compares the mean of the first half vs the second half.
    Returns 'flat' when there are fewer than 4 gaps.
    """
    if len(gaps) < 4:
        return "flat"
    mid = len(gaps) // 2
    first_half = mean(gaps[:mid])
    second_half = mean(gaps[mid:])
    if first_half == 0:
        return "increasing" if second_half > 0 else "flat"
    ratio = second_half / first_half
    if ratio > 1.3:
        return "increasing"
    elif ratio < 0.7:
        return "decreasing"
    return "flat"


def classify_pattern(gaps: list[float]) -> str:
    """Classify push rhythm as steady, bursty, or erratic.

    Uses coefficient of variation (CV = stdev / mean).
      CV < 0.5  → steady
      CV < 1.5  → bursty
      CV >= 1.5 → erratic
    """
    if len(gaps) < 2:
        return "unknown"
    avg = mean(gaps)
    if avg == 0:
        return "steady"
    variance = sum((g - avg) ** 2 for g in gaps) / (len(gaps) - 1)
    stdev = variance**0.5
    cv = stdev / avg
    if cv < 0.5:
        return "steady"
    elif cv < 1.5:
        return "bursty"
    return "erratic"


def health_score(
    gaps: list[float],
    push_count: int,
    trend: str,
    window_hours: int,
) -> int:
    """Score push health 0-100.

    Scoring:
      +40  for ≥10 pushes in window
      +20  for ≥5 pushes
      +20  for steady pattern
      +20  for flat or decreasing trend
    Deductions:
      -10  per hour without any push (capped at -40)
    """
    score = 0
    if push_count >= 10:
        score += 40
    elif push_count >= 5:
        score += 20

    pattern = classify_pattern(gaps)
    if pattern == "steady":
        score += 20
    elif pattern == "bursty":
        score += 10

    if trend in ("flat", "decreasing"):
        score += 20

    if gaps:
        max_gap = max(gaps)
        gap_hours = max_gap / 3600
        score -= int(min(40, gap_hours * 10))

    if push_count == 0:
        score = 0

    return max(0, min(100, score))


def analyze(repo: Path = REPO, hours: int = 24) -> dict:
    """Run full push gap analysis and return a result dict."""
    timestamps = get_push_timestamps(repo, hours)
    gaps = compute_gaps(timestamps)
    trend = classify_trend(gaps)
    pattern = classify_pattern(gaps)

    result: dict = {
        "push_count": len(timestamps),
        "window_hours": hours,
        "gaps_s": [round(g, 1) for g in gaps],
        "trend": trend,
        "pattern": pattern,
    }

    if gaps:
        result["min_gap_s"] = round(min(gaps), 1)
        result["max_gap_s"] = round(max(gaps), 1)
        result["mean_gap_s"] = round(mean(gaps), 1)
        result["median_gap_s"] = round(median(gaps), 1)

    result["health_score"] = health_score(
        gaps, len(timestamps), trend, hours
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze push timing gaps"
    )
    parser.add_argument(
        "--window",
        type=int,
        default=24,
        help="Hours to look back (default: 24)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output as JSON",
    )
    args = parser.parse_args()

    result = analyze(hours=args.window)

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"pushes in last {args.window}h: {result['push_count']}")
        if result["gaps_s"]:
            print(f"gaps (s): min={result['min_gap_s']}, "
                  f"max={result['max_gap_s']}, "
                  f"mean={result['mean_gap_s']}, "
                  f"median={result['median_gap_s']}")
        print(f"trend: {result['trend']}")
        print(f"pattern: {result['pattern']}")
        print(f"health: {result['health_score']}/100")


if __name__ == "__main__":
    main()
