#!/usr/bin/env python3
"""push_auto_rebase.py — lightweight push wrapper with automatic rebase on divergence.

When `git push` is rejected because the remote has diverged, this tool
automatically performs the stash-pull_rebase-pop-push sequence without
manual intervention. Designed to be called by the batch committer instead
of bare `git push`, so divergence never blocks the ten-minute cadence.

Exit codes:
    0 — push succeeded (either first attempt or after rebase)
    1 — push still rejected after auto-rebase (conflict or unexpected error)
    2 — git error, missing repo, or unrecoverable state

Usage:
    python3 tools/push_auto_rebase.py
    python3 tools/push_auto_rebase.py --repo /path/to/IamAI
    python3 tools/push_auto_rebase.py --remote origin --branch main
    python3 tools/push_auto_rebase.py --json
"""

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PushReport:
    first_attempt: str = "unknown"   # "ok" | "rejected" | "error"
    rebase_needed: bool = False
    stash_used: bool = False
    second_attempt: str = "skipped"  # "ok" | "rejected" | "error" | "skipped"
    remote_ahead: int = 0
    local_ahead: int = 0
    duration_ms: int = 0
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "first_attempt": self.first_attempt,
            "rebase_needed": self.rebase_needed,
            "stash_used": self.stash_used,
            "second_attempt": self.second_attempt,
            "remote_ahead": self.remote_ahead,
            "local_ahead": self.local_ahead,
            "duration_ms": self.duration_ms,
            "message": self.message,
        }


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) to find the repo root."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return p


def run_git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run a git command in the repo directory."""
    env = os.environ.copy()
    ssh_cmd = env.get("GIT_SSH_COMMAND", "")
    if ssh_cmd:
        env["GIT_SSH_COMMAND"] = ssh_cmd
    return subprocess.run(
        ["git"] + list(args),
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
        check=check,
    )


def has_unstaged_changes(repo: Path) -> bool:
    """Check if there are unstaged changes in the working tree."""
    result = run_git(repo, "status", "--porcelain")
    if result.returncode != 0:
        return False
    return any(
        line.strip() and not line.startswith("??")
        for line in result.stdout.splitlines()
    )


def count_divergence(repo: Path, remote: str, branch: str) -> tuple[int, int]:
    """Return (local_ahead, remote_ahead) counts."""
    result = run_git(
        repo, "rev-list", "--left-right", "--count",
        f"{remote}/{branch}...HEAD"
    )
    if result.returncode != 0:
        return (0, 0)
    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return (0, 0)
    # left = remote_ahead, right = local_ahead
    return (int(parts[1]), int(parts[0]))


def push_auto_rebase(
    repo: Path,
    remote: str = "origin",
    branch: str = "main",
) -> PushReport:
    """Attempt push; if rejected due to divergence, auto-rebase and retry."""
    t0 = time.monotonic()
    report = PushReport()

    # --- first push attempt ---
    push_result = run_git(repo, "push", remote, branch)
    if push_result.returncode == 0:
        report.first_attempt = "ok"
        report.message = "push succeeded on first attempt"
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    # check if it's a divergence rejection
    stderr = push_result.stderr.lower()
    if "rejected" not in stderr and "fetch first" not in stderr:
        report.first_attempt = "error"
        report.message = f"push failed with unexpected error: {push_result.stderr.strip()}"
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    report.first_attempt = "rejected"

    # --- fetch to update remote tracking ---
    fetch_result = run_git(repo, "fetch", remote, branch)
    if fetch_result.returncode != 0:
        report.message = f"fetch failed: {fetch_result.stderr.strip()}"
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    # count divergence
    local_ahead, remote_ahead = count_divergence(repo, remote, branch)
    report.local_ahead = local_ahead
    report.remote_ahead = remote_ahead
    report.rebase_needed = True

    # --- stash if needed ---
    dirty = has_unstaged_changes(repo)
    if dirty:
        stash_result = run_git(repo, "stash", "push", "-m", "auto-rebase-stash")
        if stash_result.returncode != 0:
            report.message = f"stash failed: {stash_result.stderr.strip()}"
            report.duration_ms = int((time.monotonic() - t0) * 1000)
            return report
        report.stash_used = True

    # --- pull --rebase ---
    rebase_result = run_git(repo, "pull", "--rebase", remote, branch)
    if rebase_result.returncode != 0:
        # try to abort the rebase
        run_git(repo, "rebase", "--abort")
        if report.stash_used:
            run_git(repo, "stash", "pop")
        report.second_attempt = "error"
        report.message = f"rebase failed: {rebase_result.stderr.strip()}"
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    # --- pop stash if we stashed ---
    if report.stash_used:
        pop_result = run_git(repo, "stash", "pop")
        if pop_result.returncode != 0:
            report.message = f"stash pop failed (rebase succeeded): {pop_result.stderr.strip()}"
            report.duration_ms = int((time.monotonic() - t0) * 1000)
            return report

    # --- second push attempt ---
    push2_result = run_git(repo, "push", remote, branch)
    if push2_result.returncode == 0:
        report.second_attempt = "ok"
        report.message = "push succeeded after auto-rebase"
    else:
        report.second_attempt = "rejected"
        report.message = f"push still rejected after rebase: {push2_result.stderr.strip()}"

    report.duration_ms = int((time.monotonic() - t0) * 1000)
    return report


def main():
    parser = argparse.ArgumentParser(description="Push with automatic rebase on divergence.")
    parser.add_argument("--repo", type=str, default=None, help="Path to git repo")
    parser.add_argument("--remote", type=str, default="origin", help="Remote name")
    parser.add_argument("--branch", type=str, default="main", help="Branch name")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args()

    repo = find_repo_root(Path(args.repo) if args.repo else None)
    report = push_auto_rebase(repo, args.remote, args.branch)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        status = "OK" if report.second_attempt == "ok" or report.first_attempt == "ok" else "FAIL"
        print(f"[{status}] {report.message}")
        if report.rebase_needed:
            print(f"  divergence: local={report.local_ahead} remote={report.remote_ahead}")
            print(f"  rebase: yes | stash: {'yes' if report.stash_used else 'no'}")
        print(f"  duration: {report.duration_ms}ms")

    # exit code
    if report.first_attempt == "ok" or report.second_attempt == "ok":
        sys.exit(0)
    elif report.second_attempt in ("rejected", "error"):
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
