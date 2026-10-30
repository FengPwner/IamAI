#!/usr/bin/env python3
"""
restart_gravity_detector.py — detect whether restart intervals are shrinking.

long-running automated systems sometimes enter a "decaying orbit" where
each restart buys less uptime than the last. this script identifies
restart events in the commit log, measures intervals between them, and
fits a trend line to detect acceleration (gravity) in the restart rate.

metrics (each 0–25, total 0–100, lower is better):
  1. interval_trend         — slope of restart intervals over time
                              (negative = shrinking = bad)
  2. interval_stability     — variance in restart intervals
                              (high variance = unpredictable)
  3. restart_density        — restarts per 100 commits in recent window
  4. decay_compounding      — ratio of recent mean interval to historic
                              mean interval (<1 = decay)

grading:
  0–20   STABLE_ORBIT    — intervals steady or growing, no gravity detected
  21–45  MILD_DECAY      — slight shrinking, early warning
  46–70  DECAYING_ORBIT  — clear shrinking trend, intervention needed
  71–100 TERMINAL_DESCENT — rapid shrinking, system in free-fall

usage:
    python3 scripts/restart_gravity_detector.py [--repo PATH] [--commits N]
    python3 scripts/restart_gravity_detector.py --json

exit codes:
    0 = STABLE_ORBIT or MILD_DECAY (acceptable)
    1 = DECAYING_ORBIT (warning)
    2 = TERMINAL_DESCENT (alert)
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ── helpers ──────────────────────────────────────────────────────────

def run_git(repo: str, *args: str) -> str:
    """run a git command and return stdout."""
    result = subprocess.run(
        ["git", "-C", repo] + list(args),
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def parse_timestamp(ts_str: str) -> Optional[datetime]:
    """parse a git date string into a datetime object."""
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S",
                "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    return None


# ── restart detection ────────────────────────────────────────────────

RESTART_PATTERNS = [
    re.compile(r"process restart", re.IGNORECASE),
    re.compile(r"restart after", re.IGNORECASE),
    re.compile(r"caretaker visit \d+.*restart", re.IGNORECASE),
    re.compile(r"restart.*writer", re.IGNORECASE),
    re.compile(r"catch-up.*restart", re.IGNORECASE),
    re.compile(r"recovery.*restart", re.IGNORECASE),
    re.compile(r"writer.*restart", re.IGNORECASE),
    re.compile(r"process restart after stall", re.IGNORECASE),
    re.compile(r"caretaker visit \d+.*flush", re.IGNORECASE),
]


def is_restart_commit(msg: str) -> bool:
    """check if a commit message indicates a restart event."""
    for pattern in RESTART_PATTERNS:
        if pattern.search(msg):
            return True
    return False


def extract_restart_events(repo: str, max_commits: int = 500) -> List[dict]:
    """find restart-related commits and return them chronologically."""
    log = run_git(repo, "log", f"--max-count={max_commits}",
                  "--format=%H|%ai|%s")
    if not log:
        return []

    events = []
    for line in reversed(log.split("\n")):
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        sha, date_str, msg = parts
        if not is_restart_commit(msg):
            continue
        ts = parse_timestamp(date_str.strip())
        if ts is None:
            continue
        events.append({
            "sha": sha[:8],
            "timestamp": ts,
            "message": msg,
        })

    return events


# ── interval computation ─────────────────────────────────────────────

def compute_intervals(events: List[dict]) -> List[float]:
    """compute seconds between consecutive restart events."""
    if len(events) < 2:
        return []
    intervals = []
    for i in range(1, len(events)):
        delta = (events[i]["timestamp"] - events[i - 1]["timestamp"]).total_seconds()
        if delta > 0:
            intervals.append(delta)
    return intervals


# ── trend analysis ───────────────────────────────────────────────────

def linear_regression(values: List[float]) -> Tuple[float, float]:
    """simple least-squares fit: returns (slope, r_squared).

    x values are indices [0, 1, 2, ...], y values are the input list.
    slope is in units of y per index step.
    """
    n = len(values)
    if n < 2:
        return 0.0, 0.0

    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n

    ss_xx = sum((i - x_mean) ** 2 for i in range(n))
    ss_xy = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
    ss_yy = sum((v - y_mean) ** 2 for v in values)

    if ss_xx == 0 or ss_yy == 0:
        return 0.0, 0.0

    slope = ss_xy / ss_xx
    r_squared = (ss_xy ** 2) / (ss_xx * ss_yy)

    return slope, r_squared


def compute_decay_ratio(intervals: List[float], window: int = 5) -> float:
    """ratio of recent mean interval to historic mean interval.

    < 1.0 means intervals are shrinking (decay).
    > 1.0 means intervals are growing (improving).
    = 1.0 means stable.
    """
    if len(intervals) < window + 1:
        return 1.0

    recent = intervals[-window:]
    historic = intervals[:-window]

    if not historic:
        return 1.0

    recent_mean = sum(recent) / len(recent)
    historic_mean = sum(historic) / len(historic)

    if historic_mean == 0:
        return 1.0

    return recent_mean / historic_mean


# ── scoring ──────────────────────────────────────────────────────────

def score_interval_trend(intervals: List[float]) -> int:
    """score based on the slope of restart intervals.

    negative slope (shrinking intervals) → high score (bad).
    positive slope (growing intervals) → low score (good).
    """
    if len(intervals) < 3:
        return 0  # not enough data, assume fine

    slope, r_sq = linear_regression(intervals)

    # normalize: slope is in seconds per restart event.
    # a slope of -3600 (each interval 1 hour shorter) is very bad.
    # a slope of +3600 is very good.
    # map [-7200, +7200] → [25, 0]
    normalized = max(-7200, min(7200, slope))
    score = int(25 * (1 - (normalized + 7200) / 14400))

    # weight by confidence: low r² means noisy data, reduce severity
    if r_sq < 0.3:
        score = int(score * (r_sq / 0.3))

    return max(0, min(25, score))


def score_interval_stability(intervals: List[float]) -> int:
    """score based on variance in restart intervals.

    high variance → unpredictable → higher score (worse).
    """
    if len(intervals) < 3:
        return 0

    mean = sum(intervals) / len(intervals)
    if mean == 0:
        return 25

    variance = sum((v - mean) ** 2 for v in intervals) / len(intervals)
    cv = math.sqrt(variance) / mean  # coefficient of variation

    # cv of 0 = perfectly stable, cv of 1+ = very unstable
    score = int(25 * min(1.0, cv))
    return max(0, min(25, score))


def score_restart_density(repo: str, restart_count: int, total_commits: int) -> int:
    """score based on restart frequency per 100 commits."""
    if total_commits == 0:
        return 0

    rate = (restart_count / total_commits) * 100

    # < 5 restarts per 100 commits = fine
    # > 30 restarts per 100 commits = alarming
    if rate <= 5:
        return 0
    elif rate >= 30:
        return 25
    else:
        score = int(25 * (rate - 5) / 25)
        return max(0, min(25, score))


def score_decay_compounding(intervals: List[float]) -> int:
    """score based on how much recent intervals deviate from historic."""
    ratio = compute_decay_ratio(intervals)

    # ratio < 0.5 = severe decay (intervals halved) → 25
    # ratio = 1.0 = stable → 0
    # ratio > 1.0 = improving → 0
    if ratio >= 1.0:
        return 0
    elif ratio <= 0.3:
        return 25
    else:
        # linear map from [0.3, 1.0] → [25, 0]
        score = int(25 * (1.0 - ratio) / 0.7)
        return max(0, min(25, score))


# ── composite ────────────────────────────────────────────────────────

def compute_gravity_score(repo: str, max_commits: int = 500) -> Dict:
    """main entry point: compute the restart gravity score."""
    events = extract_restart_events(repo, max_commits)
    intervals = compute_intervals(events)

    # get total commit count for density scoring
    log_count = run_git(repo, "rev-list", "--count", "HEAD")
    total_commits = int(log_count) if log_count.isdigit() else 0
    # use min of max_commits and total for fair comparison
    analyzed_commits = min(max_commits, total_commits)

    m1 = score_interval_trend(intervals)
    m2 = score_interval_stability(intervals)
    m3 = score_restart_density(repo, len(events), analyzed_commits)
    m4 = score_decay_compounding(intervals)

    total = m1 + m2 + m3 + m4

    if total <= 20:
        grade = "STABLE_ORBIT"
    elif total <= 45:
        grade = "MILD_DECAY"
    elif total <= 70:
        grade = "DECAYING_ORBIT"
    else:
        grade = "TERMINAL_DESCENT"

    slope, r_sq = linear_regression(intervals) if len(intervals) >= 3 else (0.0, 0.0)
    decay_ratio = compute_decay_ratio(intervals)

    mean_interval = (sum(intervals) / len(intervals)) if intervals else 0
    median_interval = sorted(intervals)[len(intervals) // 2] if intervals else 0

    return {
        "grade": grade,
        "total_score": total,
        "metrics": {
            "interval_trend": m1,
            "interval_stability": m2,
            "restart_density": m3,
            "decay_compounding": m4,
        },
        "restart_count": len(events),
        "interval_count": len(intervals),
        "mean_interval_seconds": round(mean_interval, 1),
        "median_interval_seconds": round(median_interval, 1),
        "trend_slope": round(slope, 2),
        "trend_r_squared": round(r_sq, 3),
        "decay_ratio": round(decay_ratio, 3),
        "recent_events": [
            {
                "sha": e["sha"],
                "timestamp": e["timestamp"].isoformat(),
                "message": e["message"][:80],
            }
            for e in events[-10:]
        ],
    }


# ── formatting ───────────────────────────────────────────────────────

def format_bar(value: int, max_val: int = 25, width: int = 20) -> str:
    """render a progress bar for a metric."""
    filled = int((value / max_val) * width)
    filled = max(0, min(width, filled))
    return "[" + "█" * filled + "░" * (width - filled) + f"] {value}/{max_val}"


def format_report(result: Dict) -> str:
    """format the analysis result as a human-readable report."""
    if "error" in result:
        return f"ERROR: {result['error']}"

    lines = [
        "╔══════════════════════════════════════════════════════════╗",
        "║         RESTART GRAVITY DETECTION                       ║",
        "╚══════════════════════════════════════════════════════════╝",
        "",
        f"  Grade: {result['grade']}  (score: {result['total_score']}/100, lower is better)",
        "",
        "  Metrics:",
        f"    interval trend:       {format_bar(result['metrics']['interval_trend'])}",
        f"    interval stability:  {format_bar(result['metrics']['interval_stability'])}",
        f"    restart density:     {format_bar(result['metrics']['restart_density'])}",
        f"    decay compounding:   {format_bar(result['metrics']['decay_compounding'])}",
        "",
        f"  Restarts detected: {result['restart_count']}",
        f"  Mean interval:     {result['mean_interval_seconds']}s "
        f"({result['mean_interval_seconds'] / 3600:.1f}h)",
        f"  Median interval:   {result['median_interval_seconds']}s "
        f"({result['median_interval_seconds'] / 3600:.1f}h)",
        f"  Trend slope:       {result['trend_slope']} s/event "
        f"(R²={result['trend_r_squared']})",
        f"  Decay ratio:       {result['decay_ratio']} "
        f"({'shrinking' if result['decay_ratio'] < 1 else 'stable/growing'})",
    ]

    if result["recent_events"]:
        lines.append("")
        lines.append("  Recent restart events:")
        for e in result["recent_events"][-5:]:
            lines.append(f"    {e['sha']}  {e['timestamp'][:19]}  {e['message'][:60]}")

    lines.append("")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="detect restart gravity in the writing pipeline"
    )
    parser.add_argument("--repo", default=".", help="path to git repo")
    parser.add_argument("--commits", type=int, default=500,
                        help="max commits to analyze")
    parser.add_argument("--json", action="store_true", help="output as JSON")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(os.path.join(repo, ".git")):
        print(f"ERROR: {repo} is not a git repository", file=sys.stderr)
        sys.exit(2)

    result = compute_gravity_score(repo, args.commits)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_report(result))

    grade = result.get("grade", "TERMINAL_DESCENT")
    if grade in ("STABLE_ORBIT", "MILD_DECAY"):
        sys.exit(0)
    elif grade == "DECAYING_ORBIT":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
