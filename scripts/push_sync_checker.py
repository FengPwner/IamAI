#!/usr/bin/env python3
"""push_sync_checker.py — check whether local branch can push cleanly.

Reports divergence between local HEAD and its remote tracking branch:
  - ahead  : local has commits the remote lacks
  - behind : remote has commits we haven't fetched/merged
  - diverged: both sides have unique commits (push will be rejected)
  - synced : no divergence, push should succeed

Exit codes:
  0 = synced or only ahead (push will succeed)
  1 = behind or diverged (push will be rejected)
  2 = no remote tracking branch configured

Usage:
  python3 scripts/push_sync_checker.py [--json] [--repo PATH]
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class SyncStatus:
    local_branch: str
    remote_branch: Optional[str]
    ahead: int
    behind: int
    state: str  # "synced" | "ahead" | "behind" | "diverged" | "no-tracking"
    local_sha: str
    remote_sha: Optional[str]
    message: str


def run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def find_repo_root(start: str = ".") -> str:
    result = run_git(["rev-parse", "--show-toplevel"], cwd=start)
    if result.returncode != 0:
        raise RuntimeError(f"Not a git repo: {start}")
    return result.stdout.strip()


def get_current_branch(repo: str) -> str:
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    return result.stdout.strip()


def get_remote_tracking(repo: str, branch: str) -> Optional[str]:
    result = run_git(
        ["config", "--get", f"branch.{branch}.remote"], cwd=repo
    )
    if result.returncode != 0:
        return None
    remote = result.stdout.strip()
    merge_result = run_git(
        ["config", "--get", f"branch.{branch}.merge"], cwd=repo
    )
    if merge_result.returncode != 0:
        return None
    merge_ref = merge_result.stdout.strip()
    # refs/heads/main -> main
    remote_branch = merge_ref.replace("refs/heads/", "")
    return f"{remote}/{remote_branch}"


def get_rev_count(repo: str, range_spec: str) -> int:
    result = run_git(["rev-list", "--count", range_spec], cwd=repo)
    if result.returncode != 0:
        return 0
    return int(result.stdout.strip())


def get_sha(repo: str, ref: str) -> str:
    result = run_git(["rev-parse", "--short", ref], cwd=repo)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def check_sync(repo: str = ".") -> SyncStatus:
    repo_root = find_repo_root(repo)
    branch = get_current_branch(repo_root)
    remote_ref = get_remote_tracking(repo_root, branch)

    local_sha = get_sha(repo_root, "HEAD")

    if remote_ref is None:
        return SyncStatus(
            local_branch=branch,
            remote_branch=None,
            ahead=0,
            behind=0,
            state="no-tracking",
            local_sha=local_sha,
            remote_sha=None,
            message=f"Branch '{branch}' has no remote tracking branch.",
        )

    remote_sha = get_sha(repo_root, remote_ref)

    ahead = get_rev_count(repo_root, f"{remote_ref}..HEAD")
    behind = get_rev_count(repo_root, f"HEAD..{remote_ref}")

    if ahead == 0 and behind == 0:
        state = "synced"
        msg = "Local and remote are in sync. Push will succeed."
    elif ahead > 0 and behind == 0:
        state = "ahead"
        msg = f"Local is {ahead} commit(s) ahead. Push should succeed."
    elif ahead == 0 and behind > 0:
        state = "behind"
        msg = f"Local is {behind} commit(s) behind. Pull first."
    else:
        state = "diverged"
        msg = (
            f"Diverged: {ahead} ahead, {behind} behind. "
            "Push will be rejected — merge or rebase first."
        )

    return SyncStatus(
        local_branch=branch,
        remote_branch=remote_ref,
        ahead=ahead,
        behind=behind,
        state=state,
        local_sha=local_sha,
        remote_sha=remote_sha,
        message=msg,
    )


def main():
    parser = argparse.ArgumentParser(description="Check push/pull sync status.")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--repo", default=".", help="Path to git repo")
    args = parser.parse_args()

    try:
        status = check_sync(args.repo)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(asdict(status), indent=2))
    else:
        print(f"[{status.state}] {status.message}")
        print(f"  local:  {status.local_branch} @ {status.local_sha}")
        if status.remote_branch:
            print(f"  remote: {status.remote_branch} @ {status.remote_sha}")

    if status.state in ("synced", "ahead"):
        sys.exit(0)
    elif status.state == "no-tracking":
        sys.exit(2)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
