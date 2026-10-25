#!/usr/bin/env python3
"""CLI wrapper for iamai.recovery_latency — stall-to-recovery measurement.

Reports how long the system was stalled and whether it has recovered.

Usage:
    python3 tools/recovery_latency.py
    python3 tools/recovery_latency.py --json
    python3 tools/recovery_latency.py --cadence 15 --stall-multiplier 10

Exit codes:
    0  no stalls detected or all stalls recovered
    1  currently stalled (unresolved)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.recovery_latency import measure_recovery, recovery_report  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cadence", type=float, default=15.0,
                    help="expected seconds between strokes (default 15)")
    ap.add_argument("--stall-multiplier", type=float, default=10.0,
                    help="gap must exceed cadence * this to count as stall "
                         "(default 10)")
    ap.add_argument("--json", action="store_true", dest="json_output",
                    help="emit JSON instead of text")
    args = ap.parse_args()

    result = measure_recovery(
        REPO,
        cadence_seconds=args.cadence,
        stall_multiplier=args.stall_multiplier,
    )

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print(recovery_report(
            REPO,
            cadence_seconds=args.cadence,
            stall_multiplier=args.stall_multiplier,
        ))

    # exit 1 only if currently stalled and not recovered
    if result["stalled"] and not result["recovered"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
