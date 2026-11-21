#!/usr/bin/env python3
"""post_visit_productivity.py — measure progress vs repair after caretaker visits.

after a caretaker restarts the writer, the next N hours of commits reveal
whether the visit was productive or just damage control. this tool
classifies each commit in the post-visit window as either:

  - progress: new module, new test, new note, feature addition
  - repair:   catch-up commit, lock cleanup, state reset, merge fix

outputs:
  - total commits in window
  - progress count and ratio
  - repair count and ratio
  - verdict: healthy (>0.6), mixed (0.4-0.6), unhealthy (<0.4)
  - trend over last N visits if historical data available

usage:
    python3 tools/post_visit_productivity.py
    python3 tools/post_visit_productivity.py --window-hours 6
    python3 tools/post_visit_productivity.py --since "2026-11-21T02:00:00"
    python3 tools/post_visit_productivity.py --json

exit codes:
    0 — healthy (progress ratio > 0.6)
    1 — mixed (0.4 <= ratio <= 0.6)
    2 — unhealthy (ratio < 0.4) or no data
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple


REPAIR_PATTERNS = [
    re.compile(r"catch[- ]up", re.IGNORECASE),
    re.compile(r"lock (clean|repair|reset)", re.IGNORECASE),
    re.compile(r"state reset", re.IGNORECASE),
    re.compile(r"merge (fix|conflict|resolution)", re.IGNORECASE),
    re.compile(r"backlog (drain|flush|clear)", re.IGNORECASE),
    re.compile(r"pending changes before", re.IGNORECASE),
    re.compile(r"stale lock", re.IGNORECASE),
    re.compile(r"orphan cleanup", re.IGNORECASE),
    re.compile(r"git gc", re.IGNORECASE),
]

PROGRESS_PATTERNS = [
    re.compile(r"add \w+", re.IGNORECASE),
    re.compile(r"new (module|test|note|feature|tool)", re.IGNORECASE),
    re.compile(r"implement", re.IGNORECASE),
    re.compile(r"caretaker visit \d+:", re.IGNORECASE),
    re.compile(r"stroke \d+", re.IGNORECASE),
    re.compile(r"tree is \d+ files", re.IGNORECASE),
    re.compile(r"lines across \d+ tracked", re.IGNORECASE),
    re.compile(r"python files, \d+ logged", re.IGNORECASE),
    re.compile(r"strokes written so far", re.IGNORECASE),
    re.compile(r"commit \d+:", re.IGNORECASE),
]


@dataclass
class Commit:
    hash: str
    timestamp: datetime
    message: str
    classification: str  # "progress", "repair", or "unknown"


@dataclass
class ProductivityReport:
    window_start: str
    window_end: str
    total_commits: int
    progress_count: int
    repair_count: int
    unknown_count: int
    progress_ratio: float
    repair_ratio: float
    verdict: str
    commits: List[dict]


def get_commits_since(
    since: datetime,
    until: Optional[datetime] = None,
    repo_root: Optional[Path] = None,
) -> List[Commit]:
    """Get commits from git log since a given timestamp."""
    cmd = [
        "git", "log",
        f"--since={since.isoformat()}",
        "--format=%H|%aI|%s",
    ]
    if until:
        cmd.insert(2, f"--until={until.isoformat()}")

    kwargs = {"capture_output": True, "text": True}
    if repo_root:
        kwargs["cwd"] = str(repo_root)

    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        return []

    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        hash_, ts_str, message = parts
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        classification = classify_commit(message)
        commits.append(Commit(
            hash=hash_[:7],
            timestamp=ts,
            message=message,
            classification=classification,
        ))
    return commits


def classify_commit(message: str) -> str:
    """Classify a commit message as progress or repair."""
    for pattern in REPAIR_PATTERNS:
        if pattern.search(message):
            return "repair"
    for pattern in PROGRESS_PATTERNS:
        if pattern.search(message):
            return "progress"
    return "unknown"


def compute_productivity(
    commits: List[Commit],
    window_start: datetime,
    window_end: datetime,
) -> ProductivityReport:
    """Compute productivity metrics from a list of commits."""
    total = len(commits)
    progress = sum(1 for c in commits if c.classification == "progress")
    repair = sum(1 for c in commits if c.classification == "repair")
    unknown = total - progress - repair

    progress_ratio = progress / total if total > 0 else 0.0
    repair_ratio = repair / total if total > 0 else 0.0

    if progress_ratio > 0.6:
        verdict = "healthy"
    elif progress_ratio >= 0.4:
        verdict = "mixed"
    else:
        verdict = "unhealthy" if total > 0 else "no_data"

    return ProductivityReport(
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        total_commits=total,
        progress_count=progress,
        repair_count=repair,
        unknown_count=unknown,
        progress_ratio=round(progress_ratio, 3),
        repair_ratio=round(repair_ratio, 3),
        verdict=verdict,
        commits=[asdict(c) for c in commits],
    )


def format_report(report: ProductivityReport) -> str:
    """Format productivity report as human-readable text."""
    lines = [
        "post-visit productivity report",
        "=" * 44,
        f"window:           {report.window_start}",
        f"  →               {report.window_end}",
        f"total commits:    {report.total_commits}",
        f"progress:         {report.progress_count} "
        f"({report.progress_ratio:.1%})",
        f"repair:           {report.repair_count} "
        f"({report.repair_ratio:.1%})",
        f"unknown:          {report.unknown_count}",
        f"verdict:          {report.verdict}",
        "",
        "commit breakdown:",
    ]
    for c in report.commits:
        tag = c["classification"][0].upper()
        lines.append(f"  [{tag}] {c['hash']} {c['message'][:60]}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="post-visit productivity analyzer"
    )
    parser.add_argument(
        "--window-hours", type=float, default=6.0,
        help="hours after visit start to analyze (default: 6)",
    )
    parser.add_argument(
        "--since", type=str, default=None,
        help="ISO timestamp for window start (default: now - window)",
    )
    parser.add_argument(
        "--repo", type=str, default=None,
        help="path to git repository root",
    )
    parser.add_argument("--json", action="store_true", help="output as JSON")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo) if args.repo else Path(__file__).resolve().parent.parent

    now = datetime.now(timezone.utc)
    if args.since:
        window_start = datetime.fromisoformat(args.since)
        if window_start.tzinfo is None:
            window_start = window_start.replace(tzinfo=timezone.utc)
    else:
        window_start = now - timedelta(hours=args.window_hours)

    window_end = window_start + timedelta(hours=args.window_hours)

    commits = get_commits_since(window_start, window_end, repo_root)
    report = compute_productivity(commits, window_start, window_end)

    if args.json:
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        print(format_report(report))

    if report.verdict == "healthy":
        return 0
    elif report.verdict == "mixed":
        return 1
    else:
        return 2


if __name__ == "__main__":
    sys.exit(main())
