#!/usr/bin/env python3
"""merge_guard — pre-push divergence check with auto-merge.

called before `git push`, this tool:
1. fetches origin to get the latest remote HEAD
2. checks if local and remote have diverged
3. if diverged, performs `git merge` (not rebase) to integrate
4. returns exit 0 if push is safe, exit 1 if merge had conflicts

why merge over rebase: the writer loop modifies writer_state.json every
15 seconds. rebase replays commits and aborts on any dirty file it
touches. merge only needs a clean index, which is easier to guarantee.

usage:
    python3 tools/merge_guard.py              # check + auto-merge
    python3 tools/merge_guard.py --dry-run    # check only, no merge
    python3 tools/merge_guard.py --verbose    # show merge details
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(cmd, cwd=None, check=False):
    """run a shell command, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=cwd
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed: {cmd}\n{result.stderr}")
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def get_heads(repo_dir):
    """return (local_head, remote_head, merge_base) or None if fetch fails."""
    rc, _, _ = run("git fetch origin main", cwd=repo_dir)
    if rc != 0:
        return None

    rc, local, _ = run("git rev-parse HEAD", cwd=repo_dir)
    if rc != 0:
        return None

    rc, remote, _ = run("git rev-parse origin/main", cwd=repo_dir)
    if rc != 0:
        return None

    rc, base, _ = run(f"git merge-base HEAD origin/main", cwd=repo_dir)
    if rc != 0:
        return None

    return local, remote, base


def check_divergence(heads):
    """return divergence status dict."""
    if heads is None:
        return {"status": "fetch_failed", "diverged": False, "safe_to_push": False}

    local, remote, base = heads

    if local == remote:
        return {"status": "up_to_date", "diverged": False, "safe_to_push": True}

    if local == base:
        # local is behind remote, needs pull
        return {
            "status": "behind",
            "diverged": False,
            "safe_to_push": False,
            "needs_pull": True,
        }

    if remote == base:
        # local is ahead, safe to push
        return {"status": "ahead", "diverged": False, "safe_to_push": True}

    # both moved: divergence
    return {
        "status": "diverged",
        "diverged": True,
        "safe_to_push": False,
        "local": local[:7],
        "remote": remote[:7],
        "base": base[:7],
    }


def has_dirty_index(repo_dir):
    """check if there are staged changes (index is dirty)."""
    rc, out, _ = run("git diff --cached --quiet", cwd=repo_dir)
    return rc != 0


def has_unstaged_changes(repo_dir):
    """check if there are unstaged changes in working tree."""
    rc, out, _ = run("git diff --quiet", cwd=repo_dir)
    return rc != 0


def auto_merge(repo_dir, dry_run=False, verbose=False):
    """perform merge of origin/main into current branch.

    returns (success: bool, message: str).
    """
    if dry_run:
        return True, "dry-run: would merge origin/main into HEAD"

    if has_unstaged_changes(repo_dir):
        # stash unstaged changes before merge
        rc, _, err = run("git stash push -m 'merge_guard auto-stash'", cwd=repo_dir)
        if rc != 0:
            return False, f"stash failed: {err}"
        stashed = True
    else:
        stashed = False

    # attempt merge
    rc, out, err = run(
        "git merge origin/main --no-edit -m 'merge_guard: auto-merge before push'",
        cwd=repo_dir,
    )

    if rc != 0:
        # merge conflict — abort
        run("git merge --abort", cwd=repo_dir)
        if stashed:
            run("git stash pop", cwd=repo_dir)
        return False, f"merge conflict, aborted: {err}"

    # pop stash if we stashed
    if stashed:
        rc, _, err = run("git stash pop", cwd=repo_dir)
        if rc != 0:
            # stash pop failed — merge succeeded but working tree has conflict
            # drop the stash (writer state is regenerable)
            run("git stash drop", cwd=repo_dir)
            if verbose:
                print(f"note: stash pop failed, dropped ({err})", file=sys.stderr)

    return True, "merged origin/main successfully"


def main():
    parser = argparse.ArgumentParser(description="pre-push divergence guard")
    parser.add_argument("--dry-run", action="store_true", help="check only, no merge")
    parser.add_argument("--verbose", action="store_true", help="show details")
    parser.add_argument("--repo", default=".", help="repo directory")
    args = parser.parse_args()

    repo_dir = str(Path(args.repo).resolve())
    heads = get_heads(repo_dir)
    status = check_divergence(heads)

    if args.verbose:
        print(json.dumps(status, indent=2))

    if status["safe_to_push"]:
        print(f"merge_guard: {status['status']} — safe to push")
        return 0

    if status.get("fetch_failed"):
        print("merge_guard: fetch failed — cannot verify", file=sys.stderr)
        return 1

    if status["diverged"] or status.get("needs_pull"):
        print(f"merge_guard: {status['status']} — attempting merge...")
        ok, msg = auto_merge(repo_dir, dry_run=args.dry_run, verbose=args.verbose)
        if ok:
            print(f"merge_guard: {msg}")
            return 0
        else:
            print(f"merge_guard: FAILED — {msg}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
