"""Lock recovery — staged state machine for recovering from git lock failures.

When a git process dies mid-operation, the lock file it left behind is only
the visible symptom.  The real problem is a broken pipeline: nothing can
commit, nothing can push, and the backlog grows.

This module models lock recovery as a five-stage state machine:

=========  ============================================================
stage      meaning
=========  ============================================================
detect     check whether a stale lock exists
clear      remove the stale lock file
probe      verify git works after removal (``git status`` succeeds)
drain      commit all pending files in one batch
push       push to remote and confirm
=========  ============================================================

Each stage returns a result dict::

    {
        "stage": "clear",
        "status": "ok",         # ok | failed | skipped
        "detail": "removed stale lock (age 3721s)",
        "next": "probe",        # next stage, or None if terminal
    }

``run_recovery`` executes all stages in order, stopping on the first
failure.  The caller can inspect which stage failed and why.

Design choices
--------------

- **Staged, not monolithic.**  Each stage is independently testable and
  can be retried without re-running earlier stages.
- **Pure where possible.**  detect/clear/probe operate on a Path and
  return dicts.  Only drain and push invoke subprocess.
- **Idempotent.**  Running recovery on a clean repo is a no-op — every
  stage returns ``skipped`` and nothing changes.

Usage::

    from iamai.lock_recovery import run_recovery, recovery_summary

    result = run_recovery(repo_path)
    print(recovery_summary(result))
    # "recovery: detect=ok clear=ok probe=ok drain=ok push=ok — all clear"
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from iamai.index_lock_detector import detect_lock, clear_stale_lock


# ---------------------------------------------------------------------------
# Stage results
# ---------------------------------------------------------------------------

def _ok(stage: str, detail: str, next_stage: str | None) -> dict:
    return {"stage": stage, "status": "ok", "detail": detail, "next": next_stage}


def _failed(stage: str, detail: str) -> dict:
    return {"stage": stage, "status": "failed", "detail": detail, "next": None}


def _skipped(stage: str, detail: str, next_stage: str | None) -> dict:
    return {"stage": stage, "status": "skipped", "detail": detail, "next": next_stage}


# ---------------------------------------------------------------------------
# Individual stages
# ---------------------------------------------------------------------------

def stage_detect(repo: Path) -> dict:
    """Check whether a stale lock exists.

    Returns ok+next="clear" if stale lock found,
    ok+next=None if no lock (recovery not needed),
    failed if lock exists but is held by a live process.
    """
    info = detect_lock(repo)

    if not info["locked"]:
        return _ok("detect", "no lock present — nothing to recover", None)

    if info["stale"]:
        return _ok(
            "detect",
            f"stale lock found (age {info['age_seconds']:.0f}s)",
            "clear",
        )

    return _failed(
        "detect",
        f"lock held by live pid {info['holder_pid']} — manual intervention needed",
    )


def stage_clear(repo: Path) -> dict:
    """Remove the stale lock file.

    Returns ok+next="probe" on success, failed on error.
    """
    result = clear_stale_lock(repo)

    if result["removed"]:
        return _ok("clear", result["reason"], "probe")

    if "no lock" in result["reason"]:
        return _skipped("clear", "no lock to clear", "probe")

    return _failed("clear", result["reason"])


def stage_probe(repo: Path, timeout: int = 10) -> dict:
    """Verify git is operational after lock removal.

    Runs ``git status --porcelain`` and checks the exit code.

    Returns ok+next="drain" on success, failed on error or timeout.
    """
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode == 0:
            return _ok("probe", "git status succeeded", "drain")
        return _failed("probe", f"git status failed: {proc.stderr.strip()}")
    except subprocess.TimeoutExpired:
        return _failed("probe", f"git status timed out after {timeout}s")
    except FileNotFoundError:
        return _failed("probe", "git not found on PATH")


def stage_drain(repo: Path, message: str | None = None) -> dict:
    """Commit all pending changes in one batch.

    Runs ``git add -A`` then ``git commit`` with the given message
    (or a default).

    Returns ok+next="push" on success, skipped if nothing to commit,
    failed on error.
    """
    try:
        # Check if there's anything to commit
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if not status.stdout.strip():
            return _skipped("drain", "nothing to commit", "push")

        # Stage everything
        add = subprocess.run(
            ["git", "add", "-A"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if add.returncode != 0:
            return _failed("drain", f"git add failed: {add.stderr.strip()}")

        # Commit
        msg = message or "lock recovery: commit pending changes"
        commit = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if commit.returncode != 0:
            return _failed("drain", f"git commit failed: {commit.stderr.strip()}")

        # Count files committed
        file_count = len(status.stdout.strip().splitlines())
        return _ok("drain", f"committed {file_count} file(s): {msg}", "push")

    except subprocess.TimeoutExpired:
        return _failed("drain", "git operation timed out")


def stage_push(repo: Path, remote: str = "origin", timeout: int = 60) -> dict:
    """Push committed changes to remote.

    Returns ok on success, skipped if nothing to push, failed on error.
    """
    try:
        proc = subprocess.run(
            ["git", "push", remote],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stderr = proc.stderr.strip()
        if "Everything up-to-date" in stderr:
            return _skipped("push", "already up-to-date", None)
        if proc.returncode == 0:
            return _ok("push", "pushed successfully", None)
        return _failed("push", f"git push failed: {stderr}")
    except subprocess.TimeoutExpired:
        return _failed("push", f"git push timed out after {timeout}s")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

STAGE_ORDER = ["detect", "clear", "probe", "drain", "push"]
STAGE_FUNCS = {
    "detect": stage_detect,
    "clear": stage_clear,
    "probe": stage_probe,
    "drain": stage_drain,
    "push": stage_push,
}


def run_recovery(
    repo: Path | str,
    commit_message: str | None = None,
    start_stage: str = "detect",
) -> dict:
    """Execute the full recovery pipeline.

    Parameters
    ----------
    repo : Path or str
        Repository root path.
    commit_message : str, optional
        Custom commit message for the drain stage.
    start_stage : str
        Stage to begin from (default "detect").  Useful for resuming
        after a partial failure.

    Returns
    -------
    dict with keys:
        results : list of stage result dicts (in execution order)
        verdict : "recovered" | "clean" | "failed"
        failed_stage : str or None
    """
    repo = Path(repo)
    results: list[dict] = []

    start_idx = STAGE_ORDER.index(start_stage)
    current_stage = STAGE_ORDER[start_idx]

    while current_stage is not None:
        # Look up by name each time so tests can mock module-level names
        func = globals()[f"stage_{current_stage}"]

        # Inject appropriate arguments
        if current_stage == "drain":
            result = func(repo, message=commit_message)
        elif current_stage == "push":
            result = func(repo)
        else:
            result = func(repo)

        results.append(result)

        if result["status"] == "failed":
            return {
                "results": results,
                "verdict": "failed",
                "failed_stage": current_stage,
            }

        current_stage = result["next"]

    # Determine verdict
    statuses = [r["status"] for r in results]
    # "clean" = nothing needed recovery (only detect ran, found no lock)
    ran_stages = [r["stage"] for r in results]
    only_detect = ran_stages == ["detect"]

    if only_detect and statuses == ["ok"]:
        verdict = "clean"
    elif all(s in ("ok", "skipped") for s in statuses):
        verdict = "recovered"
    else:
        verdict = "recovered"  # fallback (shouldn't reach here on success path)

    return {
        "results": results,
        "verdict": verdict,
        "failed_stage": None,
    }


def recovery_summary(recovery: dict) -> str:
    """One-liner summary of a recovery run.

    Examples::

        "recovery: detect=ok clear=ok probe=ok drain=ok push=ok — recovered"
        "recovery: detect=ok clear=ok probe=FAILED — stopped at probe"
        "recovery: detect=ok clear=skipped probe=ok drain=skipped push=skipped — clean"
    """
    parts = []
    for r in recovery["results"]:
        parts.append(f"{r['stage']}={r['status']}")

    chain = " ".join(parts)
    verdict = recovery["verdict"]

    if recovery["failed_stage"]:
        return f"recovery: {chain} — stopped at {recovery['failed_stage']}"

    return f"recovery: {chain} — {verdict}"
