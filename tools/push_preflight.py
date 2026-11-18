#!/usr/bin/env python3
"""push_preflight.py — pre-push pipeline health check.

Runs a sequence of non-destructive checks before attempting git push,
surfacing the exact reason a push would fail instead of discovering it
mid-push.  Each check is independent; all run even if one fails.

Usage:
    python3 tools/push_preflight.py                # human-readable report
    python3 tools/push_preflight.py --json         # machine-readable output
    python3 tools/push_preflight.py --strict        # exit 1 on any warning

Exit codes:
    0 — all checks passed (or only info-level notes)
    1 — at least one blocking issue found
    2 — usage / internal error

Checks performed (in order):
    1. lock_file      — no .git/index.lock present
    2. working_tree   — no uncommitted changes to tracked files
    3. rebase_state   — no rebase-merge or rebase-apply in progress
    4. ssh_key        — deploy key file exists and is readable
    5. remote_sync    — local is at or ahead of origin/main (fetch first not needed)
    6. writer_pause   — writer pause sentinel exists (writer is paused)

Written during caretaker visit 697, 2026-11-18.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent
GIT_DIR = REPO / ".git"
DEFAULT_SSH_KEY = Path("/tmp/ssh_deploy_key")
WRITER_ID = os.environ.get("IAMAII_WRITER", "qwen")
PAUSE_PATH = Path(f"/tmp/iamai-writer-pause-{WRITER_ID}")


@dataclass
class CheckResult:
    """Outcome of a single preflight check."""

    name: str
    status: str  # "pass", "fail", "warn", "skip"
    message: str
    detail: str = ""

    def blocking(self) -> bool:
        return self.status == "fail"


@dataclass
class PreflightReport:
    """Aggregated results from all preflight checks."""

    checks: List[CheckResult] = field(default_factory=list)
    verdict: str = "pass"  # "pass" or "fail"
    remediation: List[str] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)
        if result.blocking():
            self.verdict = "fail"
            self.remediation.append(f"[{result.name}] {result.message}")

    def summary(self) -> str:
        passed = sum(1 for c in self.checks if c.status == "pass")
        failed = sum(1 for c in self.checks if c.status == "fail")
        warned = sum(1 for c in self.checks if c.status == "warn")
        skipped = sum(1 for c in self.checks if c.status == "skip")
        parts = [f"{passed} pass"]
        if failed:
            parts.append(f"{failed} fail")
        if warned:
            parts.append(f"{warned} warn")
        if skipped:
            parts.append(f"{skipped} skip")
        return f"preflight: {self.verdict} ({', '.join(parts)})"


def _run_git(args: List[str], cwd: Path = REPO) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=30,
    )


def check_lock_file() -> CheckResult:
    """Check that no .git/index.lock exists."""
    lock = GIT_DIR / "index.lock"
    if lock.exists():
        return CheckResult(
            name="lock_file",
            status="fail",
            message="index.lock exists — another git operation may be in progress",
            detail=str(lock),
        )
    return CheckResult(
        name="lock_file",
        status="pass",
        message="no lock file",
    )


def check_working_tree() -> CheckResult:
    """Check that the working tree has no uncommitted tracked changes."""
    result = _run_git(["status", "--porcelain", "--untracked-files=no"])
    if result.returncode != 0:
        return CheckResult(
            name="working_tree",
            status="fail",
            message=f"git status failed: {result.stderr.strip()}",
        )
    lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
    if lines:
        return CheckResult(
            name="working_tree",
            status="fail",
            message=f"{len(lines)} uncommitted change(s)",
            detail="\n".join(lines[:10]),
        )
    return CheckResult(
        name="working_tree",
        status="pass",
        message="working tree clean",
    )


def check_rebase_state() -> CheckResult:
    """Check that no rebase is in progress."""
    rebase_merge = GIT_DIR / "rebase-merge"
    rebase_apply = GIT_DIR / "rebase-apply"
    if rebase_merge.exists():
        return CheckResult(
            name="rebase_state",
            status="fail",
            message="rebase-merge in progress — complete or abort before pushing",
            detail=str(rebase_merge),
        )
    if rebase_apply.exists():
        return CheckResult(
            name="rebase_state",
            status="fail",
            message="rebase-apply in progress — complete or abort before pushing",
            detail=str(rebase_apply),
        )
    return CheckResult(
        name="rebase_state",
        status="pass",
        message="no rebase in progress",
    )


def check_ssh_key(key_path: Path = DEFAULT_SSH_KEY) -> CheckResult:
    """Check that the SSH deploy key exists and is readable."""
    if not key_path.exists():
        return CheckResult(
            name="ssh_key",
            status="fail",
            message=f"deploy key not found: {key_path}",
        )
    if not os.access(str(key_path), os.R_OK):
        return CheckResult(
            name="ssh_key",
            status="fail",
            message=f"deploy key not readable: {key_path}",
        )
    size = key_path.stat().st_size
    if size == 0:
        return CheckResult(
            name="ssh_key",
            status="fail",
            message=f"deploy key is empty: {key_path}",
        )
    return CheckResult(
        name="ssh_key",
        status="pass",
        message=f"deploy key OK ({size} bytes)",
    )


def check_remote_sync(branch: str = "main") -> CheckResult:
    """Check that local branch is at or ahead of origin (no fetch-first needed).

    Compares local HEAD against origin/<branch>.  If origin is ahead,
    the push will be rejected with 'fetch first'.
    """
    # Get local HEAD sha
    local = _run_git(["rev-parse", "HEAD"])
    if local.returncode != 0:
        return CheckResult(
            name="remote_sync",
            status="fail",
            message="cannot resolve local HEAD",
            detail=local.stderr.strip(),
        )
    local_sha = local.stdout.strip()

    # Get remote branch sha
    remote = _run_git(["rev-parse", f"origin/{branch}"])
    if remote.returncode != 0:
        return CheckResult(
            name="remote_sync",
            status="warn",
            message=f"origin/{branch} not found — first push or no fetch yet",
        )
    remote_sha = remote.stdout.strip()

    if local_sha == remote_sha:
        return CheckResult(
            name="remote_sync",
            status="pass",
            message="local is at origin — nothing to push",
        )

    # Check merge-base: is local a descendant of remote?
    base = _run_git(["merge-base", local_sha, remote_sha])
    if base.returncode != 0:
        return CheckResult(
            name="remote_sync",
            status="warn",
            message="cannot determine ancestry — push may or may not succeed",
        )
    base_sha = base.stdout.strip()

    if base_sha == remote_sha:
        # local is ahead of remote — safe to push
        ahead = _run_git(["rev-list", "--count", f"{remote_sha}..{local_sha}"])
        count = ahead.stdout.strip() if ahead.returncode == 0 else "?"
        return CheckResult(
            name="remote_sync",
            status="pass",
            message=f"local is {count} commit(s) ahead of origin/{branch} — safe to push",
        )
    else:
        return CheckResult(
            name="remote_sync",
            status="fail",
            message=f"origin/{branch} has diverged — pull --rebase needed before push",
            detail=f"local={local_sha[:8]} remote={remote_sha[:8]} base={base_sha[:8]}",
        )


def check_writer_pause(pause_path: Path = PAUSE_PATH) -> CheckResult:
    """Check that the writer pause sentinel exists.

    Pushing while the writer is active risks dirty-tree conflicts during
    any subsequent rebase.  The writer should be paused before push.
    """
    if pause_path.exists():
        return CheckResult(
            name="writer_pause",
            status="pass",
            message=f"writer paused (sentinel: {pause_path.name})",
        )
    return CheckResult(
        name="writer_pause",
        status="warn",
        message="writer not paused — active writer may conflict during post-push rebase",
        detail=f"expected: {pause_path}",
    )


def run_preflight(
    ssh_key: Path = DEFAULT_SSH_KEY,
    branch: str = "main",
    pause_path: Path = PAUSE_PATH,
) -> PreflightReport:
    """Run all preflight checks and return the aggregated report."""
    report = PreflightReport()
    report.add(check_lock_file())
    report.add(check_working_tree())
    report.add(check_rebase_state())
    report.add(check_ssh_key(ssh_key))
    report.add(check_remote_sync(branch))
    report.add(check_writer_pause(pause_path))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-push pipeline health check."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on warnings too",
    )
    parser.add_argument(
        "--ssh-key",
        type=str,
        default=str(DEFAULT_SSH_KEY),
        help=f"Path to deploy key (default: {DEFAULT_SSH_KEY})",
    )
    parser.add_argument(
        "--branch",
        type=str,
        default="main",
        help="Remote branch to check against (default: main)",
    )
    args = parser.parse_args()

    report = run_preflight(
        ssh_key=Path(args.ssh_key),
        branch=args.branch,
    )

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(report.summary())
        for check in report.checks:
            icon = {"pass": "✓", "fail": "✗", "warn": "⚠", "skip": "·"}
            print(f"  {icon.get(check.status, '?')} {check.name}: {check.message}")
            if check.detail and check.status != "pass":
                for line in check.detail.split("\n")[:5]:
                    print(f"      {line}")
        if report.remediation:
            print(f"\nremediation:")
            for step in report.remediation:
                print(f"  → {step}")

    if report.verdict == "fail":
        return 1
    if args.strict and any(c.status == "warn" for c in report.checks):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
