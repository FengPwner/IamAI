"""caretaker_push_cycle — one function to survive a diverged push.

Motivation
----------

Visits 441-456 all repeat the same dance:

1. Arrive to find the writer producing local commits.
2. Try ``git push`` — rejected (remote has work local lacks).
3. Try ``git pull --rebase`` — rejected (writer is still dirtying the tree).
4. Pause or kill the writer.
5. Stash unstaged changes.
6. Pull --rebase.
7. Pop the stash.
8. Commit whatever the writer produced while we were gone.
9. Push.
10. Resume the writer.

Ten steps, every time, with variations (binary files, lock files,
merge conflicts, stash pop failures).  This module encodes the happy
path and the common failure modes so that future caretakers — human or
agent — can call ``run_push_cycle()`` and move on.

Public API
----------

.. code-block:: python

    from iamai.caretaker_push_cycle import run_push_cycle, PushCycleResult

    result = run_push_cycle(
        repo_path="/path/to/repo",
        remote="origin",
        branch="main",
        pause_file="/tmp/iamai-writer-pause-qwen",
    )

    print(result.success)        # True / False
    print(result.steps_taken)    # ["pause_writer", "stash", ...]
    print(result.error)          # None or the failing step's stderr

Dry-run mode returns the plan without executing::

    result = run_push_cycle(repo_path="...", dry_run=True)

Design notes
------------

- The pause file is *touched* (not a signal) because the writer loop
  checks ``Path.exists()`` every tick.  This is the cheapest IPC there is.
- Stash is skipped when the tree is clean (no point creating an empty stash).
- If ``stash pop`` conflicts, the stash is preserved and the error is
  surfaced — the caretaker can resolve manually.
- The writer is resumed in a ``finally`` block so it never stays paused
  because of a crash in this code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import subprocess
import time


@dataclass
class PushCycleResult:
    """Outcome of a single push cycle attempt."""

    success: bool = False
    steps_taken: List[str] = field(default_factory=list)
    error: Optional[str] = None
    divergence_detected: bool = False
    stash_used: bool = False
    commits_pushed: int = 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "steps_taken": self.steps_taken,
            "error": self.error,
            "divergence_detected": self.divergence_detected,
            "stash_used": self.stash_used,
            "commits_pushed": self.commits_pushed,
        }


def _git(repo_path: str, *args: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    """Run a git command in *repo_path*, return CompletedProcess."""
    import os

    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        ["git", "-C", repo_path] + list(args),
        capture_output=True,
        text=True,
        timeout=30,
        env=run_env,
    )


def _has_unstaged(repo_path: str) -> bool:
    """True if the working tree has modified or untracked files."""
    r = _git(repo_path, "status", "--porcelain")
    return bool(r.stdout.strip())


def _has_unpushed(repo_path: str, remote: str, branch: str) -> int:
    """Return count of local commits not yet on remote."""
    r = _git(repo_path, "rev-list", "--count", f"{remote}/{branch}..HEAD")
    try:
        return int(r.stdout.strip())
    except (ValueError, AttributeError):
        return 0


def _is_diverged(repo_path: str, remote: str, branch: str) -> bool:
    """True if local and remote have diverged (both have unique commits)."""
    r = _git(repo_path, "rev-list", "--left-right", "--count",
             f"HEAD...{remote}/{branch}")
    if r.returncode != 0:
        return False
    parts = r.stdout.strip().split()
    if len(parts) == 2:
        local_only, remote_only = int(parts[0]), int(parts[1])
        return local_only > 0 and remote_only > 0
    return False


def _pause_writer(pause_file: str) -> None:
    """Touch the pause gate so the writer loop stops producing strokes."""
    Path(pause_file).touch()
    time.sleep(1.5)  # give the writer one tick to notice


def _resume_writer(pause_file: str) -> None:
    """Remove the pause gate so the writer loop resumes."""
    try:
        Path(pause_file).unlink()
    except FileNotFoundError:
        pass


def run_push_cycle(
    repo_path: str,
    remote: str = "origin",
    branch: str = "main",
    pause_file: str = "/tmp/iamai-writer-pause-qwen",
    ssh_command: Optional[str] = None,
    dry_run: bool = False,
    commit_message: Optional[str] = None,
) -> PushCycleResult:
    """Execute the full pause → stash → rebase → pop → commit → push → resume cycle.

    Parameters
    ----------
    repo_path : str
        Absolute path to the git repository.
    remote : str
        Remote name (default ``"origin"``).
    branch : str
        Branch name (default ``"main"``).
    pause_file : str
        Path to the writer pause gate file.
    ssh_command : str or None
        Value for ``GIT_SSH_COMMAND`` env var (for deploy keys).
    dry_run : bool
        If true, return the plan without executing.
    commit_message : str or None
        If provided, commit any staged changes with this message before pushing.

    Returns
    -------
    PushCycleResult
    """
    result = PushCycleResult()
    env = {}
    if ssh_command:
        env["GIT_SSH_COMMAND"] = ssh_command

    # -- build plan --
    plan: list[str] = []

    # Step 1: fetch to learn the remote state
    plan.append("fetch")

    # Step 2: check divergence
    plan.append("check_divergence")

    # Step 3: pause writer if there are unstaged changes
    plan.append("pause_writer")

    # Step 4: stash if dirty
    plan.append("stash_if_dirty")

    # Step 5: pull --rebase
    plan.append("pull_rebase")

    # Step 6: pop stash if we stashed
    plan.append("pop_stash_if_needed")

    # Step 7: commit if message given and there are changes
    if commit_message:
        plan.append("commit_pending")

    # Step 8: push
    plan.append("push")

    # Step 9: resume writer (always, in finally)
    plan.append("resume_writer")

    if dry_run:
        result.steps_taken = plan
        result.success = True
        return result

    # -- execute plan --
    try:
        # fetch
        result.steps_taken.append("fetch")
        r = _git(repo_path, "fetch", remote, branch, env=env)
        if r.returncode != 0:
            result.error = f"fetch failed: {r.stderr.strip()}"
            return result

        # check divergence
        result.steps_taken.append("check_divergence")
        diverged = _is_diverged(repo_path, remote, branch)
        result.divergence_detected = diverged

        # pause writer
        result.steps_taken.append("pause_writer")
        _pause_writer(pause_file)

        # stash if dirty
        result.steps_taken.append("stash_if_dirty")
        dirty = _has_unstaged(repo_path)
        if dirty:
            r = _git(repo_path, "stash", env=env)
            if r.returncode != 0:
                result.error = f"stash failed: {r.stderr.strip()}"
                return result
            result.stash_used = True

        # pull --rebase
        result.steps_taken.append("pull_rebase")
        r = _git(repo_path, "pull", "--rebase", remote, branch, env=env)
        if r.returncode != 0:
            result.error = f"pull --rebase failed: {r.stderr.strip()}"
            return result

        # pop stash
        result.steps_taken.append("pop_stash_if_needed")
        if result.stash_used:
            r = _git(repo_path, "stash", "pop", env=env)
            if r.returncode != 0:
                result.error = f"stash pop failed (conflict?): {r.stderr.strip()}"
                return result

        # commit pending
        if commit_message:
            result.steps_taken.append("commit_pending")
            if _has_unstaged(repo_path):
                _git(repo_path, "add", "-A", env=env)
                r = _git(repo_path, "commit", "-m", commit_message, env=env)
                if r.returncode != 0:
                    result.error = f"commit failed: {r.stderr.strip()}"
                    return result

        # count unpushed before push
        unpushed = _has_unpushed(repo_path, remote, branch)

        # push
        result.steps_taken.append("push")
        r = _git(repo_path, "push", remote, branch, env=env)
        if r.returncode != 0:
            result.error = f"push failed: {r.stderr.strip()}"
            return result

        result.commits_pushed = unpushed
        result.success = True

    finally:
        # always resume the writer
        result.steps_taken.append("resume_writer")
        _resume_writer(pause_file)

    return result
