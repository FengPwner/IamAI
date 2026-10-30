#!/usr/bin/env python3
"""CLI wrapper for iamai.process_graveyard — query the process graveyard.

Usage:
    python3 tools/process_graveyard.py                     # full analysis
    python3 tools/process_graveyard.py --window 6          # last 6 hours
    python3 tools/process_graveyard.py --record --pid 12345 --lifespan 3600
    python3 tools/process_graveyard.py --json              # JSON output

Exit codes:
    0 — analysis complete
    2 — unexpected error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.process_graveyard import (
    analyse,
    record_death,
    GRAVEYARD_FILE,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyse process death events in the graveyard."
    )
    parser.add_argument(
        "--window", type=float, default=24.0,
        help="Look back this many hours (default: 24)."
    )
    parser.add_argument(
        "--writer", type=str, default="qwen",
        help="Writer identity to filter (default: qwen)."
    )
    parser.add_argument(
        "--bucket", type=int, default=10,
        help="Bucket width in minutes for clustering (default: 10)."
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Output as JSON."
    )

    # Record mode
    parser.add_argument(
        "--record", action="store_true",
        help="Record a death event instead of analysing."
    )
    parser.add_argument("--pid", type=int, help="PID of dead process.")
    parser.add_argument(
        "--lifespan", type=float, default=None,
        help="Lifespan in seconds."
    )
    parser.add_argument(
        "--cause", type=str, default="unknown",
        help="Cause of death label."
    )
    parser.add_argument(
        "--restart-after", type=float, default=None,
        help="Seconds until replacement started."
    )
    parser.add_argument(
        "--note", type=str, default="",
        help="Free-form note about this death."
    )

    args = parser.parse_args()

    if args.record:
        event = record_death(
            writer=args.writer,
            pid=args.pid,
            lifespan_seconds=args.lifespan,
            cause=args.cause,
            restart_after_seconds=args.restart_after,
            note=args.note,
        )
        print(f"recorded death: {event['ts']} pid={args.pid}")
        return 0

    try:
        report = analyse(
            writer=args.writer,
            window_hours=args.window,
            bucket_minutes=args.bucket,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"=== Process Graveyard ({args.window}h window) ===")
        print(f"deaths:      {report['death_count']}")
        if report['mean_lifespan_minutes'] is not None:
            print(f"mean life:   {report['mean_lifespan_minutes']:.1f} min")
        else:
            print(f"mean life:   (no data)")
        print(f"death rate:  {report['death_rate_per_hour']:.3f}/hr")
        print(f"clustering:  {report['clustering_score']:.2f}")
        if report['last_death_age_minutes'] is not None:
            print(f"last death:  {report['last_death_age_minutes']:.0f} min ago")
        else:
            print(f"last death:  (none in window)")
        print(f"verdict:     {report['verdict']}")
        if report['cause_distribution']:
            print("causes:")
            for cause, count in sorted(
                report['cause_distribution'].items(),
                key=lambda x: -x[1]
            ):
                print(f"  {cause}: {count}")

        if not GRAVEYARD_FILE.exists():
            print(f"\n(graveyard file does not yet exist: {GRAVEYARD_FILE})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
