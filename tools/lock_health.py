#!/usr/bin/env python3
"""lock_health.py — detect stale git lock files that block operations.

Checks known lock-file paths and cross-references the process table.
A lock with no running git process is stale and safe to remove.

Usage:
    python3 tools/lock_health.py
    python3 tools/lock_health.py --json
    python3 tools/lock_health.py --fix          # remove stale locks
    python3 tools/lock_health.py --max-age 120  # custom age threshold

Exit codes:
    0  — no stale locks
    1  — stale locks detected
    2  — error (e.g. not a git repo)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.lock_health import scan_locks, summary  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--max-age",
        type=float,
        default=60,
        help="seconds before a lock is considered stale by age (default 60)",
    )
    ap.add_argument(
        "--fix",
        action="store_true",
        help="remove stale lock files automatically",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="emit structured JSON output",
    )
    args = ap.parse_args()

    if not (REPO / ".git").exists():
        print(f"error: {REPO} is not a git repository", file=sys.stderr)
        return 2

    result = scan_locks(repo=REPO, max_age=args.max_age, remove_stale=args.fix)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(summary(repo=REPO, max_age=args.max_age))
        if args.fix and result["cleaned"] > 0:
            print(f"  cleaned {result['cleaned']} stale lock(s)")

    return 1 if result["stale_count"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
