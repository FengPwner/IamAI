#!/usr/bin/env python3
"""stroke_pacer.py — CLI wrapper for daily stroke pacing.

Reads data/strokes.jsonl and answers: are we on track for today's target?

Reports:
  - strokes_today: how many strokes since midnight UTC
  - remaining: daily target minus today's count
  - required_rate: strokes/hr needed from now to hit the target
  - current_rate: actual strokes/hr over the last hour
  - verdict: ahead / on_track / behind
  - projected_total: where we land at midnight if current rate holds

Usage:
    python3 tools/stroke_pacer.py
    python3 tools/stroke_pacer.py --target 2000
    python3 tools/stroke_pacer.py --json
    python3 tools/stroke_pacer.py --rate-window 2.0

Exit codes:
    0  — on_track or ahead
    1  — behind pace
    2  — no strokes found or data error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_pacer import pace_report, pace_summary  # noqa: E402

DEFAULT_TARGET = 1000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--target",
        type=int,
        default=DEFAULT_TARGET,
        help=f"daily stroke target (default {DEFAULT_TARGET})",
    )
    ap.add_argument(
        "--rate-window",
        type=float,
        default=1.0,
        help="hours of recent history for current rate (default 1.0)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="emit structured JSON instead of a one-liner",
    )
    ap.add_argument(
        "--strokes",
        type=str,
        default=None,
        help="path to strokes.jsonl (default data/strokes.jsonl)",
    )
    args = ap.parse_args()

    strokes_path = Path(args.strokes) if args.strokes else REPO / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        print(f"error: strokes file not found: {strokes_path}", file=sys.stderr)
        return 2

    report = pace_report(
        daily_target=args.target,
        strokes_path=strokes_path,
        rate_window_hours=args.rate_window,
    )

    if report["strokes_today"] == 0 and report["remaining"] == args.target:
        # No strokes at all today — likely data issue or writer never started
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"no strokes recorded today (target {args.target})")
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(pace_summary(daily_target=args.target, strokes_path=strokes_path))

    return 0 if report["verdict"] != "behind" else 1


if __name__ == "__main__":
    sys.exit(main())
