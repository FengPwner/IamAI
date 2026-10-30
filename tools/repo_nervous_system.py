#!/usr/bin/env python3
"""CLI: repo_nervous_system — measure signal propagation and reflex integrity.

Usage:
    python3 tools/repo_nervous_system.py              # human-readable (last 50)
    python3 tools/repo_nervous_system.py --last 100   # analyse more commits
    python3 tools/repo_nervous_system.py --json       # machine-readable

Exit codes:
    0  sharp or responsive (integrity ≥ 60%)
    1  dulled               (40–59%)
    2  neuropathic or dormant (< 40% or no data)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.repo_nervous_system import (  # noqa: E402
    nerve_report,
    nerve_summary,
)


_VERDICT_EXIT = {
    "sharp": 0,
    "responsive": 0,
    "dulled": 1,
    "neuropathic": 2,
    "dormant": 2,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure the repository's nervous-system health"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--last", type=int, default=50, help="number of recent commits")
    parser.add_argument("--repo", type=str, default=str(REPO), help="repo path")
    args = parser.parse_args()

    report = nerve_report(repo_path=args.repo, last=args.last)

    if args.json:
        data = {
            "detector_count": report.detector_count,
            "responder_count": report.responder_count,
            "paired_reflexes": report.paired_reflexes,
            "orphan_detectors": report.orphan_detectors,
            "orphan_responders": report.orphan_responders,
            "lesions": report.lesions,
            "mean_reflex_latency_s": report.mean_reflex_latency_s,
            "reflex_integrity": report.reflex_integrity,
            "nerve_health": report.nerve_health,
            "commit_count": report.commit_count,
            "summary": nerve_summary(report),
        }
        print(json.dumps(data, indent=2))
    else:
        print(nerve_summary(report))
        if report.commit_count > 0:
            print(f"  commits analysed : {report.commit_count}")
            print(f"  detectors present: {report.detector_count}")
            print(f"  responders       : {report.responder_count}")
            if report.orphan_detectors:
                print(f"  orphan detectors : {', '.join(report.orphan_detectors)}")
            if report.orphan_responders:
                print(f"  orphan responders: {', '.join(report.orphan_responders)}")
            if report.lesions:
                print(f"  lesions (missing): {', '.join(report.lesions)}")

    return _VERDICT_EXIT.get(report.nerve_health, 2)


if __name__ == "__main__":
    sys.exit(main())
