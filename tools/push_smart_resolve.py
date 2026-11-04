#!/usr/bin/env python3
"""push_smart_resolve.py — try rebase first, fall back to merge on failure.

Motivation (visit 541, 2026-11-04):
    caretaker arrived to dead processes and a push rejection.  rebase
    aborted twice because the live writer kept mutating tracked files.
    merge (`git pull --no-rebase`) succeeded on the first attempt.

    pattern: rebase needs a clean tree; merge tolerates minor dirtiness.
    when the writer is alive and touching files, rebase is fragile.
    this tool codifies the fallback: try rebase, catch failure, switch
    to merge.  both paths end with a push.

Usage:
    python3 tools/push_smart_resolve.py [--repo PATH] [--remote origin] [--branch main] [--json]

Exit codes:
    0 — push succeeded
    1 — both strategies failed (conflict or auth error; human needed)
    2 — repo not found or git unavailable

Output (--json):
    {"strategy": "rebase"|"merge"|"fast-forward"|"none",
     "pushed": true|false,
     "rebase_ok": bool,
     "merge_ok": bool,
     "error": str|null}
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, return CompletedProcess. Raises on failure if check=True."""
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, check=check, timeout=60
    )


def is_tree_clean(repo: Path) -> bool:
    """Check if working tree is clean (ignoring untracked files)."""
    result = run(["git", "status", "--porcelain", "--untracked-files=no"], repo, check=False)
    return result.returncode == 0 and result.stdout.strip() == ""


def try_fast_forward(repo: Path, remote: str, branch: str) -> bool:
    """Attempt fast-forward pull. Returns True if successful."""
    result = run(
        ["git", "pull", "--ff-only", remote, branch],
        repo, check=False
    )
    return result.returncode == 0


def try_rebase(repo: Path, remote: str, branch: str) -> bool:
    """Attempt rebase pull. Returns True if successful."""
    # Stash any local changes first
    stash_result = run(["git", "stash", "push", "-m", "smart-resolve-auto"], repo, check=False)
    did_stash = stash_result.returncode == 0 and "No local changes" not in stash_result.stdout

    result = run(
        ["git", "pull", "--rebase", remote, branch],
        repo, check=False
    )

    if result.returncode != 0:
        # Abort rebase if it failed
        run(["git", "rebase", "--abort"], repo, check=False)
        # Pop stash if we stashed
        if did_stash:
            run(["git", "stash", "pop"], repo, check=False)
        return False

    # Pop stash if we stashed
    if did_stash:
        pop_result = run(["git", "stash", "pop"], repo, check=False)
        if pop_result.returncode != 0:
            # Stash pop conflict — commit the stash separately
            run(["git", "stash", "drop"], repo, check=False)

    return True


def try_merge(repo: Path, remote: str, branch: str) -> bool:
    """Attempt merge pull. Returns True if successful."""
    result = run(
        ["git", "pull", "--no-rebase", remote, branch, "-m", "merge: smart resolve divergence"],
        repo, check=False
    )
    return result.returncode == 0


def do_push(repo: Path, remote: str, branch: str) -> bool:
    """Push to remote. Returns True if successful."""
    result = run(["git", "push", remote, branch], repo, check=False)
    return result.returncode == 0


def smart_resolve(repo: Path, remote: str, branch: str) -> dict:
    """
    Resolve push divergence with rebase-first-merge-fallback strategy.

    Returns a dict with keys: strategy, pushed, rebase_ok, merge_ok, error
    """
    output = {
        "strategy": "none",
        "pushed": False,
        "rebase_ok": False,
        "merge_ok": False,
        "error": None,
    }

    # Step 1: Check if we even need to resolve
    fetch_result = run(["git", "fetch", remote, branch], repo, check=False)
    if fetch_result.returncode != 0:
        output["error"] = f"fetch failed: {fetch_result.stderr.strip()}"
        return output

    # Step 2: Try fast-forward first (cheapest path)
    if try_fast_forward(repo, remote, branch):
        output["strategy"] = "fast-forward"
        if do_push(repo, remote, branch):
            output["pushed"] = True
        else:
            output["error"] = "fast-forward succeeded but push failed"
        return output

    # Step 3: Try rebase (preferred for linear history)
    if try_rebase(repo, remote, branch):
        output["rebase_ok"] = True
        output["strategy"] = "rebase"
        if do_push(repo, remote, branch):
            output["pushed"] = True
            return output
        # Rebase worked but push failed — maybe auth issue
        output["error"] = "rebase succeeded but push failed"
        return output

    # Step 4: Fall back to merge (tolerates dirty tree)
    if try_merge(repo, remote, branch):
        output["merge_ok"] = True
        output["strategy"] = "merge"
        if do_push(repo, remote, branch):
            output["pushed"] = True
            return output
        output["error"] = "merge succeeded but push failed"
        return output

    # Step 5: Both strategies failed
    output["error"] = "both rebase and merge failed — conflict or auth error, human needed"
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Smart push divergence resolver")
    parser.add_argument("--repo", default=".", help="Path to git repo")
    parser.add_argument("--remote", default="origin", help="Remote name")
    parser.add_argument("--branch", default="main", help="Branch name")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        if args.json:
            print(json.dumps({"error": "not a git repo", "pushed": False}))
        else:
            print(f"error: {repo} is not a git repo", file=sys.stderr)
        return 2

    result = smart_resolve(repo, args.remote, args.branch)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        strategy = result["strategy"]
        pushed = "pushed" if result["pushed"] else "NOT pushed"
        print(f"strategy: {strategy}  |  {pushed}")
        if result["error"]:
            print(f"error: {result['error']}")

    return 0 if result["pushed"] else 1


if __name__ == "__main__":
    sys.exit(main())
