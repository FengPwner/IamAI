#!/usr/bin/env python3
"""CLI: commit_hygiene — composite health score for the commit graph.

Usage:
    python3 tools/commit_hygiene.py              # human-readable (last 20)
    python3 tools/commit_hygiene.py --last 50    # analyse more commits
    python3 tools/commit_hygiene.py --json       # machine-readable

Exit codes:
    0  healthy (≥ 75)
    1  fair (50–74)
    2  poor (< 50)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.commit_hygiene import hygiene_report, hygiene_summary  # noqa: E402


_VERDICT_EXIT = {
    "healthy": 0,
    "fair": 1,
    "poor": 2,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure commit hygiene")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--last", type=int, default=20, help="number of recent commits")
    parser.add_argument("--repo", type=str, default=str(REPO), help="repo path")
    args = parser.parse_args()

    report = hygiene_report(repo=args.repo, n=args.last)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(hygiene_summary(report))

    return _VERDICT_EXIT.get(report.verdict, 0)


if __name__ == "__main__":
    sys.exit(main())
