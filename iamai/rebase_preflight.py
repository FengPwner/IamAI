"""
rebase_preflight — check whether git pull --rebase is safe before pushing.

motivated by the recurring pattern: push rejected (non-fast-forward),
caretaker tries `git pull --rebase`, gets "cannot pull with rebase:
you have unstaged changes", then has to stash → pull → pop → push.

this module automates the preflight check so the caretaker knows
*before* attempting the rebase whether it needs to stash first.

public API
----------

  check_rebase_safety(repo_path: str) -> RebasePreflight

returns a dataclass with:
  - verdict: "clean" | "needs_stash" | "needs_commit" | "blocked"
  - unstaged_files: list[str]
  - untracked_files: list[str]
  - staged_files: list[str]
  - stash_required: bool
  - safe_to_rebase: bool
  - recommendation: str — human-readable next step

verdict logic:
  - "clean": no working-tree changes, safe to rebase directly
  - "needs_stash": unstaged or staged changes exist but no conflicts
    likely; stash first, rebase, pop
  - "needs_commit": changes exist and stash might lose context
    (e.g. binary files modified); commit first then rebase
  - "blocked": merge in progress, rebase in progress, or lock file
    present; resolve before proceeding
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
import subprocess


@dataclass
class RebasePreflight:
    verdict: str = "clean"
    unstaged_files: List[str] = field(default_factory=list)
    untracked_files: List[str] = field(default_factory=list)
    staged_files: List[str] = field(default_factory=list)
    stash_required: bool = False
    safe_to_rebase: bool = True
    recommendation: str = "safe to rebase directly"

    @property
    def has_changes(self) -> bool:
        return bool(self.unstaged_files or self.untracked_files or self.staged_files)

    @property
    def blocked(self) -> bool:
        return self.verdict == "blocked"

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "unstaged_files": self.unstaged_files,
            "untracked_files": self.untracked_files,
            "staged_files": self.staged_files,
            "stash_required": self.stash_required,
            "safe_to_rebase": self.safe_to_rebase,
            "recommendation": self.recommendation,
        }


def _run_git(repo_path: str, *args: str) -> subprocess.CompletedProcess:
    """run a git command in the given repo path."""
    return subprocess.run(
        ["git", "-C", repo_path] + list(args),
        capture_output=True,
        text=True,
        timeout=10,
    )


def _parse_status(repo_path: str) -> tuple[list[str], list[str], list[str]]:
    """parse git status --porcelain into (staged, unstaged, untracked)."""
    result = _run_git(repo_path, "status", "--porcelain")
    staged = []
    unstaged = []
    untracked = []

    for line in result.stdout.split("\n"):
        line = line.rstrip()
        if not line:
            continue
        # porcelain format: XY filename (XY is 2 chars, then 1 space)
        # X = index status, Y = working tree status
        if len(line) < 4:
            continue
        x, y = line[0], line[1]
        filename = line[3:]

        if x == "?" and y == "?":
            untracked.append(filename)
        else:
            if x not in (" ", "?"):
                staged.append(filename)
            if y not in (" ", "?"):
                unstaged.append(filename)

    return staged, unstaged, untracked


def _check_lock_files(repo_path: str) -> bool:
    """check for rebase/merge lock files that indicate operations in progress."""
    git_dir = Path(repo_path) / ".git"
    lock_indicators = [
        "rebase-merge",
        "rebase-apply",
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
    ]
    return any((git_dir / lock).exists() for lock in lock_indicators)


def _has_binary_changes(repo_path: str, files: list[str]) -> bool:
    """check if any modified files appear to be binary."""
    if not files:
        return False
    result = _run_git(repo_path, "diff", "--name-only", "--diff-filter=M")
    modified = result.stdout.strip().split("\n") if result.stdout.strip() else []
    for f in modified:
        f = f.strip()
        if not f:
            continue
        diff_result = _run_git(repo_path, "diff", "--numstat", "--", f)
        if diff_result.stdout.strip():
            parts = diff_result.stdout.strip().split("\t")
            if len(parts) >= 2 and (parts[0] == "-" or parts[1] == "-"):
                return True
    return False


def check_rebase_safety(repo_path: str) -> RebasePreflight:
    """check whether it's safe to run git pull --rebase in the given repo.

    returns a RebasePreflight with a verdict and recommendation.
    """
    pf = RebasePreflight()

    # check for lock files first (operations in progress)
    if _check_lock_files(repo_path):
        pf.verdict = "blocked"
        pf.safe_to_rebase = False
        pf.recommendation = "merge or rebase in progress — resolve before proceeding"
        return pf

    # parse working tree status
    staged, unstaged, untracked = _parse_status(repo_path)
    pf.staged_files = staged
    pf.unstaged_files = unstaged
    pf.untracked_files = untracked

    # clean tree — safe to rebase directly
    if not staged and not unstaged and not untracked:
        pf.verdict = "clean"
        pf.safe_to_rebase = True
        pf.recommendation = "safe to rebase directly"
        return pf

    # changes exist — check if binary files are involved
    has_binary = _has_binary_changes(repo_path, unstaged + staged)

    if has_binary:
        pf.verdict = "needs_commit"
        pf.stash_required = False
        pf.safe_to_rebase = False
        pf.recommendation = (
            "binary files modified — commit first, then rebase; "
            "stash may lose binary context"
        )
        return pf

    # regular text changes — stash is safe
    pf.verdict = "needs_stash"
    pf.stash_required = True
    pf.safe_to_rebase = False
    pf.recommendation = (
        "stash changes first, then pull --rebase, then stash pop"
    )
    return pf


def safe_pull_rebase_push(
    repo_path: str,
    remote: str = "origin",
    branch: str = "main",
    dry_run: bool = False,
) -> dict:
    """orchestrate a safe push cycle: preflight → stash → pull → pop → push.

    if dry_run is true, returns the plan without executing it.
    returns a dict with keys: plan (list[str]), executed (bool), result (str).
    """
    pf = check_rebase_safety(repo_path)
    plan = []

    if pf.blocked:
        plan.append("BLOCKED: " + pf.recommendation)
        return {"plan": plan, "executed": False, "result": "blocked"}

    if pf.stash_required:
        plan.append("git stash")
    plan.append(f"git pull --rebase {remote} {branch}")
    if pf.stash_required:
        plan.append("git stash pop")
    plan.append(f"git push {remote} {branch}")

    if dry_run:
        return {"plan": plan, "executed": False, "result": "dry_run"}

    # execute the plan
    for step in plan:
        parts = step.split()
        r = _run_git(repo_path, *parts[1:]) if parts[0] == "git" else None
        if r and r.returncode != 0:
            return {
                "plan": plan,
                "executed": True,
                "result": f"failed at step: {step}",
                "error": r.stderr.strip(),
            }

    return {"plan": plan, "executed": True, "result": "success"}
