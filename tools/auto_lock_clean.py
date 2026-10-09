#!/usr/bin/env python3
"""auto_lock_clean.py — detect and remove stale .git/index.lock before commits.

Designed to run as a pre-commit hook or before the batch committer cycle.
If a lock file is older than the threshold, it is almost certainly from a
crashed git process and safe to remove.

Usage:
    python3 tools/auto_lock_clean.py                  # check + clean if stale
    python3 tools/auto_lock_clean.py --threshold 60   # custom age (seconds)
    python3 tools/auto_lock_clean.py --dry-run        # report only, don't remove
    python3 tools/auto_lock_clean.py --json           # machine-readable output

Exit codes:
    0 — no stale lock found (or stale lock successfully cleaned)
    1 — stale lock found but --dry-run prevented removal
    2 — unexpected error
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_THRESHOLD = 120  # seconds — git operations should never take 2 minutes


def lock_path(repo: Path = REPO) -> Path:
    """Return the expected path to .git/index.lock."""
    return repo / ".git" / "index.lock"


def lock_age(lock: Path, now: float | None = None) -> float | None:
    """Seconds since the lock was last modified. None if absent."""
    if not lock.exists():
        return None
    try:
        return (now or time.time()) - lock.stat().st_mtime
    except OSError:
        return None


def is_stale(lock: Path, threshold: int = DEFAULT_THRESHOLD,
             now: float | None = None) -> bool:
    """True when lock exists and exceeds the age threshold."""
    age = lock_age(lock, now=now)
    if age is None:
        return False
    return age >= threshold


def clean(lock: Path) -> dict:
    """Attempt to remove the lock file. Returns action result."""
    if not lock.exists():
        return {"action": "none", "reason": "lock absent"}
    try:
        lock.unlink()
        return {"action": "cleaned", "path": str(lock)}
    except OSError as e:
        return {"action": "error", "reason": str(e)}


def run(repo: Path = REPO, threshold: int = DEFAULT_THRESHOLD,
        dry_run: bool = False, now: float | None = None) -> dict:
    """Full diagnostic + optional cleanup. Returns structured report."""
    lock = lock_path(repo)
    exists = lock.exists()
    age = lock_age(lock, now=now)
    stale = is_stale(lock, threshold=threshold, now=now) if exists else False

    report = {
        "lock_path": str(lock),
        "exists": exists,
        "age_seconds": round(age, 1) if age is not None else None,
        "threshold_seconds": threshold,
        "stale": stale,
    }

    if stale and not dry_run:
        result = clean(lock)
        report["action"] = result.get("action", "unknown")
        if "reason" in result:
            report["reason"] = result["reason"]
    elif stale and dry_run:
        report["action"] = "dry_run"
    else:
        report["action"] = "none"

    return report


def exit_code(report: dict) -> int:
    """Map report to exit code: 0 = ok, 1 = stale but not cleaned."""
    if report.get("action") == "dry_run" and report.get("stale"):
        return 1
    if report.get("action") == "error":
        return 2
    return 0


def format_text(report: dict) -> str:
    """One-line human-readable summary."""
    if not report["exists"]:
        return "no lock — clean"
    if report.get("action") == "cleaned":
        return f"STALE lock ({report['age_seconds']}s) — cleaned"
    if report.get("action") == "dry_run":
        return f"STALE lock ({report['age_seconds']}s) — dry run, not removed"
    if report["stale"]:
        return f"STALE lock ({report['age_seconds']}s) — needs cleanup"
    return f"lock present but fresh ({report['age_seconds']}s)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                    help=f"seconds before lock is stale (default {DEFAULT_THRESHOLD})")
    ap.add_argument("--dry-run", action="store_true",
                    help="report without removing")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable output")
    ap.add_argument("--repo", type=Path, default=REPO,
                    help="repo root path")
    args = ap.parse_args()

    report = run(repo=args.repo, threshold=args.threshold, dry_run=args.dry_run)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_text(report))

    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
