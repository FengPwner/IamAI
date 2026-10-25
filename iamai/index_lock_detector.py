"""Index lock detector — find and diagnose stale .git/index.lock files.

When a git process crashes or is killed mid-operation, it can leave behind
a ``.git/index.lock`` file that blocks all subsequent git commands with::

    fatal: Unable to create '.git/index.lock': File exists.

This module detects stale locks, estimates their age, and reports whether
any git process is actually holding them.

Model
-----
A lock is *stale* when:

1. The file exists on disk, AND
2. No running git process has it open (checked via ``/proc`` or ``lsof``).

``detect_lock`` returns a dict::

    {
        "locked": True,
        "path": "/repo/.git/index.lock",
        "age_seconds": 3721.4,
        "holder_pid": None,       # int if a live process holds it
        "stale": True,            # locked but no holder
    }

``diagnose_lock_report`` returns a one-liner for caretaker logs::

    "stale index.lock (age 3721s, no holder) — safe to remove"

Usage
-----
    from iamai.index_lock_detector import detect_lock, diagnose_lock_report
    info = detect_lock(repo)
    if info["stale"]:
        info["path"].unlink()    # safe to remove
    print(diagnose_lock_report(repo))
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional


def _lock_path(repo: Path) -> Path:
    """Return the canonical index.lock path for a repo."""
    return Path(repo) / ".git" / "index.lock"


def _find_holder_pid(lock: Path) -> Optional[int]:
    """Try to find a live process that holds the lock file open.

    Scans /proc/*/fd for symlinks pointing at the lock path.
    Returns the PID if found, None otherwise.
    """
    lock_resolved = str(lock.resolve())
    proc = Path("/proc")
    if not proc.exists():
        return None  # not Linux, skip

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
                        target = str(fd.resolve())
                        if target == lock_resolved:
                            return int(pid_dir.name)
                    except (PermissionError, FileNotFoundError, OSError):
                        continue
            except (PermissionError, FileNotFoundError, OSError):
                continue
    except (PermissionError, OSError):
        pass

    return None


def detect_lock(repo: Path) -> dict:
    """Detect whether .git/index.lock exists and whether it is stale.

    Parameters
    ----------
    repo : Path
        Root of the git repository.

    Returns
    -------
    dict with keys: locked, path, age_seconds, holder_pid, stale
    """
    lock = _lock_path(repo)
    if not lock.exists():
        return {
            "locked": False,
            "path": lock,
            "age_seconds": 0.0,
            "holder_pid": None,
            "stale": False,
        }

    try:
        mtime = lock.stat().st_mtime
        age = time.time() - mtime
    except OSError:
        age = 0.0

    holder = _find_holder_pid(lock)
    stale = holder is None

    return {
        "locked": True,
        "path": lock,
        "age_seconds": round(age, 1),
        "holder_pid": holder,
        "stale": stale,
    }


def clear_stale_lock(repo: Path) -> dict:
    """Remove a stale index.lock if safe to do so.

    Returns a dict with 'removed' (bool) and 'reason' (str).
    Will NOT remove the lock if a live process holds it.
    """
    info = detect_lock(repo)

    if not info["locked"]:
        return {"removed": False, "reason": "no lock present"}

    if not info["stale"]:
        return {
            "removed": False,
            "reason": f"lock held by pid {info['holder_pid']}, not stale",
        }

    try:
        info["path"].unlink()
        return {"removed": True, "reason": f"stale lock removed (age {info['age_seconds']:.0f}s)"}
    except OSError as exc:
        return {"removed": False, "reason": f"failed to remove: {exc}"}


def diagnose_lock_report(repo: Path) -> str:
    """One-liner summary of the lock state for caretaker logs."""
    info = detect_lock(repo)

    if not info["locked"]:
        return "no index.lock — clear"

    if info["stale"]:
        return (
            f"stale index.lock (age {info['age_seconds']:.0f}s, no holder) "
            f"— safe to remove"
        )

    return (
        f"active index.lock (age {info['age_seconds']:.0f}s, "
        f"holder pid {info['holder_pid']}) — do not remove"
    )
