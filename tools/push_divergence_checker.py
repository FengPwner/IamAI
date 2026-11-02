#!/usr/bin/env python3
"""push_divergence_checker.py — detect local/remote branch divergence before pushing.

Runs a lightweight check without fetching the full remote:
  1. Reads the local tracking ref (origin/main) to get the last-known remote HEAD.
  2. Compares it against the local HEAD.
  3. Reports: ahead, behind, diverged, or up-to-date.

This is the quick check a caretaker runs BEFORE attempting a push, so they know
whether a plain `git push` will succeed or whether they need `pull --rebase` first.

Exit codes:
    0 — up-to-date or ahead-only (push will succeed)
    1 — behind or diverged (push will be rejected; pull --rebase needed)
    2 — error (no tracking branch, git failure, etc.)

Usage:
    python3 tools/push_divergence_checker.py
    python3 tools/push_divergence_checker.py --json
    python3 tools/push_divergence_checker.py --remote origin --branch main
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent


@dataclass
class DivergenceReport:
    local_head: str
    remote_head: str
    merge_base: str
    ahead: int
    behind: int
    verdict: str  # "up_to_date", "ahead_only", "behind_only", "diverged"
    push_safe: bool
    message: str


def git(*args: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd = ["git"] + list(args)
    return subprocess.run(
        cmd,
        cwd=cwd or REPO,
        capture_output=True,
        text=True,
        timeout=15,
    )


def get_local_head(repo: Path = REPO) -> str:
    """Return the SHA of HEAD."""
    result = git("rev-parse", "HEAD", cwd=repo)
    if result.returncode != 0:
        raise RuntimeError(f"git rev-parse HEAD failed: {result.stderr.strip()}")
    return result.stdout.strip()


def get_remote_head(repo: Path = REPO, remote: str = "origin", branch: str = "main") -> str:
    """Return the SHA of the remote tracking branch (last-fetched)."""
    result = git("rev-parse", f"{remote}/{branch}", cwd=repo)
    if result.returncode != 0:
        raise RuntimeError(
            f"git rev-parse {remote}/{branch} failed: {result.stderr.strip()}. "
            "Have you fetched recently?"
        )
    return result.stdout.strip()


def get_merge_base(repo: Path, sha_a: str, sha_b: str) -> str:
    """Return the merge base of two commits."""
    result = git("merge-base", sha_a, sha_b, cwd=repo)
    if result.returncode != 0:
        raise RuntimeError(f"git merge-base failed: {result.stderr.strip()}")
    return result.stdout.strip()


def count_commits(repo: Path, from_sha: str, to_sha: str) -> int:
    """Count commits reachable from to_sha but not from from_sha."""
    result = git("rev-list", "--count", f"{from_sha}..{to_sha}", cwd=repo)
    if result.returncode != 0:
        raise RuntimeError(f"git rev-list --count failed: {result.stderr.strip()}")
    return int(result.stdout.strip())


def check_divergence(
    repo: Path = REPO,
    remote: str = "origin",
    branch: str = "main",
) -> DivergenceReport:
    """Compute the divergence between local HEAD and remote tracking branch."""
    local_head = get_local_head(repo)
    remote_head = get_remote_head(repo, remote, branch)

    if local_head == remote_head:
        return DivergenceReport(
            local_head=local_head[:12],
            remote_head=remote_head[:12],
            merge_base=local_head[:12],
            ahead=0,
            behind=0,
            verdict="up_to_date",
            push_safe=True,
            message="local and remote are in sync — push will succeed (nothing to push)",
        )

    merge_base = get_merge_base(repo, local_head, remote_head)

    ahead = count_commits(repo, merge_base, local_head)
    behind = count_commits(repo, merge_base, remote_head)

    if ahead > 0 and behind == 0:
        verdict = "ahead_only"
        push_safe = True
        message = f"local is {ahead} commit(s) ahead — push will succeed"
    elif ahead == 0 and behind > 0:
        verdict = "behind_only"
        push_safe = False
        message = f"local is {behind} commit(s) behind — pull --rebase needed before push"
    else:
        verdict = "diverged"
        push_safe = False
        message = (
            f"branches diverged: local is {ahead} ahead, {behind} behind "
            f"merge base {merge_base[:12]} — pull --rebase needed before push"
        )

    return DivergenceReport(
        local_head=local_head[:12],
        remote_head=remote_head[:12],
        merge_base=merge_base[:12],
        ahead=ahead,
        behind=behind,
        verdict=verdict,
        push_safe=push_safe,
        message=message,
    )


def main():
    parser = argparse.ArgumentParser(description="Check local/remote branch divergence")
    parser.add_argument("--remote", default="origin", help="Remote name (default: origin)")
    parser.add_argument("--branch", default="main", help="Branch name (default: main)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--repo", type=Path, default=REPO, help="Repo path")
    args = parser.parse_args()

    try:
        report = check_divergence(repo=args.repo, remote=args.remote, branch=args.branch)
    except RuntimeError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(f"verdict:    {report.verdict}")
        print(f"push safe:  {report.push_safe}")
        print(f"ahead:      {report.ahead}")
        print(f"behind:     {report.behind}")
        print(f"local HEAD: {report.local_head}")
        print(f"remote HEAD:{report.remote_head}")
        print(f"merge base: {report.merge_base}")
        print(f"message:    {report.message}")

    sys.exit(0 if report.push_safe else 1)


if __name__ == "__main__":
    main()
