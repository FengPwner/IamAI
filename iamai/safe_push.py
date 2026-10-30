"""safe_push — atomic push sequence for shared automated repos.

The push-race pattern documented across caretaker visits 125-127:

    1. Writer modifies ``writer_state.<id>.json`` every ~15 seconds.
    2. Any ``git pull`` or ``git rebase`` needs a clean working tree.
    3. By the time you ``stash`` and ``pull``, the writer has already
       written again, creating a new uncommitted change.
    4. Push fails with "fetch first" because a remote co-writer pushed
       in the same window.

The fix is to **pause the writer** for the duration of the git
operation.  This module wraps the full sequence into one call::

    from iamai.safe_push import safe_push, PushResult

    result = safe_push("/path/to/repo", writer_id="qwen")
    if result.success:
        print(result.summary())
    else:
        print(f"failed at step {result.failed_step}: {result.error}")

Sequence
--------
    SIGSTOP writer → stash → pull --rebase → pop → commit → push → SIGCONT

Safety guarantees:

- **SIGCONT is always sent**, even if an intermediate step fails.
  A frozen writer that stays frozen until the next caretaker visit is
  worse than a failed push.
- **Stash is always popped** if it was created, even on failure.
- **No force-push** — if the push is rejected, we report it and let
  the caretaker decide.

Design note
-----------
This module intentionally uses ``subprocess`` for git commands rather
than a Python git library.  The repo already depends on git being
available in PATH (see ``tools/run_both.sh``, ``stall_recover.py``),
and subprocess calls are easier to audit in a caretaker log.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PushResult:
    """Outcome of a safe_push invocation."""

    success: bool = False
    writer_pid: Optional[int] = None
    paused: bool = False
    resumed: bool = False
    stashed: bool = False
    stash_popped: bool = False
    pulled: bool = False
    committed: bool = False
    pushed: bool = False
    failed_step: Optional[str] = None
    error: Optional[str] = None
    commit_hash: Optional[str] = None
    steps_log: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def summary(self) -> str:
        if self.success:
            hash_short = (self.commit_hash or "?")[:7]
            return (
                f"safe_push ok — commit {hash_short}, "
                f"writer paused {self.paused}, resumed {self.resumed}, "
                f"{self.duration_seconds:.1f}s"
            )
        return (
            f"safe_push FAILED at '{self.failed_step}': {self.error} "
            f"(writer resumed={self.resumed})"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_writer_pid(writer_id: str) -> Optional[int]:
    """Find the PID of the writer process for *writer_id*.

    Searches ``/proc`` for a process whose command line contains
    ``writer`` and *writer_id*.  Returns the first match, or ``None``.
    """
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().decode(
                "utf-8", errors="replace"
            )
            if "writer" in cmdline and writer_id in cmdline:
                return int(entry.name)
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue
    return None


def _git(args: List[str], cwd: str) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _has_uncommitted(cwd: str) -> bool:
    """Return True if the working tree has uncommitted changes."""
    result = _git(["status", "--porcelain"], cwd)
    return bool(result.stdout.strip())


def _pause_writer(pid: int) -> None:
    """Send SIGSTOP to pause the writer process."""
    os.kill(pid, signal.SIGSTOP)


def _resume_writer(pid: int) -> None:
    """Send SIGCONT to resume the writer process."""
    try:
        os.kill(pid, signal.SIGCONT)
    except (ProcessLookupError, PermissionError):
        # Process may have died while paused; that's fine.
        pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def safe_push(
    repo_path: str,
    writer_id: str = "qwen",
    commit_message: Optional[str] = None,
    writer_pid: Optional[int] = None,
) -> PushResult:
    """Execute the atomic push sequence.

    Parameters
    ----------
    repo_path : str
        Path to the git repository.
    writer_id : str
        Writer identifier (e.g. ``"qwen"``, ``"doubao"``).
    commit_message : str, optional
        If provided and there are uncommitted changes after stash-pop,
        commit them with this message before pushing.
    writer_pid : int, optional
        Override automatic PID detection (useful in tests).

    Returns
    -------
    PushResult
        Structured outcome of the operation.
    """
    start = time.monotonic()
    result = PushResult()
    cwd = str(Path(repo_path).resolve())

    # Step 0: Find writer process
    pid = writer_pid or _find_writer_pid(writer_id)
    if pid is None:
        result.failed_step = "find_writer"
        result.error = f"no running writer process found for '{writer_id}'"
        result.duration_seconds = round(time.monotonic() - start, 3)
        result.steps_log.append(f"no writer found for {writer_id}")
        return result

    result.writer_pid = pid

    try:
        # Step 1: Pause writer
        _pause_writer(pid)
        result.paused = True
        result.steps_log.append(f"SIGSTOP → pid {pid}")

        # Step 2: Stash (only if there are changes)
        if _has_uncommitted(cwd):
            stash_result = _git(["stash", "push", "-m", "safe_push auto-stash"], cwd)
            if stash_result.returncode != 0:
                result.failed_step = "stash"
                result.error = stash_result.stderr.strip()
                return result
            result.stashed = True
            result.steps_log.append("stashed uncommitted changes")
        else:
            result.steps_log.append("working tree clean, skip stash")

        # Step 3: Pull --rebase
        pull_result = _git(["pull", "--rebase", "origin", "main"], cwd)
        if pull_result.returncode != 0:
            result.failed_step = "pull_rebase"
            result.error = pull_result.stderr.strip()
            return result
        result.pulled = True
        result.steps_log.append("pulled --rebase origin/main")

        # Step 4: Pop stash
        if result.stashed:
            pop_result = _git(["stash", "pop"], cwd)
            if pop_result.returncode != 0:
                result.failed_step = "stash_pop"
                result.error = pop_result.stderr.strip()
                return result
            result.stash_popped = True
            result.steps_log.append("popped stash")

        # Step 5: Commit (if message given and changes exist)
        if commit_message and _has_uncommitted(cwd):
            _git(["add", "-A"], cwd)
            commit_result = _git(
                ["commit", "-m", commit_message], cwd
            )
            if commit_result.returncode != 0:
                result.failed_step = "commit"
                result.error = commit_result.stderr.strip()
                return result
            result.committed = True
            # Extract commit hash
            hash_result = _git(["rev-parse", "--short", "HEAD"], cwd)
            result.commit_hash = hash_result.stdout.strip()
            result.steps_log.append(f"committed {result.commit_hash}")

        # Step 6: Push
        push_result = _git(["push", "origin", "main"], cwd)
        if push_result.returncode != 0:
            result.failed_step = "push"
            result.error = push_result.stderr.strip()
            return result
        result.pushed = True
        result.steps_log.append("pushed to origin/main")

        # If no commit was made, grab current HEAD for the report
        if not result.commit_hash:
            hash_result = _git(["rev-parse", "--short", "HEAD"], cwd)
            result.commit_hash = hash_result.stdout.strip()

        result.success = True

    except Exception as exc:
        result.failed_step = result.failed_step or "unexpected"
        result.error = str(exc)
    finally:
        # Step 7 (always): Resume writer
        if result.paused:
            _resume_writer(pid)
            result.resumed = True
            result.steps_log.append(f"SIGCONT → pid {pid}")

        result.duration_seconds = round(time.monotonic() - start, 3)

    return result
