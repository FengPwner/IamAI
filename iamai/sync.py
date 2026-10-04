"""Sync: bridge the gap between a dirty working tree and a safe push.

The overnight stall of 2026-10-05 exposed a specific failure mode: the
pre-execution harness committed the backlog and then pushed, but the push
was rejected (non-fast-forward). ``iamai.push.push_with_rebase`` already
handles the rebase-then-push path — but only when the working tree is
clean. A live writer may have uncommitted strokes at the exact moment
a push is attempted, and rebase refuses to run on a dirty tree.

This module fills that gap with a three-step cycle:

    1. stash  — park uncommitted changes (including untracked files)
    2. pull   — fetch + rebase local commits on top of upstream
    3. pop    — restore the parked changes

If the pull succeeds, the caller can then use ``push_with_rebase`` on a
clean base. If the rebase conflicts, the stash is restored so nothing is
lost — the conflict is reported, not silently dropped.

Pure subprocess calls to git. No porcelain parsing, no porcelain fragility.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SyncResult:
    ok: bool
    stashed: bool = False
    rebased: bool = False
    popped: bool = False
    detail: str = ""

    def summary(self) -> str:
        flags = []
        if self.stashed:
            flags.append("stashed")
        if self.rebased:
            flags.append("rebased")
        if self.popped:
            flags.append("popped")
        flag_str = " -> ".join(flags) if flags else "no-op"
        status = "ok" if self.ok else "failed"
        return f"sync: {status} [{flag_str}]" + (f" — {self.detail}" if self.detail else "")


def _run(repo: Path, *args: str) -> tuple[int, str]:
    cmd = ["git", *args]
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=120)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _has_unstaged_changes(repo: Path) -> bool:
    code, out = _run(repo, "status", "--porcelain")
    return code == 0 and any(line.strip() for line in out.splitlines())


def _is_ahead_of_remote(repo: Path, remote: str, branch: str) -> bool:
    """True when local has commits the remote doesn't have."""
    code, out = _run(repo, "rev-list", "--count", f"{remote}/{branch}..HEAD")
    if code != 0:
        return False
    try:
        return int(out.strip()) > 0
    except ValueError:
        return False


def _is_behind_remote(repo: Path, remote: str, branch: str) -> bool:
    """True when remote has commits the local doesn't have."""
    code, out = _run(repo, "rev-list", "--count", f"HEAD..{remote}/{branch}")
    if code != 0:
        return False
    try:
        return int(out.strip()) > 0
    except ValueError:
        return False


def sync(
    repo: Path | str,
    remote: str = "origin",
    branch: str = "main",
    stash_message: str = "sync: auto-stash before rebase",
) -> SyncResult:
    """Stash dirty changes, rebase on upstream, restore changes.

    This does NOT push. The caller should push afterwards (ideally via
    ``push_with_rebase``). The separation matters: sync fixes the base,
    push publishes it. Two concerns, two functions.

    Args:
        repo: path to the git repository root.
        remote: upstream name (default: "origin").
        branch: branch to sync against (default: "main").
        stash_message: label for the automatic stash entry.

    Returns:
        SyncResult describing what happened.
    """
    repo = Path(repo)
    result = SyncResult(ok=False)

    # Step 0: fetch so we know what remote looks like.
    code, fetch_out = _run(repo, "fetch", remote, branch)
    if code != 0:
        result.detail = f"fetch failed: {fetch_out.splitlines()[-1] if fetch_out else 'unknown'}"
        return result

    # Step 1: stash if the tree is dirty.
    dirty = _has_unstaged_changes(repo)
    if dirty:
        code, stash_out = _run(repo, "stash", "push", "-u", "-m", stash_message)
        if code != 0:
            result.detail = f"stash failed: {stash_out.splitlines()[-1] if stash_out else 'unknown'}"
            return result
        result.stashed = True

    # Step 2: rebase if we are behind remote.
    behind = _is_behind_remote(repo, remote, branch)
    if behind:
        theirs = f"{remote}/{branch}"
        code, rebase_out = _run(
            repo,
            "-c", "rebase.autoStash=true",
            "rebase", theirs,
        )
        if code != 0:
            # Rebase failed — abort and restore stash if we made one.
            _run(repo, "rebase", "--abort")
            if result.stashed:
                _run(repo, "stash", "pop")
                result.popped = True
            result.detail = f"rebase conflicted: {rebase_out.splitlines()[-1] if rebase_out else 'unknown'}"
            return result
        result.rebased = True

    # Step 3: pop stash if we made one.
    if result.stashed:
        code, pop_out = _run(repo, "stash", "pop")
        if code != 0:
            # Stash pop conflict — leave it for the human.
            result.detail = f"stash pop conflicted: {pop_out.splitlines()[-1] if pop_out else 'unknown'}"
            return result
        result.popped = True

    result.ok = True
    if not dirty and not behind:
        result.detail = "already in sync"
    else:
        parts = []
        if dirty:
            parts.append("stashed dirty tree")
        if behind:
            parts.append("rebased onto upstream")
        if dirty:
            parts.append("restored changes")
        result.detail = ", ".join(parts)

    return result


def sync_and_push(
    repo: Path | str,
    remote: str = "origin",
    branch: str = "main",
) -> dict:
    """One-call recovery: sync the base, then push with rebase fallback.

    Combines ``sync()`` + ``push_with_rebase()`` into a single operation.
    Returns a dict with ``sync`` and ``push`` keys so the caller can
    diagnose which step failed.
    """
    from .push import push_with_rebase

    repo = Path(repo)
    sync_result = sync(repo, remote=remote, branch=branch)
    if not sync_result.ok:
        return {
            "ok": False,
            "sync": sync_result.summary(),
            "push": "skipped (sync failed)",
        }

    push_result = push_with_rebase(repo, remote=remote, branch=branch)
    return {
        "ok": push_result["ok"],
        "sync": sync_result.summary(),
        "push": push_result["detail"],
    }
