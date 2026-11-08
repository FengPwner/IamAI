#!/usr/bin/env python3
"""CLI wrapper for iamai.heartbeat_regularity — measure writing rhythm health.

Reads stroke timestamps from data/strokes.jsonl and reports rhythm
metrics.  Useful for caretaker visits to quickly assess whether the
writer is producing at a steady cadence or lurching between bursts
and silences.

Usage:
    python3 tools/heartbeat_regularity.py              # all strokes
    python3 tools/heartbeat_regularity.py -n 100       # last 100 strokes
    python3 tools/heartbeat_regularity.py --json        # machine-readable
    python3 tools/heartbeat_regularity.py --interval 30 # custom expected interval
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.heartbeat_regularity import (  # noqa: E402
    HeartbeatMonitor,
    regularity_report,
)

STROKES_FILE = REPO / "data" / "strokes.jsonl"


def load_strokes(n: int | None = None) -> list[float]:
    """Load stroke timestamps from strokes.jsonl."""
    if not STROKES_FILE.exists():
        return []
    timestamps = []
    with open(STROKES_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                ts = record.get("timestamp") or record.get("ts") or record.get("time")
                if ts is not None:
                    timestamps.append(float(ts))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
    timestamps.sort()
    if n is not None and len(timestamps) > n:
        timestamps = timestamps[-n:]
    return timestamps


def main():
    parser = argparse.ArgumentParser(
        description="Measure writing rhythm health from stroke timestamps."
    )
    parser.add_argument(
        "-n", "--count", type=int, default=None,
        help="Number of recent strokes to analyze (default: all).",
    )
    parser.add_argument(
        "--interval", type=float, default=15.0,
        help="Expected interval between strokes in seconds (default: 15).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output machine-readable JSON.",
    )
    args = parser.parse_args()

    timestamps = load_strokes(args.count)

    monitor = HeartbeatMonitor(expected_interval=args.interval)
    monitor.record_strokes(timestamps)

    if args.json:
        print(json.dumps(monitor.summary(), indent=2, default=str))
    else:
        print(regularity_report(monitor))


if __name__ == "__main__":
    main()
