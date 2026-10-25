#!/usr/bin/env python3
"""CLI: repo_metabolism — measure the repository's productive metabolism.

Usage:
    python3 tools/repo_metabolism.py              # human-readable (last 50)
    python3 tools/repo_metabolism.py --last 100   # analyse more commits
    python3 tools/repo_metabolism.py --json       # machine-readable

Exit codes:
    0  thriving or healthy (score ≥ 55)
    1  stagnant            (40–54)
    2  stressed or dormant (< 40)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.repo_metabolism import (  # noqa: E402
    metabolism_report,
    metabolism_summary,
)


_VERDICT_EXIT = {
    "thriving": 0,
    "healthy": 0,
    "stagnant": 1,
    "stressed": 2,
    "dormant": 2,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure the repository's productive metabolism"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--last", type=int, default=50, help="number of recent commits")
    parser.add_argument("--repo", type=str, default=str(REPO), help="repo path")
    args = parser.parse_args()

    report = metabolism_report(repo_path=args.repo, last=args.last)

    if args.json:
        data = {
            "commit_count": report.commit_count,
            "metabolic_rate": report.metabolic_rate,
            "productive_ratio": report.productive_ratio,
            "overhead_ratio": report.overhead_ratio,
            "neutral_ratio": report.neutral_ratio,
            "anabolic_ratio": report.anabolic_ratio,
            "efficiency_score": report.efficiency_score,
            "state": report.state,
            "window_seconds": report.window_seconds,
            "summary": metabolism_summary(report),
        }
        print(json.dumps(data, indent=2))
    else:
        print(metabolism_summary(report))
        if report.commit_count > 0:
            print(f"  commits analysed : {report.commit_count}")
            print(f"  anabolic ratio   : {report.anabolic_ratio:.2%}")
            print(f"  window           : {report.window_seconds / 3600:.1f} hours")

    return _VERDICT_EXIT.get(report.state, 2)


if __name__ == "__main__":
    sys.exit(main())
