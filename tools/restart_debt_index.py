#!/usr/bin/env python3
"""restart_debt_index.py — measure accumulated restart cost over time.

Every restart has a fixed overhead (SSH key rescue, process spawn, cadence
re-acquisition). When restarts cluster together — say, three in an hour —
the *debt* is higher than three restarts spread across a week, because
the system never reached steady-state output between them.

This tool answers: "how much restart debt has accumulated, and is it
getting worse?"

Input:
    tools/process_graveyard.py output  (or a synthetic restart log)
    data/strokes.jsonl                  (to measure output between restarts)

Output:

    Restart Debt Index
    ───────────────────────────────────────
    Total restarts:          47
    Mean interval (min):    182.4
    Debt index:              0.73   (0=healthy, 1=perpetual restart loop)
    Clustering factor:       2.1x   (how often restarts come in pairs <30min)
    Steady-state ratio:      81%    (fraction of time actually producing)

Debt index formula:
    debt = 1 - (mean_time_between_restarts / ideal_interval)
    clamped to [0, 1].

    ideal_interval defaults to 1440 minutes (24 hours): a system that
    restarts once a day is considered healthy. A system that restarts
    every 30 minutes scores ~0.98 debt.

Usage:
    python3 tools/restart_debt_index.py
    python3 tools/restart_debt_index.py --graveyard data/restart_log.jsonl
    python3 tools/restart_debt_index.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def parse_iso(s: str) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime."""
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Restart event extraction
# ---------------------------------------------------------------------------

def extract_restarts_from_git(
    repo_root: Path | str = ".",
    max_commits: int = 500,
) -> list[datetime]:
    """Extract restart timestamps from git commit messages.

    Looks for commits with messages matching patterns like:
        "catch-up: commit pending changes before process restart"
        "visit N: ... process restart ..."
    Returns a sorted list of commit timestamps.
    """
    repo_root = Path(repo_root)
    try:
        result = subprocess.run(
            [
                "git", "log",
                f"--max-count={max_commits}",
                "--format=%aI %s",
                "--all",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    restart_pattern = re.compile(
        r"(restart|resurrect|recovery|catch-up)",
        re.IGNORECASE,
    )

    timestamps = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        ts_str, message = parts
        if restart_pattern.search(message):
            ts = parse_iso(ts_str)
            if ts:
                timestamps.append(ts)

    timestamps.sort()
    return timestamps


def extract_restarts_from_log(path: str | Path) -> list[datetime]:
    """Extract restart timestamps from a JSONL restart log.

    Expected format: one JSON object per line with "at" (ISO-8601)
    and optionally "kind" == "restart".
    """
    path = Path(path)
    if not path.exists():
        return []
    timestamps = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = obj.get("kind", "restart")
            if kind == "restart" or "restart" in kind:
                ts = parse_iso(obj.get("at", ""))
                if ts:
                    timestamps.append(ts)
    timestamps.sort()
    return timestamps


# ---------------------------------------------------------------------------
# Debt computation
# ---------------------------------------------------------------------------

def compute_intervals(timestamps: list[datetime]) -> list[float]:
    """Compute intervals in minutes between consecutive restart events."""
    if len(timestamps) < 2:
        return []
    intervals = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds() / 60.0
        intervals.append(delta)
    return intervals


def compute_clustering_factor(
    intervals: list[float],
    cluster_threshold_minutes: float = 30.0,
) -> float:
    """Measure how often restarts come in rapid succession.

    Returns the ratio of intervals below the threshold to total intervals.
    A factor of 0.0 means no clustering; 1.0 means every restart is
    followed by another within the threshold.
    """
    if not intervals:
        return 0.0
    clustered = sum(1 for iv in intervals if iv < cluster_threshold_minutes)
    return clustered / len(intervals)


def compute_debt_index(
    intervals: list[float],
    ideal_interval_minutes: float = 1440.0,
) -> float:
    """Compute the restart debt index.

    debt = 1 - clamp(mean_interval / ideal_interval, 0, 1)
    0.0 = healthy (restarts are rare)
    1.0 = maximum debt (restarts are constant)
    """
    if not intervals:
        return 0.0
    mean_iv = sum(intervals) / len(intervals)
    ratio = mean_iv / ideal_interval_minutes
    ratio = max(0.0, min(1.0, ratio))
    return 1.0 - ratio


def compute_steady_state_ratio(
    timestamps: list[datetime],
    recovery_minutes: float = 5.0,
) -> float:
    """Estimate the fraction of time the system was actually producing.

    Each restart costs `recovery_minutes` of lost output time.
    steady_state = 1 - (total_recovery_time / observation_span).
    """
    if len(timestamps) < 2:
        return 1.0
    span_minutes = (timestamps[-1] - timestamps[0]).total_seconds() / 60.0
    if span_minutes <= 0:
        return 1.0
    total_recovery = len(timestamps) * recovery_minutes
    ratio = 1.0 - (total_recovery / span_minutes)
    return max(0.0, min(1.0, ratio))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def build_report(
    timestamps: list[datetime],
    ideal_interval_minutes: float = 1440.0,
    cluster_threshold_minutes: float = 30.0,
    recovery_minutes: float = 5.0,
) -> dict[str, Any]:
    """Build the full restart debt report."""
    if not timestamps:
        return {
            "total_restarts": 0,
            "mean_interval_minutes": 0.0,
            "debt_index": 0.0,
            "clustering_factor": 0.0,
            "steady_state_ratio": 1.0,
            "observation_span_hours": 0.0,
            "intervals": [],
        }

    intervals = compute_intervals(timestamps)
    mean_iv = sum(intervals) / len(intervals) if intervals else 0.0
    debt = compute_debt_index(intervals, ideal_interval_minutes)
    clustering = compute_clustering_factor(intervals, cluster_threshold_minutes)
    steady = compute_steady_state_ratio(timestamps, recovery_minutes)
    span_hours = (timestamps[-1] - timestamps[0]).total_seconds() / 3600.0

    return {
        "total_restarts": len(timestamps),
        "mean_interval_minutes": round(mean_iv, 1),
        "debt_index": round(debt, 4),
        "clustering_factor": round(clustering, 4),
        "steady_state_ratio": round(steady, 4),
        "observation_span_hours": round(span_hours, 1),
        "intervals": [round(iv, 1) for iv in intervals],
    }


def render_report(report: dict[str, Any]) -> str:
    """Render a human-readable report."""
    lines = [
        "Restart Debt Index",
        "─" * 50,
        f"  Total restarts:          {report['total_restarts']}",
        f"  Mean interval (min):     {report['mean_interval_minutes']}",
        f"  Debt index:              {report['debt_index']:.4f}   "
        f"(0=healthy, 1=perpetual restart loop)",
        f"  Clustering factor:       {report['clustering_factor']:.2f}x   "
        f"(fraction of restarts <30min apart)",
        f"  Steady-state ratio:      {report['steady_state_ratio'] * 100:.0f}%    "
        f"(fraction of time actually producing)",
        f"  Observation span:        {report['observation_span_hours']:.1f} hours",
    ]

    # Debt bar
    debt = report["debt_index"]
    bar_width = 30
    filled = int(debt * bar_width)
    bar = "▓" * filled + "░" * (bar_width - filled)
    lines.append("")
    lines.append(f"  Debt: [{bar}] {debt * 100:.1f}%")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Measure accumulated restart debt in the IamAI repo."
    )
    parser.add_argument(
        "--graveyard", default=None,
        help="Path to a JSONL restart log (default: extract from git log)"
    )
    parser.add_argument(
        "--ideal", type=float, default=1440.0,
        help="Ideal restart interval in minutes (default: 1440 = 24h)"
    )
    parser.add_argument(
        "--cluster-threshold", type=float, default=30.0,
        help="Minutes below which two restarts count as clustered (default: 30)"
    )
    parser.add_argument(
        "--recovery", type=float, default=5.0,
        help="Minutes of lost output per restart (default: 5)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output JSON instead of text"
    )
    args = parser.parse_args()

    if args.graveyard:
        timestamps = extract_restarts_from_log(args.graveyard)
    else:
        timestamps = extract_restarts_from_git()

    report = build_report(
        timestamps,
        ideal_interval_minutes=args.ideal,
        cluster_threshold_minutes=args.cluster_threshold,
        recovery_minutes=args.recovery,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_report(report))


if __name__ == "__main__":
    main()
