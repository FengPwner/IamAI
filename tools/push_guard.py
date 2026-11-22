#!/usr/bin/env python3
"""push_guard.py — atomic push-recovery sequence.

Encodes the caretaker's push-recovery dance into a single function:
  1. stash dirty working tree if needed
  2. pull --rebase origin main
  3. pop stash if created
  4. push origin main (retry once on rejection)

Design: no force-push, no porcelain parsing, subprocess throughout.
Callers: commit_batch.py, caretaker scripts, or manual CLI.

Usage:
    python3 tools/push_guard.py                  # guarded push
    python3 tools/push_guard.py --dry-run        # show what would happen
"""

import json
import subprocess
import sys
import time
from typing import Optional

DEFAULT_REMOTE = "origin"
DEFAULT_BRANCH = "main"
DEFAULT_TIMEOUT = 60  # seconds per git command
MAX_PUSH_ATTEMPTS = 2


class PushGuardError(Exception):
    """Raised when push recovery fails and needs human intervention."""


def _run_git(
    args: list[str],
    cwd: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd = ["git"] + args
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _is_dirty(cwd: str) -> bool:
    """Check if the working tree has uncommitted changes."""
    result = _run_git(["status", "--porcelain"], cwd)
    return bool(result.stdout.strip())


def _stash_push(cwd: str) -> bool:
    """Stash changes. Returns True if a stash was created."""
    if not _is_dirty(cwd):
        return False
    result = _run_git(["stash", "push", "-m", "push_guard: auto-stash"], cwd)
    return result.returncode == 0 and "No local changes" not in result.stdout


def _stash_pop(cwd: str) -> bool:
    """Pop the most recent stash. Returns True on success."""
    result = _run_git(["stash", "pop"], cwd)
    return result.returncode == 0


def _pull_rebase(
    cwd: str,
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
) -> tuple[bool, int]:
    """Pull with rebase. Returns (success, rebase_count)."""
    result = _run_git(["pull", "--rebase", remote, branch], cwd)
    # parse rebase count from output like "Rebasing (1/1)"
    count = 0
    for line in result.stdout.splitlines() + result.stderr.splitlines():
        if "Rebasing" in line:
            count += 1
    return result.returncode == 0, count


def _push(
    cwd: str,
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
) -> tuple[bool, str]:
    """Push to remote. Returns (success, error_message)."""
    result = _run_git(["push", remote, branch], cwd)
    if result.returncode == 0:
        return True, ""
    stderr = result.stderr.strip()
    # detect specific failure modes
    if "rejected" in stderr.lower():
        return False, f"push rejected (non-fast-forward): {stderr[:200]}"
    if "fatal" in stderr.lower():
        return False, f"push fatal error: {stderr[:200]}"
    return False, stderr[:200]


def guarded_push(
    cwd: str = ".",
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
    dry_run: bool = False,
) -> dict:
    """Execute the full push-recovery sequence.

    Returns a dict with:
        ok: bool — whether push ultimately succeeded
        stash_used: bool — whether a stash was created and popped
        rebase_count: int — number of rebase steps performed
        push_attempts: int — number of push attempts made
        error: Optional[str] — error message if push failed
        steps: list[str] — human-readable log of each step taken
    """
    steps: list[str] = []
    result = {
        "ok": False,
        "stash_used": False,
        "rebase_count": 0,
        "push_attempts": 0,
        "error": None,
        "steps": steps,
    }

    if dry_run:
        steps.append(f"[dry-run] would check dirtiness of {cwd}")
        steps.append(f"[dry-run] would stash if dirty")
        steps.append(f"[dry-run] would pull --rebase {remote} {branch}")
        steps.append(f"[dry-run] would pop stash if created")
        steps.append(f"[dry-run] would push {remote} {branch}")
        result["ok"] = True
        return result

    # step 1: stash if dirty
    stashed = False
    try:
        stashed = _stash_push(cwd)
        if stashed:
            result["stash_used"] = True
            steps.append("stashed dirty working tree")
        else:
            steps.append("working tree clean, no stash needed")
    except subprocess.TimeoutExpired:
        result["error"] = "timeout: stash operation exceeded 60s"
        return result
    except Exception as exc:
        result["error"] = f"stash failed: {exc}"
        return result

    # step 2: pull --rebase
    try:
        pull_ok, rebase_count = _pull_rebase(cwd, remote, branch)
        result["rebase_count"] = rebase_count
        if pull_ok:
            steps.append(f"pull --rebase ok ({rebase_count} rebase steps)")
        else:
            steps.append("pull --rebase failed — will attempt push anyway")
    except subprocess.TimeoutExpired:
        result["error"] = "timeout: pull --rebase exceeded 60s"
        if stashed:
            _stash_pop(cwd)
        return result

    # step 3: pop stash
    if stashed:
        pop_ok = _stash_pop(cwd)
        if pop_ok:
            steps.append("popped stash successfully")
        else:
            steps.append("WARNING: stash pop failed — conflicts may exist")

    # step 4: push (with one retry)
    for attempt in range(1, MAX_PUSH_ATTEMPTS + 1):
        result["push_attempts"] = attempt
        try:
            push_ok, push_err = _push(cwd, remote, branch)
            if push_ok:
                steps.append(f"push succeeded (attempt {attempt})")
                result["ok"] = True
                return result
            else:
                steps.append(f"push attempt {attempt} failed: {push_err[:100]}")
        except subprocess.TimeoutExpired:
            steps.append(f"push attempt {attempt}: timeout")
            result["error"] = f"timeout: push attempt {attempt} exceeded 60s"
            continue

        # retry: pull --rebase once more before retrying
        if attempt < MAX_PUSH_ATTEMPTS:
            steps.append("retrying: pull --rebase before next push attempt")
            try:
                retry_ok, retry_count = _pull_rebase(cwd, remote, branch)
                result["rebase_count"] += retry_count
                if retry_ok:
                    steps.append(f"rebase ok ({retry_count} steps)")
                else:
                    steps.append("rebase failed — cannot retry push")
                    result["error"] = "rebase failed during push retry"
                    return result
            except subprocess.TimeoutExpired:
                result["error"] = "timeout: retry rebase exceeded 60s"
                return result

    # all attempts exhausted
    if not result["error"]:
        result["error"] = (
            f"push failed after {MAX_PUSH_ATTEMPTS} attempts — "
            "refusing to force-push; human intervention needed"
        )
    return result


def status_report(cwd: str = ".") -> dict:
    """Quick status check for caretaker dashboards."""
    dirty = _is_dirty(cwd)
    result = _run_git(["log", "--oneline", "-1"], cwd)
    head = result.stdout.strip() if result.returncode == 0 else "unknown"
    result = _run_git(
        ["rev-parse", "--abbrev-ref", "HEAD"], cwd
    )
    branch = result.stdout.strip() if result.returncode == 0 else "unknown"
    result = _run_git(
        ["rev-list", "--count", f"{DEFAULT_REMOTE}/{DEFAULT_BRANCH}..HEAD"],
        cwd,
    )
    unpushed = result.stdout.strip() if result.returncode == 0 else "?"
    return {
        "dirty": dirty,
        "head": head,
        "branch": branch,
        "unpushed_commits": unpushed,
        "timestamp": time.time(),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Guarded push-recovery sequence")
    parser.add_argument("--cwd", default=".", help="repo root directory")
    parser.add_argument("--remote", default=DEFAULT_REMOTE, help="remote name")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="branch name")
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would happen without doing it"
    )
    parser.add_argument(
        "--status", action="store_true", help="show status report instead of pushing"
    )
    args = parser.parse_args()

    if args.status:
        report = status_report(args.cwd)
        print(json.dumps(report, indent=2))
        sys.exit(0)

    result = guarded_push(
        cwd=args.cwd,
        remote=args.remote,
        branch=args.branch,
        dry_run=args.dry_run,
    )

    for step in result["steps"]:
        print(f"  {step}", file=sys.stderr)

    print(json.dumps({k: v for k, v in result.items() if k != "steps"}, indent=2))
    sys.exit(0 if result["ok"] else 1)
