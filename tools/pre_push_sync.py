#!/usr/bin/env python3
"""pre_push_sync.py — detect remote divergence and sync before push.

The push race in this repo is a clock: every ten minutes someone tries to
push and discovers the remote moved ahead. This tool breaks the cycle into
deterministic steps:

    1. Fetch origin.
    2. Check if local and remote have diverged.
    3. If diverged: stash dirty files, sync (merge or rebase), pop stash, report.
    4. If clean: just report "ready to push".

Two sync strategies are available:

    merge  — git pull --no-rebase (default, produces merge commits)
    rebase — git pull --rebase   (linear history, matches push_with_rebase)

Visit 66 wired sync into commit_batch but used merge only. Visit 67 adds
the rebase strategy so the sync path matches the push path.

Exit codes:
    0 — ready to push (no divergence, or divergence resolved)
    1 — divergence remains after sync attempt (manual intervention needed)
    2 — repository or git error

Usage:
    python3 tools/pre_push_sync.py [--remote origin] [--branch main] [--strategy merge|rebase] [--dry-run]
"""

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SyncResult:
    diverged: bool
    stashed: bool
    merged: bool
    stash_popped: bool
    ready: bool
    message: str


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a git command, return CompletedProcess."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def get_local_sha(repo: Path, branch: str = "main") -> str:
    r = run(["git", "rev-parse", branch], cwd=repo)
    return r.stdout.strip() if r.returncode == 0 else ""


def get_remote_sha(repo: Path, remote: str = "origin", branch: str = "main") -> str:
    r = run(["git", "rev-parse", f"{remote}/{branch}"], cwd=repo)
    return r.stdout.strip() if r.returncode == 0 else ""


def get_merge_base(repo: Path, local_sha: str, remote_sha: str) -> str:
    r = run(["git", "merge-base", local_sha, remote_sha], cwd=repo)
    return r.stdout.strip() if r.returncode == 0 else ""


def has_diverged(repo: Path, remote: str = "origin", branch: str = "main") -> bool:
    """True if local and remote have diverged (non-fast-forward)."""
    local = get_local_sha(repo, branch)
    remote = get_remote_sha(repo, remote, branch)
    if not local or not remote:
        return False
    if local == remote:
        return False
    base = get_merge_base(repo, local, remote)
    return base != local


def has_dirty_files(repo: Path) -> bool:
    r = run(["git", "status", "--porcelain"], cwd=repo)
    return bool(r.stdout.strip())


def sync(
    repo: Path,
    remote: str = "origin",
    branch: str = "main",
    dry_run: bool = False,
    strategy: str = "merge",
) -> SyncResult:
    """Attempt to sync local with remote, resolving divergence if needed.

    strategy: "merge" (default) uses git pull --no-rebase,
              "rebase" uses git pull --rebase for linear history.
    """
    if strategy not in ("merge", "rebase"):
        return SyncResult(False, False, False, False, False, f"unknown strategy: {strategy}")

    # Step 1: fetch
    r = run(["git", "fetch", remote], cwd=repo)
    if r.returncode != 0:
        return SyncResult(False, False, False, False, False, f"fetch failed: {r.stderr.strip()}")

    if not has_diverged(repo, remote, branch):
        return SyncResult(False, False, False, False, True, "no divergence — ready to push")

    if dry_run:
        return SyncResult(True, False, False, False, False, "diverged (dry-run, no action taken)")

    # Step 2: stash if dirty
    dirty = has_dirty_files(repo)
    if dirty:
        r = run(["git", "stash", "--include-untracked"], cwd=repo)
        if r.returncode != 0:
            return SyncResult(True, False, False, False, False, f"stash failed: {r.stderr.strip()}")

    # Step 3: sync (merge or rebase)
    if strategy == "rebase":
        r = run(["git", "pull", "--rebase", remote, branch], cwd=repo)
        if r.returncode != 0:
            run(["git", "rebase", "--abort"], cwd=repo)
            if dirty:
                run(["git", "stash", "pop"], cwd=repo)
            return SyncResult(True, dirty, False, dirty, False, f"rebase failed: {r.stderr.strip()}")
    else:
        r = run(["git", "pull", "--no-rebase", remote, branch], cwd=repo)
        if r.returncode != 0:
            run(["git", "merge", "--abort"], cwd=repo)
            if dirty:
                run(["git", "stash", "pop"], cwd=repo)
            return SyncResult(True, dirty, False, dirty, False, f"merge failed: {r.stderr.strip()}")

    # Step 4: pop stash
    popped = False
    if dirty:
        r = run(["git", "stash", "pop"], cwd=repo)
        popped = r.returncode == 0

    return SyncResult(True, dirty, True, popped, True, f"synced ({strategy}) — ready to push")


def main():
    parser = argparse.ArgumentParser(description="Sync local with remote before push")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--strategy", default="merge", choices=["merge", "rebase"],
                        help="sync strategy: merge (default) or rebase for linear history")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    result = sync(repo, args.remote, args.branch, args.dry_run, args.strategy)

    print(f"diverged: {result.diverged}")
    print(f"stashed:  {result.stashed}")
    print(f"merged:   {result.merged}")
    print(f"popped:   {result.stash_popped}")
    print(f"ready:    {result.ready}")
    print(f"message:  {result.message}")

    sys.exit(0 if result.ready else 1)


if __name__ == "__main__":
    main()
