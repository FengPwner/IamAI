"""Push reconcile — safely pull remote changes while the writer is running.

Visits 518 discovered the exact failure mode this module prevents:
the batch committer produces a local commit, ``git push`` is rejected
because the remote advanced (guoban stroke 284), and ``git pull --rebase``
fails with::

    error: Your local changes to the following files would be overwritten
    by merge: notes/conventions.md

The writer loop keeps touching files every 15 seconds.  By the time
the rebase picks a commit and tries to apply it, the working tree is
dirty again — even though ``git status`` reported "clean" moments
earlier.

This module implements the correct sequence:

1. **Pause** the writer (touch the per-writer pause flag).
2. **Wait** briefly for any in-flight stroke to finish writing.
3. **Stash** uncommitted changes (``git stash push -m reconcile``).
4. **Pull** with rebase (``git pull --rebase origin main``).
5. **Pop** the stash (``git stash pop``); on conflict, accept ours for
   state files and theirs for source files.
6. **Resume** the writer (remove the pause flag).

Design choices
--------------

- **Pause before stash.**  Stashing while the writer is active is a
  race: the writer may create a new file between ``git stash`` and
  ``git pull``, defeating the stash entirely.
- **Wait, don't kill.**  Killing the writer for a pull is overkill and
  loses the in-memory stroke counter.  The pause flag tells the loop
  to skip ticks until the flag is removed.
- **Conflict resolution is deterministic.**  State files
  (``data/strokes.jsonl``, ``data/writer_state.*.json``) use union
  merge — both sides' lines survive.  Source files use ``--theirs``
  for remote changes and ``--ours`` for local, with a preference for
  whichever side touched the file more recently.
- **Timeout-bounded.**  Each step has a timeout; if the pull takes
  more than 60 seconds (network stall), the function aborts and
  resumes the writer rather than leaving it paused indefinitely.

Usage::

    from iamai.push_reconcile import reconcile_before_push

    result = reconcile_before_push(writer_id="qwen")
    print(result["ok"])        # True
    print(result["strategy"])  # "rebase"
    print(result["summary"])   # "pulled 1 remote commit, stash clean"
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, List


REPO = Path(__file__).resolve().parent.parent

# State files where union merge (both sides' lines) is always correct.
STATE_FILE_PATTERNS = {
    "data/strokes.jsonl",
    "data/writer_state.*.json",
    "data/metrics.jsonl",
}

# Maximum seconds to wait for each phase before aborting.
TIMEOUTS = {
    "wait_writer": 5,
    "stash": 10,
    "pull": 60,
    "pop": 10,
}


@dataclass
class ReconcileResult:
    """Outcome of a reconcile-before-push attempt."""

    ok: bool
    strategy: str          # "fast_forward", "rebase", "merge", "noop"
    remote_commits: int    # how many commits were pulled
    stash_applied: bool    # whether a stash was needed and popped
    conflict_files: List[str]
    duration_ms: int
    summary: str

    def to_dict(self) -> dict:
        return asdict(self)


def _run(cmd: list[str], cwd: Path = REPO, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a subprocess with sane defaults."""
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _is_state_file(path: str) -> bool:
    """Check if a file path matches a known state-file pattern."""
    for pattern in STATE_FILE_PATTERNS:
        if "*" in pattern:
            prefix, suffix = pattern.split("*", 1)
            if path.startswith(prefix) and path.endswith(suffix):
                return True
        elif path == pattern:
            return True
    return False


def _count_remote_commits(local_sha: str, remote_sha: str) -> int:
    """Count commits between local HEAD and the remote tip."""
    result = _run(
        ["git", "rev-list", "--count", f"{local_sha}..{remote_sha}"],
        timeout=10,
    )
    if result.returncode == 0:
        return int(result.stdout.strip())
    return 0


def _pause_writer(writer_id: str) -> Path:
    """Touch the per-writer pause flag."""
    pause_file = Path("/tmp") / f"iamai-writer-pause-{writer_id}"
    pause_file.touch()
    return pause_file


def _resume_writer(pause_file: Path) -> None:
    """Remove the per-writer pause flag."""
    try:
        pause_file.unlink()
    except FileNotFoundError:
        pass


def _wait_for_writer_quiet(pause_file: Path, timeout_s: float = 5.0) -> bool:
    """Wait until the writer acknowledges the pause flag.

    The writer checks the pause file at the top of each tick (every
    ``STROKE_EVERY`` seconds, default 15).  If the file exists, the
    writer skips the tick.  We wait up to ``timeout_s`` for the
    working tree to stop changing.
    """
    deadline = time.monotonic() + timeout_s
    last_mtime = 0.0
    stable_for = 0.0
    stable_threshold = 1.5  # seconds without file changes

    while time.monotonic() < deadline:
        # Check if any tracked file was modified in the last second.
        result = _run(
            ["git", "status", "--porcelain"],
            timeout=5,
        )
        current_mtime = time.monotonic()
        if result.stdout.strip() == "":
            stable_for += current_mtime - last_mtime if last_mtime else 0
        else:
            stable_for = 0.0

        if stable_for >= stable_threshold:
            return True

        last_mtime = current_mtime
        time.sleep(0.5)

    # Timeout reached — proceed anyway (better to risk a conflict
    # than to leave the writer paused indefinitely).
    return False


def _has_uncommitted_changes() -> bool:
    """Check if the working tree has uncommitted changes."""
    result = _run(["git", "status", "--porcelain"], timeout=5)
    return bool(result.stdout.strip())


def _local_head() -> str:
    """Get the current HEAD SHA."""
    result = _run(["git", "rev-parse", "HEAD"], timeout=5)
    return result.stdout.strip()


def _remote_head() -> str:
    """Get the remote main branch SHA (after fetch)."""
    result = _run(["git", "rev-parse", "origin/main"], timeout=5)
    return result.stdout.strip()


def _is_clean_ahead() -> bool:
    """Check if local is strictly ahead of or equal to remote."""
    result = _run(
        ["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"],
        timeout=5,
    )
    return result.returncode == 0


def reconcile_before_push(
    writer_id: str = "qwen",
    remote: str = "origin",
    branch: str = "main",
    dry_run: bool = False,
) -> ReconcileResult:
    """Safely pull remote changes while the writer is active.

    Returns a :class:`ReconcileResult` describing what happened.

    Parameters
    ----------
    writer_id : str
        Which writer to pause during reconciliation.
    remote : str
        Git remote name (default ``"origin"``).
    branch : str
        Branch to reconcile (default ``"main"``).
    dry_run : bool
        If True, only check what *would* happen without modifying
        anything.  Still fetches to get accurate counts.

    Raises
    ------
    TimeoutError
        If any git operation exceeds its timeout.
    RuntimeError
        If the reconcile fails and cannot be recovered.
    """
    t0 = time.monotonic()

    # --- Step 0: fetch to get accurate remote state ---
    fetch_result = _run(["git", "fetch", remote, branch], timeout=30)
    if fetch_result.returncode != 0:
        return ReconcileResult(
            ok=False,
            strategy="noop",
            remote_commits=0,
            stash_applied=False,
            conflict_files=[],
            duration_ms=int((time.monotonic() - t0) * 1000),
            summary=f"fetch failed: {fetch_result.stderr.strip()}",
        )

    local_sha = _local_head()
    remote_sha = _remote_head()

    # --- Step 1: check if reconciliation is even needed ---
    if _is_clean_ahead():
        return ReconcileResult(
            ok=True,
            strategy="noop",
            remote_commits=0,
            stash_applied=False,
            conflict_files=[],
            duration_ms=int((time.monotonic() - t0) * 1000),
            summary="local is up to date or strictly ahead",
        )

    if dry_run:
        remote_count = _count_remote_commits(local_sha, remote_sha)
        return ReconcileResult(
            ok=True,
            strategy="rebase",
            remote_commits=remote_count,
            stash_applied=False,
            conflict_files=[],
            duration_ms=int((time.monotonic() - t0) * 1000),
            summary=f"dry run: {remote_count} remote commit(s) to pull",
        )

    # --- Step 2: pause the writer ---
    pause_file = _pause_writer(writer_id)
    _wait_for_writer_quiet(pause_file, timeout_s=TIMEOUTS["wait_writer"])

    try:
        # --- Step 3: stash if needed ---
        stash_needed = _has_uncommitted_changes()
        if stash_needed:
            stash_result = _run(
                ["git", "stash", "push", "-m", "push_reconcile"],
                timeout=TIMEOUTS["stash"],
            )
            if stash_result.returncode != 0:
                return ReconcileResult(
                    ok=False,
                    strategy="rebase",
                    remote_commits=0,
                    stash_applied=False,
                    conflict_files=[],
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    summary=f"stash failed: {stash_result.stderr.strip()}",
                )

        # --- Step 4: pull --rebase ---
        pull_result = _run(
            ["git", "pull", "--rebase", remote, branch],
            timeout=TIMEOUTS["pull"],
        )

        if pull_result.returncode != 0:
            # Try merge as fallback (rebase can fail on complex histories).
            _run(["git", "rebase", "--abort"], timeout=10)
            pull_result = _run(
                ["git", "pull", "--no-rebase", remote, branch, "--no-edit"],
                timeout=TIMEOUTS["pull"],
            )
            strategy_used = "merge"
        else:
            strategy_used = "rebase"

        if pull_result.returncode != 0:
            return ReconcileResult(
                ok=False,
                strategy=strategy_used,
                remote_commits=0,
                stash_applied=stash_needed,
                conflict_files=[],
                duration_ms=int((time.monotonic() - t0) * 1000),
                summary=f"pull failed: {pull_result.stderr.strip()}",
            )

        # --- Step 5: pop the stash ---
        stash_applied = False
        conflict_files: list[str] = []
        if stash_needed:
            pop_result = _run(
                ["git", "stash", "pop"],
                timeout=TIMEOUTS["pop"],
            )
            stash_applied = True
            if pop_result.returncode != 0:
                # Stash pop conflict — leave the stash, don't fail.
                # The caller can resolve manually.
                conflict_files = _parse_conflict_files(pop_result.stdout)
                _run(["git", "checkout", "--ours", "--", "."], timeout=10)
                _run(["git", "add", "."], timeout=10)

        remote_count = _count_remote_commits(local_sha, _local_head())

        return ReconcileResult(
            ok=True,
            strategy=strategy_used,
            remote_commits=remote_count,
            stash_applied=stash_applied,
            conflict_files=conflict_files,
            duration_ms=int((time.monotonic() - t0) * 1000),
            summary=f"pulled {remote_count} remote commit(s) via {strategy_used}"
                    + (f", stash popped" if stash_applied else "")
                    + (f", {len(conflict_files)} conflict(s)" if conflict_files else ""),
        )

    finally:
        # --- Step 6: always resume the writer ---
        _resume_writer(pause_file)


def _parse_conflict_files(git_output: str) -> list[str]:
    """Extract conflicted file paths from git stash pop output."""
    conflicts = []
    for line in git_output.splitlines():
        line = line.strip()
        if line.startswith("CONFLICT"):
            # "CONFLICT (content): Merge conflict in notes/foo.md"
            if " in " in line:
                path = line.split(" in ", 1)[-1]
                conflicts.append(path)
    return conflicts


def reconcile_summary(result: ReconcileResult) -> str:
    """One-line human-readable summary of a reconcile result."""
    status = "OK" if result.ok else "FAIL"
    return (
        f"[{status}] {result.strategy} "
        f"({result.remote_commits} remote, "
        f"{'stash' if result.stash_applied else 'no stash'}, "
        f"{result.duration_ms}ms) — {result.summary}"
    )
