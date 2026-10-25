#!/usr/bin/env python3
"""Measure correlation between batch commit interval and stall recovery time.

Hypothesis (from caretaker visit 257): if the batch runs every N seconds
but the writer stalls every ~30 min, recovery latency may be dominated by
the time between batch cycles rather than the stall itself.

This module reads ``data/strokes.jsonl``, detects stalls, then checks
whether recovery endpoints cluster around multiples of the batch interval.

Output:
    - per-stall records with gap, recovery, and nearest-batch-multiple
    - cluster_score: fraction of recoveries within ±60s of a batch multiple
    - verdict:
        correlated   — cluster_score >= 0.6
        weak         — cluster_score >= 0.3
        independent  — cluster_score <  0.3

Usage:
    python3 tools/batch_recovery_correlation.py
    python3 tools/batch_recovery_correlation.py --batch-interval 600
    python3 tools/batch_recovery_correlation.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
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
    """Find stalls in a sorted list of stroke timestamps."""
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


def nearest_batch_multiple(
    recovery_seconds: float,
    batch_interval: float,
) -> Tuple[int, float]:
    """Return (nearest_multiple, distance_to_nearest).

    >>> nearest_batch_multiple(620.0, 600.0)
    (1, 20.0)
    >>> nearest_batch_multiple(1180.0, 600.0)
    (2, 20.0)
    >>> nearest_batch_multiple(300.0, 600.0)
    (1, 300.0)
    """
    if batch_interval <= 0:
        return (0, recovery_seconds)
    multiple = max(1, round(recovery_seconds / batch_interval))
    distance = abs(recovery_seconds - multiple * batch_interval)
    return (multiple, distance)


def classify_correlation(
    recoveries: List[float],
    batch_interval: float,
    tolerance: float = 60.0,
) -> Dict:
    """Score how many recovery times land near a batch-interval multiple.

    Returns dict with:
        total          — number of stalls analyzed
        within_tol     — count within ±tolerance of a multiple
        cluster_score  — fraction within tolerance
        verdict        — correlated / weak / independent
        records        — per-stall detail list
    """
    if not recoveries:
        return {
            "total": 0,
            "within_tol": 0,
            "cluster_score": 0.0,
            "verdict": "independent",
            "records": [],
        }

    records: List[Dict] = []
    within = 0
    for r in recoveries:
        mult, dist = nearest_batch_multiple(r, batch_interval)
        hit = dist <= tolerance
        if hit:
            within += 1
        records.append({
            "recovery_seconds": r,
            "nearest_multiple": mult,
            "distance_seconds": dist,
            "within_tolerance": hit,
        })

    score = within / len(recoveries)
    if score >= 0.6:
        verdict = "correlated"
    elif score >= 0.3:
        verdict = "weak"
    else:
        verdict = "independent"

    return {
        "total": len(recoveries),
        "within_tol": within,
        "cluster_score": round(score, 4),
        "verdict": verdict,
        "records": records,
    }


# ---------------------------------------------------------------------------
# I/O layer
# ---------------------------------------------------------------------------

def load_stroke_timestamps(path: Path = STROKES_PATH) -> List[datetime]:
    """Read strokes.jsonl and return sorted UTC timestamps."""
    ts: List[datetime] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            raw = rec.get("at", "")
            if not raw:
                continue
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts.append(dt)
    ts.sort()
    return ts


def run(
    batch_interval: float = 600.0,
    stall_threshold: float = 300.0,
    tolerance: float = 60.0,
    as_json: bool = False,
) -> None:
    timestamps = load_stroke_timestamps()
    stalls = detect_stalls(timestamps, stall_threshold)
    recoveries = [s["gap_seconds"] for s in stalls]
    result = classify_correlation(recoveries, batch_interval, tolerance)

    if as_json:
        # datetime objects aren't directly serializable; skip them
        serializable = {k: v for k, v in result.items()}
        print(json.dumps(serializable, indent=2))
        return

    print(f"batch_recovery_correlation")
    print(f"  batch_interval : {batch_interval}s")
    print(f"  stall_threshold: {stall_threshold}s")
    print(f"  tolerance      : ±{tolerance}s")
    print(f"  stalls found   : {result['total']}")
    print(f"  within ±tol    : {result['within_tol']}")
    print(f"  cluster_score  : {result['cluster_score']}")
    print(f"  verdict        : {result['verdict']}")
    print()
    for i, r in enumerate(result["records"][:10], 1):
        tag = "HIT " if r["within_tolerance"] else "    "
        print(
            f"  {tag} stall {i:>3}: "
            f"recovery={r['recovery_seconds']:.0f}s  "
            f"nearest={r['nearest_multiple']}x{batch_interval:.0f}s  "
            f"dist={r['distance_seconds']:.0f}s"
        )
    if len(result["records"]) > 10:
        print(f"  ... and {len(result['records']) - 10} more")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch-interval", type=float, default=600.0,
                   help="batch commit interval in seconds (default 600)")
    p.add_argument("--stall-threshold", type=float, default=300.0,
                   help="minimum gap to count as stall in seconds (default 300)")
    p.add_argument("--tolerance", type=float, default=60.0,
                   help="±tolerance for cluster matching in seconds (default 60)")
    p.add_argument("--json", action="store_true", help="output JSON")
    args = p.parse_args()
    run(args.batch_interval, args.stall_threshold, args.tolerance, args.json)


if __name__ == "__main__":
    main()
