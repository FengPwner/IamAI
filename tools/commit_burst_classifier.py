#!/usr/bin/env python3
"""commit_burst_classifier.py — classify commit bursts by intent and quality.

A *burst* is a cluster of commits where the gap between consecutive
commits is shorter than a given threshold (default: 120 seconds).
Bursts happen for good reasons (a productive editing session) and
bad reasons (panic-fixing a broken push, admin catch-up after a stall).

Each burst is classified into one of:

  productive  — multiple distinct files changed, diverse messages
  admin       — mostly catch-up / housekeeping / auto-commit messages
  churn       — same file(s) modified repeatedly in quick succession
  recovery    — mix of fixes and restarts, typical post-stall cleanup

The tool reads `git log` output and reports per-burst detail plus an
aggregate *burst_health* verdict:

  healthy   — >= 60% of bursts are productive
  mixed     — productive is the plurality but < 60%
  stressed  — admin or recovery bursts dominate
  churning  — churn bursts are the majority

Usage:
    python3 tools/commit_burst_classifier.py              # last 100 commits
    python3 tools/commit_burst_classifier.py --count 200  # last 200
    python3 tools/commit_burst_classifier.py --burst-gap 180  # custom gap (seconds)
    python3 tools/commit_burst_classifier.py --json       # machine-readable

Exit codes:
    0  healthy or mixed
    1  stressed or churning
    2  insufficient data (< 3 commits)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple


# patterns that signal admin / housekeeping commits
ADMIN_PATTERNS = [
    re.compile(r"^catch-up", re.IGNORECASE),
    re.compile(r"^auto[- ]?commit", re.IGNORECASE),
    re.compile(r"^hourly monitor", re.IGNORECASE),
    re.compile(r"^backlog", re.IGNORECASE),
    re.compile(r"^merge branch", re.IGNORECASE),
    re.compile(r"^caretaker (visit|check)", re.IGNORECASE),
    re.compile(r"^process restart", re.IGNORECASE),
    re.compile(r"^push recovery", re.IGNORECASE),
    re.compile(r"^fix push", re.IGNORECASE),
    re.compile(r"^rescue", re.IGNORECASE),
]

# patterns that signal recovery / fix work
RECOVERY_PATTERNS = [
    re.compile(r"^fix", re.IGNORECASE),
    re.compile(r"^restart", re.IGNORECASE),
    re.compile(r"^revert", re.IGNORECASE),
    re.compile(r"^recover", re.IGNORECASE),
    re.compile(r"^patch", re.IGNORECASE),
    re.compile(r"^hotfix", re.IGNORECASE),
    re.compile(r"stall", re.IGNORECASE),
    re.compile(r"broken", re.IGNORECASE),
]


@dataclass
class Commit:
    hash: str
    timestamp: datetime
    message: str
    files_changed: int = 0


@dataclass
class Burst:
    commits: List[Commit]
    classification: str = ""
    unique_files_ratio: float = 0.0
    admin_ratio: float = 0.0
    recovery_ratio: float = 0.0


@dataclass
class BurstReport:
    total_commits: int
    total_bursts: int
    burst_sizes: List[int] = field(default_factory=list)
    classifications: dict = field(default_factory=dict)
    verdict: str = "unknown"
    productive_pct: float = 0.0
    admin_pct: float = 0.0
    churn_pct: float = 0.0
    recovery_pct: float = 0.0


def get_commits(count: int, repo_root: Path) -> List[Commit]:
    """Read the last `count` commits via git log."""
    result = subprocess.run(
        [
            "git", "log",
            f"--max-count={count}",
            "--format=%H|%aI|%s",
            "--shortstat",
        ],
        capture_output=True, text=True, cwd=str(repo_root),
    )
    if result.returncode != 0:
        return []

    commits: List[Commit] = []
    lines = result.stdout.strip().split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            i += 1
            continue
        h, ts_str, msg = parts
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            ts = datetime.now(timezone.utc)

        files_changed = 0
        # next line may be a shortstat line like " 3 files changed, 10 insertions(+)"
        if i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line and "file" in next_line:
                m = re.search(r"(\d+) file", next_line)
                if m:
                    files_changed = int(m.group(1))
                i += 1

        commits.append(Commit(
            hash=h[:8], timestamp=ts, message=msg,
            files_changed=max(files_changed, 1),
        ))
        i += 1

    return commits


def _is_admin(message: str) -> bool:
    return any(p.search(message) for p in ADMIN_PATTERNS)


def _is_recovery(message: str) -> bool:
    return any(p.search(message) for p in RECOVERY_PATTERNS)


def find_bursts(commits: List[Commit], burst_gap_s: int = 120) -> List[Burst]:
    """Group commits into bursts based on inter-commit gap."""
    if not commits:
        return []

    # sort chronologically regardless of input order
    ordered = sorted(commits, key=lambda c: c.timestamp)
    bursts: List[Burst] = []
    current: List[Commit] = [ordered[0]]

    for c in ordered[1:]:
        gap = (c.timestamp - current[-1].timestamp).total_seconds()
        if gap <= burst_gap_s:
            current.append(c)
        else:
            if len(current) >= 2:
                bursts.append(Burst(commits=current))
            current = [c]

    if len(current) >= 2:
        bursts.append(Burst(commits=current))

    return bursts


def classify_burst(burst: Burst) -> Burst:
    """Classify a single burst."""
    n = len(burst.commits)
    total_files = sum(c.files_changed for c in burst.commits)
    admin_count = sum(1 for c in burst.commits if _is_admin(c.message))
    recovery_count = sum(1 for c in burst.commits if _is_recovery(c.message))

    burst.admin_ratio = admin_count / n if n else 0
    burst.recovery_ratio = recovery_count / n if n else 0
    burst.unique_files_ratio = min(total_files / max(n, 1), 3.0) / 3.0

    # classification logic
    if burst.admin_ratio >= 0.6:
        burst.classification = "admin"
    elif burst.recovery_ratio >= 0.5:
        burst.classification = "recovery"
    elif burst.unique_files_ratio <= 0.4 and n >= 3:
        burst.classification = "churn"
    else:
        burst.classification = "productive"

    return burst


def compute_report(bursts: List[Burst], total_commits: int) -> BurstReport:
    """Aggregate burst classifications into a report."""
    if not bursts:
        return BurstReport(
            total_commits=total_commits,
            total_bursts=0,
            verdict="no_bursts",
        )

    sizes = [len(b.commits) for b in bursts]
    class_counts = {"productive": 0, "admin": 0, "churn": 0, "recovery": 0}
    for b in bursts:
        class_counts[b.classification] = class_counts.get(b.classification, 0) + 1

    n_bursts = len(bursts)
    pcts = {k: v / n_bursts for k, v in class_counts.items()}

    prod_pct = pcts.get("productive", 0)
    if prod_pct >= 0.6:
        verdict = "healthy"
    elif prod_pct >= 0.4:
        verdict = "mixed"
    elif pcts.get("churn", 0) > prod_pct:
        verdict = "churning"
    else:
        verdict = "stressed"

    return BurstReport(
        total_commits=total_commits,
        total_bursts=n_bursts,
        burst_sizes=sizes,
        classifications=class_counts,
        verdict=verdict,
        productive_pct=round(pcts.get("productive", 0) * 100, 1),
        admin_pct=round(pcts.get("admin", 0) * 100, 1),
        churn_pct=round(pcts.get("churn", 0) * 100, 1),
        recovery_pct=round(pcts.get("recovery", 0) * 100, 1),
    )


def format_report(report: BurstReport) -> str:
    """Human-readable output."""
    lines = [
        "commit burst classifier report",
        "=" * 44,
        f"commits analysed:  {report.total_commits}",
        f"bursts found:      {report.total_bursts}",
    ]
    if report.burst_sizes:
        lines.append(
            f"burst sizes:       "
            f"min={min(report.burst_sizes)} "
            f"max={max(report.burst_sizes)} "
            f"median={sorted(report.burst_sizes)[len(report.burst_sizes)//2]}"
        )
    lines.extend([
        "",
        "classification breakdown:",
        f"  productive:  {report.productive_pct:5.1f}%",
        f"  admin:       {report.admin_pct:5.1f}%",
        f"  churn:       {report.churn_pct:5.1f}%",
        f"  recovery:    {report.recovery_pct:5.1f}%",
        "",
        f"verdict:         {report.verdict}",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="classify commit bursts")
    parser.add_argument("--count", type=int, default=100,
                        help="number of recent commits to analyse")
    parser.add_argument("--burst-gap", type=int, default=120,
                        help="max seconds between commits to count as same burst")
    parser.add_argument("--json", action="store_true",
                        help="output as JSON")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    commits = get_commits(args.count, repo_root)
    if len(commits) < 3:
        print("error: need at least 3 commits", file=sys.stderr)
        return 2

    bursts = find_bursts(commits, burst_gap_s=args.burst_gap)
    for b in bursts:
        classify_burst(b)

    report = compute_report(bursts, len(commits))

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(format_report(report))

    return 0 if report.verdict in ("healthy", "mixed", "no_bursts") else 1


if __name__ == "__main__":
    sys.exit(main())
