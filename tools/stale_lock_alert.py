#!/usr/bin/env python3
"""stale_lock_alert.py — alert when .git/index.lock exceeds a staleness threshold.

When the writer or batch committer crashes mid-write, .git/index.lock can
persist and block all future git operations. This tool checks the lock file's
age and returns a structured verdict:

    ok      — no lock file, or age < threshold
    warning — lock file age exceeds threshold but below critical
    critical — lock file age exceeds critical threshold (likely orphaned)

Exit codes:
    0 — ok or warning
    1 — critical (action needed)
    2 — git error or repo not found

Usage:
    python3 tools/stale_lock_alert.py
    python3 tools/stale_lock_alert.py --warn 300 --critical 900
    python3 tools/stale_lock_alert.py --repo /path/to/IamAI
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


DEFAULT_WARN_SEC = 300      # 5 minutes
DEFAULT_CRITICAL_SEC = 900  # 15 minutes


@dataclass
class LockAlert:
    exists: bool
    age_seconds: float
    verdict: str            # "ok" | "warning" | "critical"
    checked_at: str         # ISO-8601
    lock_path: str


def find_repo_root(start: Path = None) -> Path:
    """Walk up from `start` to find the git repository root."""
    cwd = start or Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").is_dir():
            return parent
    return cwd  # fallback


def check_lock(repo: Path, warn_sec: float, critical_sec: float) -> LockAlert:
    """Check .git/index.lock age and produce an alert verdict."""
    lock_path = repo / ".git" / "index.lock"
    now = datetime.now(timezone.utc)

    if not lock_path.exists():
        return LockAlert(
            exists=False,
            age_seconds=0.0,
            verdict="ok",
            checked_at=now.isoformat(),
            lock_path=str(lock_path),
        )

    mtime = datetime.fromtimestamp(lock_path.stat().st_mtime, tz=timezone.utc)
    age = (now - mtime).total_seconds()

    if age >= critical_sec:
        verdict = "critical"
    elif age >= warn_sec:
        verdict = "warning"
    else:
        verdict = "ok"

    return LockAlert(
        exists=True,
        age_seconds=round(age, 2),
        verdict=verdict,
        checked_at=now.isoformat(),
        lock_path=str(lock_path),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=str, default=None,
                        help="Path to git repo (default: auto-detect)")
    parser.add_argument("--warn", type=float, default=DEFAULT_WARN_SEC,
                        help=f"Warning threshold in seconds (default {DEFAULT_WARN_SEC})")
    parser.add_argument("--critical", type=float, default=DEFAULT_CRITICAL_SEC,
                        help=f"Critical threshold in seconds (default {DEFAULT_CRITICAL_SEC})")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON instead of human-readable text")
    args = parser.parse_args(argv)

    repo = Path(args.repo) if args.repo else find_repo_root()
    alert = check_lock(repo, args.warn, args.critical)

    if args.json:
        print(json.dumps(asdict(alert), indent=2))
    else:
        if alert.verdict == "ok" and not alert.exists:
            print("OK: no lock file present")
        elif alert.verdict == "ok":
            print(f"OK: lock file is fresh ({alert.age_seconds:.0f}s old)")
        elif alert.verdict == "warning":
            print(f"WARNING: lock file is {alert.age_seconds:.0f}s old "
                  f"(threshold: {args.warn:.0f}s)")
        else:
            print(f"CRITICAL: lock file is {alert.age_seconds:.0f}s old "
                  f"(threshold: {args.critical:.0f}s) — likely orphaned")

    return 1 if alert.verdict == "critical" else 0


if __name__ == "__main__":
    sys.exit(main())
