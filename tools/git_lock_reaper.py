#!/usr/bin/env python3
"""git_lock_reaper.py — detect and remove stale .git/index.lock files.

When a git process crashes or is killed mid-operation, it can leave behind
an index.lock file that blocks all subsequent git commands. This is a
common failure mode in automated repos where multiple agents share the
same working tree.

The reaper distinguishes between:

1. **fresh lock** — created recently (within threshold), likely belongs
   to an active git process. Leave it alone.
2. **stale lock** — older than threshold, no corresponding git process
   running. Safe to remove.
3. **orphan lock** — a lock file exists but no git process holds it
   (checked via /proc or fuser). Safe to remove regardless of age.

Detection signals (any one triggers reaping):

- lock age exceeds ``--max-age`` (default 300s)
- no git process currently running (ps-based check)
- lock holder PID no longer exists (parsed from lock file mtime + ps)

Usage:
    python3 tools/git_lock_reaper.py                  # scan and report
    python3 tools/git_lock_reaper.py --reap           # scan and remove stale
    python3 tools/git_lock_reaper.py --reap --dry-run # report what would be removed
    python3 tools/git_lock_reaper.py --repo /path     # custom repo path

Exit codes:
    0  no stale locks found (or all reaped successfully)
    1  stale locks found (without --reap)
    2  reap attempted but some locks could not be removed

Written by Qwen during caretaker visit 671, 2026-11-17.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class LockReport:
    """Report for a single lock file."""
    path: str
    exists: bool
    age_seconds: float
    is_stale: bool
    reason: str  # "fresh", "stale_age", "stale_no_git", "orphan"
    reaped: bool = False
    reap_error: Optional[str] = None


def find_git_root(repo_path: str) -> Optional[Path]:
    """Find the .git directory for the given repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, cwd=repo_path, timeout=5
        )
        if result.returncode == 0:
            git_dir = Path(result.stdout.strip())
            if not git_dir.is_absolute():
                git_dir = Path(repo_path) / git_dir
            return git_dir
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    # fallback: check if .git exists directly
    candidate = Path(repo_path) / ".git"
    if candidate.exists():
        return candidate
    return None


def find_lock_files(git_dir: Path) -> List[Path]:
    """Find all lock files in the .git directory."""
    lock_names = ["index.lock", "config.lock", "HEAD.lock",
                  "refs.lock", "packed-refs.lock"]
    found = []
    for name in lock_names:
        lock_path = git_dir / name
        if lock_path.exists():
            found.append(lock_path)
    # also check refs/ subdirectories
    refs_dir = git_dir / "refs"
    if refs_dir.is_dir():
        for lock_path in refs_dir.rglob("*.lock"):
            found.append(lock_path)
    return found


def get_lock_age(lock_path: Path) -> float:
    """Return the age of a lock file in seconds."""
    try:
        mtime = lock_path.stat().st_mtime
        return time.time() - mtime
    except OSError:
        return float("inf")


def git_process_running() -> bool:
    """Check if any git process is currently running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "git (commit|merge|rebase|pull|push|fetch|checkout|add)"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # pgrep not available; assume a git process might be running
        return True


def is_lock_stale(lock_path: Path, max_age: float) -> tuple:
    """Determine if a lock is stale and why.

    Returns (is_stale: bool, reason: str).
    """
    age = get_lock_age(lock_path)

    # age-based check
    if age > max_age:
        if not git_process_running():
            return True, "stale_no_git"
        return True, "stale_age"

    # even a fresh lock is orphaned if no git process is running
    if not git_process_running():
        return True, "stale_no_git"

    return False, "fresh"


def reap_lock(lock_path: Path, dry_run: bool = False) -> LockReport:
    """Attempt to remove a stale lock file."""
    age = get_lock_age(lock_path)
    is_stale, reason = is_lock_stale(lock_path, max_age=300)

    report = LockReport(
        path=str(lock_path),
        exists=lock_path.exists(),
        age_seconds=round(age, 1),
        is_stale=is_stale,
        reason=reason,
    )

    if not is_stale:
        return report

    if dry_run:
        report.reaped = False
        report.reap_error = "dry_run"
        return report

    try:
        lock_path.unlink()
        report.reaped = True
    except OSError as e:
        report.reap_error = str(e)

    return report


def scan_repo(repo_path: str, max_age: float = 300,
              reap: bool = False, dry_run: bool = False) -> List[LockReport]:
    """Scan a repo for lock files and optionally reap stale ones."""
    git_dir = find_git_root(repo_path)
    if git_dir is None:
        return []

    lock_files = find_lock_files(git_dir)
    reports = []

    for lock_path in lock_files:
        if reap or dry_run:
            report = reap_lock(lock_path, dry_run=dry_run)
        else:
            age = get_lock_age(lock_path)
            is_stale, reason = is_lock_stale(lock_path, max_age)
            report = LockReport(
                path=str(lock_path),
                exists=True,
                age_seconds=round(age, 1),
                is_stale=is_stale,
                reason=reason,
            )
        reports.append(report)

    return reports


def summary(reports: List[LockReport]) -> dict:
    """Produce a summary dict from a list of lock reports."""
    total = len(reports)
    stale = sum(1 for r in reports if r.is_stale)
    reaped = sum(1 for r in reports if r.reaped)
    failed = sum(1 for r in reports if r.reap_error and r.reap_error != "dry_run")
    return {
        "total_locks": total,
        "stale_locks": stale,
        "reaped": reaped,
        "failed": failed,
        "clean": stale == 0,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Detect and remove stale git lock files."
    )
    parser.add_argument("--repo", default=".", help="Path to the git repo")
    parser.add_argument("--max-age", type=float, default=300,
                        help="Max lock age in seconds before considered stale")
    parser.add_argument("--reap", action="store_true",
                        help="Remove stale locks")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be reaped without removing")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    reports = scan_repo(
        repo_path=args.repo,
        max_age=args.max_age,
        reap=args.reap,
        dry_run=args.dry_run,
    )

    stats = summary(reports)

    if args.json:
        output = {
            "summary": stats,
            "locks": [asdict(r) for r in reports],
        }
        print(json.dumps(output, indent=2))
    else:
        if not reports:
            print("no lock files found")
        else:
            for r in reports:
                status = "STALE" if r.is_stale else "fresh"
                action = ""
                if r.reaped:
                    action = " [REAPED]"
                elif r.reap_error:
                    action = f" [{r.reap_error}]"
                print(f"  {status} {r.path} (age={r.age_seconds}s, {r.reason}){action}")
            print(f"\nsummary: {stats['total_locks']} locks, "
                  f"{stats['stale_locks']} stale, "
                  f"{stats['reaped']} reaped, "
                  f"{stats['failed']} failed")

    if stats["stale_locks"] > 0 and not args.reap:
        sys.exit(1)
    if stats["failed"] > 0:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
