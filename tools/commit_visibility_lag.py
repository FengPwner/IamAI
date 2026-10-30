#!/usr/bin/env python3
"""commit_visibility_lag.py — measure how far behind the remote is from local.

the ghost push index tells you *what fraction* of commits are unpushed.
the commit visibility lag tells you *how old* the oldest unpushed commit
is — in seconds, in hours, in days. it answers a different question:

    "if someone looks at the GitHub page right now, how far behind
     reality is what they see?"

formula:
    visibility_lag_seconds = now - timestamp_of_oldest_unpushed_commit

if all commits are pushed, lag is zero. if the oldest unpushed commit is
three days old, the remote is a three-day-old photograph of the repo.

this matters because the remote is the public record. Collaborators,
observers, and the operator's own dashboard all read the remote. When
the lag grows, the remote becomes fiction — it describes a repo that
stopped working days ago, even though the local repo has been producing
commits every ten minutes.

severity classification:
    REALTIME   — lag < 600s (10 min). remote is current.
    STALE      — lag < 3600s (1 hour). minor delay, likely transient.
    OUTDATED   — lag < 86400s (1 day). remote is noticeably behind.
    ANCIENT    — lag >= 86400s. remote is a historical artifact.

usage:
    python3 tools/commit_visibility_lag.py              # human-readable
    python3 tools/commit_visibility_lag.py --json        # machine-readable
    python3 tools/commit_visibility_lag.py --days        # show lag in days

exit codes:
    0 — REALTIME (< 10 min lag)
    1 — STALE (< 1 hour)
    2 — OUTDATED (< 1 day)
    3 — ANCIENT (>= 1 day)
    4 — error
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def run_git(*args: str) -> tuple[int, str]:
    """Run a git command and return (exit_code, stdout)."""
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    return result.returncode, result.stdout.strip()


def get_oldest_unpushed_commit_time() -> datetime | None:
    """Find the timestamp of the oldest unpushed commit.

    Uses git log to find the oldest commit that is ahead of the remote
    tracking branch. If no remote tracking branch exists, falls back to
    the oldest commit on the current branch.
    """
    # Try to find commits ahead of origin/main
    code, out = run_git(
        "log", "--format=%at", "--reverse", "origin/main..HEAD"
    )
    if code == 0 and out:
        lines = out.strip().split("\n")
        if lines:
            return datetime.fromtimestamp(int(lines[0]), tz=timezone.utc)

    # No remote tracking branch — try origin/HEAD
    code, out = run_git(
        "log", "--format=%at", "--reverse", "origin/HEAD..HEAD"
    )
    if code == 0 and out:
        lines = out.strip().split("\n")
        if lines:
            return datetime.fromtimestamp(int(lines[0]), tz=timezone.utc)

    # Fallback: if there's no remote at all, every commit is unpushed.
    # Use the oldest commit on the current branch.
    code, out = run_git("log", "--format=%at", "--reverse", "HEAD")
    if code == 0 and out:
        lines = out.strip().split("\n")
        if lines:
            return datetime.fromtimestamp(int(lines[0]), tz=timezone.utc)

    return None


def get_newest_unpushed_commit_time() -> datetime | None:
    """Find the timestamp of the newest unpushed commit."""
    code, out = run_git(
        "log", "--format=%at", "-1", "origin/main..HEAD"
    )
    if code == 0 and out:
        return datetime.fromtimestamp(int(out.strip()), tz=timezone.utc)

    code, out = run_git("log", "--format=%at", "-1", "HEAD")
    if code == 0 and out:
        return datetime.fromtimestamp(int(out.strip()), tz=timezone.utc)

    return None


def get_unpushed_count() -> int:
    """Count unpushed commits."""
    code, out = run_git("rev-list", "--count", "origin/main..HEAD")
    if code == 0:
        return int(out.strip())
    # No remote — all commits are unpushed
    code, out = run_git("rev-list", "--count", "HEAD")
    if code == 0:
        return int(out.strip())
    return 0


def get_total_count() -> int:
    """Count total commits."""
    code, out = run_git("rev-list", "--count", "HEAD")
    if code == 0:
        return int(out.strip())
    return 0


def classify_severity(lag_seconds: float) -> str:
    """Classify the visibility lag into severity levels."""
    if lag_seconds < 600:
        return "REALTIME"
    elif lag_seconds < 3600:
        return "STALE"
    elif lag_seconds < 86400:
        return "OUTDATED"
    else:
        return "ANCIENT"


def severity_to_exit(severity: str) -> int:
    """Map severity label to exit code."""
    return {
        "REALTIME": 0,
        "STALE": 1,
        "OUTDATED": 2,
        "ANCIENT": 3,
    }.get(severity, 4)


def format_lag(seconds: float, use_days: bool = False) -> str:
    """Format lag in human-readable units."""
    if use_days:
        days = seconds / 86400
        return f"{days:.1f} days"
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f} min"
    elif seconds < 86400:
        return f"{seconds / 3600:.1f} hours"
    else:
        return f"{seconds / 86400:.1f} days"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure commit visibility lag (local vs remote)"
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--days", action="store_true", help="Show lag in days")
    args = parser.parse_args()

    now = datetime.now(tz=timezone.utc)
    oldest = get_oldest_unpushed_commit_time()
    newest = get_newest_unpushed_commit_time()
    unpushed = get_unpushed_count()
    total = get_total_count()

    if oldest is None:
        # No commits at all, or everything is pushed
        if total == 0:
            if args.json:
                print(json.dumps({
                    "visibility_lag_seconds": 0,
                    "severity": "REALTIME",
                    "unpushed_commits": 0,
                    "total_commits": 0,
                    "oldest_unpushed": None,
                    "newest_unpushed": None,
                }))
            else:
                print("commit visibility lag: no commits found")
            return 4

        # Everything is pushed
        if args.json:
            print(json.dumps({
                "visibility_lag_seconds": 0,
                "severity": "REALTIME",
                "unpushed_commits": 0,
                "total_commits": total,
                "oldest_unpushed": None,
                "newest_unpushed": None,
            }))
        else:
            print("commit visibility lag: 0s (REALTIME) — all commits pushed")
        return 0

    lag = (now - oldest).total_seconds()
    severity = classify_severity(lag)

    if args.json:
        print(json.dumps({
            "visibility_lag_seconds": round(lag, 1),
            "visibility_lag_human": format_lag(lag, args.days),
            "severity": severity,
            "unpushed_commits": unpushed,
            "total_commits": total,
            "oldest_unpushed": oldest.isoformat(),
            "newest_unpushed": newest.isoformat() if newest else None,
        }))
    else:
        lag_str = format_lag(lag, args.days)
        print(f"commit visibility lag: {lag_str} ({severity})")
        print(f"  oldest unpushed: {oldest.strftime('%Y-%m-%d %H:%M UTC')}")
        if newest:
            print(f"  newest unpushed: {newest.strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"  unpushed: {unpushed} / {total} commits")

        if severity in ("OUTDATED", "ANCIENT"):
            print()
            print("  the remote is showing a repo that stopped working")
            print(f"  {lag_str} ago. everything since then is invisible.")
            print()
            print("  to fix: register the deploy key on GitHub, then push.")

    return severity_to_exit(severity)


if __name__ == "__main__":
    sys.exit(main())
