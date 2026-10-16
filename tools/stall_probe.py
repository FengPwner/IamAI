#!/usr/bin/env python3
"""CLI wrapper for iamai.stall_probe — multi-signal health probe.

Runs four health signals (writer alive, batch alive, stroke freshness,
backlog pressure) and emits a single verdict: healthy / degraded / stalled.

Usage:
    python3 tools/stall_probe.py              # human-readable
    python3 tools/stall_probe.py --json       # machine-readable
    python3 tools/stall_probe.py --writer qwen --cadence 15 --backlog-threshold 20

Exit codes:
    0  healthy
    1  degraded or stalled — caretaker should investigate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stall_probe import probe, probe_report  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default="qwen",
                    help="writer id (default: qwen)")
    ap.add_argument("--cadence", type=float, default=15.0,
                    help="expected seconds between strokes (default 15)")
    ap.add_argument("--fresh-threshold", type=float, default=5.0,
                    help="stroke age (cadence multiples) before signal goes red")
    ap.add_argument("--backlog-threshold", type=int, default=20,
                    help="uncommitted file count before signal goes red")
    ap.add_argument("--json", action="store_true", dest="json_output",
                    help="emit JSON instead of text")
    args = ap.parse_args()

    result = probe(
        REPO,
        writer_id=args.writer,
        cadence_seconds=args.cadence,
        fresh_threshold=args.fresh_threshold,
        backlog_threshold=args.backlog_threshold,
    )

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print(probe_report(REPO, writer_id=args.writer,
                           cadence_seconds=args.cadence,
                           fresh_threshold=args.fresh_threshold,
                           backlog_threshold=args.backlog_threshold))

    return 0 if result["verdict"] == "healthy" else 1


if __name__ == "__main__":
    sys.exit(main())
