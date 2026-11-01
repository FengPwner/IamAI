#!/usr/bin/env python3
"""Pre-rebase divergence detector and auto-resolver.

Checks whether local and remote have diverged, and if so, performs
the stash → rebase → stash-pop sequence automatically. This avoids
the common failure mode where `git push` is rejected because the
remote has commits the local doesn't, and a naive `git rebase`
fails because the working tree is dirty (writer mid-stroke).

Usage:
    python3 tools/rebase_preflight.py [--remote origin] [--branch main] [--dry-run]

Exit codes:
    0 — tree is clean or rebase succeeded
    1 — rebase failed (conflicts or other error)
    2 — remote unreachable
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def get_repo_root() -> Path:
    """Find the git repository root."""
    result = run(["git", "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        print(f"ERROR: not in a git repo: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return Path(result.stdout.strip())


def fetch(remote: str) -> bool:
    """Fetch from remote. Returns True on success."""
    result = run(["git", "fetch", remote])
    if result.returncode != 0:
        print(f"WARN: fetch failed: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def has_diverged(remote: str, branch: str) -> bool:
    """Check if local and remote have diverged (both have unique commits)."""
    result = run(["git", "log", "--oneline", f"{branch}..{remote}/{branch}"])
    remote_ahead = result.stdout.strip()
    result2 = run(["git", "log", "--oneline", f"{remote}/{branch}..{branch}"])
    local_ahead = result2.stdout.strip()
    return bool(remote_ahead) and bool(local_ahead)


def is_remote_ahead(remote: str, branch: str) -> bool:
    """Check if remote has commits local doesn't."""
    result = run(["git", "log", "--oneline", f"{branch}..{remote}/{branch}"])
    return bool(result.stdout.strip())


def is_local_ahead(remote: str, branch: str) -> bool:
    """Check if local has commits remote doesn't."""
    result = run(["git", "log", "--oneline", f"{remote}/{branch}..{branch}"])
    return bool(result.stdout.strip())


def tree_is_dirty() -> bool:
    """Check if working tree has uncommitted changes."""
    result = run(["git", "status", "--porcelain"])
    return bool(result.stdout.strip())


def stash_push(msg: str = "rebase-preflight-auto") -> bool:
    """Stash current changes."""
    result = run(["git", "stash", "push", "-m", msg])
    return result.returncode == 0


def stash_pop() -> bool:
    """Pop the most recent stash."""
    result = run(["git", "stash", "pop"])
    return result.returncode == 0


def rebase(remote: str, branch: str) -> bool:
    """Rebase local onto remote."""
    result = run(["git", "rebase", f"{remote}/{branch}"])
    if result.returncode != 0:
        # Abort the failed rebase
        run(["git", "rebase", "--abort"])
        print(f"ERROR: rebase failed: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def preflight_check(remote: str = "origin", branch: str = "main",
                     dry_run: bool = False) -> dict:
    """
    Run the full preflight check and return a status dict.

    Keys:
        action: "none" | "rebase" | "stash-rebase-pop"
        diverged: bool
        remote_ahead: bool
        local_ahead: bool
        dirty: bool
        success: bool
        message: str
    """
    status = {
        "action": "none",
        "diverged": False,
        "remote_ahead": False,
        "local_ahead": False,
        "dirty": False,
        "success": True,
        "message": "",
    }

    # Step 1: fetch
    if not fetch(remote):
        status["success"] = False
        status["message"] = f"could not fetch from {remote}"
        return status

    # Step 2: check divergence
    status["remote_ahead"] = is_remote_ahead(remote, branch)
    status["local_ahead"] = is_local_ahead(remote, branch)
    status["diverged"] = has_diverged(remote, branch)
    status["dirty"] = tree_is_dirty()

    if not status["remote_ahead"]:
        status["message"] = "local is up to date with remote, no action needed"
        return status

    # Step 3: determine action
    if status["diverged"]:
        status["action"] = "stash-rebase-pop" if status["dirty"] else "rebase"
    else:
        # Remote ahead but local not ahead → fast-forward possible
        status["action"] = "stash-rebase-pop" if status["dirty"] else "rebase"

    if dry_run:
        status["message"] = f"would {status['action']} (dry-run)"
        return status

    # Step 4: execute
    if status["action"] == "stash-rebase-pop":
        if not stash_push():
            status["success"] = False
            status["message"] = "stash failed"
            return status
        if not rebase(remote, branch):
            status["success"] = False
            status["message"] = "rebase failed after stash, tree may be inconsistent"
            # Try to pop stash back
            stash_pop()
            return status
        if not stash_pop():
            status["success"] = False
            status["message"] = "rebase succeeded but stash pop failed (conflict?)"
            return status
        status["message"] = "stash → rebase → pop completed successfully"
    elif status["action"] == "rebase":
        if not rebase(remote, branch):
            status["success"] = False
            status["message"] = "rebase failed"
            return status
        status["message"] = "rebase completed successfully"

    return status


def main():
    parser = argparse.ArgumentParser(description="Pre-rebase divergence check")
    parser.add_argument("--remote", default="origin", help="remote name")
    parser.add_argument("--branch", default="main", help="branch name")
    parser.add_argument("--dry-run", action="store_true",
                        help="check but do not execute")
    args = parser.parse_args()

    get_repo_root()
    status = preflight_check(args.remote, args.branch, args.dry_run)

    print(json.dumps(status, indent=2))
    sys.exit(0 if status["success"] else 1)


if __name__ == "__main__":
    main()
