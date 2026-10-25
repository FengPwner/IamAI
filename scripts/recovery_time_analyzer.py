#!/usr/bin/env python3
"""
recovery_time_analyzer.py — measure how quickly the writing pipeline
recovers after a stall, restart, or caretaker intervention.

the IamAI repo runs an automated writer that produces strokes every ~15s.
when it stalls (process crash, resource exhaustion, caretaker pause), the
gap between the last pre-stall stroke and the first post-recovery stroke
is the *recovery time*. this tool finds, classifies, and scores those gaps.

metrics (each 0–25, total 0–100, lower is better):
  1. mean_recovery_time    — average seconds from stall-end to first stroke
  2. recovery_consistency  — std-dev of recovery times (lower = more predictable)
  3. stall_frequency       — how often stalls occur per 100 commits
  4. post_recovery_cadence — does the writer return to normal cadence or limp?

grading:
  0–20   RESILIENT  — recovers fast, rarely stalls, bounces back at full speed
  21–45  ROBUST     — occasional stalls with prompt recovery
  46–70  FRAGILE    — slow or inconsistent recovery
  71–100 BRITTLE    — frequent stalls, long recovery, degraded post-recovery

usage:
    python3 scripts/recovery_time_analyzer.py [--repo PATH] [--commits N]
    python3 scripts/recovery_time_analyzer.py --json

exit codes:
    0 = RESILIENT or ROBUST (healthy)
    1 = FRAGILE (warning)
    2 = BRITTLE (alert)
"""

import argparse
import json
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
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(ts_str.strip(), fmt)
        except ValueError:
            continue
    return None


# ── commit log parsing ──────────────────────────────────────────────

def get_commit_timeline(repo: str, max_commits: int = 500) -> List[Dict]:
    """fetch commit timestamps and messages in chronological order."""
    raw = run_git(
        repo, "log", f"--max-count={max_commits}",
        "--format=%H|%ai|%s", "--reverse"
    )
    if not raw:
        return []

    commits = []
    for line in raw.splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        sha, ts_str, msg = parts
        ts = parse_timestamp(ts_str)
        if ts is None:
            continue
        commits.append({
            "sha": sha[:8],
            "timestamp": ts,
            "message": msg.strip(),
        })
    return commits


def classify_commit(msg: str) -> str:
    """classify a commit message as writer-stroke, caretaker-visit, or other."""
    msg_lower = msg.lower()
    if "stroke" in msg_lower or "writer" in msg_lower and "sync" in msg_lower:
        return "stroke"
    if "caretaker visit" in msg_lower or "visit note" in msg_lower:
        return "caretaker"
    if "catch-up" in msg_lower or "restart" in msg_lower or "recovery" in msg_lower:
        return "recovery"
    return "other"


# ── stall detection ──────────────────────────────────────────────────

def detect_stalls(commits: List[Dict], threshold_seconds: float = 300.0) -> List[Dict]:
    """find gaps between consecutive commits that exceed the threshold.

    a stall is defined as any inter-commit gap > threshold_seconds.
    returns a list of stall records with start, end, duration, and context.
    """
    stalls = []
    if len(commits) < 2:
        return stalls

    for i in range(1, len(commits)):
        prev = commits[i - 1]
        curr = commits[i]
        gap = (curr["timestamp"] - prev["timestamp"]).total_seconds()

        if gap > threshold_seconds:
            stalls.append({
                "before_sha": prev["sha"],
                "after_sha": curr["sha"],
                "before_ts": prev["timestamp"],
                "after_ts": curr["timestamp"],
                "gap_seconds": gap,
                "before_msg": prev["message"][:80],
                "after_msg": curr["message"][:80],
                "before_kind": classify_commit(prev["message"]),
                "after_kind": classify_commit(curr["message"]),
            })
    return stalls


def compute_recovery_times(stalls: List[Dict]) -> List[float]:
    """extract recovery times (gap_seconds) from stall records."""
    return [s["gap_seconds"] for s in stalls]


# ── metrics ──────────────────────────────────────────────────────────

def score_mean_recovery(recovery_times: List[float], target: float = 60.0) -> int:
    """score mean recovery time. 0 = instant, 25 = very slow.

    scoring:
      0s–60s    → 0–5  (excellent)
      60s–300s  → 5–12 (good)
      300s–900s → 12–18 (moderate)
      900s+     → 18–25 (slow)
    """
    if not recovery_times:
        return 0
    mean = sum(recovery_times) / len(recovery_times)
    if mean <= target:
        return int(min(5, (mean / target) * 5))
    elif mean <= 300:
        return int(5 + ((mean - target) / (300 - target)) * 7)
    elif mean <= 900:
        return int(12 + ((mean - 300) / 600) * 6)
    else:
        return int(min(25, 18 + ((mean - 900) / 1800) * 7))


def score_consistency(recovery_times: List[float]) -> int:
    """score std-dev of recovery times. 0 = perfectly consistent, 25 = chaotic."""
    if len(recovery_times) < 2:
        return 0
    mean = sum(recovery_times) / len(recovery_times)
    variance = sum((t - mean) ** 2 for t in recovery_times) / (len(recovery_times) - 1)
    std_dev = variance ** 0.5

    if std_dev <= 30:
        return 0
    elif std_dev <= 120:
        return int((std_dev - 30) / 90 * 8)
    elif std_dev <= 600:
        return int(8 + (std_dev - 120) / 480 * 9)
    else:
        return int(min(25, 17 + (std_dev - 600) / 1200 * 8))


def score_stall_frequency(stalls: List[Dict], total_commits: int) -> int:
    """score how often stalls occur per 100 commits. 0 = rare, 25 = constant."""
    if total_commits <= 0:
        return 0
    rate = (len(stalls) / total_commits) * 100

    if rate <= 1:
        return 0
    elif rate <= 5:
        return int((rate - 1) / 4 * 8)
    elif rate <= 15:
        return int(8 + (rate - 5) / 10 * 9)
    else:
        return int(min(25, 17 + (rate - 15) / 20 * 8))


def score_post_recovery_cadence(commits: List[Dict], stalls: List[Dict]) -> int:
    """measure whether post-recovery commits return to normal cadence.

    compares the median inter-commit gap in the 5 commits before the stall
    with the 5 commits after recovery. 0 = same speed, 25 = severely degraded.
    """
    if not stalls or len(commits) < 12:
        return 0

    degraded_count = 0
    total_stalls = 0

    for stall in stalls:
        after_sha = stall["after_sha"]
        # find index of recovery commit
        idx = None
        for i, c in enumerate(commits):
            if c["sha"] == after_sha:
                idx = i
                break
        if idx is None:
            continue

        total_stalls += 1

        # pre-stall cadence (5 commits before stall)
        pre_start = max(0, idx - 6)
        pre_gaps = []
        for j in range(pre_start, idx - 1):
            gap = (commits[j + 1]["timestamp"] - commits[j]["timestamp"]).total_seconds()
            if gap > 0:
                pre_gaps.append(gap)

        # post-recovery cadence (5 commits after recovery)
        post_end = min(len(commits), idx + 6)
        post_gaps = []
        for j in range(idx, post_end - 1):
            gap = (commits[j + 1]["timestamp"] - commits[j]["timestamp"]).total_seconds()
            if gap > 0:
                post_gaps.append(gap)

        if not pre_gaps or not post_gaps:
            continue

        pre_median = sorted(pre_gaps)[len(pre_gaps) // 2]
        post_median = sorted(post_gaps)[len(post_gaps) // 2]

        if pre_median > 0 and post_median / pre_median > 2.0:
            degraded_count += 1

    if total_stalls == 0:
        return 0
    degradation_rate = degraded_count / total_stalls
    return int(min(25, degradation_rate * 25))


# ── aggregation ──────────────────────────────────────────────────────

def compute_recovery_score(repo: str, max_commits: int = 500) -> Dict:
    """compute the full recovery score for a repository."""
    commits = get_commit_timeline(repo, max_commits)
    if not commits:
        return {
            "error": "no commits found",
            "total_score": 100,
            "grade": "BRITTLE",
        }

    stalls = detect_stalls(commits)
    recovery_times = compute_recovery_times(stalls)

    m1 = score_mean_recovery(recovery_times)
    m2 = score_consistency(recovery_times)
    m3 = score_stall_frequency(stalls, len(commits))
    m4 = score_post_recovery_cadence(commits, stalls)

    total = m1 + m2 + m3 + m4

    if total <= 20:
        grade = "RESILIENT"
    elif total <= 45:
        grade = "ROBUST"
    elif total <= 70:
        grade = "FRAGILE"
    else:
        grade = "BRITTLE"

    return {
        "total_score": total,
        "grade": grade,
        "metrics": {
            "mean_recovery_time": m1,
            "recovery_consistency": m2,
            "stall_frequency": m3,
            "post_recovery_cadence": m4,
        },
        "stall_count": len(stalls),
        "total_commits": len(commits),
        "mean_recovery_seconds": (
            round(sum(recovery_times) / len(recovery_times), 1)
            if recovery_times else 0
        ),
        "stalls": [
            {
                "gap_seconds": round(s["gap_seconds"], 1),
                "before_sha": s["before_sha"],
                "after_sha": s["after_sha"],
                "before_kind": s["before_kind"],
                "after_kind": s["after_kind"],
            }
            for s in stalls[:10]  # cap at 10 for readability
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
        "║         RECOVERY TIME ANALYSIS                         ║",
        "╚══════════════════════════════════════════════════════════╝",
        "",
        f"  Grade: {result['grade']}  (score: {result['total_score']}/100, lower is better)",
        "",
        "  Metrics:",
        f"    mean recovery time:    {format_bar(result['metrics']['mean_recovery_time'])}",
        f"    recovery consistency:  {format_bar(result['metrics']['recovery_consistency'])}",
        f"    stall frequency:       {format_bar(result['metrics']['stall_frequency'])}",
        f"    post-recovery cadence: {format_bar(result['metrics']['post_recovery_cadence'])}",
        "",
        f"  Stalls detected: {result['stall_count']} across {result['total_commits']} commits",
        f"  Mean recovery:   {result['mean_recovery_seconds']}s",
    ]

    if result["stalls"]:
        lines.append("")
        lines.append("  Recent stalls:")
        for s in result["stalls"][:5]:
            lines.append(
                f"    {s['gap_seconds']:>8.0f}s  {s['before_sha']}→{s['after_sha']}  "
                f"({s['before_kind']}→{s['after_kind']})"
            )

    lines.append("")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="analyze writing pipeline recovery health"
    )
    parser.add_argument("--repo", default=".", help="path to git repo")
    parser.add_argument("--commits", type=int, default=500, help="max commits to analyze")
    parser.add_argument("--json", action="store_true", help="output as JSON")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(os.path.join(repo, ".git")):
        print(f"ERROR: {repo} is not a git repository", file=sys.stderr)
        sys.exit(2)

    result = compute_recovery_score(repo, args.commits)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_report(result))

    grade = result.get("grade", "BRITTLE")
    if grade in ("RESILIENT", "ROBUST"):
        sys.exit(0)
    elif grade == "FRAGILE":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
