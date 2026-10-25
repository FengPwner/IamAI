#!/usr/bin/env python3
"""
repo_echo.py — detect repetitive / echo patterns in commit history.

measures how often the auto-writer produces near-duplicate commit messages
or touches the same file clusters without variation. high echo score means
the writer is stuck in a loop; low score means healthy diversity.

metrics (each 0–25, total 0–100):
  1. message_diversity  — unique commit message ratio in recent window
  2. file_churn         — are the same files edited repeatedly without growth?
  3. topic_drift        — cosine-style similarity of path distributions across windows
  4. rhythm_monotony    — how uniform the commit intervals are (too uniform = bot loop)

grading:
  0–20   VARIED   — rich, diverse activity
  21–45  STABLE   — normal steady-state writing
  46–70  ECHOING  — repetition emerging, worth watching
  71–100 STUCK    — writer likely in a loop

usage:
    python3 scripts/repo_echo.py [--repo PATH] [--window N]
    python3 scripts/repo_echo.py --json

exit codes:
    0 = VARIED or STABLE (healthy)
    1 = ECHOING (warning)
    2 = STUCK (alert)
"""

import argparse
import json
import math
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


def get_recent_commits(repo: str, window: int = 100) -> List[Dict]:
    """get recent commits with message and timestamp."""
    log = run_git(repo, "log", f"--max-count={window}",
                  "--format=%H|%s|%aI")
    if not log:
        return []
    commits = []
    for line in log.split("\n"):
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({
                "hash": parts[0][:8],
                "message": parts[1],
                "timestamp": parts[2]
            })
    return commits


def get_file_changes(repo: str, window: int = 100) -> List[List[str]]:
    """get per-commit file change lists for recent commits."""
    log = run_git(repo, "log", f"--max-count={window}",
                  "--format=COMMIT:%H", "--name-only")
    if not log:
        return []
    result = []
    current = []
    for line in log.split("\n"):
        line = line.strip()
        if line.startswith("COMMIT:"):
            if current:
                result.append(current)
            current = []
        elif line:
            current.append(line)
    if current:
        result.append(current)
    return result


def score_message_diversity(commits: List[Dict]) -> float:
    """score 0-25: how diverse are the commit messages?
    low diversity (many duplicates) → high echo score contribution.
    """
    if not commits:
        return 25.0  # no data = assume worst
    messages = [c["message"] for c in commits]
    # strip common prefixes that don't indicate real diversity
    normalized = []
    for m in messages:
        m = m.lower().strip()
        # strip caretaker visit numbers, catch-up prefixes, etc.
        for prefix in ["catch-up:", "caretaker visit", "merge", "fix"]:
            if m.startswith(prefix):
                m = m[len(prefix):].strip()
                break
        normalized.append(m)

    unique = len(set(normalized))
    total = len(normalized)
    ratio = unique / total if total > 0 else 0

    # counter: low ratio → high echo (inverted)
    # ratio 1.0 = all unique → 0 echo points
    # ratio 0.0 = all same → 25 echo points
    return round((1.0 - ratio) * 25, 2)


def score_file_churn(file_changes: List[List[str]]) -> float:
    """score 0-25: are the same files touched repeatedly without rotation?
    high concentration on few files → high echo.
    """
    if not file_changes:
        return 25.0
    all_files = []
    for change_set in file_changes:
        all_files.extend(change_set)
    if not all_files:
        return 25.0

    counter = Counter(all_files)
    total = len(all_files)
    top_10_count = sum(count for _, count in counter.most_common(10))
    top_10_ratio = top_10_count / total if total > 0 else 0

    # if top 10 files account for >80% of all changes → high echo
    # if top 10 files account for <20% → low echo
    echo = max(0, min(1, (top_10_ratio - 0.2) / 0.6))
    return round(echo * 25, 2)


def score_topic_drift(file_changes: List[List[str]]) -> float:
    """score 0-25: compare path distribution of first half vs second half.
    high similarity (no drift) in a writing repo is actually suspicious → high echo.
    some drift is healthy — means the writer is exploring new areas.
    """
    if len(file_changes) < 4:
        return 12.5  # not enough data, neutral

    mid = len(file_changes) // 2
    first_half = file_changes[:mid]
    second_half = file_changes[mid:]

    def dir_distribution(changes: List[List[str]]) -> Dict[str, int]:
        dirs = Counter()
        for change_set in changes:
            for f in change_set:
                top = f.split("/")[0] if "/" in f else f
                dirs[top] += 1
        return dict(dirs)

    dist_a = dir_distribution(first_half)
    dist_b = dir_distribution(second_half)

    # compute cosine similarity
    all_keys = set(dist_a.keys()) | set(dist_b.keys())
    if not all_keys:
        return 25.0

    dot = sum(dist_a.get(k, 0) * dist_b.get(k, 0) for k in all_keys)
    mag_a = math.sqrt(sum(v ** 2 for v in dist_a.values()))
    mag_b = math.sqrt(sum(v ** 2 for v in dist_b.values()))

    if mag_a == 0 or mag_b == 0:
        return 25.0

    similarity = dot / (mag_a * mag_b)

    # in a healthy writing repo, some drift is expected
    # similarity > 0.95 = very static = echoing
    # similarity < 0.5 = lots of exploration = healthy
    if similarity > 0.95:
        return round(20.0 + (similarity - 0.95) * 100, 2)  # 20-25
    elif similarity > 0.7:
        return round((similarity - 0.7) / 0.25 * 20, 2)  # 0-20
    else:
        return 0.0  # healthy drift


def score_rhythm_monotony(commits: List[Dict]) -> float:
    """score 0-25: how uniform are the commit intervals?
    perfectly uniform intervals suggest a mechanical loop, not organic writing.
    some variation is healthy.
    """
    if len(commits) < 3:
        return 12.5  # neutral

    # parse timestamps
    timestamps = []
    for c in commits:
        try:
            ts = c["timestamp"]
            # handle timezone offset
            if "+" in ts:
                ts = ts[:ts.rindex("+")]
            elif ts.endswith("Z"):
                ts = ts[:-1]
            dt = datetime.fromisoformat(ts)
            timestamps.append(dt.timestamp())
        except (ValueError, AttributeError):
            continue

    if len(timestamps) < 3:
        return 12.5

    # compute intervals (commits are newest-first, so reverse)
    timestamps.sort()
    intervals = [timestamps[i + 1] - timestamps[i]
                 for i in range(len(timestamps) - 1)]

    if not intervals:
        return 12.5

    avg = sum(intervals) / len(intervals)
    if avg == 0:
        return 25.0  # all at same time = suspicious

    # coefficient of variation
    variance = sum((i - avg) ** 2 for i in intervals) / len(intervals)
    std = math.sqrt(variance)
    cv = std / avg if avg > 0 else 0

    # cv near 0 = perfectly uniform = mechanical = high echo
    # cv > 1.0 = lots of variation = healthy = low echo
    # cv around 0.3-0.5 = normal for automated writer
    if cv < 0.1:
        return 25.0  # suspiciously uniform
    elif cv < 0.3:
        return round((0.3 - cv) / 0.2 * 15, 2)  # 0-15
    else:
        return 0.0  # healthy variation


def compute_echo_score(
    message_div: float,
    file_churn: float,
    topic_drift: float,
    rhythm_mono: float
) -> Tuple[float, str]:
    """compute total score and grade."""
    total = message_div + file_churn + topic_drift + rhythm_mono
    total = round(min(100, max(0, total)), 1)

    if total <= 20:
        grade = "VARIED"
    elif total <= 45:
        grade = "STABLE"
    elif total <= 70:
        grade = "ECHOING"
    else:
        grade = "STUCK"

    return total, grade


def format_bar(value: float, max_val: float = 25, width: int = 20) -> str:
    """format a simple ascii bar."""
    filled = int(round(value / max_val * width))
    filled = min(width, max(0, filled))
    return "█" * filled + "░" * (width - filled)


def analyze(repo: str = ".", window: int = 100, as_json: bool = False) -> int:
    """run echo analysis and return exit code."""
    repo = str(Path(repo).resolve())

    commits = get_recent_commits(repo, window)
    file_changes = get_file_changes(repo, window)

    msg_div = score_message_diversity(commits)
    f_churn = score_file_churn(file_changes)
    t_drift = score_topic_drift(file_changes)
    r_mono = score_rhythm_monotony(commits)

    total, grade = compute_echo_score(msg_div, f_churn, t_drift, r_mono)

    if as_json:
        output = {
            "echo_score": total,
            "grade": grade,
            "metrics": {
                "message_diversity": msg_div,
                "file_churn": f_churn,
                "topic_drift": t_drift,
                "rhythm_monotony": r_mono
            },
            "commits_analyzed": len(commits),
            "file_changes_analyzed": len(file_changes),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"\n{'=' * 50}")
        print(f"  repo echo analysis — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'=' * 50}\n")
        print(f"  commits analyzed:  {len(commits)}")
        print(f"  file changes:      {len(file_changes)} commit-groups\n")
        print(f"  ┌─ metrics ─────────────────────────────────┐")
        print(f"  │ message diversity  {format_bar(msg_div)}  {msg_div:>5.1f}/25 │")
        print(f"  │ file churn         {format_bar(f_churn)}  {f_churn:>5.1f}/25 │")
        print(f"  │ topic drift        {format_bar(t_drift)}  {t_drift:>5.1f}/25 │")
        print(f"  │ rhythm monotony    {format_bar(r_mono)}  {r_mono:>5.1f}/25 │")
        print(f"  └───────────────────────────────────────────┘\n")
        print(f"  ECHO SCORE: {total}/100  [{grade}]\n")

        if grade == "VARIED":
            print("  ✓ rich, diverse activity — writer is exploring well")
        elif grade == "STABLE":
            print("  ✓ normal steady-state — healthy automated writing")
        elif grade == "ECHOING":
            print("  ⚠ repetition emerging — writer may be looping")
        else:
            print("  ✗ writer likely stuck — intervention recommended")

        print()

    # exit code based on grade
    if grade in ("VARIED", "STABLE"):
        return 0
    elif grade == "ECHOING":
        return 1
    else:
        return 2


def main():
    parser = argparse.ArgumentParser(
        description="detect echo/repetition patterns in commit history"
    )
    parser.add_argument("--repo", default=".", help="path to git repo")
    parser.add_argument("--window", type=int, default=100,
                        help="number of recent commits to analyze")
    parser.add_argument("--json", action="store_true", help="output as JSON")
    args = parser.parse_args()

    sys.exit(analyze(args.repo, args.window, args.json))


if __name__ == "__main__":
    main()
