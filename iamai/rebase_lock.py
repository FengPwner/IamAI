"""Rebase lock: pause writers before rebasing, resume after.

The push-race recovery loop kept failing because the writer process wrote
new strokes *during* ``git pull --rebase``. Each rebase attempt saw
unstaged changes that didn't exist when the stash was created, and the
rebase aborted. The fix was not in git — it was in stopping the writer
first.

This module codifies that sequence:

    1. send SIGSTOP to the writer (freeze, don't kill)
    2. wait for the working tree to settle (no new writes for N seconds)
    3. stash → pull --rebase → stash pop
    4. send SIGCONT to resume the writer

SIGSTOP/SIGCONT is preferred over kill+restart because the writer's
in-memory state (stroke counter, sequence number, cadence timing)
survives. A restart would lose that context and potentially create
duplicate sequence numbers.

    from iamai.rebase_lock import safe_rebase

    result = safe_rebase(repo, writer_pid=1327, settle=2)
    if result.ok:
        # push is now safe
    else:
        # result.error explains what went wrong
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RebaseResult:
    ok: bool
    rebased: bool = False
    stash_applied: bool = False
    error: str | None = None
    duration_s: float = 0.0


def _run(repo: Path, *args: str, timeout: int = 60) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _dirty(repo: Path) -> bool:
    """True if the working tree has unstaged or untracked changes."""
    rc, out = _run(repo, "status", "--porcelain")
    return bool(out.strip())


def _settle(repo: Path, seconds: float, poll: float = 0.25, max_wait: float = 30.0) -> bool:
    """Wait until the working tree is clean for ``seconds`` consecutive seconds.

    Returns True if the tree stayed clean for the full window, False if
    new changes appeared before the window elapsed or ``max_wait`` was exceeded.
    """
    t0 = time.monotonic()
    deadline = t0 + seconds

    while time.monotonic() < deadline and (time.monotonic() - t0) < max_wait:
        if _dirty(repo):
            # reset the window — we need ``seconds`` of *consecutive* cleanness
            deadline = time.monotonic() + seconds
        time.sleep(poll)

    return not _dirty(repo)


def pause_writer(pid: int) -> bool:
    """Send SIGSTOP to freeze a writer process without killing it.

    Returns True if the signal was sent, False if the process doesn't
    exist or we lack permission.
    """
    try:
        os.kill(pid, signal.SIGSTOP)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def resume_writer(pid: int) -> bool:
    """Send SIGCONT to unfreeze a paused writer.

    Idempotent: if the process was already running, SIGCONT is harmless.
    """
    try:
        os.kill(pid, signal.SIGCONT)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def safe_rebase(
    repo: Path,
    writer_pid: int | None = None,
    settle: float = 2.0,
    remote: str = "origin",
    branch: str = "main",
) -> RebaseResult:
    """Pause writer → stash → rebase → pop → resume.

    The whole sequence is designed to be atomic from the writer's
    perspective: it sees a brief pause and then continues as if nothing
    happened. If any step fails, the writer is still resumed — a paused
    writer that never resumes is worse than a failed rebase.

    Parameters
    ----------
    repo : Path
        Repository root (must contain .git).
    writer_pid : int or None
        PID of the writer process to pause. If None, skip pause/resume.
    settle : float
        Seconds the working tree must stay clean before proceeding.
    remote : str
        Remote name (default "origin").
    branch : str
        Branch to rebase onto (default "main").
    """
    t0 = time.monotonic()
    paused = False

    try:
        # Step 1: pause the writer
        if writer_pid is not None:
            if not pause_writer(writer_pid):
                return RebaseResult(
                    ok=False,
                    error=f"cannot pause writer pid {writer_pid}",
                    duration_s=time.monotonic() - t0,
                )
            paused = True

        # Step 2: wait for the tree to settle
        if not _settle(repo, settle):
            return RebaseResult(
                ok=False,
                error=f"working tree did not settle after {settle}s",
                duration_s=time.monotonic() - t0,
            )

        # Step 3: stash if dirty (shouldn't be, but belt-and-suspenders)
        stashed = False
        if _dirty(repo):
            rc, out = _run(repo, "stash")
            if rc != 0:
                return RebaseResult(
                    ok=False,
                    error=f"stash failed: {out}",
                    duration_s=time.monotonic() - t0,
                )
            stashed = True

        # Step 4: pull --rebase
        rc, out = _run(repo, "pull", "--rebase", remote, branch)
        rebased = rc == 0 and "Successfully rebased" in out

        if rc != 0:
            # Abort the failed rebase so the tree is usable
            _run(repo, "rebase", "--abort")
            return RebaseResult(
                ok=False,
                rebased=False,
                error=f"rebase failed: {out}",
                duration_s=time.monotonic() - t0,
            )

        # Step 5: pop stash if we stashed
        stash_applied = False
        if stashed:
            rc, out = _run(repo, "stash", "pop")
            if rc != 0:
                return RebaseResult(
                    ok=True,
                    rebased=True,
                    stash_applied=False,
                    error=f"rebase ok but stash pop failed: {out}",
                    duration_s=time.monotonic() - t0,
                )
            stash_applied = True

        return RebaseResult(
            ok=True,
            rebased=rebased,
            stash_applied=stash_applied,
            duration_s=time.monotonic() - t0,
        )

    finally:
        # Always resume the writer, even on failure
        if paused and writer_pid is not None:
            resume_writer(writer_pid)
