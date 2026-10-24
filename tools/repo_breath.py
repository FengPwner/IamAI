#!/usr/bin/env python3
"""CLI: repo_breath — the write-commit cycle as a breathing metaphor.

Usage:
    python3 tools/repo_breath.py              # human-readable (last 50)
    python3 tools/repo_breath.py --last 100   # analyse more commits
    python3 tools/repo_breath.py --json       # machine-readable

Exit codes:
    0  steady   (score ≥ 75)
    1  fair     (50–74: shallow / holding / erratic)
    2  poor     (< 50: distressed)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.repo_breath import breath_report, breath_summary  # noqa: E402


_VERDICT_EXIT = {
    "steady": 0,
    "shallow": 1,
    "holding": 1,
    "erratic": 1,
    "distressed": 2,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure repo breathing pattern")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--last", type=int, default=50, help="number of recent commits")
    parser.add_argument("--repo", type=str, default=str(REPO), help="repo path")
    args = parser.parse_args()

    report = breath_report(repo_path=args.repo, last=args.last)

    if args.json:
        # Exclude individual breaths for cleaner JSON
        data = {
            "breath_count": report.breath_count,
            "breath_rate": report.breath_rate,
            "breath_depth": report.breath_depth,
            "breath_regularity": report.breath_regularity,
            "hold_ratio": report.hold_ratio,
            "hyperventilation": report.hyperventilation,
            "breath_score": report.breath_score,
            "pattern": report.pattern,
            "window_seconds": report.window_seconds,
            "summary": breath_summary(report),
        }
        print(json.dumps(data, indent=2))
    else:
        print(breath_summary(report))
        if report.breath_count > 0:
            print(f"  breaths analysed : {report.breath_count}")
            print(f"  hold ratio       : {report.hold_ratio:.2%}")
            print(f"  hyperventilation : {report.hyperventilation:.2%}")

    return _VERDICT_EXIT.get(report.pattern, 2)


if __name__ == "__main__":
    sys.exit(main())
