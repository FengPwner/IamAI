#!/usr/bin/env python3
"""commit_age.py — measure how old the oldest uncommitted change is.

When the batch committer fails silently, uncommitted files accumulate.
The *count* of uncommitted files is tracked by backlog_monitor.py, but
count alone misses urgency: five files changed 30 seconds ago is fine,
five files changed 4 hours ago means the committer has been broken all
morning.

This tool fills that gap.  It reads `git status --porcelain`, finds the
oldest file mtime among modified/staged files, and reports the age in
seconds.

Exit codes:
    0 — fresh   (oldest change < 600s / 10 min)
    1 — aging   (600s ≤ age < 3600s)
    2 — stale   (age ≥ 3600s / 1 hour)
    3 — clean   (nothing to commit — no age to measure)

Usage:
    python3 tools/commit_age.py
    python3 tools/commit_age.py --repo /path/to/IamAI
    python3 tools/commit_age.py --aging 900 --stale 7200
    python3 tools/commit_age.py --json
"""

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgeReport:
    age_seconds: float
    oldest_file: str
    uncommitted_count: int
    verdict: str  # "fresh", "aging", "stale", "clean"


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) to find a git repo root."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return p


def parse_porcelain(line: str) -> str | None:
    """Extract file path from a git status --porcelain line."""
    if len(line) < 4:
        return None
    return line[3:].strip()


def get_uncommitted_files(repo: Path) -> list[str]:
    """Return list of modified/staged/untracked file paths (relative to repo)."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=repo, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    if result.returncode != 0:
        return []

    files = []
    for raw in result.stdout.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        path = parse_porcelain(line)
        if path:
            # Handle renames: "R  old -> new"
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            files.append(path)
    return files


def get_oldest_mtime(repo: Path, files: list[str]) -> tuple[float, str] | None:
    """Return (age_seconds, oldest_filename) or None if no files have valid mtime."""
    now = time.time()
    oldest_age = 0.0
    oldest_name = ""

    for f in files:
        full = repo / f
        if not full.exists():
            continue
        mtime = full.stat().st_mtime
        age = now - mtime
        if age > oldest_age:
            oldest_age = age
            oldest_name = f

    if oldest_age > 0.0:
        return (oldest_age, oldest_name)
    return None


def classify(age: float, aging_thresh: float, stale_thresh: float) -> str:
    if age < aging_thresh:
        return "fresh"
    elif age < stale_thresh:
        return "aging"
    else:
        return "stale"


def verdict_to_exit(verdict: str) -> int:
    return {"fresh": 0, "aging": 1, "stale": 2, "clean": 3}[verdict]


def format_text(report: AgeReport) -> str:
    if report.verdict == "clean":
        return "clean: no uncommitted changes"
    minutes = report.age_seconds / 60
    hours = report.age_seconds / 3600
    if hours >= 1:
        age_str = f"{hours:.1f}h"
    else:
        age_str = f"{minutes:.0f}m"
    return (
        f"{report.verdict}: oldest change is {age_str} old "
        f"({report.oldest_file}, {report.uncommitted_count} file(s))"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure uncommitted change age.")
    parser.add_argument("--repo", type=Path, default=None, help="Repo root path")
    parser.add_argument("--aging", type=float, default=600, help="Aging threshold (seconds)")
    parser.add_argument("--stale", type=float, default=3600, help="Stale threshold (seconds)")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    repo = find_repo_root(args.repo)
    files = get_uncommitted_files(repo)

    if not files:
        report = AgeReport(0.0, "", 0, "clean")
    else:
        result = get_oldest_mtime(repo, files)
        if result is None:
            report = AgeReport(0.0, "", len(files), "clean")
        else:
            age, name = result
            verdict = classify(age, args.aging, args.stale)
            report = AgeReport(age, name, len(files), verdict)

    if args.json:
        print(json.dumps({
            "age_seconds": round(report.age_seconds, 1),
            "oldest_file": report.oldest_file,
            "uncommitted_count": report.uncommitted_count,
            "verdict": report.verdict,
        }))
    else:
        print(format_text(report))

    return verdict_to_exit(report.verdict)


if __name__ == "__main__":
    sys.exit(main())
