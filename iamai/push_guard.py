"""push_guard — detect and resolve push divergence before it blocks.

When a long-running writer repo diverges from its remote (typically
because a remote agent pushed commits while the local process was
recycled), ``git push`` fails with ``[rejected] (fetch first)``.
The usual recovery is either:

1. **rebase** — when local commits carry unique work worth preserving.
2. **reset** — when local commits are just batch catch-ups of
   writer-generated strokes that the remote already has newer copies of.

This module automates the decision:

Public API
----------

``PushVerdict``
    Dataclass: strategy ('rebase' | 'reset' | 'clean' | 'conflict'),
    local_ahead (int), remote_ahead (int), reason (str).

``assess(repo_path, remote='origin', branch='main') -> PushVerdict``
    Fetch remote and compare.  Pure function, no side-effects beyond
    ``git fetch``.

``resolve(repo_path, remote='origin', branch='main', dry_run=False) -> PushVerdict``
    Assess, then execute the chosen strategy.  Returns the verdict.

Design choices
--------------

- ``assess`` only calls ``git fetch`` and ``git log``; safe to call
  repeatedly without mutating state.
- Strategy selection heuristic: if *all* local-only commits have
  messages matching the catch-up pattern (``^catch-up:``), prefer
  reset.  Otherwise rebase.
- Reset uses ``git reset --hard origin/<branch>`` — this is safe
  because catch-up commits only bundle writer state that the remote
  already supersedes.
- Rebase uses ``git rebase -X theirs origin/<branch>`` to prefer
  remote content on conflicts (the remote is the source of truth for
  shared files like conventions.md).
- ``dry_run=True`` returns the verdict without executing.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


CATCHUP_RE = re.compile(r"^catch-up:", re.IGNORECASE)


@dataclass(frozen=True)
class PushVerdict:
    """Result of a divergence assessment."""
    strategy: str          # 'clean' | 'rebase' | 'reset' | 'conflict'
    local_ahead: int       # commits local has that remote doesn't
    remote_ahead: int      # commits remote has that local doesn't
    reason: str            # human-readable explanation
    executed: bool = False # whether resolution was actually run


def _run(cmd: list[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


def _count_ahead(repo: str, from_ref: str, to_ref: str) -> int:
    """Count commits in from_ref that are not in to_ref."""
    r = _run(
        ["git", "rev-list", "--count", f"{to_ref}..{from_ref}"],
        cwd=repo,
    )
    if r.returncode != 0:
        return 0
    return int(r.stdout.strip())


def _local_commit_messages(repo: str, from_ref: str, to_ref: str) -> list[str]:
    """Return commit messages for commits in from_ref not in to_ref."""
    r = _run(
        ["git", "log", "--format=%s", f"{to_ref}..{from_ref}"],
        cwd=repo,
    )
    if r.returncode != 0:
        return []
    return [line.strip() for line in r.stdout.strip().splitlines() if line.strip()]


def assess(
    repo_path: str | Path,
    remote: str = "origin",
    branch: str = "main",
) -> PushVerdict:
    """Fetch remote and assess divergence.

    Pure assessment — only ``git fetch`` and ``git log`` are called.
    No state is mutated beyond the fetch itself.
    """
    repo = str(repo_path)
    remote_ref = f"{remote}/{branch}"

    # Fetch latest from remote
    fetch = _run(["git", "fetch", remote, branch], cwd=repo)
    if fetch.returncode != 0:
        return PushVerdict(
            strategy="conflict",
            local_ahead=0,
            remote_ahead=0,
            reason=f"fetch failed: {fetch.stderr.strip()}",
        )

    local_ahead = _count_ahead(repo, "HEAD", remote_ref)
    remote_ahead = _count_ahead(repo, remote_ref, "HEAD")

    if local_ahead == 0 and remote_ahead == 0:
        return PushVerdict(
            strategy="clean",
            local_ahead=0,
            remote_ahead=0,
            reason="local and remote are in sync",
        )

    if local_ahead == 0 and remote_ahead > 0:
        return PushVerdict(
            strategy="rebase",
            local_ahead=0,
            remote_ahead=remote_ahead,
            reason=f"fast-forward needed: {remote_ahead} remote commit(s) ahead",
        )

    # Both diverged — decide strategy
    messages = _local_commit_messages(repo, "HEAD", remote_ref)
    all_catchup = all(CATCHUP_RE.match(m) for m in messages) if messages else False

    if all_catchup and messages:
        return PushVerdict(
            strategy="reset",
            local_ahead=local_ahead,
            remote_ahead=remote_ahead,
            reason=(
                f"diverged: {local_ahead} local catch-up commit(s) vs "
                f"{remote_ahead} remote commit(s); reset preferred"
            ),
        )

    return PushVerdict(
        strategy="rebase",
        local_ahead=local_ahead,
        remote_ahead=remote_ahead,
        reason=(
            f"diverged: {local_ahead} local commit(s) with unique work vs "
            f"{remote_ahead} remote commit(s); rebase preferred"
        ),
    )


def resolve(
    repo_path: str | Path,
    remote: str = "origin",
    branch: str = "main",
    dry_run: bool = False,
) -> PushVerdict:
    """Assess divergence and execute the recommended resolution.

    Returns the verdict with ``executed=True`` if the resolution ran.
    """
    repo = str(repo_path)
    remote_ref = f"{remote}/{branch}"

    verdict = assess(repo, remote, branch)

    if dry_run or verdict.strategy == "clean":
        return verdict

    if verdict.strategy == "reset":
        # Stash any dirty working tree first
        stash = _run(["git", "stash", "--include-untracked"], cwd=repo)
        # Hard reset to remote
        reset = _run(["git", "reset", "--hard", remote_ref], cwd=repo)
        if reset.returncode != 0:
            return PushVerdict(
                strategy="conflict",
                local_ahead=verdict.local_ahead,
                remote_ahead=verdict.remote_ahead,
                reason=f"reset failed: {reset.stderr.strip()}",
            )
        # Pop stash if we saved anything
        if stash.returncode == 0 and "No local changes" not in stash.stdout:
            _run(["git", "stash", "pop"], cwd=repo)
        return PushVerdict(
            strategy="reset",
            local_ahead=verdict.local_ahead,
            remote_ahead=verdict.remote_ahead,
            reason=verdict.reason,
            executed=True,
        )

    if verdict.strategy == "rebase":
        # Use theirs strategy for conflicts — remote wins on shared files
        rebase = _run(
            ["git", "rebase", "-X", "theirs", remote_ref],
            cwd=repo,
        )
        if rebase.returncode != 0:
            # Abort failed rebase
            _run(["git", "rebase", "--abort"], cwd=repo)
            return PushVerdict(
                strategy="conflict",
                local_ahead=verdict.local_ahead,
                remote_ahead=verdict.remote_ahead,
                reason=f"rebase failed: {rebase.stderr.strip()}",
            )
        return PushVerdict(
            strategy="rebase",
            local_ahead=verdict.local_ahead,
            remote_ahead=verdict.remote_ahead,
            reason=verdict.reason,
            executed=True,
        )

    return verdict
