#!/usr/bin/env python3
"""CLI: repo_circadian_rhythm — measure the repository's activity rhythm.

Usage:
    python3 tools/repo_circadian_rhythm.py              # human-readable (last 500)
    python3 tools/repo_circadian_rhythm.py --last 200   # analyse fewer commits
    python3 tools/repo_circadian_rhythm.py --json       # machine-readable
    python3 tools/repo_circadian_rhythm.py --tz 8       # UTC+8 offset

Exit codes:
    0  entrained or rhythmic (score ≥ 55)
    1  arrhythmic or jetlagged (score < 55)
    2  dormant (not enough data)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.repo_circadian_rhythm import (  # noqa: E402
    circadian_report,
    circadian_summary,
)


_VERDICT_EXIT = {
    "entrained": 0,
    "rhythmic": 0,
    "arrhythmic": 1,
    "jetlagged": 1,
    "dormant": 2,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure the repository's circadian rhythm"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--last", type=int, default=500, help="number of recent commits")
    parser.add_argument("--tz", type=int, default=0, help="UTC offset hours (e.g. 8)")
    parser.add_argument(
        "--work-start", type=int, default=8, help="work hours start (0-23)"
    )
    parser.add_argument(
        "--work-end", type=int, default=22, help="work hours end (0-23)"
    )
    parser.add_argument("--repo", type=str, default=str(REPO), help="repo path")
    args = parser.parse_args()

    report = circadian_report(
        repo_path=args.repo,
        last=args.last,
        work_start=args.work_start,
        work_end=args.work_end,
        tz_offset_hours=args.tz,
    )

    if args.json:
        data = {
            "hourly_distribution": report.hourly_distribution,
            "peak_hour": report.peak_hour,
            "trough_hour": report.trough_hour,
            "amplitude": report.amplitude,
            "rest_depth": report.rest_depth,
            "phase_alignment": report.phase_alignment,
            "regularity_score": report.regularity_score,
            "rhythm_score": report.rhythm_score,
            "rhythm_state": report.rhythm_state,
            "total_commits": report.total_commits,
            "active_days": report.active_days,
        }
        json.dump(data, sys.stdout, indent=2)
        print()
    else:
        print(circadian_summary(report))

    return _VERDICT_EXIT.get(report.rhythm_state, 1)


if __name__ == "__main__":
    sys.exit(main())
