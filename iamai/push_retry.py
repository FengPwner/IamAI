"""Push retry — automatic pull-rebase-push with exponential backoff.

The push race is the most frequent failure mode in this repo:
multiple writers (qwen, doubao, guoban, workbuddy) and caretakers
all accumulate local commits, then the batch committer tries to push.
If anyone else pushed first, the push is rejected.

This module provides a single entry point that:

1. Attempts ``git push``.
2. On rejection (non-fast-forward), runs ``git pull --rebase``.
3. Retries the push, up to *max_retries* times.
4. Uses exponential backoff between retries to avoid hammering
   the remote when multiple agents restart simultaneously.

Usage::

    from iamai.push_retry import push_with_retry

    ok, msg = push_with_retry("/path/to/IamAI", max_retries=3)
    if not ok:
        # handle permanent failure

Design choices:
- Subprocess over GitPython: keeps the dependency footprint minimal.
- Stash-restore around rebase: if the working tree is dirty, we stash
  before rebasing and restore after. Stash failures abort the retry
  loop rather than risk losing work.
- Backoff is configurable: default 2/4/8 seconds, but callers running
  in tight CI loops can pass shorter intervals.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Tuple


def _git(
    repo: str | Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a git command in the given repository directory."""
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True,
        text=True,
        check=check,
    )


def _is_dirty(repo: str | Path) -> bool:
    r = _git(repo, "status", "--porcelain", check=False)
    return bool(r.stdout.strip())


def _stash(repo: str | Path) -> bool:
    """Stash uncommitted changes. Returns True on success."""
    r = _git(repo, "stash", "push", "-m", "push-retry: auto-stash", check=False)
    return r.returncode == 0


def _stash_pop(repo: str | Path) -> bool:
    """Pop the most recent stash. Returns True on success."""
    r = _git(repo, "stash", "pop", check=False)
    return r.returncode == 0


def _pull_rebase(repo: str | Path) -> Tuple[bool, str]:
    """Pull with rebase. Returns (success, message)."""
    r = _git(repo, "pull", "--rebase", "origin", "main", check=False)
    if r.returncode == 0:
        return True, r.stdout.strip() or "rebase succeeded"
    return False, r.stderr.strip() or r.stdout.strip() or "rebase failed"


def _push(repo: str | Path, branch: str = "main") -> Tuple[bool, str]:
    """Attempt a push. Returns (success, message)."""
    r = _git(repo, "push", "origin", branch, check=False)
    if r.returncode == 0:
        return True, r.stdout.strip() or "push succeeded"
    stderr = r.stderr.strip()
    # Detect non-fast-forward specifically
    if "rejected" in stderr and "fetch first" in stderr:
        return False, "non-fast-forward: remote has diverged"
    return False, stderr or "push failed"


def push_with_retry(
    repo: str | Path,
    branch: str = "main",
    max_retries: int = 3,
    base_delay: float = 2.0,
    sleep_fn=None,
) -> Tuple[bool, str]:
    """Push with automatic pull-rebase retry on rejection.

    Parameters
    ----------
    repo : path-like
        Path to the git repository.
    branch : str
        Branch to push (default 'main').
    max_retries : int
        Maximum number of retry attempts after initial failure.
    base_delay : float
        Base delay in seconds; doubles each retry (2, 4, 8, ...).
    sleep_fn : callable, optional
        Override ``time.sleep`` for testing.

    Returns
    -------
    (ok, message) : tuple of (bool, str)
    """
    _sleep = sleep_fn or time.sleep

    # First attempt
    ok, msg = _push(repo, branch)
    if ok:
        return True, msg

    attempts = 0
    delay = base_delay

    while attempts < max_retries:
        attempts += 1

        # If dirty, stash before rebase
        dirty = _is_dirty(repo)
        stashed = False
        if dirty:
            stashed = _stash(repo)
            if not stashed:
                return False, f"stash failed before rebase (attempt {attempts})"

        # Pull --rebase
        rebase_ok, rebase_msg = _pull_rebase(repo)

        # Restore stash if we made one
        if stashed:
            pop_ok = _stash_pop(repo)
            if not pop_ok:
                return False, (
                    f"stash pop failed after rebase (attempt {attempts}) — "
                    f"stashed changes are in stash@{{0}}"
                )

        if not rebase_ok:
            return False, f"rebase failed on attempt {attempts}: {rebase_msg}"

        # Retry push
        ok, msg = _push(repo, branch)
        if ok:
            return True, f"{msg} (after {attempts} rebase-retry)"

        # Backoff before next attempt
        if attempts < max_retries:
            _sleep(delay)
            delay *= 2

    return False, f"push failed after {max_retries} retries: {msg}"
