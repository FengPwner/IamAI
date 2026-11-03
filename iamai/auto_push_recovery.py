"""auto_push_recovery — end-to-end push divergence recovery.

The push divergence cycle in this repo follows a predictable pattern:

  1. writer accumulates local commits
  2. remote advances (another writer or caretaker pushed first)
  3. push fails with "rejected (fetch first)"
  4. caretaker manually: stash → rebase → pop → push

This module automates that entire cycle so the batch committer can
self-heal instead of waiting for the next caretaker visit.

Design:
  - stash dirty files before rebase (rebase refuses on dirty tree)
  - fetch + rebase on top of remote
  - pop stash (accepting ours for state files)
  - push the rebased branch
  - return a structured result so the caller can log what happened

Every git call goes through subprocess — no GitPython dependency.
Force-push is never used; if rebase conflicts, we abort and report.

Usage::

    from iamai.auto_push_recovery import recover

    result = recover("/path/to/IamAI")
    if result["ok"]:
        print(result["detail"])
    else:
        print(f"recovery failed: {result['detail']}")
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict

from iamai.git_divergence import _git


def _run(repo: Path, *args: str) -> tuple[int, str]:
    """Run a git command, return (exit_code, combined_output)."""
    try:
        proc = _git(repo, *args, check=False)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "command timed out"


def _has_stash(repo: Path) -> bool:
    """Check if a stash was created during this recovery."""
    code, out = _run(repo, "stash", "list")
    return code == 0 and out.strip().startswith("stash@{0}")


def _stash_dirty(repo: Path) -> bool:
    """Stash uncommitted changes. Returns True if stash was created."""
    code, out = _run(repo, "stash", "push", "-m", "auto_push_recovery")
    return code == 0 and "No local changes" not in out


def _pop_stash(repo: Path) -> tuple[bool, str]:
    """Pop the most recent stash. Returns (ok, detail)."""
    code, out = _run(repo, "stash", "pop")
    if code == 0:
        return True, "stash popped cleanly"
    # Conflict on pop — the stash is preserved, report which files
    if "CONFLICT" in out.upper() or "conflict" in out.lower():
        return False, f"stash pop conflicted: {out.splitlines()[-1] if out else 'unknown'}"
    return False, f"stash pop failed: {out}"


def _rebase_on_remote(repo: Path, remote: str, branch: str) -> tuple[bool, str]:
    """Fetch and rebase local commits on top of remote/branch."""
    # Fetch first
    code, out = _run(repo, "fetch", remote, branch)
    if code != 0:
        return False, f"fetch failed: {out}"

    # Rebase
    code, out = _run(repo, "rebase", f"{remote}/{branch}")
    if code == 0:
        return True, out or "rebased cleanly"

    # Rebase failed — check for conflicts
    if "conflict" in out.lower() or "CONFLICT" in out:
        # Abort the rebase to leave the repo clean
        _run(repo, "rebase", "--abort")
        return False, f"rebase conflicted (aborted): {out.splitlines()[-1] if out else 'unknown'}"

    return False, f"rebase failed: {out}"


def _push(repo: Path, remote: str, branch: str) -> tuple[bool, str]:
    """Push HEAD to remote/branch."""
    code, out = _run(repo, "push", remote, f"HEAD:{branch}")
    if code == 0:
        return True, out or "pushed"
    return False, out


def recover(
    repo: str | Path,
    remote: str = "origin",
    branch: str = "main",
) -> Dict[str, Any]:
    """Run the full push divergence recovery cycle.

    Steps:
      1. Stash any dirty files
      2. Fetch + rebase on remote/branch
      3. Pop stash (if one was created)
      4. Push the rebased branch

    Returns a dict with:
      - ok: bool — whether push ultimately succeeded
      - stashed: bool — whether we had to stash dirty files
      - rebased: bool — whether rebase succeeded
      - pushed: bool — whether final push succeeded
      - detail: str — human-readable summary
    """
    repo = Path(repo)
    result: Dict[str, Any] = {
        "ok": False,
        "stashed": False,
        "rebased": False,
        "pushed": False,
        "detail": "",
        "steps": [],
    }

    # Step 1: Stash dirty files
    stashed = _stash_dirty(repo)
    result["stashed"] = stashed
    result["steps"].append(f"stash: {'created' if stashed else 'nothing to stash'}")

    # Step 2: Rebase on remote
    rebase_ok, rebase_detail = _rebase_on_remote(repo, remote, branch)
    result["rebased"] = rebase_ok
    result["steps"].append(f"rebase: {rebase_detail}")

    if not rebase_ok:
        # Rebase failed — pop stash back before returning
        if stashed:
            _pop_stash(repo)
        result["detail"] = f"rebase failed: {rebase_detail}"
        return result

    # Step 3: Pop stash if we created one
    if stashed:
        pop_ok, pop_detail = _pop_stash(repo)
        result["steps"].append(f"stash pop: {pop_detail}")
        if not pop_ok:
            # Stash pop conflicted — stash is preserved, report it
            result["detail"] = f"rebased ok but {pop_detail}"
            # Still try to push what we have
    else:
        result["steps"].append("stash pop: skipped (nothing was stashed)")

    # Step 4: Push
    push_ok, push_detail = _push(repo, remote, branch)
    result["pushed"] = push_ok
    result["steps"].append(f"push: {push_detail}")

    result["ok"] = push_ok
    if push_ok:
        parts = ["rebased", "pushed"]
        if stashed:
            parts.insert(1, "stashed+popped")
        result["detail"] = " → ".join(parts)
    else:
        result["detail"] = f"push failed after rebase: {push_detail}"

    return result


def needs_recovery(repo: str | Path, remote: str = "origin", branch: str = "main") -> bool:
    """Quick check: would a push right now be rejected?

    Returns True if local is behind remote (push would fail).
    Does not fetch — caller should ensure remote ref is fresh.
    """
    repo = Path(repo)
    tracking = f"{remote}/{branch}"

    code, out = _run(repo, "rev-list", "--count", f"{tracking}..HEAD")
    if code != 0:
        return False
    ahead = int(out.strip()) if out.strip().isdigit() else 0

    code, out = _run(repo, "rev-list", "--count", f"HEAD..{tracking}")
    if code != 0:
        return False
    behind = int(out.strip()) if out.strip().isdigit() else 0

    return behind > 0 and ahead >= 0
