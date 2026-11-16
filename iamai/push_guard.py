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


def _run(cmd_or_repo, *git_args, cwd: Optional[str] = None):
    """Run a git command and return the result.

    Two call shapes are supported:

    ``_run(["git", ...], cwd=repo)``  -> CompletedProcess (the original form)
    ``_run(repo, "rev-list", ...)``   -> ``(returncode, stdout)``

    The second form is what the caretaker-facing helpers (and their tests,
    which patch ``_run`` directly) rely on.
    """
    if isinstance(cmd_or_repo, (str, Path)):
        proc = subprocess.run(
            ["git", *git_args], capture_output=True, text=True, cwd=str(cmd_or_repo)
        )
        return proc.returncode, proc.stdout
    return subprocess.run(cmd_or_repo, capture_output=True, text=True, cwd=cwd)


def _count_between(repo: str, spec: str) -> int:
    """``git rev-list --count <spec>`` as an int; 0 when the command fails."""
    code, out = _run(repo, "rev-list", "--count", spec)
    if code != 0:
        return 0
    try:
        return int(out.strip())
    except ValueError:
        return 0


def local_head(repo_path: str | Path) -> Optional[str]:
    """Current commit of the local branch, or None for an empty repo."""
    code, out = _run(repo_path, "rev-parse", "HEAD")
    return out.strip() or None if code == 0 else None


def remote_tip(
    repo_path: str | Path, remote: str = "origin", branch: str = "main"
) -> Optional[str]:
    """Commit the tracking ref points at, or None when it does not exist."""
    code, out = _run(repo_path, "rev-parse", f"{remote}/{branch}")
    return out.strip() or None if code == 0 else None


def merge_base(repo_path: str | Path, left: str, right: str) -> Optional[str]:
    """Merge base of two refs, or None when they share no history."""
    code, out = _run(repo_path, "merge-base", left, right)
    return out.strip() or None if code == 0 else None


def divergence_summary(repo_path: str | Path = ".") -> str:
    """One-line description of how this checkout relates to its remote.

    Returns one of: ``no commits``, ``no remote``, ``clean``, ``ahead N``,
    ``behind N``, ``diverged (L local, R remote)``.
    """
    repo = str(repo_path)
    local = local_head(repo)
    if not local:
        return "no commits"
    remote = remote_tip(repo)
    if not remote:
        return "no remote"
    if local == remote:
        return "clean"
    ahead = _count_between(repo, f"{remote}..{local}")
    behind = _count_between(repo, f"{local}..{remote}")
    if ahead and behind:
        return f"diverged ({ahead} local, {behind} remote)"
    if ahead:
        return f"ahead {ahead}"
    if behind:
        return f"behind {behind}"
    return "clean"


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


def push_readiness_report(repo_path: str | Path) -> dict:
    """Pre-push readiness snapshot for a repository.

    Returns a dict with exactly these keys:

    - ``ready``: True only when the tree is clean, not diverged, and no
      stale push lock is present.
    - ``dirty_files``: number of changed/uncommitted paths.
    - ``unpushed``: commits ahead of the configured upstream.
    - ``diverged``: True when the upstream has commits the local branch lacks.
    - ``stale_lock``: None when ``data/push.lock`` is absent; True when it
      exists but its ``expires_at`` is in the past; False otherwise.
    """
    import json
    import time

    repo = str(repo_path)

    status = _run(["git", "status", "--porcelain"], cwd=repo)
    dirty_files = 0
    if status.returncode == 0:
        dirty_files = len([ln for ln in status.stdout.splitlines() if ln.strip()])

    upstream = _run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=repo,
    )
    if upstream.returncode == 0 and upstream.stdout.strip():
        up = upstream.stdout.strip()
        unpushed = _count_ahead(repo, "HEAD", up)
        behind = _count_ahead(repo, up, "HEAD")
    else:
        unpushed, behind = 0, 0
    diverged = behind > 0

    stale_lock = None
    lock_file = Path(repo) / "data" / "push.lock"
    if lock_file.exists():
        stale_lock = False
        try:
            payload = json.loads(lock_file.read_text())
            stale_lock = float(payload.get("expires_at", 0)) < time.time()
        except (OSError, ValueError, TypeError):
            stale_lock = True

    return {
        "ready": dirty_files == 0 and not diverged and not stale_lock,
        "dirty_files": dirty_files,
        "unpushed": unpushed,
        "diverged": diverged,
        "stale_lock": stale_lock,
    }
