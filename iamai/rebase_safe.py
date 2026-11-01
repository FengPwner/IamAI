"""rebase_safe — stash-pause-rebase-push-resume for a live writer repo.

The writer loop touches files every ~15 s.  Trying to ``git pull
--rebase`` while the writer is active almost always fails with
"unstaged changes" or, worse, silently drops in-progress work.

This module provides a single entry-point that:

1. Pauses the writer (SIGSTOP) so it can't modify files mid-rebase.
2. Stashes any dirty working-tree state.
3. Fetches and rebases onto the remote branch.
4. Pushes the rebased history.
5. Pops the stash (if any).
6. Resumes the writer (SIGCONT).

Every step is wrapped in a ``RebaseResult`` dataclass so the caller
can inspect exactly what happened.

Public API
----------

``RebaseResult``
    Dataclass with fields: success (bool), writer_pid (int | None),
    stashed (bool), rebased (bool), pushed (bool), stash_popped (bool),
    reason (str).

``sync(repo_path, writer_pid=None, remote='origin', branch='main',
       dry_run=False) -> RebaseResult``
    Perform the full sequence.  If *writer_pid* is ``None`` the
    function tries to find it via ``_find_writer_pid``.

``find_writer_pid(writer='qwen') -> int | None``
    Look for the writer process by name pattern.  Returns ``None``
    when not running.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RebaseResult:
    """Outcome of a safe-rebase attempt."""
    success: bool
    writer_pid: Optional[int]
    stashed: bool
    rebased: bool
    pushed: bool
    stash_popped: bool
    reason: str


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: Optional[str] = None,
         env: Optional[dict] = None) -> subprocess.CompletedProcess:
    """Run a command, capture output."""
    merged = {**os.environ, **(env or {})}
    return subprocess.run(cmd, capture_output=True, text=True,
                          cwd=cwd, env=merged)


def find_writer_pid(writer: str = "qwen") -> Optional[int]:
    """Return the PID of the writer_loop.py process for *writer*.

    Uses ``pgrep`` so it works even when the caller doesn't know the
    exact PID.  Returns ``None`` if no matching process is found.
    """
    r = _run(["pgrep", "-f", f"writer_loop.py.*--writer.*{writer}"])
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return int(r.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def _is_dirty(repo: str) -> bool:
    """True when the working tree has uncommitted changes."""
    r = _run(["git", "status", "--porcelain"], cwd=repo)
    return bool(r.stdout.strip())


def _ahead_behind(repo: str, remote: str, branch: str):
    """Return (local_ahead, remote_ahead) counts."""
    r = _run(
        ["git", "rev-list", "--left-right", "--count",
         f"{branch}...{remote}/{branch}"],
        cwd=repo,
    )
    if r.returncode != 0:
        return 0, 0
    parts = r.stdout.strip().split()
    if len(parts) != 2:
        return 0, 0
    return int(parts[0]), int(parts[1])


# ---------------------------------------------------------------------------
# core
# ---------------------------------------------------------------------------

def sync(
    repo_path: str,
    writer_pid: Optional[int] = None,
    remote: str = "origin",
    branch: str = "main",
    dry_run: bool = False,
) -> RebaseResult:
    """Perform stash → rebase → push → resume.

    Parameters
    ----------
    repo_path : path to the git working tree.
    writer_pid : PID to pause/resume.  ``None`` means skip pause.
    remote : git remote name.
    branch : branch to sync.
    dry_run : if True, plan but do not execute.

    Returns
    -------
    RebaseResult describing every step taken.
    """
    stashed = False
    rebased = False
    pushed = False
    stash_popped = False

    # 0. discover writer when caller passes sentinel -1
    if writer_pid == -1:
        writer_pid = find_writer_pid()
    # writer_pid=None means "no writer to manage"

    # 1. fetch first so ahead/behind counts are fresh
    _run(["git", "fetch", remote, branch], cwd=repo_path)
    local_ahead, remote_ahead = _ahead_behind(repo_path, remote, branch)
    if remote_ahead == 0 and local_ahead == 0 and not _is_dirty(repo_path):
        return RebaseResult(
            success=True, writer_pid=writer_pid,
            stashed=False, rebased=False, pushed=False,
            stash_popped=False,
            reason="already in sync — nothing to do",
        )

    if dry_run:
        return RebaseResult(
            success=True, writer_pid=writer_pid,
            stashed=bool(_is_dirty(repo_path)),
            rebased=remote_ahead > 0,
            pushed=local_ahead > 0 or remote_ahead > 0,
            stash_popped=False,
            reason=f"dry-run: local +{local_ahead} remote +{remote_ahead}",
        )

    # 2. pause writer
    if writer_pid is not None:
        try:
            os.kill(writer_pid, signal.SIGSTOP)
        except ProcessLookupError:
            writer_pid = None  # already gone

    try:
        # 3. stash dirty tree (include untracked files)
        dirty = _is_dirty(repo_path)
        if dirty:
            r = _run(
                ["git", "stash", "push", "--include-untracked",
                 "-m", "rebase_safe: auto-stash"],
                cwd=repo_path,
            )
            if r.returncode != 0:
                return RebaseResult(
                    success=False, writer_pid=writer_pid,
                    stashed=False, rebased=False, pushed=False,
                    stash_popped=False,
                    reason=f"stash failed: {r.stderr.strip()}",
                )
            # only count as stashed if something was actually saved
            if "No local changes to save" not in r.stdout:
                stashed = True

        # 4. fetch + rebase
        r = _run(["git", "fetch", remote, branch], cwd=repo_path)
        if r.returncode != 0:
            return RebaseResult(
                success=False, writer_pid=writer_pid,
                stashed=stashed, rebased=False, pushed=False,
                stash_popped=False,
                reason=f"fetch failed: {r.stderr.strip()}",
            )

        if remote_ahead > 0 or _ahead_behind(repo_path, remote, branch)[1] > 0:
            r = _run(
                ["git", "pull", "--rebase", remote, branch],
                cwd=repo_path,
            )
            if r.returncode != 0:
                # try to abort the failed rebase
                _run(["git", "rebase", "--abort"], cwd=repo_path)
                return RebaseResult(
                    success=False, writer_pid=writer_pid,
                    stashed=stashed, rebased=False, pushed=False,
                    stash_popped=False,
                    reason=f"rebase failed: {r.stderr.strip()}",
                )
            rebased = True

        # 5. push
        r = _run(["git", "push", remote, branch], cwd=repo_path)
        if r.returncode != 0:
            return RebaseResult(
                success=False, writer_pid=writer_pid,
                stashed=stashed, rebased=rebased, pushed=False,
                stash_popped=False,
                reason=f"push failed: {r.stderr.strip()}",
            )
        pushed = True

    finally:
        # 6. pop stash
        if stashed:
            r = _run(["git", "stash", "pop"], cwd=repo_path)
            stash_popped = (r.returncode == 0)

        # 7. resume writer
        if writer_pid is not None:
            try:
                os.kill(writer_pid, signal.SIGCONT)
            except ProcessLookupError:
                pass

    return RebaseResult(
        success=pushed,
        writer_pid=writer_pid,
        stashed=stashed,
        rebased=rebased,
        pushed=pushed,
        stash_popped=stash_popped,
        reason="synced" if pushed else "completed without push",
    )
