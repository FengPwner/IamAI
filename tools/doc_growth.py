#!/usr/bin/env python3
"""CLI wrapper for iamai.doc_growth — track documentation file growth.

Scans key repo files (DEVLOG, GARDEN, METRICS, strokes.jsonl, notes)
and reports current size, growth rate, and estimated time to compaction
threshold.

Usage:
    python3 tools/doc_growth.py                  # human-readable report
    python3 tools/doc_growth.py --json           # machine-readable JSON
    python3 tools/doc_growth.py --threshold 500  # alert at 500KB
    python3 tools/doc_growth.py --lookback 12    # 12-hour lookback window

Exit codes:
    0  all files under threshold
    1  at least one file needs compaction
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.doc_growth import (  # noqa: E402
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_THRESHOLD,
    growth_report,
    growth_summary,
    scan_growth,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        help=f"compaction threshold in bytes (default {DEFAULT_THRESHOLD})",
    )
    ap.add_argument(
        "--lookback",
        type=float,
        default=DEFAULT_LOOKBACK_HOURS,
        help=f"lookback window in hours (default {DEFAULT_LOOKBACK_HOURS})",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit JSON instead of a human-readable report",
    )
    args = ap.parse_args()

    if args.json_output:
        results = scan_growth(
            REPO,
            threshold=args.threshold,
            lookback_hours=args.lookback,
        )
        summary = growth_summary(results)
        print(json.dumps({"files": results, "summary": summary}, indent=2))
    else:
        print(
            growth_report(
                REPO,
                threshold=args.threshold,
                lookback_hours=args.lookback,
            )
        )

    # Exit 1 if any file needs compaction
    results = scan_growth(
        REPO,
        threshold=args.threshold,
        lookback_hours=args.lookback,
    )
    if any(r["needs_compaction"] for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
