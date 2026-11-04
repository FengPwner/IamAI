#!/usr/bin/env python3
"""rebase_rescue.py — automated stash-rebase-pop with conflict recovery.

When the remote has diverged (fetch-first rejection), this utility:
1. Stashes local changes (if any)
2. Pulls with --rebase from the remote
3. Pops the stash
4. If pop conflicts: keeps the working copy, drops the conflicting stash
5. Reports the outcome

Usage:
    python3 tools/rebase_rescue.py [--dry-run] [--remote REMOTE] [--branch BRANCH]
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def find_repo_root(start: str = ".") -> Path:
    """Walk up to find the .git directory."""
    p = Path(start).resolve()
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return Path(start).resolve()


def run(cmd: list[str], cwd: Path, check: bool = True,
        capture: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture,
        text=True,
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd,
            output=result.stdout, stderr=result.stderr
        )
    return result


def has_unstaged_changes(cwd: Path) -> bool:
    """Check if there are unstaged changes."""
    result = run(["git", "status", "--porcelain"], cwd)
    for line in result.stdout.strip().split("\n"):
        if line and line[0] == " " or (line and line[0] in ("M", "D", "A")):
            return True
        if line and line.strip():
            return True
    return bool(result.stdout.strip())


def has_stash(cwd: Path) -> bool:
    """Check if there are any stash entries."""
    result = run(["git", "stash", "list"], cwd)
    return bool(result.stdout.strip())


def is_remote_ahead(remote: str, branch: str, cwd: Path) -> bool:
    """Check if remote has commits we don't have."""
    run(["git", "fetch", remote, branch], cwd, check=False)
    result = run(
        ["git", "rev-list", "--count", f"HEAD..{remote}/{branch}"],
        cwd, check=False
    )
    if result.returncode != 0:
        return False
    try:
        return int(result.stdout.strip()) > 0
    except ValueError:
        return False


def rebase_rescue(cwd: Path, remote: str = "origin", branch: str = "main",
                  dry_run: bool = False) -> dict:
    """Perform the stash-rebase-pop sequence.

    Returns a dict with:
        - action: what was done
        - stash_used: whether a stash was created/used
        - conflict: whether a pop conflict occurred
        - stash_dropped: whether a conflicting stash was dropped
        - success: overall success
        - message: human-readable summary
    """
    result = {
        "action": "rebase_rescue",
        "stash_used": False,
        "conflict": False,
        "stash_dropped": False,
        "success": True,
        "message": "",
        "remote_ahead": False,
    }

    # Check if remote is ahead
    if is_remote_ahead(remote, branch, cwd):
        result["remote_ahead"] = True
        if dry_run:
            result["message"] = (
                f"dry-run: remote {remote}/{branch} has new commits; "
                f"would stash, rebase, and pop"
            )
            return result

    has_changes = has_unstaged_changes(cwd)

    if not has_changes and not has_stash(cwd):
        result["message"] = "nothing to do: clean tree, no stash"
        return result

    # Step 1: Stash if needed
    if has_changes:
        result["stash_used"] = True
        if dry_run:
            result["message"] = "dry-run: would stash local changes"
            return result
        stash_result = run(["git", "stash", "push", "-m", "rebase-rescue-auto"],
                           cwd, check=False)
        if stash_result.returncode != 0:
            result["success"] = False
            result["message"] = f"stash failed: {stash_result.stderr.strip()}"
            return result

    # Step 2: Pull --rebase
    if dry_run:
        result["message"] = "dry-run: would pull --rebase"
        return result

    pull_result = run(
        ["git", "pull", "--rebase", remote, branch],
        cwd, check=False
    )

    if pull_result.returncode != 0:
        # Rebase failed — try to abort and restore stash
        run(["git", "rebase", "--abort"], cwd, check=False)
        if result["stash_used"]:
            run(["git", "stash", "pop"], cwd, check=False)
        result["success"] = False
        result["message"] = f"rebase failed: {pull_result.stderr.strip()}"
        return result

    # Step 3: Pop stash if we stashed
    if result["stash_used"]:
        pop_result = run(["git", "stash", "pop"], cwd, check=False)
        if pop_result.returncode != 0:
            # Conflict: keep working copy, drop the stash entry
            result["conflict"] = True
            result["stash_dropped"] = True
            # The stash entry is still there (pop failed), drop it
            run(["git", "stash", "drop", "stash@{0}"], cwd, check=False)
            result["message"] = (
                "stash pop conflicted; kept working copy, "
                "dropped conflicting stash entry"
            )
            return result

    result["message"] = "rebase successful, stash applied cleanly"
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Automated stash-rebase-pop with conflict recovery"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--remote", default="origin",
        help="Remote name (default: origin)"
    )
    parser.add_argument(
        "--branch", default="main",
        help="Branch name (default: main)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output result as JSON"
    )
    args = parser.parse_args()

    cwd = find_repo_root()
    result = rebase_rescue(
        cwd, remote=args.remote, branch=args.branch, dry_run=args.dry_run
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = "ok" if result["success"] else "FAILED"
        print(f"[{status}] {result['message']}")
        if result.get("conflict"):
            print("  note: working copy preserved, conflicting stash dropped")
        if result.get("remote_ahead"):
            print(f"  info: {args.remote}/{args.branch} had new commits")

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
