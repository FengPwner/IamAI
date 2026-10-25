#!/usr/bin/env python3
"""CLI: stroke_yield — what fraction of writer output survives in commits?

Usage:
    python3 tools/stroke_yield.py              # human-readable
    python3 tools/stroke_yield.py --json       # machine-readable

Exit codes:
    0  excellent or good (≥ 90 %)
    1  fair or poor (50–89 %)
    2  critical (< 50 %)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_yield import stroke_yield_report, yield_summary  # noqa: E402


_GRADE_EXIT = {
    "excellent": 0,
    "good": 0,
    "fair": 1,
    "poor": 1,
    "critical": 2,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure stroke yield")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--repo", type=str, default=str(REPO), help="repo path")
    args = parser.parse_args()

    report = stroke_yield_report(repo_path=args.repo)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(yield_summary(report))

    return _GRADE_EXIT.get(report.grade, 0)


if __name__ == "__main__":
    sys.exit(main())
