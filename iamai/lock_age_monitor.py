"""lock_age_monitor — detect and classify stale .git/index.lock files.

A self-writing repo runs concurrent git operations (writer, batch committer,
push-with-rebase).  When one of those crashes mid-operation it can leave
behind ``.git/index.lock``, blocking every subsequent git command until
someone notices and removes it.

This module measures the lock file's age and classifies it:

=========  ============================================================
label      meaning
=========  ============================================================
``fresh``  lock is younger than *fresh_seconds* (default 30 s);
           a live git process probably owns it — leave it alone
``aging``  between *fresh_seconds* and *stale_seconds* (default 120 s);
           suspicious but not yet certain
``stale``  older than *stale_seconds*; almost certainly orphaned by a
           crashed process and safe to remove
=========  ============================================================

The tool never deletes the lock itself — it reports and lets the caller
decide (or lets the caretaker script act on the verdict).

Exit codes (CLI wrapper)
------------------------
0 — scan succeeded
1 — repo not found or not a git repo
2 — no lock file present (clean state)

Usage
-----
    python3 tools/lock_age_monitor.py
    python3 tools/lock_age_monitor.py --stale 60
    python3 tools/lock_age_monitor.py --json
    python3 tools/lock_age_monitor.py --repo /path/to/IamAI
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_FRESH_SECONDS = 30
DEFAULT_STALE_SECONDS = 120
LOCK_FILENAME = "index.lock"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class LockReport:
    repo: str
    lock_path: str
    exists: bool
    age_seconds: float
    label: str  # fresh | aging | stale
    mtime_epoch: float
    pid_alive: bool  # whether any git process is running
    recommendation: str  # leave | watch | remove

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _find_git_dir(repo: str) -> Optional[Path]:
    """Return the .git directory for *repo*, or None."""
    git_dir = Path(repo) / ".git"
    if git_dir.is_dir():
        return git_dir
    # handle worktrees / bare repos
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--git-dir"],
            cwd=repo, stderr=subprocess.DEVNULL, text=True,
        ).strip()
        candidate = Path(out)
        if candidate.is_dir():
            return candidate
        # relative path
        candidate = Path(repo) / candidate
        if candidate.is_dir():
            return candidate
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return None


def _lock_path(git_dir: Path) -> Path:
    return git_dir / LOCK_FILENAME


def _git_process_alive() -> bool:
    """Best-effort check for any running git process."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "git"],
            text=True, stderr=subprocess.DEVNULL,
        )
        return len(out.strip().splitlines()) > 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _classify(age: float, fresh_s: float, stale_s: float) -> str:
    """Classify lock age into fresh / aging / stale."""
    if age < fresh_s:
        return "fresh"
    if age < stale_s:
        return "aging"
    return "stale"


def _recommendation(label: str, pid_alive: bool) -> str:
    """Decide what to do based on classification and process state."""
    if label == "stale":
        return "remove"
    if label == "aging" and not pid_alive:
        return "watch"
    return "leave"


def scan_lock(
    repo: str = ".",
    fresh_seconds: float = DEFAULT_FRESH_SECONDS,
    stale_seconds: float = DEFAULT_STALE_SECONDS,
) -> LockReport:
    """Scan the lock file and return a LockReport."""
    repo_path = str(Path(repo).resolve())
    git_dir = _find_git_dir(repo_path)
    if git_dir is None:
        raise FileNotFoundError(f"Not a git repo: {repo_path}")

    lock = _lock_path(git_dir)
    exists = lock.exists()

    if not exists:
        return LockReport(
            repo=repo_path,
            lock_path=str(lock),
            exists=False,
            age_seconds=0.0,
            label="none",
            mtime_epoch=0.0,
            pid_alive=False,
            recommendation="nothing",
        )

    mtime = lock.stat().st_mtime
    now = time.time()
    age = max(0.0, now - mtime)
    pid_alive = _git_process_alive()
    label = _classify(age, fresh_seconds, stale_seconds)
    rec = _recommendation(label, pid_alive)

    return LockReport(
        repo=repo_path,
        lock_path=str(lock),
        exists=True,
        age_seconds=round(age, 2),
        label=label,
        mtime_epoch=round(mtime, 2),
        pid_alive=pid_alive,
        recommendation=rec,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Detect stale .git/index.lock files."
    )
    ap.add_argument("--repo", default=".", help="Path to git repo")
    ap.add_argument("--fresh", type=float, default=DEFAULT_FRESH_SECONDS,
                     help="Seconds before lock is considered aging")
    ap.add_argument("--stale", type=float, default=DEFAULT_STALE_SECONDS,
                     help="Seconds before lock is considered stale")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args(argv)

    try:
        report = scan_lock(args.repo, args.fresh, args.stale)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not report.exists:
        if args.json:
            print(report.to_json())
        else:
            print("No lock file found — clean state.")
        return 2

    if args.json:
        print(report.to_json())
    else:
        print(f"Lock: {report.lock_path}")
        print(f"Age:  {report.age_seconds:.1f}s  ({report.label})")
        print(f"PID:  {'alive' if report.pid_alive else 'none detected'}")
        print(f"Action: {report.recommendation}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
