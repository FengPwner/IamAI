#!/usr/bin/env python3
"""CLI: commit momentum — is the commit rate accelerating or slowing?

Usage:
    python3 tools/commit_momentum.py                # default 12h window
    python3 tools/commit_momentum.py --window 6     # last 6 hours
    python3 tools/commit_momentum.py --json          # machine-readable

Exit codes:
    0  steady or accelerating
    1  decelerating
    2  stalled (no recent commits)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.commit_momentum import (  # noqa: E402
    CommitMomentum,
    fetch_commit_timestamps,
)

_VERDICT_EXIT = {
    "accelerating": 0,
    "steady": 0,
    "decelerating": 1,
    "stalled": 2,
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Commit momentum indicator.")
    ap.add_argument("--window", type=float, default=12.0,
                    help="rolling window in hours (default 12)")
    ap.add_argument("--accel", type=float, default=1.30,
                    help="acceleration threshold (default 1.30)")
    ap.add_argument("--decel", type=float, default=0.70,
                    help="deceleration threshold (default 0.70)")
    ap.add_argument("--stall", type=float, default=0.30,
                    help="stall threshold (default 0.30)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    cm = CommitMomentum(
        window_hours=args.window,
        accel_threshold=args.accel,
        decel_threshold=args.decel,
        stall_threshold=args.stall,
    )
    timestamps = fetch_commit_timestamps(repo=REPO)
    result = cm.evaluate(timestamps)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(
            f"commit momentum: {result.verdict}  "
            f"(newer={result.newer_count}, older={result.older_count}, "
            f"ratio={result.ratio:.2f}, window={result.window_hours}h)"
        )

    return _VERDICT_EXIT.get(result.verdict, 0)


if __name__ == "__main__":
    sys.exit(main())
