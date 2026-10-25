#!/usr/bin/env python3
"""CLI: repo_respiration — measure the repository's breathing rhythm.

Usage:
    python3 tools/repo_respiration.py                      # human-readable
    python3 tools/repo_respiration.py --last 200           # fewer commits
    python3 tools/repo_respiration.py --json               # machine-readable
    python3 tools/repo_respiration.py --interval 300       # custom batch interval

Exit codes:
    0  eupnea or acceptable rhythm (score >= 55)
    1  degraded rhythm (score < 55)
    2  dormant (not enough data)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.repo_respiration import (  # noqa: E402
    respiration_report,
    respiration_summary,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Repo respiration check")
    ap.add_argument("--last", type=int, default=500, help="commits to analyse")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--interval", type=int, default=600, help="batch interval (s)")
    ap.add_argument("--apnea", type=int, default=1800, help="apnea threshold (s)")
    args = ap.parse_args()

    report = respiration_report(
        repo_path=REPO,
        last=args.last,
        batch_interval=args.interval,
        apnea_threshold=args.apnea,
    )

    if args.json:
        from dataclasses import asdict
        print(json.dumps(asdict(report), indent=2))
    else:
        print(respiration_summary(report))

    if report.pattern == "dormant":
        return 2
    return 0 if report.respiration_score >= 55 else 1


if __name__ == "__main__":
    sys.exit(main())
