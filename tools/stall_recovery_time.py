#!/usr/bin/env python3
"""Measure stall-to-recovery latency from stroke timestamps.

A *stall* is any gap between consecutive strokes that exceeds a given
threshold (default: 2x the writer's configured interval).  The
*recovery latency* is the wall-clock time from the end of the stall
(i.e. the next stroke) back to when the stall began.

This module reads ``data/strokes.jsonl`` and emits per-stall records
plus an aggregate verdict:

    healthy   — all recoveries < 5 min
    degraded  — median recovery < 15 min but at least one > 5 min
    slow      — median recovery >= 15 min
    stuck     — any recovery > 1 hour

Usage:
    python3 tools/stall_recovery_time.py
    python3 tools/stall_recovery_time.py --threshold 300   # custom stall threshold (seconds)
    python3 tools/stall_recovery_time.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"


# ---------------------------------------------------------------------------
# pure helpers (no I/O — easy to test)
# ---------------------------------------------------------------------------

def detect_stalls(
    timestamps: List[datetime],
    threshold_seconds: float = 300.0,
) -> List[Dict]:
    """Find stalls in a sorted list of stroke timestamps.

    Returns a list of dicts, each with:
        stall_start  — timestamp of the last stroke before the gap
        stall_end    — timestamp of the first stroke after the gap
        gap_seconds  — length of the gap
    """
    stalls: List[Dict] = []
    for i in range(1, len(timestamps)):
        gap = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if gap > threshold_seconds:
            stalls.append({
                "stall_start": timestamps[i - 1],
                "stall_end": timestamps[i],
                "gap_seconds": gap,
            })
    return stalls


def classify_recovery(gap_seconds: float) -> str:
    """Classify a single recovery latency.

    Categories:
        instant  — gap < 60 s  (writer barely hiccupped)
        quick    — gap < 300 s (recovered within one batch cycle)
        slow     — gap < 3600 s (took a while but came back)
        stuck    — gap >= 3600 s (serious stall)
    """
    if gap_seconds < 60:
        return "instant"
    if gap_seconds < 300:
        return "quick"
    if gap_seconds < 3600:
        return "slow"
    return "stuck"


def verdict(stalls: List[Dict]) -> str:
    """Aggregate verdict over all stall recoveries.

    healthy  — all recoveries < 5 min
    degraded — median < 15 min but at least one > 5 min
    slow     — median >= 15 min
    stuck    — any recovery > 1 hour
    """
    if not stalls:
        return "healthy"

    gaps = [s["gap_seconds"] for s in stalls]
    max_gap = max(gaps)
    med = median(gaps)

    if max_gap >= 3600:
        return "stuck"
    if med >= 900:
        return "slow"
    if max_gap >= 300:
        return "degraded"
    return "healthy"


def summarize(stalls: List[Dict]) -> Dict:
    """Produce a summary dict from a list of stalls."""
    if not stalls:
        return {
            "total_stalls": 0,
            "verdict": "healthy",
            "median_gap_seconds": 0.0,
            "max_gap_seconds": 0.0,
            "categories": {},
        }

    gaps = [s["gap_seconds"] for s in stalls]
    categories: Dict[str, int] = {}
    for s in stalls:
        cat = classify_recovery(s["gap_seconds"])
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "total_stalls": len(stalls),
        "verdict": verdict(stalls),
        "median_gap_seconds": median(gaps),
        "max_gap_seconds": max(gaps),
        "categories": categories,
    }


# ---------------------------------------------------------------------------
# I/O layer
# ---------------------------------------------------------------------------

def load_stroke_timestamps(path: Path = STROKES_PATH) -> List[datetime]:
    """Parse stroke timestamps from strokes.jsonl."""
    timestamps: List[datetime] = []
    if not path.exists():
        return timestamps

    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                ts = datetime.fromisoformat(record["at"])
                timestamps.append(ts)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

    timestamps.sort()
    return timestamps


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--threshold",
        type=float,
        default=300.0,
        help="stall threshold in seconds (default: 300)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit machine-readable JSON",
    )
    args = ap.parse_args()

    timestamps = load_stroke_timestamps()
    if len(timestamps) < 2:
        print("insufficient stroke data", file=sys.stderr)
        return 1

    stalls = detect_stalls(timestamps, args.threshold)
    summary = summarize(stalls)

    if args.json_output:
        # serialize datetimes for JSON
        serializable = []
        for s in stalls:
            serializable.append({
                "stall_start": s["stall_start"].isoformat(),
                "stall_end": s["stall_end"].isoformat(),
                "gap_seconds": s["gap_seconds"],
                "category": classify_recovery(s["gap_seconds"]),
            })
        output = {**summary, "stalls": serializable}
        print(json.dumps(output, indent=2))
    else:
        print(f"stall recovery analysis  (threshold: {args.threshold:.0f}s)")
        print(f"total stalls: {summary['total_stalls']}")
        print(f"verdict:      {summary['verdict']}")
        print(f"median gap:   {summary['median_gap_seconds']:.0f}s")
        print(f"max gap:      {summary['max_gap_seconds']:.0f}s")
        if summary["categories"]:
            print()
            print("categories:")
            for cat in ["instant", "quick", "slow", "stuck"]:
                count = summary["categories"].get(cat, 0)
                if count:
                    print(f"  {cat:<10} {count}")
        if stalls:
            print()
            print(f"{'stall start':<28} {'stall end':<28} {'gap':>8} {'category':<10}")
            print("-" * 80)
            for s in stalls[-20:]:  # last 20
                print(
                    f"{s['stall_start'].isoformat():<28} "
                    f"{s['stall_end'].isoformat():<28} "
                    f"{s['gap_seconds']:>7.0f}s "
                    f"{classify_recovery(s['gap_seconds']):<10}"
                )

    return 0


if __name__ == "__main__":
    sys.exit(main())
