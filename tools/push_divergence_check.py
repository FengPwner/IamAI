#!/usr/bin/env python3
"""push_divergence_check.py — detect local/remote branch divergence before push.

Compares the local HEAD with the remote tracking branch to determine whether
a push would succeed. When divergence is detected, reports the number of
commits ahead and behind, so the caller can decide whether to pull, rebase,
or force-push.

Exit codes:
    0 — clean (local is ahead or in sync, push will succeed)
    1 — diverged (remote has commits local does not; push will be rejected)
    2 — no remote tracking branch configured
    3 — cannot determine (git error or missing repo)

Usage:
    python3 tools/push_divergence_check.py
    python3 tools/push_divergence_check.py --repo /path/to/IamAI
    python3 tools/push_divergence_check.py --remote origin --branch main
    python3 tools/push_divergence_check.py --json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) to find the repo root (.git directory)."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return p  # fallback


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command in the repo directory."""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=30,
    )


def get_remote_tracking_branch(repo: Path, branch: str | None = None) -> str | None:
    """Get the remote tracking branch for the current or specified branch."""
    if branch:
        result = run_git(repo, "config", f"branch.{branch}.remote")
        if result.returncode != 0:
            return None
        remote = result.stdout.strip()
        return f"{remote}/{branch}"
    
    result = run_git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def count_commits(repo: Path, from_ref: str, to_ref: str) -> int:
    """Count commits between two refs (from_ref..to_ref)."""
    result = run_git(repo, "rev-list", "--count", f"{from_ref}..{to_ref}")
    if result.returncode != 0:
        return -1
    try:
        return int(result.stdout.strip())
    except ValueError:
        return -1


def check_divergence(
    repo: Path,
    remote: str = "origin",
    branch: str | None = None,
    fetch_first: bool = True,
) -> dict:
    """Check if local and remote branches have diverged.

    Returns a dict with:
        - status: 'clean' | 'diverged' | 'no_tracking' | 'error'
        - ahead: number of commits local is ahead
        - behind: number of commits local is behind
        - remote_ref: the remote tracking branch name
        - message: human-readable summary
    """
    repo = find_repo_root(repo)

    # Determine the branch
    if not branch:
        result = run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        if result.returncode != 0:
            return {
                "status": "error",
                "ahead": 0,
                "behind": 0,
                "remote_ref": None,
                "message": "Cannot determine current branch",
            }
        branch = result.stdout.strip()

    # Fetch remote to get latest state
    if fetch_first:
        fetch_result = run_git(repo, "fetch", remote, branch)
        # fetch failure is not fatal — we may be offline

    # Get remote tracking ref
    remote_ref = f"{remote}/{branch}"
    verify = run_git(repo, "rev-parse", "--verify", remote_ref)
    if verify.returncode != 0:
        return {
            "status": "no_tracking",
            "ahead": 0,
            "behind": 0,
            "remote_ref": remote_ref,
            "message": f"No remote tracking branch {remote_ref}",
        }

    # Count ahead/behind
    ahead = count_commits(repo, remote_ref, "HEAD")
    behind = count_commits(repo, "HEAD", remote_ref)

    if behind > 0:
        status = "diverged"
        message = (
            f"Local is {ahead} ahead and {behind} behind {remote_ref}. "
            f"Push will be rejected — pull or rebase first."
        )
    else:
        status = "clean"
        if ahead > 0:
            message = f"Local is {ahead} commit(s) ahead of {remote_ref}. Push will succeed."
        else:
            message = f"Local is in sync with {remote_ref}."

    return {
        "status": status,
        "ahead": ahead,
        "behind": behind,
        "remote_ref": remote_ref,
        "message": message,
    }


def main():
    parser = argparse.ArgumentParser(description="Check push divergence")
    parser.add_argument("--repo", type=Path, default=None, help="Repo path")
    parser.add_argument("--remote", default="origin", help="Remote name")
    parser.add_argument("--branch", default=None, help="Branch name")
    parser.add_argument("--no-fetch", action="store_true", help="Skip fetch")
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
    args = parser.parse_args()

    repo = args.repo or find_repo_root()

    try:
        result = check_divergence(
            repo=repo,
            remote=args.remote,
            branch=args.branch,
            fetch_first=not args.no_fetch,
        )
    except Exception as e:
        result = {
            "status": "error",
            "ahead": 0,
            "behind": 0,
            "remote_ref": None,
            "message": str(e),
        }

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(result["message"])

    # Exit codes
    exit_map = {"clean": 0, "diverged": 1, "no_tracking": 2, "error": 3}
    sys.exit(exit_map.get(result["status"], 3))


if __name__ == "__main__":
    main()
