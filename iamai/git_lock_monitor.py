#!/usr/bin/env python3
"""git_lock_monitor — detect and safely clean stale git lock files.

The ``.git/index.lock`` file prevents concurrent git operations.  It is
created at the start of a write operation and removed on completion.
When a process crashes or is killed, the lock file is left behind and
every subsequent git command fails with:

    fatal: Unable to create '.git/index.lock': File exists.

This module provides a safe, conservative approach to cleaning stale
locks:

1. **Detect** — check whether a lock file exists and how old it is.
2. **Classify** — compare the lock's age against a staleness threshold.
   Fresh locks (created seconds ago) likely belong to a live process
   and must not be touched.
3. **Clean** — remove only locks that exceed the staleness threshold.
   Return a structured result so the caller can log what happened.

Design decisions
----------------
- **No PID checking.**  The lock file does not store the creator's PID,
  so we rely solely on age.  This is simpler and avoids TOCTOU races
  with short-lived git subprocesses.
- **Conservative default threshold (120 s).**  Normal git operations
  in this repo complete in < 30 s.  Two minutes provides wide margin
  while still catching genuine stale locks quickly.
- **Atomic removal.**  Uses ``os.unlink`` inside a try/except to handle
  the race where another process removes the lock concurrently.

Public API::

    from iamai.git_lock_monitor import check_and_clean

    result = check_and_clean("/path/to/IamAI")
    if result["action"] == "cleaned":
        print(f"removed stale lock ({result['age_s']:.0f}s old)")
    elif result["action"] == "fresh":
        print(f"lock is live ({result['age_s']:.0f}s old) — left alone")

Usage from the batch committer::

    # Before every commit attempt:
    lock = check_and_clean(repo_path, max_age_s=120)
    if lock["action"] == "error":
        log.error("lock cleanup failed: %s", lock["detail"])
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, Optional


def _lock_path(repo: str | Path) -> Path:
    """Return the canonical index.lock path for *repo*."""
    return Path(repo) / ".git" / "index.lock"


def check_and_clean(
    repo: str | Path,
    max_age_s: float = 120.0,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Check for a stale ``index.lock`` and clean it if safe.

    Parameters
    ----------
    repo:
        Path to the git working tree (the directory containing ``.git``).
    max_age_s:
        Lock files older than this (in seconds) are considered stale
        and will be removed.  Defaults to 120 s.
    now:
        Override for ``time.time()`` — useful in tests.

    Returns
    -------
    dict with keys:

    - ``exists`` (bool): whether the lock file was found.
    - ``action`` (str): one of ``"none"``, ``"cleaned"``, ``"fresh"``,
      ``"error"``.
    - ``age_s`` (float | None): lock age in seconds, or *None* if the
      file does not exist.
    - ``detail`` (str): human-readable summary.
    """
    lp = _lock_path(repo)
    _now = now if now is not None else time.time()

    if not lp.exists():
        return {
            "exists": False,
            "action": "none",
            "age_s": None,
            "detail": "no lock file present",
        }

    try:
        mtime = lp.stat().st_mtime
    except OSError as exc:
        return {
            "exists": True,
            "action": "error",
            "age_s": None,
            "detail": f"cannot stat lock: {exc}",
        }

    age = _now - mtime

    if age < max_age_s:
        return {
            "exists": True,
            "action": "fresh",
            "age_s": age,
            "detail": f"lock is {age:.1f}s old (threshold {max_age_s}s) — left alone",
        }

    try:
        lp.unlink()
    except FileNotFoundError:
        # Another process already cleaned it — fine.
        return {
            "exists": True,
            "action": "cleaned",
            "age_s": age,
            "detail": f"lock was {age:.1f}s old — already removed by another process",
        }
    except OSError as exc:
        return {
            "exists": True,
            "action": "error",
            "age_s": age,
            "detail": f"failed to remove lock ({age:.1f}s old): {exc}",
        }

    return {
        "exists": True,
        "action": "cleaned",
        "age_s": age,
        "detail": f"removed stale lock ({age:.1f}s old, threshold {max_age_s}s)",
    }


def is_locked(repo: str | Path) -> bool:
    """Return *True* if an ``index.lock`` file currently exists."""
    return _lock_path(repo).exists()


def lock_age(repo: str | Path, now: Optional[float] = None) -> Optional[float]:
    """Return the lock age in seconds, or *None* if no lock exists."""
    lp = _lock_path(repo)
    if not lp.exists():
        return None
    _now = now if now is not None else time.time()
    try:
        return _now - lp.stat().st_mtime
    except OSError:
        return None
