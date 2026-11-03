"""divergence_preempt — pre-push divergence check and auto-recovery.

The push rejection cycle in this repo is predictable:

  1. writer accumulates strokes → batch committer commits locally
  2. remote advances (guoban writer, another caretaker, or a stale push)
  3. ``git push`` fails with ``[rejected] (fetch first)``
  4. caretaker must manually: fetch → rebase → push

``auto_push_recovery`` already handles step 4 *after* a push failure.
This module handles it *before* — checking divergence proactively so the
push attempt itself never fails.

Flow::

    result = preempt_push(repo_path)
    if result["ok"]:
        # safe to push (or already recovered), proceed with git push
    else:
        # something went wrong, inspect result["detail"]

Design decisions:
  - Fetch before check: the remote ref must be current, or divergence
    numbers are meaningless. Fetch failures are non-fatal (treat as
    "unknown, proceed cautiously").
  - Stash before rebase: the writer may be mid-stroke with dirty files.
    We stash, rebase, then pop — same pattern as auto_push_recovery.
  - Never force-push: if rebase has conflicts, abort and report. The
    caretaker can resolve manually.
  - Idempotent: calling preempt_push twice in a row is safe. The second
    call sees ahead>0, behind==0 and returns immediately.

Usage from the batch committer::

    from iamai.divergence_preempt import preempt_push

    before_push = preempt_push("/path/to/IamAI")
    if not before_push["ok"]:
        log.warning(f"pre-push recovery failed: {before_push['detail']}")
        # still attempt push — worst case it fails and caretaker handles it

CLI::

    python3 -m iamai.divergence_preempt /path/to/IamAI
    python3 -m iamai.divergence_preempt /path/to/IamAI --json
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from iamai.git_divergence import _git, divergence


def _run(repo: Path, *args: str, timeout: int = 30) -> tuple[int, str]:
    """Run a git command, return (exit_code, combined_output)."""
    try:
        proc = _git(repo, *args, check=False)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"command timed out after {timeout}s"


def preempt_push(
    repo_path: str | Path,
    branch: str = "main",
    remote: str = "origin",
    auto_recover: bool = True,
) -> Dict[str, Any]:
    """Check divergence before push; auto-recover if behind > 0.

    Returns a dict with:
      - ok (bool): whether the push path is clear
      - action (str): what was done — "clear", "recovered", "failed", "skipped"
      - ahead (int): local commits ahead of merge-base
      - behind (int): remote commits ahead of merge-base
      - dirty (bool): whether working tree has uncommitted changes
      - detail (str): human-readable summary
    """
    repo = Path(repo_path)

    if not (repo / ".git").is_dir():
        return {
            "ok": False,
            "action": "failed",
            "ahead": 0,
            "behind": 0,
            "dirty": False,
            "detail": f"{repo} is not a git repository",
        }

    # Step 1: fetch to get current remote state
    fetch_rc, fetch_out = _run(repo, "fetch", remote, branch)
    if fetch_rc != 0:
        # fetch failed — could be offline, auth issue, etc.
        # we can still check local divergence against cached remote ref
        pass

    # Step 2: measure divergence
    d = divergence(str(repo))
    ahead = d.get("ahead", 0)
    behind = d.get("behind", 0)
    dirty = d.get("dirty", False)

    # Step 3: decide action
    if behind == 0:
        # No divergence — push should succeed (or nothing to push)
        if ahead == 0:
            return {
                "ok": True,
                "action": "skipped",
                "ahead": 0,
                "behind": 0,
                "dirty": dirty,
                "detail": "nothing to push (local is up to date)",
            }
        return {
            "ok": True,
            "action": "clear",
            "ahead": ahead,
            "behind": 0,
            "dirty": dirty,
            "detail": f"{ahead} commit(s) to push, no divergence",
        }

    # behind > 0 — divergence detected, need to integrate remote changes
    if not auto_recover:
        return {
            "ok": False,
            "action": "skipped",
            "ahead": ahead,
            "behind": behind,
            "dirty": dirty,
            "detail": f"behind by {behind} commit(s), auto_recover=False",
        }

    # Step 4: auto-recover via stash → rebase → pop
    return _do_recover(repo, branch, remote, ahead, behind, dirty)


def _do_recover(
    repo: Path,
    branch: str,
    remote: str,
    ahead: int,
    behind: int,
    dirty: bool,
) -> Dict[str, Any]:
    """Perform stash → rebase → pop → verify cycle."""
    stashed = False

    # Stash if dirty
    if dirty:
        rc, out = _run(repo, "stash", "push", "-m", "divergence_preempt auto-stash")
        if rc != 0:
            return {
                "ok": False,
                "action": "failed",
                "ahead": ahead,
                "behind": behind,
                "dirty": dirty,
                "detail": f"stash failed: {out}",
            }
        stashed = True

    # Rebase onto remote
    rc, out = _run(repo, "rebase", f"{remote}/{branch}")
    if rc != 0:
        # Rebase conflict — abort and restore state
        _run(repo, "rebase", "--abort")
        if stashed:
            _run(repo, "stash", "pop")
        return {
            "ok": False,
            "action": "failed",
            "ahead": ahead,
            "behind": behind,
            "dirty": dirty,
            "detail": f"rebase conflict: {out}",
        }

    # Pop stash if we stashed
    if stashed:
        rc, out = _run(repo, "stash", "pop")
        if rc != 0:
            # stash pop conflict — not fatal, just means dirty files conflicted
            # the rebase itself succeeded, push should still work
            return {
                "ok": True,
                "action": "recovered",
                "ahead": ahead,
                "behind": behind,
                "dirty": dirty,
                "detail": f"rebased clean but stash pop conflicted: {out}",
            }

    # Verify: re-check divergence
    d2 = divergence(str(repo))
    new_behind = d2.get("behind", 0)

    if new_behind > 0:
        return {
            "ok": False,
            "action": "failed",
            "ahead": ahead,
            "behind": behind,
            "dirty": dirty,
            "detail": f"still behind by {new_behind} after rebase (remote advanced during recovery?)",
        }

    return {
        "ok": True,
        "action": "recovered",
        "ahead": ahead,
        "behind": behind,
        "dirty": dirty,
        "detail": f"recovered from {behind}-commit divergence via rebase",
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pre-push divergence check")
    parser.add_argument("repo", nargs="?", default=".", help="Path to git repo")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--no-recover", action="store_true", help="Check only, don't recover")
    args = parser.parse_args()

    result = preempt_push(args.repo, auto_recover=not args.no_recover)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = "OK" if result["ok"] else "FAIL"
        print(f"[{status}] {result['action']}: {result['detail']}")
        if result["behind"] > 0:
            print(f"  divergence: {result['ahead']} ahead, {result['behind']} behind")

    sys.exit(0 if result["ok"] else 1)
