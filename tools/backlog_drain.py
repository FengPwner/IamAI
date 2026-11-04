#!/usr/bin/env python3
"""CLI: backlog_drain — measure how fast uncommitted files are being flushed.

Usage:
    python3 tools/backlog_drain.py
    python3 tools/backlog_drain.py --json
    python3 tools/backlog_drain.py --snapshots 5

Exit codes:
    0  draining   (committer outpacing writer, rate < -1 fpm)
    1  steady     (balanced, -1 ≤ rate ≤ 1 fpm)
    2  growing    (backlog accumulating, rate > 1 fpm)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.backlog_drain import (  # noqa: E402
    classify,
    drain_rate,
    drain_report,
    snapshot,
)


_EXIT_MAP = {"draining": 0, "steady": 1, "growing": 2}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure backlog drain rate (uncommitted file flux).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--snapshots", type=int, default=1,
        help="Number of snapshots to collect (default: 1, instant read).",
    )
    parser.add_argument(
        "--interval", type=float, default=2.0,
        help="Seconds between snapshots when collecting >1 (default: 2.0).",
    )
    parser.add_argument(
        "--repo", type=str, default=None,
        help="Path to repository root (default: auto-detect).",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo) if args.repo else REPO
    history = []

    for i in range(args.snapshots):
        s = snapshot(repo)
        history.append(s)
        if i < args.snapshots - 1:
            time.sleep(args.interval)

    rate = drain_rate(history)
    verdict = classify(rate)
    current = history[-1]

    if args.json:
        print(json.dumps({
            "verdict": verdict,
            "rate_fpm": round(rate, 2),
            "pending": current["count"],
            "snapshots": len(history),
        }, indent=2))
    else:
        print(drain_report(repo, history))

    return _EXIT_MAP.get(verdict, 1)


if __name__ == "__main__":
    sys.exit(main())
