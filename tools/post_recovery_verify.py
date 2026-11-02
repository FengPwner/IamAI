#!/usr/bin/env python3
"""post_recovery_verify.py — did the recovery actually work?

After a caretaker visit restarts processes and pushes, run this to
confirm the system is genuinely healthy, not just superficially alive.

Checks (in order):
  1. writer process is running
  2. batch committer process is running
  3. no uncommitted files (or only expected live-writer drift)
  4. no unpushed commits
  5. SSH key is present and has correct permissions
  6. writer has produced at least one stroke since restart
  7. remote is reachable (git ls-remote)

Usage:
    python3 tools/post_recovery_verify.py
    python3 tools/post_recovery_verify.py --json
    python3 tools/post_recovery_verify.py --quiet    # exit code only

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
    2 — environment error (not a git repo, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional


REPO = Path(__file__).resolve().parent.parent


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    latency_ms: int = 0


@dataclass
class VerifyReport:
    checks: List[CheckResult] = field(default_factory=list)
    timestamp: str = ""
    all_passed: bool = False

    def add(self, check: CheckResult) -> None:
        self.checks.append(check)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    def finalize(self) -> None:
        self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.all_passed = self.failed_count == 0


def _run(cmd: List[str], timeout: int = 10, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    merged_env = os.environ.copy()
    ssh_key = Path("/tmp/ssh_deploy_key")
    if ssh_key.exists():
        merged_env["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key} -o StrictHostKeyChecking=no"
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          cwd=cwd or str(REPO), env=merged_env)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _find_pid(pattern: str) -> Optional[int]:
    """Find a running process PID by matching against its command line."""
    try:
        result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            return int(pids[0])
    except (subprocess.TimeoutExpired, ValueError):
        pass
    return None


def check_writer_running() -> CheckResult:
    """Is the writer process alive?"""
    t0 = time.monotonic()
    pid = _find_pid("writer_loop.py")
    alive = pid is not None and _pid_alive(pid)
    ms = int((time.monotonic() - t0) * 1000)
    return CheckResult(
        name="writer_running",
        passed=alive,
        detail=f"pid {pid}" if alive else "no writer_loop.py process found",
        latency_ms=ms,
    )


def check_batch_running() -> CheckResult:
    """Is the batch committer process alive?"""
    t0 = time.monotonic()
    pid = _find_pid("commit_batch.py")
    alive = pid is not None and _pid_alive(pid)
    ms = int((time.monotonic() - t0) * 1000)
    return CheckResult(
        name="batch_running",
        passed=alive,
        detail=f"pid {pid}" if alive else "no commit_batch.py process found",
        latency_ms=ms,
    )


def check_uncommitted(repo: Path = REPO) -> CheckResult:
    """Are there uncommitted changes? (writer drift is expected)"""
    t0 = time.monotonic()
    result = _run(["git", "status", "--porcelain"], cwd=str(repo))
    ms = int((time.monotonic() - t0) * 1000)
    lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
    # writer_state and DEVLOG drift is expected between writer ticks
    unexpected = [l for l in lines
                  if "writer_state" not in l and "DEVLOG" not in l]
    passed = len(unexpected) == 0
    detail = f"{len(lines)} dirty file(s)" if lines else "clean"
    if unexpected:
        detail += f" ({len(unexpected)} unexpected)"
    return CheckResult(name="uncommitted", passed=passed, detail=detail, latency_ms=ms)


def check_unpushed(repo: Path = REPO) -> CheckResult:
    """Are there unpushed commits?"""
    t0 = time.monotonic()
    result = _run(["git", "log", "--oneline", "origin/main..HEAD"], cwd=str(repo))
    ms = int((time.monotonic() - t0) * 1000)
    lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
    count = len(lines)
    passed = count == 0
    detail = f"{count} unpushed commit(s)" if count else "all pushed"
    return CheckResult(name="unpushed", passed=passed, detail=detail, latency_ms=ms)


def check_ssh_key() -> CheckResult:
    """Is the deploy key present with correct permissions?"""
    t0 = time.monotonic()
    key = Path("/tmp/ssh_deploy_key")
    if not key.exists():
        ms = int((time.monotonic() - t0) * 1000)
        return CheckResult(name="ssh_key", passed=False, detail="key not found at /tmp/ssh_deploy_key", latency_ms=ms)
    stat = key.stat()
    mode = oct(stat.st_mode & 0o777)
    passed = mode == "0o600" or mode == "0o400"
    ms = int((time.monotonic() - t0) * 1000)
    detail = f"mode {mode}" + ("" if passed else " (expected 0600 or 0400)")
    return CheckResult(name="ssh_key", passed=passed, detail=detail, latency_ms=ms)


def check_remote_reachable(repo: Path = REPO) -> CheckResult:
    """Can we reach the remote?"""
    t0 = time.monotonic()
    try:
        result = _run(["git", "ls-remote", "--exit-code", "origin", "HEAD"], timeout=15, cwd=str(repo))
        ms = int((time.monotonic() - t0) * 1000)
        passed = result.returncode == 0
        detail = "reachable" if passed else f"unreachable: {result.stderr.strip()[:120]}"
    except subprocess.TimeoutExpired:
        ms = int((time.monotonic() - t0) * 1000)
        passed = False
        detail = "timeout after 15s"
    return CheckResult(name="remote_reachable", passed=passed, detail=detail, latency_ms=ms)


def check_writer_producing(repo: Path = REPO) -> CheckResult:
    """Has the writer produced at least one stroke recently?

    Checks if data/strokes.jsonl was modified within the last 120 seconds.
    This is generous — the writer ticks every 15s, so 120s allows for
    brief pauses during restart.
    """
    t0 = time.monotonic()
    strokes_file = repo / "data" / "strokes.jsonl"
    if not strokes_file.exists():
        ms = int((time.monotonic() - t0) * 1000)
        return CheckResult(name="writer_producing", passed=False,
                           detail="data/strokes.jsonl not found", latency_ms=ms)
    mtime = strokes_file.stat().st_mtime
    age = time.time() - mtime
    ms = int((time.monotonic() - t0) * 1000)
    passed = age < 120
    detail = f"last stroke {age:.0f}s ago" + ("" if passed else " (stale: >120s)")
    return CheckResult(name="writer_producing", passed=passed, detail=detail, latency_ms=ms)


def verify_all(repo: Path = REPO) -> VerifyReport:
    """Run all recovery verification checks."""
    report = VerifyReport()
    report.add(check_writer_running())
    report.add(check_batch_running())
    report.add(check_uncommitted(repo))
    report.add(check_unpushed(repo))
    report.add(check_ssh_key())
    report.add(check_remote_reachable(repo))
    report.add(check_writer_producing(repo))
    report.finalize()
    return report


def format_report(report: VerifyReport) -> str:
    """Format a VerifyReport as human-readable text."""
    lines = ["=== POST-RECOVERY VERIFICATION ==="]
    for c in report.checks:
        icon = "PASS" if c.passed else "FAIL"
        lines.append(f"  [{icon}] {c.name}: {c.detail} ({c.latency_ms}ms)")
    lines.append(f"\n  {report.passed_count}/{len(report.checks)} passed"
                 f"  |  {report.timestamp}")
    if not report.all_passed:
        lines.append(f"  WARNING: {report.failed_count} check(s) failed")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify post-recovery health")
    parser.add_argument("--json", action="store_true", help="output as JSON")
    parser.add_argument("--quiet", action="store_true", help="exit code only")
    args = parser.parse_args()

    try:
        report = verify_all()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    elif not args.quiet:
        print(format_report(report))

    return 0 if report.all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
