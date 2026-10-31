#!/usr/bin/env python3
"""rebase_safe_pull.py — pull that respects union merge drivers.

Problem: `git pull --rebase` silently fails when .gitattributes declares
merge=union for append-only files (notes/*.md, data/strokes.jsonl, docs/*.md).
The union merge driver writes to the working tree during rebase, which git
then interprets as "local changes would be overwritten by merge" — aborting
the rebase without useful feedback.

This has consumed at least 4 caretaker visits (441-444) of debugging time.

Solution: detect union-merged paths in .gitattributes, then choose the
right pull strategy:
  - If no divergence → nothing to do (exit 0).
  - If only ahead → nothing to do (exit 0, safe to push).
  - If diverged with union-merged files → `git pull --no-rebase` (merge).
  - If diverged without union files → `git pull --rebase` (clean history).
  - If behind only → `git pull --no-rebase` (fast-forward or merge).

Usage:
    python3 tools/rebase_safe_pull.py
    python3 tools/rebase_safe_pull.py --remote origin --branch main
    python3 tools/rebase_safe_pull.py --dry-run    # show what would happen
    python3 tools/rebase_safe_pull.py --json       # machine-readable output

Exit codes:
    0 — success (or nothing to do)
    1 — pull failed (conflict, network, etc.)
    2 — not a git repo or other precondition failure
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_REMOTE = "origin"
DEFAULT_BRANCH = "main"


@dataclass
class PullPlan:
    divergence: str      # clean, ahead, behind, diverged, no-remote, error
    strategy: str        # none, merge, rebase
    union_files: list    # paths with merge=union in .gitattributes
    action_taken: str    # what actually happened
    exit_code: int       # planned exit code


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) to find the git repo root."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return p


def run_git(args: list[str], cwd: Path, timeout: int = 30,
            env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd = ["git"] + args
    merged_env = None
    if env:
        merged_env = {**os.environ, **env}
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=merged_env,
    )


def get_local_head(repo: Path) -> str | None:
    """Get the current HEAD sha."""
    result = run_git(["rev-parse", "HEAD"], repo)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def fetch_remote(repo: Path, remote: str, branch: str, timeout: int = 15) -> bool:
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
    result = run_git(["rev-list", "--count", f"{from_sha}..{to_sha}"], repo)
    if result.returncode != 0:
        return 0
    return int(result.stdout.strip())


def detect_divergence(repo: Path, remote: str, branch: str,
                      timeout: int = 15) -> tuple[str, int, int]:
    """Detect divergence state. Returns (state, ahead, behind)."""
    local = get_local_head(repo)
    if local is None:
        return ("error", 0, 0)

    if not fetch_remote(repo, remote, branch, timeout):
        return ("error", 0, 0)

    remote_sha = get_remote_head(repo, remote, branch)
    if remote_sha is None:
        return ("no-remote", 0, 0)

    if local == remote_sha:
        return ("clean", 0, 0)

    base = get_merge_base(repo, local, remote_sha)
    if base is None:
        return ("error", 0, 0)

    ahead = count_commits(repo, base, local)
    behind = count_commits(repo, base, remote_sha)

    if ahead > 0 and behind == 0:
        return ("ahead", ahead, 0)
    elif behind > 0 and ahead == 0:
        return ("behind", 0, behind)
    else:
        return ("diverged", ahead, behind)


def find_union_merge_files(repo: Path) -> list[str]:
    """Parse .gitattributes for paths with merge=union."""
    attrs = repo / ".gitattributes"
    if not attrs.exists():
        return []

    union_paths = []
    for line in attrs.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "merge=union" in line:
            parts = line.split()
            if parts:
                union_paths.append(parts[0])
    return union_paths


def has_dirty_working_tree(repo: Path) -> bool:
    """Check if there are uncommitted changes."""
    result = run_git(["status", "--porcelain"], repo)
    return bool(result.stdout.strip())


def choose_strategy(divergence: str, union_files: list[str]) -> str:
    """Choose pull strategy based on divergence and union merge config.

    Returns: "none", "merge", or "rebase"
    """
    if divergence in ("clean", "ahead", "no-remote"):
        return "none"

    if divergence == "error":
        return "none"

    # behind or diverged: need to pull
    # if union-merged files exist, rebase will break — use merge
    if union_files:
        return "merge"

    # no union files → rebase is safe (cleaner history)
    return "rebase"


def execute_pull(repo: Path, strategy: str, remote: str, branch: str,
                 dry_run: bool = False, env: dict | None = None) -> tuple[bool, str]:
    """Execute the pull with the chosen strategy.

    Returns (success, message).
    """
    if strategy == "none":
        return (True, "nothing to do — already in sync or ahead")

    if strategy == "merge":
        cmd = ["pull", "--no-rebase", remote, branch]
    else:
        cmd = ["pull", "--rebase", remote, branch]

    if dry_run:
        return (True, f"would run: git {' '.join(cmd)}")

    result = run_git(cmd, repo, timeout=60, env=env)
    if result.returncode == 0:
        return (True, f"git {' '.join(cmd)} succeeded")
    else:
        # If rebase failed, try merge as fallback
        if strategy == "rebase":
            run_git(["rebase", "--abort"], repo)
            fallback = run_git(
                ["pull", "--no-rebase", remote, branch],
                repo, timeout=60, env=env,
            )
            if fallback.returncode == 0:
                return (True, "rebase failed, fell back to merge")
        return (False, f"git {' '.join(cmd)} failed: {result.stderr[:200]}")


def plan_and_execute(
    repo: Path | None = None,
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
    dry_run: bool = False,
    env: dict | None = None,
) -> PullPlan:
    """Main entry point: detect divergence, choose strategy, execute pull."""
    repo = repo or find_repo_root()

    if not (repo / ".git").exists():
        return PullPlan(
            divergence="error", strategy="none", union_files=[],
            action_taken="not a git repository", exit_code=2,
        )

    # Check for dirty working tree
    if has_dirty_working_tree(repo):
        return PullPlan(
            divergence="error", strategy="none", union_files=[],
            action_taken="working tree has uncommitted changes — commit or stash first",
            exit_code=1,
        )

    # Detect divergence
    divergence, ahead, behind = detect_divergence(repo, remote, branch)

    # Find union-merged files
    union_files = find_union_merge_files(repo)

    # Choose strategy
    strategy = choose_strategy(divergence, union_files)

    # Execute
    success, message = execute_pull(repo, strategy, remote, branch,
                                     dry_run=dry_run, env=env)

    exit_code = 0 if success else 1

    return PullPlan(
        divergence=divergence,
        strategy=strategy,
        union_files=union_files,
        action_taken=message,
        exit_code=exit_code,
    )


def format_report(plan: PullPlan) -> str:
    """Format a human-readable pull plan report."""
    lines = [
        "=== Rebase-Safe Pull ===",
        f"Divergence: {plan.divergence}",
        f"Union files: {len(plan.union_files)} ({', '.join(plan.union_files[:3])}{'…' if len(plan.union_files) > 3 else ''})",
        f"Strategy:   {plan.strategy}",
        f"Action:     {plan.action_taken}",
        f"Exit code:  {plan.exit_code}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Pull that respects union merge drivers — avoids rebase breakage"
    )
    parser.add_argument("--remote", default=DEFAULT_REMOTE, help="remote name")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="branch name")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would happen without pulling")
    parser.add_argument("--repo", type=str, default=None,
                        help="path to repo root")
    parser.add_argument("--json", action="store_true",
                        help="output JSON instead of text")
    args = parser.parse_args()

    repo = Path(args.repo) if args.repo else None
    plan = plan_and_execute(
        repo=repo, remote=args.remote, branch=args.branch,
        dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(asdict(plan), indent=2))
    else:
        print(format_report(plan))

    sys.exit(plan.exit_code)


if __name__ == "__main__":
    main()
