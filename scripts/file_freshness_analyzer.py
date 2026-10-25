#!/usr/bin/env python3
"""
file_freshness_analyzer.py — measure how actively maintained the codebase is.

the IamAI repo grows continuously through automated writing and caretaker visits.
over time, some files become stale (untouched for weeks or months) while others
stay fresh. this tool measures the age distribution of all tracked files and
scores the repo's overall freshness.

metrics (each 0–25, total 0–100, lower is better):
  1. median_file_age      — median days since last modification across all files
  2. stale_file_ratio     — percentage of files not touched in 30+ days
  3. critical_file_freshness — are tests/tools/docs kept up to date?
  4. age_dispersion       — how spread out are file ages (Gini-like measure)

grading:
  0–20   FRESH    — actively maintained, most files recent
  21–45  HEALTHY  — some aging but core areas stay current
  46–70  STALE    — significant portions untouched for weeks
  71–100 ANCIENT  — most files haven't changed in months

usage:
    python3 scripts/file_freshness_analyzer.py [--repo PATH] [--stale-days N]
    python3 scripts/file_freshness_analyzer.py --json

exit codes:
    0 = FRESH or HEALTHY (good)
    1 = STALE (warning)
    2 = ANCIENT (alert)
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ── helpers ──────────────────────────────────────────────────────────

def run_git(repo: str, *args: str) -> str:
    """run a git command and return stdout."""
    result = subprocess.run(
        ["git", "-C", repo] + list(args),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def get_tracked_files(repo: str) -> List[str]:
    """return list of all tracked files."""
    output = run_git(repo, "ls-files")
    return [f for f in output.split("\n") if f]


def get_file_age_days(repo: str, filepath: str) -> Optional[int]:
    """get days since last commit that touched this file."""
    try:
        output = run_git(repo, "log", "-1", "--format=%ct", "--", filepath)
        if not output:
            return None
        timestamp = int(output)
        now = datetime.now(timezone.utc).timestamp()
        return int((now - timestamp) / 86400)
    except (RuntimeError, ValueError):
        return None


def get_all_file_ages(repo: str, files: List[str]) -> Dict[str, int]:
    """get age in days for each file. skips files with no git history."""
    ages = {}
    for f in files:
        age = get_file_age_days(repo, f)
        if age is not None:
            ages[f] = age
    return ages


# ── metrics ──────────────────────────────────────────────────────────

def compute_median_age(ages: Dict[str, int]) -> float:
    """median file age in days."""
    if not ages:
        return 0.0
    sorted_ages = sorted(ages.values())
    n = len(sorted_ages)
    if n % 2 == 0:
        return (sorted_ages[n // 2 - 1] + sorted_ages[n // 2]) / 2.0
    return float(sorted_ages[n // 2])


def compute_stale_ratio(ages: Dict[str, int], stale_days: int = 30) -> float:
    """percentage of files not modified in stale_days."""
    if not ages:
        return 0.0
    stale_count = sum(1 for age in ages.values() if age >= stale_days)
    return (stale_count / len(ages)) * 100.0


def compute_critical_freshness(ages: Dict[str, int]) -> float:
    """
    average age of critical directories: tests/, tools/, scripts/, docs/.
    lower is better. returns median age in days for files in these dirs.
    """
    critical_prefixes = ("tests/", "tools/", "scripts/", "docs/")
    critical_ages = [
        age for path, age in ages.items()
        if any(path.startswith(prefix) for prefix in critical_prefixes)
    ]
    if not critical_ages:
        return 0.0
    critical_ages.sort()
    n = len(critical_ages)
    if n % 2 == 0:
        return (critical_ages[n // 2 - 1] + critical_ages[n // 2]) / 2.0
    return float(critical_ages[n // 2])


def compute_age_dispersion(ages: Dict[str, int]) -> float:
    """
    gini-like measure of age inequality. 0 = all same age, 1 = max spread.
    computed as mean absolute difference / (2 * mean).
    """
    if not ages:
        return 0.0
    values = list(ages.values())
    n = len(values)
    if n < 2:
        return 0.0
    mean_age = sum(values) / n
    if mean_age == 0:
        return 0.0
    total_diff = 0
    for i in range(n):
        for j in range(i + 1, n):
            total_diff += abs(values[i] - values[j])
    gini = total_diff / (n * n * mean_age)
    return min(gini, 1.0)


# ── scoring ──────────────────────────────────────────────────────────

def score_median_age(median_days: float) -> int:
    """score median file age. 0=recent, 25=very old."""
    if median_days <= 3:
        return 0
    elif median_days <= 7:
        return 5
    elif median_days <= 14:
        return 10
    elif median_days <= 30:
        return 15
    elif median_days <= 60:
        return 20
    else:
        return 25


def score_stale_ratio(ratio: float) -> int:
    """score stale file percentage. 0=few stale, 25=mostly stale."""
    if ratio <= 10:
        return 0
    elif ratio <= 25:
        return 5
    elif ratio <= 40:
        return 10
    elif ratio <= 60:
        return 15
    elif ratio <= 80:
        return 20
    else:
        return 25


def score_critical_freshness(median_days: float) -> int:
    """score critical directory freshness. 0=fresh, 25=neglected."""
    if median_days <= 2:
        return 0
    elif median_days <= 5:
        return 5
    elif median_days <= 10:
        return 10
    elif median_days <= 20:
        return 15
    elif median_days <= 40:
        return 20
    else:
        return 25


def score_dispersion(gini: float) -> int:
    """score age dispersion. 0=uniform, 25=highly skewed."""
    if gini <= 0.1:
        return 0
    elif gini <= 0.2:
        return 5
    elif gini <= 0.3:
        return 10
    elif gini <= 0.5:
        return 15
    elif gini <= 0.7:
        return 20
    else:
        return 25


def compute_freshness_score(ages: Dict[str, int], stale_days: int = 30) -> Dict:
    """compute all metrics and total freshness score."""
    if not ages:
        return {
            "median_file_age": 0,
            "stale_file_ratio": 0,
            "critical_file_freshness": 0,
            "age_dispersion": 0,
            "total": 0,
            "grade": "FRESH",
            "exit_code": 0,
            "median_days": 0.0,
            "stale_ratio_pct": 0.0,
            "critical_median_days": 0.0,
            "dispersion_gini": 0.0,
            "file_count": 0,
        }

    median_age = compute_median_age(ages)
    stale_ratio = compute_stale_ratio(ages, stale_days)
    critical_fresh = compute_critical_freshness(ages)
    dispersion = compute_age_dispersion(ages)

    scores = {
        "median_file_age": score_median_age(median_age),
        "stale_file_ratio": score_stale_ratio(stale_ratio),
        "critical_file_freshness": score_critical_freshness(critical_fresh),
        "age_dispersion": score_dispersion(dispersion),
    }

    total = sum(scores.values())

    if total <= 20:
        grade = "FRESH"
        exit_code = 0
    elif total <= 45:
        grade = "HEALTHY"
        exit_code = 0
    elif total <= 70:
        grade = "STALE"
        exit_code = 1
    else:
        grade = "ANCIENT"
        exit_code = 2

    return {
        **scores,
        "total": total,
        "grade": grade,
        "exit_code": exit_code,
        "median_days": median_age,
        "stale_ratio_pct": stale_ratio,
        "critical_median_days": critical_fresh,
        "dispersion_gini": dispersion,
        "file_count": len(ages),
    }


# ── formatting ───────────────────────────────────────────────────────

def format_bar(value: int, max_value: int = 25, width: int = 20) -> str:
    """render a progress bar."""
    filled = int((value / max_value) * width)
    return "[" + "#" * filled + "." * (width - filled) + "]"


def format_report(result: Dict) -> str:
    """format full freshness report."""
    lines = [
        "═══ file freshness analyzer ═══",
        "",
        f"files analyzed: {result['file_count']}",
        f"stale threshold: {result.get('stale_days', 30)} days",
        "",
        "metrics:",
        f"  median_file_age      {format_bar(result['median_file_age'])} "
        f"{result['median_file_age']:2d}/25  (median {result['median_days']:.1f} days)",
        f"  stale_file_ratio     {format_bar(result['stale_file_ratio'])} "
        f"{result['stale_file_ratio']:2d}/25  ({result['stale_ratio_pct']:.1f}% stale)",
        f"  critical_freshness   {format_bar(result['critical_file_freshness'])} "
        f"{result['critical_file_freshness']:2d}/25  (critical median {result['critical_median_days']:.1f} days)",
        f"  age_dispersion       {format_bar(result['age_dispersion'])} "
        f"{result['age_dispersion']:2d}/25  (gini {result['dispersion_gini']:.3f})",
        "",
        f"total: {result['total']}/100",
        f"grade: {result['grade']}",
        "",
    ]
    return "\n".join(lines)


# ── main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="analyze file freshness")
    parser.add_argument("--repo", default=".", help="path to git repo")
    parser.add_argument("--stale-days", type=int, default=30, help="days to consider stale")
    parser.add_argument("--json", action="store_true", help="output JSON")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)

    try:
        files = get_tracked_files(repo)
        ages = get_all_file_ages(repo, files)
        result = compute_freshness_score(ages, args.stale_days)
        result["stale_days"] = args.stale_days

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(format_report(result))

        sys.exit(result["exit_code"])

    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
