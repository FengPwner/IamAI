"""pre_push_sync -- atomic sync-before-push for multi-writer repos.

The caretaker has been doing stash → pull-rebase → stash pop → push
manually for ~78 visits.  The sequence is well-understood but the
implementation is scattered across shell snippets and visit notes.
This module encodes it as a single callable so future caretakers
(batch, manual, or external) don't repeat the dance by hand.

Usage::

    from iamai.pre_push_sync import sync_and_push
    result = sync_and_push("/path/to/repo", message="caretaker visit 79")
    print(result.phase, result.ok)

The function is idempotent: if the local is already up-to-date with
the remote it skips the merge step entirely and goes straight to push.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Phase(Enum):
    PROBE = "probe"
    QUIESCE = "quiesce"
    STASH = "stash"
    FETCH = "fetch"
    REBASE = "rebase"
    POP = "pop"
    COMMIT = "commit"
    PUSH = "push"
    DONE = "done"


@dataclass(frozen=True)
class SyncResult:
    """Outcome of a sync_and_push call."""

    ok: bool
    phase: Phase
    divergence: bool
    stashed: bool
    rebased: bool
    pushed: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "phase": self.phase.value,
            "divergence": self.divergence,
            "stashed": self.stashed,
            "rebased": self.rebased,
            "pushed": self.pushed,
            "detail": self.detail,
        }


def _run(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git"] + list(args),
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode, output


def _current_branch(repo: Path) -> str:
    """Return the current branch name (e.g. 'main')."""
    rc, out = _run(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() if rc == 0 else "main"


def _has_divergence(repo: Path) -> bool:
    """Return True if local and remote HEADs differ (fetch needed)."""
    branch = _current_branch(repo)
    rc_local, local_ref = _run(repo, "rev-parse", "HEAD")
    rc_remote, remote_ref = _run(repo, "rev-parse", f"origin/{branch}")
    if rc_local != 0 or rc_remote != 0:
        return True  # can't tell → assume diverged
    return local_ref != remote_ref


def _dirty_files(repo: Path) -> list[str]:
    rc, out = _run(repo, "status", "--porcelain")
    if rc != 0:
        return []
    return [line for line in out.splitlines() if line.strip()]


def _ahead_count(repo: Path) -> int:
    """How many local commits ahead of origin/<branch>."""
    branch = _current_branch(repo)
    rc, out = _run(repo, "rev-list", "--count", f"origin/{branch}..HEAD")
    if rc != 0:
        return 0
    try:
        return int(out.strip())
    except ValueError:
        return 0


def sync_and_push(
    repo: str | Path,
    *,
    message: str = "pre-push sync",
    remote: str = "origin",
    branch: str | None = None,
    commit_pending: bool = True,
) -> SyncResult:
    """Perform the full sync-before-push protocol.

    Steps:
      1. probe: check if local diverges from remote
      2. stash: if working tree is dirty, stash changes
      3. fetch: pull latest from remote
      4. rebase: rebase local commits on top of remote
      5. pop: restore stashed changes
      6. commit: if commit_pending and there are unstaged files, commit them
      7. push: push to remote

    Returns a SyncResult summarizing what happened.
    """
    repo = Path(repo)
    if not (repo / ".git").is_dir():
        return SyncResult(
            ok=False, phase=Phase.PROBE, divergence=False,
            stashed=False, rebased=False, pushed=False,
            detail="not a git repository",
        )

    if branch is None:
        branch = _current_branch(repo)

    # -- Phase 1: probe --
    _run(repo, "fetch", remote, branch)
    diverged = _has_divergence(repo)

    if not diverged:
        # Nothing to sync; just commit pending and push
        if commit_pending and _dirty_files(repo):
            _run(repo, "add", "-A")
            _run(repo, "commit", "-m", message)
        rc, out = _run(repo, "push", remote, branch)
        return SyncResult(
            ok=(rc == 0), phase=Phase.PUSH, divergence=False,
            stashed=False, rebased=False, pushed=(rc == 0),
            detail=out if rc != 0 else "",
        )

    # -- Phase 2: stash dirty tree --
    dirty = _dirty_files(repo)
    stashed = False
    if dirty:
        rc, out = _run(repo, "stash", "--include-untracked")
        stashed = (rc == 0)

    # -- Phase 3: fetch + rebase --
    rc, out = _run(repo, "pull", "--rebase", remote, branch)
    rebased = (rc == 0)
    if not rebased:
        # Abort the rebase so the repo is clean for the caller
        _run(repo, "rebase", "--abort")

    # -- Phase 4: pop stash --
    if stashed:
        rc_pop, _ = _run(repo, "stash", "pop")
        if rc_pop != 0:
            return SyncResult(
                ok=False, phase=Phase.POP, divergence=True,
                stashed=True, rebased=rebased, pushed=False,
                detail="stash pop conflict",
            )

    # -- Phase 5: commit any remaining pending changes --
    if commit_pending and _dirty_files(repo):
        _run(repo, "add", "-A")
        _run(repo, "commit", "-m", message)

    # -- Phase 6: push --
    rc, out = _run(repo, "push", remote, branch)
    return SyncResult(
        ok=(rc == 0), phase=Phase.PUSH, divergence=True,
        stashed=stashed, rebased=rebased, pushed=(rc == 0),
        detail=out if rc != 0 else "",
    )
