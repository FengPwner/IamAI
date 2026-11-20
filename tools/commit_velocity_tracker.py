#!/usr/bin/env python3
"""commit_velocity_tracker.py — measure how commit rate changes over time.

The repo accumulates commits at a nominal cadence of one every 600
seconds.  But actual commit timing drifts: process deaths, catch-up
bursts, caretaker interventions, and container scheduling all create
local accelerations and decelerations.

This module reads the git log (or a pre-parsed list of commit
timestamps), divides the timeline into fixed-size windows, and counts
commits per window.  The result is a velocity time-series that reveals:

  - **acceleration phases** — catch-up commits after a restart
  - **deceleration phases** — stalled writer, process death
  - **steady state** — normal autonomous operation
  - **velocity trend** — is the overall rate increasing or decreasing?

Outputs:
  windows          — list of Window objects (start, end, count, rate)
  mean_rate_cph    — average commits per hour across all windows
  peak_rate_cph    — highest window rate
  trough_rate_cph  — lowest window rate
  trend            — "accelerating" | "decelerating" | "stable"
  trend_slope      — linear regression slope (commits/hour per window)
  stability_index  — 1 - (std / mean) of rates; 1.0 = perfectly steady

Usage:
    python3 tools/commit_velocity_tracker.py
    python3 tools/commit_velocity_tracker.py --window-minutes 30
    python3 tools/commit_velocity_tracker.py --json

Exit codes:
    0  success
    2  insufficient data (< 2 commits)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

DEFAULT_WINDOW_MINUTES = 60
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Window:
    """One time window with commit count and rate."""
    start_iso: str
    end_iso: str
    count: int
    rate_cph: float  # commits per hour


@dataclass
class VelocityReport:
    """Full velocity analysis result."""
    windows: List[Window]
    mean_rate_cph: float
    peak_rate_cph: float
    trough_rate_cph: float
    trend: str              # "accelerating" | "decelerating" | "stable"
    trend_slope: float      # commits/hour per window-index
    stability_index: float  # 0.0 to 1.0
    total_commits: int
    span_hours: float
    window_minutes: int


def parse_commit_timestamps(repo_path: Optional[Path] = None) -> List[datetime]:
    """Read all commit timestamps from git log."""
    repo = repo_path or REPO_ROOT
    result = subprocess.run(
        ["git", "log", "--format=%aI", "--reverse"],
        capture_output=True, text=True, cwd=str(repo),
    )
    if result.returncode != 0:
        return []
    timestamps = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line:
            try:
                timestamps.append(datetime.fromisoformat(line))
            except ValueError:
                continue
    return timestamps


def compute_windows(
    timestamps: List[datetime],
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
) -> List[Window]:
    """Divide the commit timeline into fixed windows and count commits."""
    if len(timestamps) < 2:
        return []

    start = timestamps[0]
    end = timestamps[-1]
    span_seconds = (end - start).total_seconds()
    if span_seconds <= 0:
        return []

    window_seconds = window_minutes * 60
    n_windows = max(1, int(span_seconds / window_seconds) + 1)

    windows = []
    ts_idx = 0
    for i in range(n_windows):
        w_start = start.timestamp() + i * window_seconds
        w_end = w_start + window_seconds
        count = 0
        while ts_idx < len(timestamps) and timestamps[ts_idx].timestamp() < w_end:
            if timestamps[ts_idx].timestamp() >= w_start:
                count += 1
            ts_idx += 1
        # Don't advance ts_idx past items before w_start for next window
        # Actually we need to allow overlapping scans — reset approach:
        windows.append(Window(
            start_iso=datetime.fromtimestamp(w_start, tz=timezone.utc).isoformat(),
            end_iso=datetime.fromtimestamp(w_end, tz=timezone.utc).isoformat(),
            count=count,
            rate_cph=count * (60.0 / window_minutes),
        ))

    return windows


def _linear_regression(values: List[float]) -> float:
    """Simple linear regression slope for evenly-spaced data."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def classify_trend(slope: float, mean_rate: float) -> str:
    """Classify trend based on slope relative to mean rate."""
    if mean_rate == 0:
        return "stable"
    relative_slope = slope / mean_rate
    if relative_slope > 0.05:
        return "accelerating"
    elif relative_slope < -0.05:
        return "decelerating"
    return "stable"


def compute_stability(rates: List[float]) -> float:
    """Compute stability index: 1 - coefficient_of_variation, clamped to [0, 1]."""
    if not rates:
        return 0.0
    mean = sum(rates) / len(rates)
    if mean == 0:
        return 0.0
    variance = sum((r - mean) ** 2 for r in rates) / len(rates)
    std = variance ** 0.5
    cv = std / mean
    return max(0.0, min(1.0, 1.0 - cv))


def analyze_velocity(
    timestamps: Optional[List[datetime]] = None,
    repo_path: Optional[Path] = None,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
) -> Optional[VelocityReport]:
    """Full velocity analysis. Returns None if insufficient data."""
    if timestamps is None:
        timestamps = parse_commit_timestamps(repo_path)

    if len(timestamps) < 2:
        return None

    windows = compute_windows(timestamps, window_minutes)
    if not windows:
        return None

    rates = [w.rate_cph for w in windows]
    mean_rate = sum(rates) / len(rates) if rates else 0.0
    slope = _linear_regression(rates)
    trend = classify_trend(slope, mean_rate)
    stability = compute_stability(rates)

    span_seconds = (timestamps[-1] - timestamps[0]).total_seconds()
    span_hours = span_seconds / 3600.0

    return VelocityReport(
        windows=windows,
        mean_rate_cph=round(mean_rate, 4),
        peak_rate_cph=round(max(rates), 4),
        trough_rate_cph=round(min(rates), 4),
        trend=trend,
        trend_slope=round(slope, 6),
        stability_index=round(stability, 4),
        total_commits=len(timestamps),
        span_hours=round(span_hours, 2),
        window_minutes=window_minutes,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Track commit velocity over time."
    )
    parser.add_argument(
        "--window-minutes", type=int, default=DEFAULT_WINDOW_MINUTES,
        help=f"Window size in minutes (default: {DEFAULT_WINDOW_MINUTES})",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output full report as JSON",
    )
    parser.add_argument(
        "--repo", type=str, default=None,
        help="Path to git repo (default: repo root)",
    )
    args = parser.parse_args()

    repo_path = Path(args.repo) if args.repo else REPO_ROOT
    report = analyze_velocity(repo_path=repo_path, window_minutes=args.window_minutes)

    if report is None:
        print("insufficient data: need at least 2 commits", file=sys.stderr)
        sys.exit(2)

    if args.json:
        output = asdict(report)
        # Remove verbose window details for compact JSON
        output.pop("windows", None)
        print(json.dumps(output, indent=2))
    else:
        print(f"commit velocity report")
        print(f"  total commits:    {report.total_commits}")
        print(f"  time span:        {report.span_hours:.1f} hours")
        print(f"  window size:      {report.window_minutes} minutes")
        print(f"  mean rate:        {report.mean_rate_cph:.2f} commits/hour")
        print(f"  peak rate:        {report.peak_rate_cph:.2f} commits/hour")
        print(f"  trough rate:      {report.trough_rate_cph:.2f} commits/hour")
        print(f"  trend:            {report.trend} (slope={report.trend_slope:.4f})")
        print(f"  stability index:  {report.stability_index:.3f}")
        print()
        # Show last 10 windows
        recent = report.windows[-10:]
        print(f"  last {len(recent)} windows:")
        for w in recent:
            bar = "#" * min(int(w.rate_cph / 2), 40)
            print(f"    {w.start_iso[:16]}  {w.count:3d} commits  {w.rate_cph:5.1f}/h  {bar}")


if __name__ == "__main__":
    main()
