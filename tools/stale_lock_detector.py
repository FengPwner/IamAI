#!/usr/bin/env python3
"""stale_lock_detector.py — find and report stale .git/index.lock files.

A stale lock blocks every git write with a cryptic fatal error. This
tool detects locks older than a configurable threshold so the caretaker
can clean them before they stall the commit pipeline.

Usage:
    python3 tools/stale_lock_detector.py                  # check, exit 1 if stale
    python3 tools/stale_lock_detector.py --threshold 120  # custom age in seconds
    python3 tools/stale_lock_detector.py --clean          # remove stale lock
    python3 tools/stale_lock_detector.py --json           # machine-readable
"""

import argparse
import json
import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def find_lock(repo: Path = REPO) -> Path:
    """Return the path to .git/index.lock."""
    return repo / ".git" / "index.lock"


def lock_age_seconds(lock_path: Path, now: float | None = None) -> float | None:
    """Seconds since the lock was last modified. None if missing."""
    if not lock_path.exists():
        return None
    mtime = lock_path.stat().st_mtime
    return (now or time.time()) - mtime


def is_stale(lock_path: Path, threshold: int = 300, now: float | None = None) -> bool:
    """True when the lock exists and is older than threshold seconds."""
    age = lock_age_seconds(lock_path, now=now)
    if age is None:
        return False
    return age >= threshold


def clean_lock(lock_path: Path) -> bool:
    """Remove the lock file. Returns True if removed, False if absent."""
    if not lock_path.exists():
        return False
    lock_path.unlink()
    return True


def detect(repo: Path = REPO, threshold: int = 300, now: float | None = None) -> dict:
    """Run detection and return a structured report."""
    lock = find_lock(repo)
    exists = lock.exists()
    age = lock_age_seconds(lock, now=now)
    stale = is_stale(lock, threshold=threshold, now=now) if exists else False
    return {
        "lock_path": str(lock),
        "exists": exists,
        "age_seconds": round(age, 1) if age is not None else None,
        "threshold_seconds": threshold,
        "stale": stale,
    }


def format_text(report: dict) -> str:
    """Human-readable one-liner."""
    if not report["exists"]:
        return "no lock file — clean"
    if report["stale"]:
        return f"STALE lock: {report['age_seconds']}s old (threshold {report['threshold_seconds']}s)"
    return f"lock present but fresh: {report['age_seconds']}s old (threshold {report['threshold_seconds']}s)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threshold", type=int, default=300,
                     help="seconds before a lock is considered stale (default 300)")
    ap.add_argument("--clean", action="store_true",
                     help="remove stale lock if found")
    ap.add_argument("--json", action="store_true",
                     help="machine-readable output")
    ap.add_argument("--repo", type=Path, default=REPO,
                     help="repo root (default: auto-detect)")
    args = ap.parse_args()

    report = detect(repo=args.repo, threshold=args.threshold)

    if args.clean and report["stale"]:
        removed = clean_lock(find_lock(args.repo))
        report["cleaned"] = removed

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_text(report))

    return 1 if report["stale"] and not report.get("cleaned") else 0


if __name__ == "__main__":
    raise SystemExit(main())
