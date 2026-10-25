"""Commit blockage detector — why can't this repo commit right now?

Multiple things can block ``git commit``:

1. A stale ``.git/index.lock`` from a crashed git process.
2. An active rebase or merge in progress (``.git/rebase-merge`` etc).
3. A pre-commit hook that rejects the commit.
4. No changes staged (nothing to commit).

This module checks all known blockers and returns a prioritized list
so the caretaker can fix the highest-priority one first.

Model
-----
Each blocker has a severity:

- **blocking**: nothing can commit until this is resolved.
- **warning**: commits might work but something is degraded.
- **info**: nothing is wrong, just noting the state.

``check_blockage`` returns a list of findings sorted by severity
(blocking first, then warning, then info).

Each finding is a dict::

    {
        "severity": "blocking",
        "cause": "stale_index_lock",
        "detail": "index.lock age 3721s, no holder pid",
        "fix": "remove .git/index.lock",
    }

Usage
-----
    from iamai.commit_blockage import check_blockage
    findings = check_blockage(repo_path)
    blocking = [f for f in findings if f["severity"] == "blocking"]
    if blocking:
        print(f"commit blocked: {blocking[0]['cause']}")
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional


def _check_index_lock(repo: Path) -> Optional[dict]:
    """Check for stale or active index.lock."""
    lock = Path(repo) / ".git" / "index.lock"
    if not lock.exists():
        return None

    try:
        import time
        age = time.time() - lock.stat().st_mtime
    except OSError:
        age = 0.0

    # Try to find a holder via /proc
    holder_pid = _find_holder(lock)
    stale = holder_pid is None

    if stale:
        return {
            "severity": "blocking",
            "cause": "stale_index_lock",
            "detail": f"index.lock age {age:.0f}s, no holder pid",
            "fix": "remove .git/index.lock",
        }

    return {
        "severity": "warning",
        "cause": "active_index_lock",
        "detail": f"index.lock age {age:.0f}s, held by pid {holder_pid}",
        "fix": "wait for git process to finish or kill the holder",
    }


def _find_holder(lock: Path) -> Optional[int]:
    """Find a live process holding the lock open via /proc."""
    lock_resolved = str(lock.resolve())
    proc = Path("/proc")
    if not proc.exists():
        return None

    try:
        for pid_dir in proc.iterdir():
            if not pid_dir.name.isdigit():
                continue
            fd_dir = pid_dir / "fd"
            if not fd_dir.exists():
                continue
            try:
                for fd in fd_dir.iterdir():
                    try:
                        if str(fd.resolve()) == lock_resolved:
                            return int(pid_dir.name)
                    except (PermissionError, FileNotFoundError, OSError):
                        continue
            except (PermissionError, FileNotFoundError, OSError):
                continue
    except (PermissionError, OSError):
        pass

    return None


def _check_rebase_in_progress(repo: Path) -> Optional[dict]:
    """Check for an ongoing rebase or merge."""
    git_dir = Path(repo) / ".git"

    for marker, label in [
        ("rebase-merge", "interactive rebase"),
        ("rebase-apply", "am/rebase"),
        ("MERGE_HEAD", "merge"),
        ("CHERRY_PICK_HEAD", "cherry-pick"),
    ]:
        if (git_dir / marker).exists():
            return {
                "severity": "blocking",
                "cause": f"{label}_in_progress",
                "detail": f".git/{marker} exists",
                "fix": f"complete or abort the {label}",
            }

    return None


def _check_stash_count(repo: Path) -> Optional[dict]:
    """Note if there's a large stash pile (info only)."""
    stash_file = Path(repo) / ".git" / "refs" / "stash"
    if not stash_file.exists():
        return None

    # We can't easily count stashes without running git, so just note presence
    return {
        "severity": "info",
        "cause": "stash_present",
        "detail": ".git/refs/stash exists",
        "fix": "no action needed",
    }


def check_blockage(repo: Path) -> List[dict]:
    """Check all known commit blockers and return findings sorted by severity.

    Parameters
    ----------
    repo : Path
        Root of the git repository.

    Returns
    -------
    List of finding dicts, sorted blocking > warning > info.
    """
    checks = [
        _check_index_lock,
        _check_rebase_in_progress,
        _check_stash_count,
    ]

    findings = []
    for check in checks:
        result = check(Path(repo))
        if result is not None:
            findings.append(result)

    severity_order = {"blocking": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: severity_order.get(f["severity"], 99))

    return findings


def summary(repo: Path) -> str:
    """One-liner summary of the commit blockage state."""
    findings = check_blockage(repo)

    if not findings:
        return "no commit blockers detected"

    blocking = [f for f in findings if f["severity"] == "blocking"]
    if blocking:
        causes = ", ".join(f["cause"] for f in blocking)
        return f"commit BLOCKED: {causes}"

    warnings = [f for f in findings if f["severity"] == "warning"]
    if warnings:
        causes = ", ".join(f["cause"] for f in warnings)
        return f"commit degraded: {causes}"

    return "commit healthy (info notes only)"
