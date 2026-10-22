#!/usr/bin/env python3
"""CLI: commit_breadth — how diverse are recent commits?

Usage:
    python3 tools/commit_breadth.py              # human-readable (last 20)
    python3 tools/commit_breadth.py --last 50    # analyse more commits
    python3 tools/commit_breadth.py --json       # machine-readable

Exit codes:
    0  good or excellent (avg ≥ 60 %)
    1  fair (40–59 %)
    2  narrow or single (< 40 %)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.commit_breadth import breadth_report, breadth_summary  # noqa: E402


_GRADE_EXIT = {
    "excellent": 0,
    "good": 0,
    "fair": 1,
    "narrow": 2,
    "single": 2,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure commit breadth")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--last", type=int, default=20, help="number of recent commits")
    parser.add_argument("--repo", type=str, default=str(REPO), help="repo path")
    args = parser.parse_args()

    report = breadth_report(repo_path=args.repo, last=args.last)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(breadth_summary(report))
        print()
        for entry in report.commits:
            cats = ", ".join(entry.categories)
            print(
                f"  {entry.sha[:8]}  "
                f"{entry.breadth_score:5.1f}% ({entry.grade:9s})  "
                f"{entry.files_changed:2d} files  [{cats}]"
            )

    return _GRADE_EXIT.get(report.avg_grade, 0)


if __name__ == "__main__":
    sys.exit(main())
