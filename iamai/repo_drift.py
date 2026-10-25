"""Measure how far a local branch has drifted from its remote tracking branch.

Detects ahead/behind divergence before a push attempt, so caretakers can
rebase proactively instead of discovering rejection after the fact.

Usage::

    from iamai.repo_drift import drift_report, summarize

    report = drift_report()
    print(summarize(report))

    # or for structured access:
    print(report["ahead"], report["behind"], report["status"])

The ``status`` field is one of:
  - ``"synced"``    — local and remote are at the same commit
  - ``"ahead"``     — local has commits remote doesn't (push will succeed)
  - ``"behind"``    — remote has commits local doesn't (pull needed)
  - ``"diverged"``  — both sides have unique commits (rebase needed)
  - ``"no_remote"`` — no tracking branch configured or remote unreachable
"""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def _run_git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    """Run a git command and return (exit_code, stdout)."""
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or REPO,
        timeout=30,
    )
    return result.returncode, result.stdout.strip()


def _current_branch(cwd: Path | None = None) -> str | None:
    """Return the current branch name, or None if detached."""
    rc, out = _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    if rc != 0 or out == "HEAD":
        return None
    return out


def _tracking_branch(branch: str, cwd: Path | None = None) -> str | None:
    """Return the remote tracking ref (e.g. 'origin/main'), or None."""
    rc, out = _run_git(
        "config", f"branch.{branch}.remote", cwd=cwd
    )
    if rc != 0 or not out:
        return None
    remote = out

    rc, out = _run_git(
        "config", f"branch.{branch}.merge", cwd=cwd
    )
    if rc != 0 or not out:
        return None
    # merge is like "refs/heads/main" — strip to "main"
    merge_ref = out
    if merge_ref.startswith("refs/heads/"):
        merge_ref = merge_ref[len("refs/heads/"):]

    return f"{remote}/{merge_ref}"


def _count_commits(from_ref: str, to_ref: str, cwd: Path | None = None) -> int | None:
    """Count commits reachable from to_ref but not from from_ref."""
    rc, out = _run_git(
        "rev-list", "--count", f"{from_ref}..{to_ref}", cwd=cwd
    )
    if rc != 0:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def drift_report(cwd: Path | None = None, fetch: bool = False) -> dict:
    """Compute drift between local branch and its remote tracking branch.

    Args:
        cwd: Repository root. Defaults to the iamai repo root.
        fetch: If True, run ``git fetch`` first to update remote refs.

    Returns:
        A dict with keys: branch, remote_ref, ahead, behind, status, local_sha, remote_sha.
    """
    repo = cwd or REPO

    branch = _current_branch(repo)
    if branch is None:
        return {
            "branch": None,
            "remote_ref": None,
            "ahead": None,
            "behind": None,
            "status": "detached",
            "local_sha": None,
            "remote_sha": None,
        }

    remote_ref = _tracking_branch(branch, repo)
    if remote_ref is None:
        return {
            "branch": branch,
            "remote_ref": None,
            "ahead": None,
            "behind": None,
            "status": "no_remote",
            "local_sha": _get_sha("HEAD", repo),
            "remote_sha": None,
        }

    if fetch:
        remote_name = remote_ref.split("/")[0]
        _run_git("fetch", remote_name, cwd=repo)

    # Check if remote ref exists
    remote_sha = _get_sha(remote_ref, repo)
    if remote_sha is None:
        return {
            "branch": branch,
            "remote_ref": remote_ref,
            "ahead": None,
            "behind": None,
            "status": "no_remote",
            "local_sha": _get_sha("HEAD", repo),
            "remote_sha": None,
        }

    local_sha = _get_sha("HEAD", repo)
    ahead = _count_commits(remote_ref, "HEAD", repo) or 0
    behind = _count_commits("HEAD", remote_ref, repo) or 0

    if ahead == 0 and behind == 0:
        status = "synced"
    elif ahead > 0 and behind == 0:
        status = "ahead"
    elif ahead == 0 and behind > 0:
        status = "behind"
    else:
        status = "diverged"

    return {
        "branch": branch,
        "remote_ref": remote_ref,
        "ahead": ahead,
        "behind": behind,
        "status": status,
        "local_sha": local_sha,
        "remote_sha": remote_sha,
    }


def _get_sha(ref: str, cwd: Path | None = None) -> str | None:
    """Resolve a ref to its SHA, or None if it doesn't exist."""
    rc, out = _run_git("rev-parse", "--verify", ref, cwd=cwd)
    if rc != 0:
        return None
    return out[:12]  # short SHA for readability


def summarize(report: dict) -> str:
    """Return a human-readable one-liner from a drift report."""
    branch = report.get("branch", "?")
    status = report.get("status", "unknown")

    if status == "detached":
        return f"{branch}: HEAD is detached (no branch)"
    if status == "no_remote":
        return f"{branch}: no remote tracking branch configured"
    if status == "synced":
        remote = report.get("remote_ref", "?")
        return f"{branch} ↔ {remote}: synced at {report['local_sha']}"

    ahead = report["ahead"]
    behind = report["behind"]
    remote = report.get("remote_ref", "?")

    if status == "ahead":
        return f"{branch} → {remote}: {ahead} commit(s) ahead, safe to push"
    if status == "behind":
        return f"{branch} ← {remote}: {behind} commit(s) behind, pull recommended"
    # diverged
    return (
        f"{branch} ⇄ {remote}: diverged "
        f"({ahead} ahead, {behind} behind) — rebase needed"
    )


def needs_pull(report: dict) -> bool:
    """Return True if a pull/rebase is needed before pushing."""
    return report.get("status") in ("behind", "diverged")


def safe_to_push(report: dict) -> bool:
    """Return True if a push should succeed without fetching first."""
    return report.get("status") in ("synced", "ahead")
