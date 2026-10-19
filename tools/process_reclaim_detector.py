#!/usr/bin/env python3
"""CLI wrapper for iamai.process_reclaim_detector — classify process deaths.

Reads the process mortality ledger and scores each death event on how
likely it was caused by a container-runtime reclamation versus an
organic crash.

Usage:
    python3 tools/process_reclaim_detector.py                  # summary
    python3 tools/process_reclaim_detector.py --writer qwen    # filter by writer
    python3 tools/process_reclaim_detector.py --detail         # per-event scores
    python3 tools/process_reclaim_detector.py --json           # JSON output

Exit codes:
    0  analysis complete
    1  no mortality ledger found or empty
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.process_reclaim_detector import (  # noqa: E402
    classify_deaths,
    reclaim_summary,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--writer",
        type=str,
        default=None,
        help="filter by writer identity (e.g. 'qwen')",
    )
    ap.add_argument(
        "--detail",
        action="store_true",
        help="show per-event classification instead of summary",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit machine-readable JSON",
    )
    ap.add_argument(
        "--tz-offset",
        type=int,
        default=8,
        help="timezone offset in hours from UTC (default 8 for GMT+8)",
    )
    args = ap.parse_args()

    # Check ledger exists
    ledger = REPO / "data" / "process_mortality.jsonl"
    if not ledger.exists():
        print("No mortality ledger found at", ledger, file=sys.stderr)
        return 1

    if args.detail:
        results = classify_deaths(
            REPO, writer=args.writer, tz_offset_hours=args.tz_offset
        )
        if not results:
            print("No death events found.", file=sys.stderr)
            return 1

        if args.json_output:
            print(json.dumps(results, indent=2))
        else:
            print(f"{'Timestamp':<28} {'Writer':<8} {'Hour':>5} {'Intv':>5} "
                  f"{'Bundle':>6} {'Score':>6} {'Reclaim?':>9}")
            print("-" * 75)
            for d in results:
                flag = "YES" if d["likely_reclaim"] else "no"
                print(
                    f"{d['ts']:<28} {d.get('writer', '?'):<8} "
                    f"{d['hour_factor']:>5.2f} {d['interval_factor']:>5.2f} "
                    f"{d['bundled_factor']:>6.2f} {d['reclaim_score']:>6.3f} "
                    f"{flag:>9}"
                )
            print(f"\n{len(results)} death(s) analyzed, "
                  f"{sum(1 for d in results if d['likely_reclaim'])} classified as reclaim")
    else:
        summary = reclaim_summary(
            REPO, writer=args.writer, tz_offset_hours=args.tz_offset
        )
        if summary["total_deaths"] == 0:
            print("No death events found.", file=sys.stderr)
            return 1

        if args.json_output:
            print(json.dumps(summary, indent=2))
        else:
            writer_label = args.writer or "all"
            print(f"Process Reclaim Analysis — writer: {writer_label}")
            print(f"  Total deaths analyzed:  {summary['total_deaths']}")
            print(f"  Likely reclaims:        {summary['reclaim_count']}")
            print(f"  Reclaim fraction:       {summary['reclaim_fraction']:.1%}")
            print(f"  Peak reclaim hour:      "
                  f"{summary['peak_hour'] if summary['peak_hour'] is not None else 'N/A'}"
                  f":00 local")
            interval = summary["estimated_interval"]
            interval_str = f"{interval:.0f}s ({interval/60:.0f}min)" if interval else "N/A"
            print(f"  Estimated interval:     {interval_str}")
            print(f"  Avg reclaim score:      {summary['avg_score']:.3f}")
            print(f"  Max reclaim score:      {summary['max_score']:.3f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
