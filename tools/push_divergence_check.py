#!/usr/bin/env python3
"""push_divergence_check.py — detect local/remote branch divergence before push.

Push failures from remote divergence are the single most common caretaker
disruption. This tool checks whether local and remote branches have diverged
(each has commits the other doesn't) so the caretaker can resolve conflicts
proactively instead of discovering them on a failed push.

Strategy:
  1. Fetch the remote ref (with configurable timeout).
  2. Compare local HEAD against the remote tracking branch.
  3. Count commits ahead/behind using merge-base arithmetic.

Reports:
  - "clean"     : local and remote are identical
  - "ahead"     : local has commits remote doesn't (safe to push)
  - "behind"    : remote has commits local doesn't (need pull first)
  - "diverged"  : both sides have unique commits (need pull --rebase)
  - "no-remote" : remote ref doesn't exist yet (first push, safe)

Usage:
    python3 tools/push_divergence_check.py
    python3 tools/push_divergence_check.py --branch main
    python3 tools/push_divergence_check.py --remote origin --timeout 10
    python3 tools/push_divergence_check.py --json

Exit codes:
    0 — clean or ahead (safe to push)
    1 — behind or diverged (must pull/rebase first)
    2 — cannot determine (fetch failed, not a git repo, etc.)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_REMOTE = "origin"
DEFAULT_BRANCH = "main"
DEFAULT_TIMEOUT = 15  # seconds for git fetch


@dataclass
class DivergenceStatus:
    state: str          # clean, ahead, behind, diverged, no-remote, error
    local: str          # local HEAD sha
    remote: str         # remote HEAD sha (empty if no-remote)
    merge_base: str     # common ancestor sha (empty if no-remote)
    ahead: int          # commits local has that remote doesn't
    behind: int         # commits remote has that local doesn't
    message: str        # human-readable summary


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) to find the git repo root."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return p


def run_git(args: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd = ["git"] + args
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def get_local_head(repo: Path) -> str | None:
    """Get the current HEAD sha."""
    result = run_git(["rev-parse", "HEAD"], repo)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def fetch_remote(repo: Path, remote: str, branch: str, timeout: int) -> bool:
    """Fetch the remote ref. Returns True on success."""
    result = run_git(["fetch", remote, branch], repo, timeout=timeout)
    return result.returncode == 0


def get_remote_head(repo: Path, remote: str, branch: str) -> str | None:
    """Get the remote tracking branch sha."""
    result = run_git(["rev-parse", f"{remote}/{branch}"], repo)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def get_merge_base(repo: Path, local: str, remote: str) -> str | None:
    """Find the common ancestor of local and remote."""
    result = run_git(["merge-base", local, remote], repo)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def count_commits(repo: Path, from_sha: str, to_sha: str) -> int:
    """Count commits reachable from to_sha but not from from_sha."""
    result = run_git(
        ["rev-list", "--count", f"{from_sha}..{to_sha}"],
        repo,
    )
    if result.returncode != 0:
        return 0
    return int(result.stdout.strip())


def check_divergence(
    repo: Path | None = None,
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
    timeout: int = DEFAULT_TIMEOUT,
) -> DivergenceStatus:
    """Check whether local and remote branches have diverged.

    Returns a DivergenceStatus with the full diagnosis.
    """
    repo = repo or find_repo_root()

    # Get local HEAD
    local = get_local_head(repo)
    if local is None:
        return DivergenceStatus(
            state="error", local="", remote="", merge_base="",
            ahead=0, behind=0, message="not a git repository or no commits",
        )

    # Fetch remote
    if not fetch_remote(repo, remote, branch, timeout):
        return DivergenceStatus(
            state="error", local=local, remote="", merge_base="",
            ahead=0, behind=0,
            message=f"fetch from {remote}/{branch} failed (timeout or network)",
        )

    # Get remote HEAD
    remote_sha = get_remote_head(repo, remote, branch)
    if remote_sha is None:
        return DivergenceStatus(
            state="no-remote", local=local, remote="", merge_base="",
            ahead=0, behind=0,
            message=f"remote ref {remote}/{branch} does not exist (first push is safe)",
        )

    # Identical?
    if local == remote_sha:
        return DivergenceStatus(
            state="clean", local=local, remote=remote_sha, merge_base=local,
            ahead=0, behind=0,
            message="local and remote are in sync",
        )

    # Find merge base
    base = get_merge_base(repo, local, remote_sha)
    if base is None:
        return DivergenceStatus(
            state="error", local=local, remote=remote_sha, merge_base="",
            ahead=0, behind=0,
            message="cannot find merge base (unrelated histories?)",
        )

    # Count ahead/behind
    ahead = count_commits(repo, base, local)
    behind = count_commits(repo, base, remote_sha)

    if ahead > 0 and behind == 0:
        state = "ahead"
        msg = f"local is {ahead} commit(s) ahead of {remote}/{branch} — safe to push"
    elif behind > 0 and ahead == 0:
        state = "behind"
        msg = f"local is {behind} commit(s) behind {remote}/{branch} — pull first"
    else:
        state = "diverged"
        msg = (
            f"diverged: {ahead} local + {behind} remote commit(s) — "
            f"pull --rebase before pushing"
        )

    return DivergenceStatus(
        state=state, local=local, remote=remote_sha, merge_base=base,
        ahead=ahead, behind=behind, message=msg,
    )


def format_report(status: DivergenceStatus) -> str:
    """Format a human-readable divergence report."""
    lines = [
        "=== Push Divergence Check ===",
        f"State:      {status.state}",
        f"Local:      {status.local[:12] if status.local else 'N/A'}",
        f"Remote:     {status.remote[:12] if status.remote else 'N/A'}",
        f"Merge base: {status.merge_base[:12] if status.merge_base else 'N/A'}",
        f"Ahead:      {status.ahead}",
        f"Behind:     {status.behind}",
        f"Verdict:    {status.message}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Check local/remote branch divergence before push"
    )
    parser.add_argument("--remote", default=DEFAULT_REMOTE, help="remote name")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="branch name")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="fetch timeout in seconds")
    parser.add_argument("--repo", type=str, default=None,
                        help="path to repo root")
    parser.add_argument("--json", action="store_true",
                        help="output JSON instead of text")
    args = parser.parse_args()

    repo = Path(args.repo) if args.repo else None
    status = check_divergence(repo=repo, remote=args.remote,
                               branch=args.branch, timeout=args.timeout)

    if args.json:
        print(json.dumps(asdict(status), indent=2))
    else:
        print(format_report(status))

    # Exit codes: 0=safe to push, 1=must resolve, 2=error
    if status.state in ("clean", "ahead", "no-remote"):
        sys.exit(0)
    elif status.state in ("behind", "diverged"):
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
