"""Detect stale git lock files that block commits and rebases.

A crashed ``git commit`` or ``git rebase`` can leave behind ``.lock`` files
under ``.git/``.  Until removed, every subsequent git operation fails with
``fatal: Unable to create ...: File exists``.

This module checks known lock-file paths and cross-references the process
table: if a lock exists but no ``git`` process is running, the lock is
**stale** and safe to remove.

Design note: on some FUSE / object-storage filesystems, directory traversal
resets file mtime to "now", so a pure age-based check is unreliable.
Process-based staleness detection works regardless of filesystem quirks.

Usage::

    from iamai.lock_health import scan_locks, summary

    result = scan_locks()
    for lf in result["locks"]:
        print(lf["path"], lf["stale"])

    print(summary())   # one-liner for dashboards

Pass ``remove_stale=True`` to delete stale locks automatically.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Well-known lock paths that git creates
KNOWN_LOCKS = [
    ".git/index.lock",
    ".git/HEAD.lock",
    ".git/packed-refs.lock",
    ".git/refs/stash.lock",
    ".git/refs/heads/main.lock",
    ".git/refs/heads/master.lock",
    ".git/refs/remotes/origin/main.lock",
    ".git/refs/remotes/origin/master.lock",
    ".git/refs/remotes/origin/HEAD.lock",
    ".git/logs/HEAD.lock",
    ".git/logs/refs/heads/main.lock",
    ".git/logs/refs/remotes/origin/main.lock",
    ".git/rebase-merge/done.lock",
    ".git/rebase-apply/patch.lock",
    ".git/MERGE_HEAD.lock",
    ".git/CHERRY_PICK_HEAD.lock",
    ".git/REVERT_HEAD.lock",
]


def _git_running() -> bool:
    """Return True if any git process is currently running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "git"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # pgrep returns 0 if matches found, 1 if none
        if result.returncode == 0:
            # Filter out our own check and common false positives
            for line in result.stdout.strip().splitlines():
                pid = int(line.strip())
                if pid == os.getpid():
                    continue
                # Read the process cmdline to verify it's actually git
                try:
                    cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
                    if b"git" in cmdline:
                        return True
                except (OSError, PermissionError):
                    continue
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # pgrep not available; fall back to True (assume git might be running)
        return True


def _discover_locks(repo: Path) -> list[Path]:
    """Find lock files: check known paths, then do a broad scan.

    The broad scan may return inaccurate mtimes on FUSE filesystems,
    but the existence check is still valid — staleness is determined
    by process detection, not mtime.
    """
    found: set[Path] = set()
    # Check known paths
    for rel in KNOWN_LOCKS:
        lock = repo / rel
        if lock.exists():
            found.add(lock)

    # Also do a quick scan for any other .lock files
    git_dir = repo / ".git"
    if git_dir.exists():
        try:
            for lock in git_dir.rglob("*.lock"):
                found.add(lock)
        except OSError:
            pass

    return sorted(found)


def scan_locks(
    repo: Path | None = None,
    max_age: float = 60,
    remove_stale: bool = False,
) -> dict:
    """Scan the repo's .git directory for lock files.

    A lock is **stale** when:
    - no git process is running (primary check), OR
    - the lock's mtime exceeds *max_age* seconds (fallback for
      non-FUSE filesystems where mtime is reliable).

    Returns a dict::

        {
            "locks": [
                {"path": ".git/index.lock", "age_s": 123.4, "stale": True},
                ...
            ],
            "stale_count": int,
            "total_count": int,
            "cleaned": int,
            "git_running": bool,
        }
    """
    repo = repo or REPO
    git_running = _git_running()
    locks = _discover_locks(repo)
    now = time.time()
    entries: list[dict] = []
    cleaned = 0

    for lock in locks:
        try:
            age = now - lock.stat().st_mtime
        except OSError:
            continue
        # Stale if no git process, or age exceeds threshold
        stale = (not git_running) or (age > max_age)
        entry = {
            "path": str(lock.relative_to(repo)),
            "age_s": round(age, 1),
            "stale": stale,
        }
        entries.append(entry)
        if stale and remove_stale:
            try:
                lock.unlink()
                cleaned += 1
            except OSError:
                pass

    stale_count = sum(1 for e in entries if e["stale"])
    return {
        "locks": entries,
        "stale_count": stale_count,
        "total_count": len(entries),
        "cleaned": cleaned,
        "git_running": git_running,
    }


def summary(repo: Path | None = None, max_age: float = 60) -> str:
    """Return a one-line human-readable summary."""
    result = scan_locks(repo=repo, max_age=max_age)
    total = result["total_count"]
    stale = result["stale_count"]
    git = result["git_running"]
    if total == 0:
        return "no lock files found — git is healthy"
    if stale == 0:
        return f"{total} lock(s) present, git {'running' if git else 'idle'} — healthy"
    names = ", ".join(e["path"] for e in result["locks"] if e["stale"])
    return f"{stale}/{total} lock(s) STALE (git {'running' if git else 'idle'}): {names}"
