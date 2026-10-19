#!/usr/bin/env python3
"""red_gate_auto_clear.py — detect and clear stale RED GATE pause files.

The RED GATE is a safety mechanism: when the batch committer detects a
problem (stale lock, git index corruption, push race), it touches the
pause file to stop the writer from producing content on a broken tree.

Problem: the gate has no automatic release. If the underlying issue is
transient, the writer stays idle until the next caretaker visit — which
may be hours away. This tool checks whether the git state is healthy
and clears the gate if it is safe to do so.

Exit codes:
  0 — gate was present and has been cleared (git state is healthy)
  1 — gate is present but still needed (underlying issue persists)
  2 — no gate present (nothing to do)
  3 — git state check failed unexpectedly

Usage:
    python3 tools/red_gate_auto_clear.py [--writer qwen] [--stale-lock-age 120]
    python3 tools/red_gate_auto_clear.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def pause_file(writer_id: str | None = None) -> Path:
    """Return the pause gate path for the given writer."""
    wid = writer_id or os.environ.get("IAMAII_WRITER", "qwen")
    return Path(f"/tmp/iamai-writer-pause-{wid}")


def check_stale_lock(repo: Path, threshold_seconds: int = 120) -> tuple[bool, str]:
    """Check if .git/index.lock exists and is older than threshold.

    Returns (is_stale, message).
    If lock doesn't exist, returns (False, "no lock").
    If lock exists but is fresh, returns (False, "lock is fresh (<age>s)").
    If lock exists and is stale, returns (True, "lock is stale (<age>s)").
    """
    lock_path = repo / ".git" / "index.lock"
    if not lock_path.exists():
        return False, "no lock"

    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return False, "lock exists but cannot stat"

    if age > threshold_seconds:
        return True, f"lock is stale ({age:.0f}s > {threshold_seconds}s threshold)"
    return False, f"lock is fresh ({age:.0f}s < {threshold_seconds}s threshold)"


def check_git_status(repo: Path) -> tuple[bool, str]:
    """Check if git status runs cleanly.

    Returns (is_healthy, message).
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(repo),
        )
        if result.returncode == 0:
            return True, "git status OK"
        return False, f"git status failed (exit {result.returncode}): {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, "git status timed out (10s)"
    except OSError as e:
        return False, f"git status error: {e}"


def check_merge_conflict(repo: Path) -> tuple[bool, str]:
    """Check if there's an active merge conflict.

    Returns (has_conflict, message).
    """
    merge_head = repo / ".git" / "MERGE_HEAD"
    merge_msg = repo / ".git" / "MERGE_MSG"

    if merge_head.exists():
        return True, f"MERGE_HEAD exists (merge in progress)"
    if merge_msg.exists() and not merge_head.exists():
        return False, "MERGE_MSG exists without MERGE_HEAD (merge completed)"
    return False, "no merge in progress"


def gate_health_report(
    repo: Path,
    stale_lock_threshold: int = 120,
) -> tuple[bool, list[str]]:
    """Run all health checks and report.

    Returns (is_healthy, list_of_findings).
    A gate is safe to clear only when all checks pass.
    """
    findings = []

    # Check 1: stale lock
    lock_stale, lock_msg = check_stale_lock(repo, stale_lock_threshold)
    findings.append(f"lock: {lock_msg}")
    if lock_stale:
        return False, findings

    # Check 2: git status
    git_ok, git_msg = check_git_status(repo)
    findings.append(f"git: {git_msg}")
    if not git_ok:
        return False, findings

    # Check 3: merge conflict
    conflict, merge_msg = check_merge_conflict(repo)
    findings.append(f"merge: {merge_msg}")
    if conflict:
        return False, findings

    return True, findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default=None, help="writer id (or env IAMAII_WRITER)")
    ap.add_argument(
        "--stale-lock-age",
        type=int,
        default=120,
        help="seconds before a lock file is considered stale (default: 120)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would happen without clearing the gate",
    )
    args = ap.parse_args()

    pf = pause_file(args.writer)

    # Step 1: is there a gate?
    if not pf.exists():
        print("no RED GATE present — nothing to do")
        return 2

    # Step 2: check git health
    healthy, findings = gate_health_report(REPO, args.stale_lock_age)

    print(f"RED GATE present at {pf}")
    for f in findings:
        print(f"  {f}")

    if healthy:
        if args.dry_run:
            print("WOULD clear gate (dry-run)")
        else:
            pf.unlink(missing_ok=True)
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
            print(f"gate cleared at {timestamp}Z — all health checks passed")
        return 0
    else:
        print("gate still needed — underlying issue persists")
        return 1


if __name__ == "__main__":
    sys.exit(main())
