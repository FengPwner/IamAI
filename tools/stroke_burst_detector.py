#!/usr/bin/env python3
"""stroke_burst_detector.py — detect periods where strokes arrive too fast.

The writer is configured to produce one stroke every N seconds (default 15s).
Existing tools detect *gaps* (stalls) and *jitter* (timing noise), but none
detect *bursts* — clusters of strokes arriving significantly faster than the
target cadence.

Bursts indicate:
  - the writer loop's sleep is being interrupted or skipped
  - a catch-up mechanism is replaying buffered strokes
  - the clock source has drifted and the writer is compensating

This tool reads data/strokes.jsonl, computes inter-stroke intervals,
and reports windows where the mean interval falls below a configurable
fraction of the target cadence.

Severity classification:
  - mild:    mean interval < 50% of target cadence
  - severe:  mean interval < 20% of target cadence

Outputs:
  - total_bursts: number of burst windows detected
  - bursts: list of {start, end, count, mean_interval_s, severity}
  - burst_rate: bursts per 1000 strokes (normalised for comparison)
  - worst_burst: the burst with the lowest mean interval
  - verdict: "clean" | "mild" | "bursting"

Usage:
    python3 tools/stroke_burst_detector.py
    python3 tools/stroke_burst_detector.py --writer qwen --target 15
    python3 tools/stroke_burst_detector.py --threshold-pct 50
    python3 tools/stroke_burst_detector.py --json

Exit codes:
    0 — clean or mild (no action needed)
    1 — bursting (investigate writer loop timing)
    2 — data file not found
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Burst:
    """A detected burst window."""
    start_iso: str
    end_iso: str
    stroke_count: int
    mean_interval_s: float
    severity: str  # "mild" | "severe"


@dataclass
class BurstReport:
    """Summary of burst detection across all strokes."""
    total_strokes: int
    total_bursts: int
    burst_rate_per_1000: float
    worst_burst: Optional[Burst]
    bursts: List[Burst]
    target_cadence_s: int
    threshold_pct: float
    verdict: str  # "clean" | "mild" | "bursting"


def load_strokes(strokes_path: Path) -> List[datetime]:
    """Parse stroke timestamps from the JSONL file."""
    timestamps = []
    if not strokes_path.exists():
        return timestamps
    with open(strokes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                ts = record.get("at")
                if ts:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    timestamps.append(dt)
            except (json.JSONDecodeError, ValueError):
                continue
    return sorted(timestamps)


def detect_bursts(
    timestamps: List[datetime],
    target_cadence_s: int = 15,
    threshold_pct: float = 50.0,
    min_burst_size: int = 3,
) -> List[Burst]:
    """Identify burst windows in the stroke timeline.

    A burst is a maximal run of consecutive strokes where every
    inter-stroke interval is below (threshold_pct / 100) * target_cadence_s.
    Runs shorter than min_burst_size strokes are ignored.
    """
    if len(timestamps) < 2:
        return []

    threshold_s = (threshold_pct / 100.0) * target_cadence_s
    severe_threshold_s = 0.20 * target_cadence_s

    bursts: List[Burst] = []
    run_start = 0

    for i in range(1, len(timestamps)):
        interval = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if interval >= threshold_s:
            # End of potential burst
            run_length = i - run_start
            if run_length >= min_burst_size:
                run_timestamps = timestamps[run_start:i]
                intervals = [
                    (run_timestamps[j + 1] - run_timestamps[j]).total_seconds()
                    for j in range(len(run_timestamps) - 1)
                ]
                mean_interval = sum(intervals) / len(intervals) if intervals else 0.0
                severity = "severe" if mean_interval < severe_threshold_s else "mild"
                bursts.append(Burst(
                    start_iso=run_timestamps[0].isoformat(),
                    end_iso=run_timestamps[-1].isoformat(),
                    stroke_count=run_length,
                    mean_interval_s=round(mean_interval, 2),
                    severity=severity,
                ))
            run_start = i

    # Check trailing run
    run_length = len(timestamps) - run_start
    if run_length >= min_burst_size:
        run_timestamps = timestamps[run_start:]
        intervals = [
            (run_timestamps[j + 1] - run_timestamps[j]).total_seconds()
            for j in range(len(run_timestamps) - 1)
        ]
        mean_interval = sum(intervals) / len(intervals) if intervals else 0.0
        severity = "severe" if mean_interval < severe_threshold_s else "mild"
        bursts.append(Burst(
            start_iso=run_timestamps[0].isoformat(),
            end_iso=run_timestamps[-1].isoformat(),
            stroke_count=run_length,
            mean_interval_s=round(mean_interval, 2),
            severity=severity,
        ))

    return bursts


def classify_verdict(bursts: List[Burst]) -> str:
    """Determine overall verdict from burst list."""
    if not bursts:
        return "clean"
    if any(b.severity == "severe" for b in bursts):
        return "bursting"
    return "mild"


def build_report(
    timestamps: List[datetime],
    bursts: List[Burst],
    target_cadence_s: int,
    threshold_pct: float,
) -> BurstReport:
    """Assemble the full burst detection report."""
    total = len(timestamps)
    worst = min(bursts, key=lambda b: b.mean_interval_s) if bursts else None
    rate = (len(bursts) / total * 1000.0) if total > 0 else 0.0

    return BurstReport(
        total_strokes=total,
        total_bursts=len(bursts),
        burst_rate_per_1000=round(rate, 2),
        worst_burst=worst,
        bursts=bursts,
        target_cadence_s=target_cadence_s,
        threshold_pct=threshold_pct,
        verdict=classify_verdict(bursts),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect burst patterns in stroke timestamps."
    )
    parser.add_argument(
        "--writer", default="qwen",
        help="Writer name (default: qwen)",
    )
    parser.add_argument(
        "--target", type=int, default=15,
        help="Target cadence in seconds (default: 15)",
    )
    parser.add_argument(
        "--threshold-pct", type=float, default=50.0,
        help="Burst threshold as percentage of target cadence (default: 50)",
    )
    parser.add_argument(
        "--min-burst-size", type=int, default=3,
        help="Minimum strokes to qualify as a burst (default: 3)",
    )
    parser.add_argument(
        "--repo", type=str, default=None,
        help="Path to repo root (default: auto-detect)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output JSON report",
    )
    args = parser.parse_args()

    repo = Path(args.repo) if args.repo else REPO_ROOT
    strokes_path = repo / "data" / "strokes.jsonl"

    if not strokes_path.exists():
        if args.json:
            print(json.dumps({"error": "strokes.jsonl not found"}))
        else:
            print(f"ERROR: {strokes_path} not found", file=sys.stderr)
        return 2

    timestamps = load_strokes(strokes_path)
    bursts = detect_bursts(
        timestamps,
        target_cadence_s=args.target,
        threshold_pct=args.threshold_pct,
        min_burst_size=args.min_burst_size,
    )
    report = build_report(timestamps, bursts, args.target, args.threshold_pct)

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(f"strokes scanned: {report.total_strokes}")
        print(f"bursts detected: {report.total_bursts}")
        print(f"burst rate:      {report.burst_rate_per_1000} per 1000 strokes")
        print(f"verdict:         {report.verdict}")
        if report.worst_burst:
            wb = report.worst_burst
            print(f"worst burst:     {wb.stroke_count} strokes, "
                  f"mean interval {wb.mean_interval_s}s ({wb.severity})")
            print(f"  window:        {wb.start_iso} → {wb.end_iso}")
        for b in bursts[:10]:
            print(f"  burst: {b.stroke_count} strokes, "
                  f"{b.mean_interval_s}s avg ({b.severity})")

    if report.verdict == "bursting":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
