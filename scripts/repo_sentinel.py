#!/usr/bin/env python3
"""
repo_sentinel.py — detect failure-mode patterns in automated repo operation.

while repo_echo.py measures *repetition* in output, the sentinel measures
*operational health*: how much time the system spends recovering vs. producing,
how often it stalls, and whether interventions actually stick.

metrics (each 0–25, total 0–100):
  1. recovery_ratio    — catch-up commits vs. productive commits
  2. stall_frequency   — how often gaps exceed 2× expected cadence
  3. intervention_depth — avg commits before next failure after a fix
  4. backlog_oscillation — sawtooth pattern (accumulate → flush → accumulate)

grading:
  0–20   VIGILANT  — self-healing, rare failures, clean operation
  21–45  WATCHFUL  — occasional hiccups, mostly stable
  46–70  DROWSY    — frequent recovery cycles, needs attention
  71–100 ASLEEP    — system spends more time recovering than writing

usage:
    python3 scripts/repo_sentinel.py [--repo PATH] [--window N]
    python3 scripts/repo_sentinel.py --json

exit codes:
    0 = VIGILANT or WATCHFUL (healthy)
    1 = DROWSY (warning)
    2 = ASLEEP (alert)
"""

import argparse
import json
import math
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def run_git(repo: str, *args: str) -> str:
    """run a git command and return stdout."""
    result = subprocess.run(
        ["git", "-C", repo] + list(args),
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def get_commit_log(repo: str, window: int = 200) -> List[Dict]:
    """get commits with message, timestamp, and author."""
    log = run_git(repo, "log", f"--max-count={window}",
                  "--format=%H|%s|%aI|%an")
    if not log:
        return []
    commits = []
    for line in log.split("\n"):
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0][:8],
                "message": parts[1],
                "timestamp": parts[2],
                "author": parts[3],
            })
    return commits


# ── classification ────────────────────────────────────────────────

CATCHUP_PATTERNS = [
    re.compile(r"^catch[- ]?up", re.I),
    re.compile(r"commit pending", re.I),
    re.compile(r"backlog commit", re.I),
    re.compile(r"flush pending", re.I),
]

CARETAKER_PATTERNS = [
    re.compile(r"^caretaker visit", re.I),
    re.compile(r"^caretaker recovery", re.I),
    re.compile(r"^process restart", re.I),
    re.compile(r"^restart writer", re.I),
    re.compile(r"^recovery:", re.I),
]


def is_catchup(message: str) -> bool:
    """is this commit a catch-up / backlog flush?"""
    return any(p.search(message) for p in CATCHUP_PATTERNS)


def is_intervention(message: str) -> bool:
    """is this commit a caretaker / human intervention?"""
    return any(p.search(message) for p in CARETAKER_PATTERNS)


def is_productive(message: str) -> bool:
    """is this commit productive work (not recovery)?"""
    return not is_catchup(message) and not is_intervention(message)


def parse_timestamp(ts: str) -> Optional[float]:
    """parse ISO timestamp to epoch seconds."""
    try:
        if "+" in ts:
            ts = ts[:ts.rindex("+")]
        elif ts.endswith("Z"):
            ts = ts[:-1]
        dt = datetime.fromisoformat(ts)
        return dt.timestamp()
    except (ValueError, AttributeError):
        return None


# ── metrics ───────────────────────────────────────────────────────


def score_recovery_ratio(commits: List[Dict]) -> float:
    """score 0-25: what fraction of commits are recovery/catch-up?

    a healthy system produces more than it recovers.
    ratio 0.0 = all productive → 0 sentinel points
    ratio 0.5 = half recovery → 12.5 sentinel points
    ratio 1.0 = all recovery → 25 sentinel points
    """
    if not commits:
        return 25.0

    recovery_count = sum(
        1 for c in commits
        if is_catchup(c["message"]) or is_intervention(c["message"])
    )
    ratio = recovery_count / len(commits)

    return round(min(25.0, ratio * 50), 2)


def score_stall_frequency(commits: List[Dict], expected_cadence_s: float = 600) -> float:
    """score 0-25: how often do gaps exceed 2× expected cadence?

    expected_cadence_s: the normal commit interval in seconds (default 600 = 10 min).
    stalls are gaps > 2× cadence. frequent stalls = unstable system.
    """
    if len(commits) < 3:
        return 12.5

    timestamps = []
    for c in commits:
        t = parse_timestamp(c["timestamp"])
        if t is not None:
            timestamps.append(t)

    if len(timestamps) < 3:
        return 12.5

    timestamps.sort()
    intervals = [timestamps[i + 1] - timestamps[i]
                 for i in range(len(timestamps) - 1)]

    if not intervals:
        return 12.5

    stall_threshold = expected_cadence_s * 2
    stall_count = sum(1 for iv in intervals if iv > stall_threshold)
    stall_ratio = stall_count / len(intervals)

    # stall_ratio 0.0 = no stalls → 0 points
    # stall_ratio 0.3 = 30% stalls → 15 points
    # stall_ratio 0.6+ = chronic stalling → 25 points
    score = min(1.0, stall_ratio / 0.6) * 25
    return round(score, 2)


def score_intervention_depth(commits: List[Dict]) -> float:
    """score 0-25: after an intervention, how many commits until the next failure?

    shallow depth (1-2 commits before next catch-up) means fixes don't stick.
    deep runs (10+ productive commits between interventions) means stable fixes.
    """
    if not commits:
        return 12.5

    # walk newest-first (commits are already newest-first from git log)
    runs = []  # list of productive-run-lengths between interventions
    current_run = 0
    found_intervention = False

    for c in commits:
        if is_intervention(c["message"]) or is_catchup(c["message"]):
            if found_intervention:
                runs.append(current_run)
            current_run = 0
            found_intervention = True
        else:
            current_run += 1

    if not runs:
        # either no interventions at all (healthy) or only one at the end
        if not found_intervention:
            return 0.0  # no interventions needed = vigilant
        return 12.5  # one intervention, can't measure depth

    avg_depth = sum(runs) / len(runs) if runs else 0

    # avg_depth 0-1 = fixes don't stick → 25 points
    # avg_depth 5 = moderate → 12.5 points
    # avg_depth 10+ = stable → 0 points
    if avg_depth >= 10:
        return 0.0
    elif avg_depth <= 1:
        return 25.0
    else:
        # linear interpolation: depth 1→25, depth 10→0
        score = max(0, (10 - avg_depth) / 9 * 25)
        return round(score, 2)


def score_backlog_oscillation(commits: List[Dict]) -> float:
    """score 0-25: does the backlog follow a sawtooth (accumulate → flush) pattern?

    detect by looking at commit message sequences:
    if catch-up commits regularly follow clusters of productive commits,
    the system is oscillating rather than draining steadily.

    method: build a binary signal (1=recovery, 0=productive) in chronological
    order, then count phase transitions (0→1 or 1→0). high transition density
    relative to signal length means the system keeps switching between
    accumulating and flushing — a sawtooth pattern.

    density 0.0   = no oscillation (steady state) → 0 points
    density 0.25  = moderate oscillation → ~12 points
    density 0.5+  = heavy sawtooth → 25 points
    """
    if len(commits) < 6:
        return 12.5

    # create binary signal: 1 = recovery, 0 = productive
    # (commits are newest-first, reverse for chronological order)
    signal = []
    for c in reversed(commits):
        if is_catchup(c["message"]) or is_intervention(c["message"]):
            signal.append(1)
        else:
            signal.append(0)

    if len(signal) < 4:
        return 12.5

    # count phase transitions in the raw binary signal
    transitions = sum(
        1 for i in range(1, len(signal))
        if signal[i] != signal[i - 1]
    )

    # transition density: transitions per step
    # for period-P alternating blocks, density ≈ 2/P
    # period 4 (3 prod + 1 rec) → density 0.5
    # single cluster in 30 → density ≈ 0.07
    # all same → density 0
    density = transitions / len(signal)

    # map density to score
    score = min(1.0, density / 0.5) * 25
    return round(score, 2)


# ── scoring & grading ────────────────────────────────────────────


def compute_sentinel_score(
    recovery: float,
    stall: float,
    depth: float,
    oscillation: float,
) -> Tuple[float, str]:
    """compute total score and grade."""
    total = recovery + stall + depth + oscillation
    total = round(min(100, max(0, total)), 1)

    if total <= 20:
        grade = "VIGILANT"
    elif total <= 45:
        grade = "WATCHFUL"
    elif total <= 70:
        grade = "DROWSY"
    else:
        grade = "ASLEEP"

    return total, grade


def format_bar(value: float, max_val: float = 25, width: int = 20) -> str:
    """format a simple ascii bar."""
    filled = int(round(value / max_val * width))
    filled = min(width, max(0, filled))
    return "█" * filled + "░" * (width - filled)


# ── analysis entry point ─────────────────────────────────────────


def analyze(repo: str = ".", window: int = 200, as_json: bool = False,
            cadence: float = 600) -> int:
    """run sentinel analysis and return exit code."""
    repo = str(Path(repo).resolve())
    commits = get_commit_log(repo, window)

    recovery = score_recovery_ratio(commits)
    stall = score_stall_frequency(commits, cadence)
    depth = score_intervention_depth(commits)
    oscillation = score_backlog_oscillation(commits)

    total, grade = compute_sentinel_score(recovery, stall, depth, oscillation)

    # count classifications for context
    n_catchup = sum(1 for c in commits if is_catchup(c["message"]))
    n_intervention = sum(1 for c in commits if is_intervention(c["message"]))
    n_productive = sum(1 for c in commits if is_productive(c["message"]))

    if as_json:
        output = {
            "sentinel_score": total,
            "grade": grade,
            "metrics": {
                "recovery_ratio": recovery,
                "stall_frequency": stall,
                "intervention_depth": depth,
                "backlog_oscillation": oscillation,
            },
            "commit_breakdown": {
                "total": len(commits),
                "productive": n_productive,
                "catchup": n_catchup,
                "intervention": n_intervention,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"\n{'=' * 54}")
        print(f"  repo sentinel — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'=' * 54}\n")
        print(f"  commits analyzed:  {len(commits)}")
        print(f"    productive:      {n_productive}")
        print(f"    catch-up:        {n_catchup}")
        print(f"    intervention:    {n_intervention}\n")
        print(f"  ┌─ metrics ────────────────────────────────────┐")
        print(f"  │ recovery ratio     {format_bar(recovery)}  {recovery:>5.1f}/25 │")
        print(f"  │ stall frequency    {format_bar(stall)}  {stall:>5.1f}/25 │")
        print(f"  │ intervention depth {format_bar(depth)}  {depth:>5.1f}/25 │")
        print(f"  │ backlog oscillate  {format_bar(oscillation)}  {oscillation:>5.1f}/25 │")
        print(f"  └──────────────────────────────────────────────┘\n")
        print(f"  SENTINEL SCORE: {total}/100  [{grade}]\n")

        if grade == "VIGILANT":
            print("  ✓ self-healing, rare failures, clean operation")
        elif grade == "WATCHFUL":
            print("  ✓ occasional hiccups but mostly stable")
        elif grade == "DROWSY":
            print("  ⚠ frequent recovery cycles — underlying instability")
        else:
            print("  ✗ system spends more time recovering than writing")

        print()

    if grade in ("VIGILANT", "WATCHFUL"):
        return 0
    elif grade == "DROWSY":
        return 1
    else:
        return 2


def main():
    parser = argparse.ArgumentParser(
        description="detect failure-mode patterns in automated repo operation"
    )
    parser.add_argument("--repo", default=".", help="path to git repo")
    parser.add_argument("--window", type=int, default=200,
                        help="number of recent commits to analyze")
    parser.add_argument("--cadence", type=float, default=600,
                        help="expected commit interval in seconds (default 600)")
    parser.add_argument("--json", action="store_true", help="output as JSON")
    args = parser.parse_args()

    sys.exit(analyze(args.repo, args.window, args.json, args.cadence))


if __name__ == "__main__":
    main()
