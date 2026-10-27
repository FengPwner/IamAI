#!/usr/bin/env python3
"""commit_drift_monitor.py — measure local-vs-remote divergence and recovery cost.

Push debt is a stock; commit drift is the flow *and* the stock together.
This tool answers three questions:

  1. **How far ahead** is local from remote?  (commit count, time span)
  2. **How fast** is the gap growing?        (commits/hour over recent window)
  3. **How hard** will recovery be?          (estimated push time, conflict risk)

Recovery difficulty classification:
  - trivial:    <5 commits, <1h divergence
  - easy:       5–20 commits, <6h divergence
  - moderate:   20–50 commits, <24h divergence
  - hard:       50–100 commits, 1–7d divergence
  - extreme:    >100 commits or >7d divergence

Each classification carries a suggested action:
  - trivial/easy → just push
  - moderate     → push with --force-with-lease after verifying no collaborators
  - hard         → create a PR branch, squash-merge
  - extreme      → consider rebase onto remote/main, squash into logical batches

Usage:
    python3 tools/commit_drift_monitor.py
    python3 tools/commit_drift_monitor.py --json
    python3 tools/commit_drift_monitor.py --repo /path/to/repo

Exit codes:
    0 — trivial or no drift
    1 — drift detected (easy or worse)
    2 — error
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


TRIVIAL_THRESHOLD = 5
EASY_THRESHOLD = 20
MODERATE_THRESHOLD = 50
HARD_THRESHOLD = 100

TRIVIAL_HOURS = 1
EASY_HOURS = 6
MODERATE_HOURS = 24
HARD_HOURS = 168  # 7 days

DRIFT_WINDOW_HOURS = 2  # lookback for rate calculation


@dataclass
class DriftSnapshot:
    unpushed_count: int
    oldest_unpushed_age_hours: Optional[float]
    newest_unpushed_age_hours: Optional[float]
    divergence_span_hours: Optional[float]
    recent_rate_per_hour: float
    severity: str
    suggested_action: str
    remote_name: str
    branch: str
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)


def run_cmd(cmd: List[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=30, cwd=cwd
    )


def get_remote_name(repo_path: Optional[str] = None) -> str:
    r = run_cmd(["git", "remote"], cwd=repo_path)
    remotes = r.stdout.strip().split("\n")
    if "origin" in remotes:
        return "origin"
    return remotes[0] if remotes and remotes[0] else "origin"


def get_current_branch(repo_path: Optional[str] = None) -> str:
    r = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    return r.stdout.strip() or "main"


def count_unpushed(remote: str, branch: str, repo_path: Optional[str] = None) -> int:
    r = run_cmd(
        ["git", "rev-list", "--count", f"{remote}/{branch}..{branch}"],
        cwd=repo_path,
    )
    try:
        return int(r.stdout.strip())
    except (ValueError, AttributeError):
        return 0


def get_oldest_unpushed_age_hours(
    remote: str, branch: str, repo_path: Optional[str] = None
) -> Optional[float]:
    """Hours since the oldest unpushed commit was authored."""
    r = run_cmd(
        ["git", "log", "--format=%aI", f"{remote}/{branch}..{branch}", "--reverse"],
        cwd=repo_path,
    )
    lines = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
    if not lines:
        return None
    try:
        oldest = datetime.fromisoformat(lines[0])
        now = datetime.now(timezone.utc)
        return (now - oldest).total_seconds() / 3600
    except (ValueError, IndexError):
        return None


def get_newest_unpushed_age_hours(
    remote: str, branch: str, repo_path: Optional[str] = None
) -> Optional[float]:
    """Hours since the newest unpushed commit was authored."""
    r = run_cmd(
        ["git", "log", "--format=%aI", f"{remote}/{branch}..{branch}", "-1"],
        cwd=repo_path,
    )
    line = r.stdout.strip()
    if not line:
        return None
    try:
        newest = datetime.fromisoformat(line)
        now = datetime.now(timezone.utc)
        return (now - newest).total_seconds() / 3600
    except (ValueError, IndexError):
        return None


def get_recent_rate(
    remote: str, branch: str, window_hours: float = DRIFT_WINDOW_HOURS,
    repo_path: Optional[str] = None
) -> float:
    """Commits per hour in the recent window."""
    r = run_cmd(
        ["git", "log", "--format=%aI", f"{remote}/{branch}..{branch}"],
        cwd=repo_path,
    )
    lines = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
    if not lines:
        return 0.0

    now = datetime.now(timezone.utc)
    cutoff_hours = []
    for line in lines:
        try:
            dt = datetime.fromisoformat(line)
            age_h = (now - dt).total_seconds() / 3600
            if age_h <= window_hours:
                cutoff_hours.append(age_h)
        except ValueError:
            continue

    if window_hours <= 0:
        return 0.0
    return len(cutoff_hours) / window_hours


def classify_drift(
    unpushed_count: int, age_hours: Optional[float]
) -> tuple[str, str]:
    """Return (severity, suggested_action)."""
    if unpushed_count == 0:
        return "none", "nothing to do"

    h = age_hours or 0

    if unpushed_count >= HARD_THRESHOLD or h > HARD_HOURS:
        return "extreme", "consider rebase onto remote/main, squash into logical batches"
    if unpushed_count >= MODERATE_THRESHOLD or h > MODERATE_HOURS:
        return "hard", "create a PR branch, squash-merge to avoid force-push"
    if unpushed_count >= EASY_THRESHOLD or h > EASY_HOURS:
        return "moderate", "push with --force-with-lease after verifying no collaborators"
    if unpushed_count >= TRIVIAL_THRESHOLD or h > TRIVIAL_HOURS:
        return "easy", "just push"
    return "trivial", "just push"


def measure(repo_path: Optional[str] = None) -> DriftSnapshot:
    remote = get_remote_name(repo_path)
    branch = get_current_branch(repo_path)
    unpushed = count_unpushed(remote, branch, repo_path)
    oldest_age = get_oldest_unpushed_age_hours(remote, branch, repo_path)
    newest_age = get_newest_unpushed_age_hours(remote, branch, repo_path)
    span = None
    if oldest_age is not None and newest_age is not None:
        span = oldest_age - newest_age

    rate = get_recent_rate(remote, branch, repo_path=repo_path)
    severity, action = classify_drift(unpushed, oldest_age)

    return DriftSnapshot(
        unpushed_count=unpushed,
        oldest_unpushed_age_hours=round(oldest_age, 2) if oldest_age is not None else None,
        newest_unpushed_age_hours=round(newest_age, 2) if newest_age is not None else None,
        divergence_span_hours=round(span, 2) if span is not None else None,
        recent_rate_per_hour=round(rate, 2),
        severity=severity,
        suggested_action=action,
        remote_name=remote,
        branch=branch,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def format_human(s: DriftSnapshot) -> str:
    lines = [
        f"Commit Drift Monitor — {s.timestamp}",
        f"  remote/branch:  {s.remote_name}/{s.branch}",
        f"  unpushed:       {s.unpushed_count} commits",
        f"  oldest age:     {s.oldest_unpushed_age_hours or '?'}h",
        f"  newest age:     {s.newest_unpushed_age_hours or '?'}h",
        f"  span:           {s.divergence_span_hours or '?'}h",
        f"  recent rate:    {s.recent_rate_per_hour} commits/h",
        f"  severity:       {s.severity}",
        f"  suggested:      {s.suggested_action}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Measure commit drift")
    parser.add_argument("--repo", default=None, help="path to git repo")
    parser.add_argument("--json", action="store_true", help="output JSON")
    args = parser.parse_args()

    try:
        snap = measure(args.repo)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(snap.to_dict(), indent=2))
    else:
        print(format_human(snap))

    if snap.severity in ("none", "trivial"):
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
