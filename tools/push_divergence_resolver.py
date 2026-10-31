#!/usr/bin/env python3
"""push_divergence_resolver.py — detect, resolve, and verify push divergence.

Problem: when local and remote diverge, `git push` fails. The caretaker
then enters a debugging loop: try rebase, fail (union merge driver), try
merge, succeed, push. This has consumed visits 441-445.

Solution: a single tool that:
1. Detects divergence (ahead/behind/diverged/clean).
2. Checks .gitattributes for union-merged paths.
3. Chooses the right strategy (merge if union files exist, rebase otherwise).
4. Executes the pull.
5. Optionally pushes the result.
6. Reports what happened.

Usage:
    python3 tools/push_divergence_resolver.py
    python3 tools/push_divergence_resolver.py --push
    python3 tools/push_divergence_resolver.py --dry-run
    python3 tools/push_divergence_resolver.py --json
    python3 tools/push_divergence_resolver.py --remote origin --branch main

Exit codes:
    0 — success (or nothing to do)
    1 — pull or push failed
    2 — not a git repo or precondition failure
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class ResolverResult:
    divergence: str          # clean, ahead, behind, diverged
    union_files: list        # paths with merge=union in .gitattributes
    strategy: str            # none, merge, rebase
    pulled: bool             # whether a pull was executed
    pushed: bool             # whether a push was executed
    exit_code: int
    message: str


def find_repo_root(start: str = ".") -> Optional[str]:
    """Walk up from start to find .git directory."""
    path = Path(start).resolve()
    while path != path.parent:
        if (path / ".git").is_dir():
            return str(path)
        path = path.parent
    if (path / ".git").is_dir():
        return str(path)
    return None


def run_git(*args: str, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=60,
    )


def find_union_merge_files(repo_root: str) -> list[str]:
    """Parse .gitattributes for paths with merge=union."""
    attrs_path = Path(repo_root) / ".gitattributes"
    if not attrs_path.exists():
        return []

    union_paths = []
    for line in attrs_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Format: pattern attr1 attr2 ...
        # We want lines containing merge=union
        if "merge=union" in line:
            parts = line.split()
            if parts:
                union_paths.append(parts[0])
    return union_paths


def count_commits(repo_root: str, spec: str) -> int:
    """Count commits in a range spec like 'A..B'."""
    result = run_git("rev-list", "--count", spec, cwd=repo_root)
    if result.returncode != 0:
        return -1
    return int(result.stdout.strip())


def detect_divergence(repo_root: str, remote: str = "origin", branch: str = "main") -> str:
    """Detect divergence state between local and remote.

    Returns one of: clean, ahead, behind, diverged, error
    """
    # Fetch first
    fetch = run_git("fetch", remote, branch, cwd=repo_root)
    if fetch.returncode != 0:
        return "error"

    local_head = run_git("rev-parse", "HEAD", cwd=repo_root)
    remote_head = run_git("rev-parse", f"{remote}/{branch}", cwd=repo_root)
    if local_head.returncode != 0 or remote_head.returncode != 0:
        return "error"

    local_sha = local_head.stdout.strip()
    remote_sha = remote_head.stdout.strip()

    if local_sha == remote_sha:
        return "clean"

    # Count commits in each direction
    ahead = count_commits(repo_root, f"{remote_sha}..{local_sha}")
    behind = count_commits(repo_root, f"{local_sha}..{remote_sha}")

    if ahead > 0 and behind == 0:
        return "ahead"
    if behind > 0 and ahead == 0:
        return "behind"
    if ahead > 0 and behind > 0:
        return "diverged"
    return "error"


def choose_strategy(divergence: str, union_files: list[str]) -> str:
    """Choose pull strategy based on divergence and union merge files.

    Returns: none, merge, rebase
    """
    if divergence in ("clean", "ahead", "error"):
        return "none"
    # behind or diverged
    if union_files:
        return "merge"
    return "rebase"


def execute_pull(repo_root: str, strategy: str, remote: str = "origin",
                 branch: str = "main", dry_run: bool = False) -> tuple[bool, str]:
    """Execute the pull with the chosen strategy.

    Returns (success, message).
    """
    if strategy == "none":
        return True, "nothing to do"

    if dry_run:
        if strategy == "merge":
            return True, f"would run: git pull --no-rebase {remote} {branch}"
        return True, f"would run: git pull --rebase {remote} {branch}"

    args = ["pull"]
    if strategy == "merge":
        args.append("--no-rebase")
    else:
        args.append("--rebase")
    args.extend([remote, branch])

    result = run_git(*args, cwd=repo_root)
    if result.returncode == 0:
        return True, result.stdout.strip()
    return False, result.stderr.strip()


def execute_push(repo_root: str, remote: str = "origin", branch: str = "main",
                 dry_run: bool = False) -> tuple[bool, str]:
    """Push to remote.

    Returns (success, message).
    """
    if dry_run:
        return True, f"would run: git push {remote} {branch}"

    result = run_git("push", remote, branch, cwd=repo_root)
    if result.returncode == 0:
        return True, result.stdout.strip() + result.stderr.strip()
    return False, result.stderr.strip()


def resolve(repo_root: str, remote: str = "origin", branch: str = "main",
            do_push: bool = False, dry_run: bool = False) -> ResolverResult:
    """Main resolution logic."""
    if repo_root is None:
        return ResolverResult(
            divergence="error", union_files=[], strategy="none",
            pulled=False, pushed=False, exit_code=2,
            message="not a git repository",
        )

    union_files = find_union_merge_files(repo_root)
    divergence = detect_divergence(repo_root, remote, branch)

    if divergence == "error":
        return ResolverResult(
            divergence=divergence, union_files=union_files, strategy="none",
            pulled=False, pushed=False, exit_code=2,
            message="could not determine divergence (fetch failed or bad refs)",
        )

    strategy = choose_strategy(divergence, union_files)

    if strategy == "none":
        msg = f"{divergence} — no pull needed"
        pushed = False
        if do_push and divergence == "ahead":
            ok, push_msg = execute_push(repo_root, remote, branch, dry_run)
            pushed = ok
            msg += f"; push: {'ok' if ok else 'FAILED'} ({push_msg})"
            if not ok:
                return ResolverResult(
                    divergence=divergence, union_files=union_files,
                    strategy=strategy, pulled=False, pushed=False,
                    exit_code=1, message=msg,
                )
        return ResolverResult(
            divergence=divergence, union_files=union_files, strategy=strategy,
            pulled=False, pushed=pushed, exit_code=0, message=msg,
        )

    # Execute pull
    ok, pull_msg = execute_pull(repo_root, strategy, remote, branch, dry_run)
    if not ok:
        return ResolverResult(
            divergence=divergence, union_files=union_files, strategy=strategy,
            pulled=False, pushed=False, exit_code=1,
            message=f"pull ({strategy}) FAILED: {pull_msg}",
        )

    pushed = False
    push_msg = ""
    if do_push and not dry_run:
        ok, push_msg = execute_push(repo_root, remote, branch)
        pushed = ok
        if not ok:
            return ResolverResult(
                divergence=divergence, union_files=union_files,
                strategy=strategy, pulled=True, pushed=False,
                exit_code=1,
                message=f"pull ({strategy}) ok; push FAILED: {push_msg}",
            )

    parts = [f"pull ({strategy}) ok: {pull_msg}"]
    if do_push:
        state = "ok" if pushed else "dry-run"
        parts.append(f"push: {state}" + (f" ({push_msg})" if pushed else ""))
    return ResolverResult(
        divergence=divergence, union_files=union_files, strategy=strategy,
        pulled=True, pushed=pushed, exit_code=0,
        message="; ".join(parts),
    )


def format_report(result: ResolverResult, as_json: bool = False) -> str:
    """Format the result for display."""
    if as_json:
        return json.dumps(asdict(result), indent=2)

    lines = [
        f"divergence:  {result.divergence}",
        f"union files: {len(result.union_files)} ({', '.join(result.union_files[:5])})",
        f"strategy:    {result.strategy}",
        f"pulled:      {result.pulled}",
        f"pushed:      {result.pushed}",
        f"exit code:   {result.exit_code}",
        f"message:     {result.message}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Detect and resolve push divergence automatically."
    )
    parser.add_argument("--remote", default="origin", help="remote name")
    parser.add_argument("--branch", default="main", help="branch name")
    parser.add_argument("--push", action="store_true", help="push after resolving")
    parser.add_argument("--dry-run", action="store_true", help="show plan without executing")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--repo", default=".", help="path to repo root")
    args = parser.parse_args()

    repo_root = find_repo_root(args.repo)
    if repo_root is None:
        result = ResolverResult(
            divergence="error", union_files=[], strategy="none",
            pulled=False, pushed=False, exit_code=2,
            message=f"not a git repository: {args.repo}",
        )
    else:
        result = resolve(
            repo_root, remote=args.remote, branch=args.branch,
            do_push=args.push, dry_run=args.dry_run,
        )

    print(format_report(result, as_json=args.json))
    sys.exit(result.exit_code)


if __name__ == "__main__":
    main()
