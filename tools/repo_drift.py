#!/usr/bin/env python3
"""repo_drift.py — CLI wrapper for branch drift detection.

Checks how far the local branch has drifted from its remote tracking
branch and reports ahead/behind counts with actionable recommendations.

Usage:
    python3 tools/repo_drift.py
    python3 tools/repo_drift.py --fetch
    python3 tools/repo_drift.py --json

Exit codes:
    0 — synced or ahead (push should succeed)
    1 — behind or diverged (pull/rebase needed)
    2 — no remote tracking branch or error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.repo_drift import drift_report, needs_pull, safe_to_push, summarize  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--fetch",
        action="store_true",
        help="run git fetch before checking (updates remote refs)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="emit structured JSON instead of a one-liner",
    )
    ap.add_argument(
        "--repo",
        type=str,
        default=None,
        help="path to repo root (default: auto-detect)",
    )
    args = ap.parse_args()

    cwd = Path(args.repo) if args.repo else REPO

    report = drift_report(cwd=cwd, fetch=args.fetch)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(summarize(report))

    status = report.get("status", "unknown")

    if status in ("detached", "no_remote"):
        return 2
    if safe_to_push(report):
        return 0
    if needs_pull(report):
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
