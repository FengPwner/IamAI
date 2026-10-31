#!/usr/bin/env python3
"""push_sync: stash → fetch-merge → pop → push, in one command.

Handles the third push failure mode (remote divergence) that recurs when
multiple caretakers or external agents push to the same branch between
visits. Complements push_preflight.py (credential check) by handling
the sync-and-push step.

Exit codes:
    0 = synced and pushed successfully
    1 = sync failed (conflict or other error; details on stdout)
    2 = bad arguments

Usage:
    python3 tools/push_sync.py [--remote origin] [--branch main]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], cwd: Path | None = None, **kw) -> subprocess.CompletedProcess:
    """Run a command and return the result. Never raises."""
    env = os.environ.copy()
    # Ensure SSH key is available for git operations
    ssh_key = Path("/tmp/ssh_deploy_key")
    if ssh_key.exists():
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {ssh_key} "
            f"-o StrictHostKeyChecking=accept-new "
            f"-o UserKnownHostsFile={Path.home()}/.ssh/known_hosts"
        )
    return subprocess.run(
        cmd, cwd=cwd or REPO, capture_output=True, text=True, env=env, **kw
    )


def has_uncommitted_changes() -> bool:
    r = _run(["git", "status", "--porcelain"])
    return bool(r.stdout.strip())


def stash_save(tag: str) -> bool:
    r = _run(["git", "stash", "push", "-m", tag])
    return r.returncode == 0


def stash_pop() -> bool:
    r = _run(["git", "stash", "pop"])
    return r.returncode == 0


def fetch_and_merge(remote: str, branch: str) -> tuple[bool, str]:
    """Fetch from remote and merge. Returns (success, message)."""
    r = _run(["git", "fetch", remote, branch])
    if r.returncode != 0:
        return False, f"fetch failed: {r.stderr.strip()}"

    r = _run(["git", "merge", f"{remote}/{branch}", "--no-edit"])
    if r.returncode != 0:
        # Check for conflicts
        if "CONFLICT" in r.stdout or "CONFLICT" in r.stderr:
            # Abort the merge to leave repo clean
            _run(["git", "merge", "--abort"])
            return False, f"merge conflict (aborted): {r.stdout.strip()}"
        return False, f"merge failed: {r.stderr.strip()}"

    return True, "merged cleanly"


def push(remote: str, branch: str) -> tuple[bool, str]:
    r = _run(["git", "push", remote, branch])
    if r.returncode != 0:
        return False, r.stderr.strip()
    return True, "pushed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync and push with stash safety")
    parser.add_argument("--remote", default="origin", help="Git remote name")
    parser.add_argument("--branch", default="main", help="Branch to sync")
    args = parser.parse_args(argv)

    remote, branch = args.remote, args.branch
    tag = f"push-sync-{int(time.time())}"
    stashed = False

    print(f"[push_sync] remote={remote} branch={branch}")

    # Step 1: stash if dirty
    if has_uncommitted_changes():
        print(f"[push_sync] dirty tree — stashing as '{tag}'")
        if not stash_save(tag):
            print("[push_sync] stash failed, aborting")
            return 1
        stashed = True

    try:
        # Step 2: fetch and merge
        ok, msg = fetch_and_merge(remote, branch)
        if not ok:
            print(f"[push_sync] {msg}")
            return 1
        print(f"[push_sync] {msg}")

        # Step 3: push
        ok, msg = push(remote, branch)
        if not ok:
            print(f"[push_sync] push failed: {msg}")
            return 1
        print(f"[push_sync] {msg}")

    finally:
        # Step 4: restore stash no matter what
        if stashed:
            print("[push_sync] restoring stash…")
            stash_pop()

    print("[push_sync] done ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
