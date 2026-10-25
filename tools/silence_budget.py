#!/usr/bin/env python3
"""CLI: silence budget — how much stalling the window can still absorb.

Usage:
    python3 tools/silence_budget.py                  # default 24h window
    python3 tools/silence_budget.py --window 12      # last 12 hours
    python3 tools/silence_budget.py --cadence 30     # 30s cadence
    python3 tools/silence_budget.py --json           # machine-readable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.silence_budget import (  # noqa: E402
    SilenceBudget,
    extract_stall_gaps,
    silence_report,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Silence budget for the writer.")
    ap.add_argument("--cadence", type=int, default=15,
                    help="expected inter-stroke gap in seconds (default 15)")
    ap.add_argument("--window", type=int, default=24,
                    help="rolling window in hours (default 24)")
    ap.add_argument("--fraction", type=float, default=0.10,
                    help="max silence fraction of window (default 0.10)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    report = silence_report(
        cadence_seconds=args.cadence,
        window_hours=args.window,
        max_fraction=args.fraction,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        sb = SilenceBudget(
            cadence_seconds=args.cadence,
            window_hours=args.window,
            max_fraction=args.fraction,
        )
        gaps = extract_stall_gaps(
            cadence_seconds=args.cadence,
            window_hours=args.window,
        )
        from iamai.silence_budget import BudgetResult
        result = sb.evaluate(gaps)
        print(result.describe())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
