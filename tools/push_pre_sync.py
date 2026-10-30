#!/usr/bin/env python3
"""push_pre_sync.py — ensure local branch is synced with remote before push.

encodes the three-step dance every caretaker ends up doing by hand:
  1. stash uncommitted changes
  2. pull --rebase (integrate remote commits)
  3. stash pop (restore local work)

exit codes:
  0 — clean, safe to push
  1 — rebase conflict (human needed)
  2 — git error (network, auth, etc.)

usage:
  python3 tools/push_pre_sync.py              # dry-run: check only
  python3 tools/push_pre_sync.py --apply      # actually stash, rebase, pop
  python3 tools/push_pre_sync.py --push       # apply + push if clean
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def run(cmd, cwd=REPO, check=True):
    """Run a command, return (returncode, stdout, stderr)."""
    env = os.environ.copy()
    r = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, env=env, timeout=60
    )
    if check and r.returncode != 0:
        return r.returncode, r.stdout, r.stderr
    return r.returncode, r.stdout, r.stderr


def is_diverged():
    """Check if local and remote have diverged."""
    rc, out, _ = run(["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"], check=False)
    if rc != 0:
        return False  # can't tell, assume clean
    parts = out.strip().split()
    if len(parts) == 2:
        ahead, behind = int(parts[0]), int(parts[1])
        return behind > 0
    return False


def has_uncommitted():
    """Check for uncommitted changes."""
    rc, out, _ = run(["git", "status", "--porcelain"], check=False)
    return len(out.strip()) > 0


def sync(apply=False):
    """Perform the stash → rebase → pop sequence.
    
    Returns (success: bool, message: str).
    """
    if not is_diverged():
        return True, "already in sync — nothing to do"

    if not apply:
        return False, "diverged but --apply not set; run with --apply to fix"

    # step 1: stash if needed
    stashed = False
    if has_uncommitted():
        rc, _, err = run(["git", "stash", "push", "-m", "push_pre_sync: auto-stash"])
        if rc != 0:
            return False, f"stash failed: {err.strip()}"
        stashed = True

    # step 2: pull --rebase
    env_prefix = []
    ssh_key = "/tmp/ssh_deploy_key"
    if os.path.isfile(ssh_key):
        env_prefix = ["env", f"GIT_SSH_COMMAND=ssh -i {ssh_key} -o StrictHostKeyChecking=no"]

    rc, out, err = run(env_prefix + ["git", "pull", "--rebase", "origin", "main"], check=False)
    if rc != 0:
        # rebase failed — abort
        run(["git", "rebase", "--abort"], check=False)
        if stashed:
            run(["git", "stash", "pop"], check=False)
        return False, f"rebase failed: {err.strip()}"

    # step 3: pop stash if we stashed
    if stashed:
        rc, _, err = run(["git", "stash", "pop"], check=False)
        if rc != 0:
            return False, f"stash pop failed (conflict): {err.strip()}"

    return True, "synced: stash → rebase → pop complete"


def do_push():
    """Push to remote."""
    ssh_key = "/tmp/ssh_deploy_key"
    env_prefix = []
    if os.path.isfile(ssh_key):
        env_prefix = ["env", f"GIT_SSH_COMMAND=ssh -i {ssh_key} -o StrictHostKeyChecking=no"]

    rc, out, err = run(env_prefix + ["git", "push", "origin", "main"], check=False)
    if rc != 0:
        return False, f"push failed: {err.strip()}"
    return True, out.strip()


def main():
    parser = argparse.ArgumentParser(description="sync before push")
    parser.add_argument("--apply", action="store_true", help="actually perform sync")
    parser.add_argument("--push", action="store_true", help="sync and push")
    args = parser.parse_args()

    ok, msg = sync(apply=args.apply or args.push)
    print(f"sync: {'OK' if ok else 'FAIL'} — {msg}")

    if not ok:
        sys.exit(1)

    if args.push:
        ok, msg = do_push()
        print(f"push: {'OK' if ok else 'FAIL'} — {msg}")
        if not ok:
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
