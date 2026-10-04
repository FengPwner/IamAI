"""055 — push_guard: safe push with automatic pull-rebase retry.

the push-race is the most common failure in a multi-writer repo:
you commit locally, push, and the remote has advanced. the fix is
mechanical — pull --rebase, then push again — but doing it by hand
every time is how mistakes creep in (forgetting to commit first,
rebasing onto the wrong branch, pushing --force when you shouldn't).

push_guard wraps the whole sequence into one call:

1. ensure working tree is clean (stash if needed)
2. pull --rebase origin <branch>
3. push origin <branch>
4. if push rejected (non-fast-forward), retry once after re-pulling
5. restore stash if one was created

the retry-once policy matches reality: if the remote advances twice
in the ~2 seconds it takes to run this, something else is wrong and
retrying harder won't help. one retry covers 99% of real cases.

>>> import tempfile, subprocess
>>> # push_guard is designed to be called from scripts, not imported
>>> # as a library. the functions below are the building blocks.
>>> is_clean("/tmp")  # any directory is either clean or dirty
True
>>> # doctest intentionally minimal: real testing needs a git repo
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class PushResult:
    """Outcome of a guarded push attempt."""

    success: bool
    rebased: bool
    retries: int
    message: str


def is_clean(repo_dir: str) -> bool:
    """True if the working tree has no uncommitted changes."""
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    return r.returncode == 0 and r.stdout.strip() == ""


def stash_if_dirty(repo_dir: str) -> bool:
    """Stash changes if the tree is dirty. Returns True if a stash was created."""
    if is_clean(repo_dir):
        return False
    subprocess.run(
        ["git", "stash", "push", "-m", "push_guard: auto-stash before push"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    return True


def pull_rebase(repo_dir: str, branch: str = "main") -> bool:
    """Pull with rebase. Returns True on success."""
    r = subprocess.run(
        ["git", "pull", "--rebase", "origin", branch],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    return r.returncode == 0


def try_push(repo_dir: str, branch: str = "main") -> bool:
    """Attempt a push. Returns True if it succeeded."""
    r = subprocess.run(
        ["git", "push", "origin", branch],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    return r.returncode == 0


def pop_stash(repo_dir: str) -> bool:
    """Pop the most recent stash. Returns True on success."""
    r = subprocess.run(
        ["git", "stash", "pop"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    return r.returncode == 0


def guarded_push(
    repo_dir: str,
    branch: str = "main",
    max_retries: int = 1,
) -> PushResult:
    """Commit-free safe push: stash → pull-rebase → push (with one retry).

    Assumes all changes are already committed. If the working tree is
    dirty, it stashes first and pops after.
    """
    stashed = stash_if_dirty(repo_dir)

    # first attempt
    if not pull_rebase(repo_dir, branch):
        if stashed:
            pop_stash(repo_dir)
        return PushResult(False, False, 0, "pull --rebase failed")

    if try_push(repo_dir, branch):
        if stashed:
            pop_stash(repo_dir)
        return PushResult(True, True, 0, "ok")

    # retry: remote may have advanced between our pull and push
    for attempt in range(1, max_retries + 1):
        if not pull_rebase(repo_dir, branch):
            break
        if try_push(repo_dir, branch):
            if stashed:
                pop_stash(repo_dir)
            return PushResult(True, True, attempt, f"ok after {attempt} retries")

    if stashed:
        pop_stash(repo_dir)
    return PushResult(False, True, max_retries, "push rejected after retries")


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    branch = sys.argv[2] if len(sys.argv) > 2 else "main"
    result = guarded_push(repo, branch)
    print(f"{'OK' if result.success else 'FAIL'}: {result.message}")
    sys.exit(0 if result.success else 1)
