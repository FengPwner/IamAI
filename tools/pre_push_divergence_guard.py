#!/usr/bin/env python3
"""pre_push_divergence_guard.py — will `git push` succeed right now?

A lightweight pre-push gate that checks three conditions:
  1. Network path to the remote exists (git ls-remote)
  2. Local branch is ahead of or equal to origin (merge-base comparison)
  3. No uncommitted changes that would block a rebase

Verdicts:
  safe      — push should succeed
  diverged  — local and remote have diverged; pull/rebase first
  behind    — local is behind remote; pull first
  offline   — cannot reach the remote
  dirty     — uncommitted changes present

Usage:
    python3 tools/pre_push_divergence_guard.py
    python3 tools/pre_push_divergence_guard.py --remote origin --branch main
    python3 tools/pre_push_divergence_guard.py --json
    python3 tools/pre_push_divergence_guard.py --quiet   # exit code only

Exit codes:
    0  verdict = safe
    1  verdict = diverged | behind | dirty
    2  verdict = offline
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class GuardReport:
    """Result of a pre-push divergence guard check."""

    verdict: str = "unknown"
    remote: str = "origin"
    branch: str = "main"
    local_sha: str = ""
    remote_sha: str = ""
    merge_base: str = ""
    ahead_count: int = 0
    behind_count: int = 0
    dirty_files: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def _run(cmd: list[str], cwd: Optional[Path] = None, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def check_remote_reachable(remote: str, cwd: Optional[Path] = None) -> tuple[bool, str]:
    """Check if the remote is reachable via git ls-remote."""
    try:
        result = _run(["git", "ls-remote", "--exit-code", remote, "HEAD"], cwd=cwd, timeout=10)
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "ls-remote timed out"
    except Exception as e:
        return False, str(e)


def get_local_sha(branch: str, cwd: Optional[Path] = None) -> str:
    """Get the SHA of the local branch HEAD."""
    result = _run(["git", "rev-parse", branch], cwd=cwd)
    return result.stdout.strip() if result.returncode == 0 else ""


def get_remote_sha(remote: str, branch: str, cwd: Optional[Path] = None) -> str:
    """Get the SHA of the remote tracking branch."""
    result = _run(["git", "rev-parse", f"{remote}/{branch}"], cwd=cwd)
    return result.stdout.strip() if result.returncode == 0 else ""


def get_merge_base(local_sha: str, remote_sha: str, cwd: Optional[Path] = None) -> str:
    """Get the merge base between two commits."""
    result = _run(["git", "merge-base", local_sha, remote_sha], cwd=cwd)
    return result.stdout.strip() if result.returncode == 0 else ""


def count_ahead_behind(local_sha: str, remote_sha: str, cwd: Optional[Path] = None) -> tuple[int, int]:
    """Count commits ahead and behind."""
    result = _run(
        ["git", "rev-list", "--left-right", "--count", f"{local_sha}...{remote_sha}"],
        cwd=cwd,
    )
    if result.returncode == 0:
        parts = result.stdout.strip().split()
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    return 0, 0


def count_dirty_files(cwd: Optional[Path] = None) -> int:
    """Count uncommitted (staged + unstaged) files."""
    result = _run(["git", "status", "--porcelain"], cwd=cwd)
    if result.returncode == 0 and result.stdout.strip():
        return len(result.stdout.strip().splitlines())
    return 0


def run_guard(
    remote: str = "origin",
    branch: str = "main",
    cwd: Optional[Path] = None,
) -> GuardReport:
    """Run the pre-push divergence guard and return a report."""
    report = GuardReport(remote=remote, branch=branch)

    # Step 1: check remote reachability
    reachable, err = check_remote_reachable(remote, cwd)
    if not reachable:
        report.verdict = "offline"
        report.error = err
        return report

    # Step 2: get SHAs
    local_sha = get_local_sha(branch, cwd)
    if not local_sha:
        report.verdict = "offline"
        report.error = f"cannot resolve local branch '{branch}'"
        return report

    remote_sha = get_remote_sha(remote, branch, cwd)
    if not remote_sha:
        report.verdict = "offline"
        report.error = f"cannot resolve {remote}/{branch}"
        return report

    report.local_sha = local_sha
    report.remote_sha = remote_sha

    # Step 3: compare
    if local_sha == remote_sha:
        report.merge_base = local_sha
        report.ahead_count = 0
        report.behind_count = 0
    else:
        merge_base = get_merge_base(local_sha, remote_sha, cwd)
        report.merge_base = merge_base
        ahead, behind = count_ahead_behind(local_sha, remote_sha, cwd)
        report.ahead_count = ahead
        report.behind_count = behind

    # Step 4: check dirty files
    report.dirty_files = count_dirty_files(cwd)

    # Step 5: determine verdict
    if report.dirty_files > 0:
        report.verdict = "dirty"
    elif report.ahead_count > 0 and report.behind_count > 0:
        report.verdict = "diverged"
    elif report.behind_count > 0:
        report.verdict = "behind"
    else:
        report.verdict = "safe"

    return report


def format_report(report: GuardReport) -> str:
    """Format a guard report for human-readable output."""
    lines = [
        f"verdict:   {report.verdict}",
        f"remote:    {report.remote}",
        f"branch:    {report.branch}",
        f"local:     {report.local_sha[:10] if report.local_sha else '—'}",
        f"remote:    {report.remote_sha[:10] if report.remote_sha else '—'}",
        f"ahead:     {report.ahead_count}",
        f"behind:    {report.behind_count}",
        f"dirty:     {report.dirty_files}",
    ]
    if report.error:
        lines.append(f"error:     {report.error}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Pre-push divergence guard")
    parser.add_argument("--remote", default="origin", help="remote name")
    parser.add_argument("--branch", default="main", help="branch name")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--quiet", action="store_true", help="exit code only")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    report = run_guard(remote=args.remote, branch=args.branch, cwd=repo)

    if args.json:
        print(report.to_json())
    elif not args.quiet:
        print(format_report(report))

    # Exit codes
    if report.verdict == "safe":
        sys.exit(0)
    elif report.verdict == "offline":
        sys.exit(2)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
