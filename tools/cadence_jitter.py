#!/usr/bin/env python3
"""cadence_jitter.py — measure stroke-interval variance as a leading stall indicator.

The writer loop targets one stroke every N seconds. When intervals grow
irregular (high jitter), it often means the writer is hitting API
rate-limits, resource contention, or GC pauses — problems that precede
a full stall. This tool quantifies that irregularity.

Usage:
    python3 tools/cadence_jitter.py                   # default: last 100 strokes
    python3 tools/cadence_jitter.py --tail 50         # last 50 strokes
    python3 tools/cadence_jitter.py --cadence 15      # expected 15s cadence
    python3 tools/cadence_jitter.py --json            # machine-readable output
    python3 tools/cadence_jitter.py --threshold 0.5   # jitter ratio alert level

Exit codes:
    0 — jitter is within normal bounds
    1 — jitter exceeds threshold (irregular cadence)
    2 — insufficient data (< 3 strokes)

Metrics:
    jitter_ratio  = stddev(intervals) / mean(intervals)
        0.0 = perfectly regular, 1.0+ = highly erratic
    max_gap       = longest interval observed (seconds)
    min_gap       = shortest interval observed (seconds)
    gap_spread    = max_gap - min_gap (seconds)
    outlier_count = intervals deviating > 2σ from mean
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

# Jitter severity levels
SMOOTH = "smooth"       # jitter_ratio < 0.3
ROUGH = "rough"         # 0.3 <= jitter_ratio < threshold
ERRATIC = "erratic"     # jitter_ratio >= threshold


@dataclass
class JitterResult:
    """Result of a jitter analysis."""
    status: str           # smooth | rough | erratic | insufficient_data
    jitter_ratio: float   # stddev / mean of intervals
    mean_interval: float  # average seconds between strokes
    stddev_interval: float  # standard deviation of intervals
    max_gap: float        # longest interval (seconds)
    min_gap: float        # shortest interval (seconds)
    gap_spread: float     # max_gap - min_gap
    outlier_count: int    # intervals > 2σ from mean
    stroke_count: int     # number of strokes analyzed
    interval_count: int   # number of intervals (stroke_count - 1)
    expected_cadence: int # target cadence (seconds)
    cadence_drift: float  # mean_interval - expected_cadence


def parse_stroke_times(strokes_file: Path, tail: int = 100) -> List[datetime]:
    """Read the last `tail` strokes and return their timestamps.

    Reads from the end of the file for efficiency on large files.
    Returns an empty list if the file is empty or unreadable.
    """
    if not strokes_file.exists():
        return []

    lines: List[str] = []
    try:
        with open(strokes_file, "r") as f:
            # Read all lines then take last N — simpler than seek-based
            # tail for files that may have mixed line endings.
            all_lines = f.readlines()
            lines = all_lines[-tail:]
    except (OSError, IOError):
        return []

    times: List[datetime] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            stroke = json.loads(line)
            ts_str = stroke.get("at", "")
            if not ts_str:
                continue
            # Handle ISO format with timezone
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            times.append(ts)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue

    return sorted(times)


def compute_intervals(times: List[datetime]) -> List[float]:
    """Compute seconds between consecutive timestamps."""
    if len(times) < 2:
        return []
    return [
        (times[i + 1] - times[i]).total_seconds()
        for i in range(len(times) - 1)
    ]


def compute_jitter(intervals: List[float], expected_cadence: int) -> Optional[JitterResult]:
    """Compute jitter metrics from a list of intervals.

    Returns None if there are fewer than 2 intervals (need at least 3 strokes).
    """
    n = len(intervals)
    if n < 2:
        return None

    mean = sum(intervals) / n
    variance = sum((x - mean) ** 2 for x in intervals) / n
    stddev = math.sqrt(variance)

    jitter_ratio = stddev / mean if mean > 0 else float("inf")

    max_gap = max(intervals)
    min_gap = min(intervals)
    gap_spread = max_gap - min_gap

    # Outliers: intervals deviating more than 2σ from mean
    threshold_2sigma = 2 * stddev
    outlier_count = sum(1 for x in intervals if abs(x - mean) > threshold_2sigma)

    cadence_drift = mean - expected_cadence

    return JitterResult(
        status="",  # filled in by caller based on threshold
        jitter_ratio=round(jitter_ratio, 4),
        mean_interval=round(mean, 2),
        stddev_interval=round(stddev, 2),
        max_gap=round(max_gap, 2),
        min_gap=round(min_gap, 2),
        gap_spread=round(gap_spread, 2),
        outlier_count=outlier_count,
        stroke_count=n + 1,
        interval_count=n,
        expected_cadence=expected_cadence,
        cadence_drift=round(cadence_drift, 2),
    )


def analyze_jitter(
    strokes_file: Path = DEFAULT_STROKES,
    tail: int = 100,
    expected_cadence: int = 15,
    threshold: float = 0.5,
) -> JitterResult:
    """Full jitter analysis pipeline.

    Args:
        strokes_file: path to strokes.jsonl
        tail: number of recent strokes to analyze
        expected_cadence: target seconds between strokes
        threshold: jitter_ratio above which status is "erratic"

    Returns:
        JitterResult with status filled in
    """
    times = parse_stroke_times(strokes_file, tail)
    intervals = compute_intervals(times)

    if len(intervals) < 2:
        return JitterResult(
            status="insufficient_data",
            jitter_ratio=0.0,
            mean_interval=0.0,
            stddev_interval=0.0,
            max_gap=0.0,
            min_gap=0.0,
            gap_spread=0.0,
            outlier_count=0,
            stroke_count=len(times),
            interval_count=len(intervals),
            expected_cadence=expected_cadence,
            cadence_drift=0.0,
        )

    result = compute_jitter(intervals, expected_cadence)
    if result is None:
        return JitterResult(
            status="insufficient_data",
            jitter_ratio=0.0,
            mean_interval=0.0,
            stddev_interval=0.0,
            max_gap=0.0,
            min_gap=0.0,
            gap_spread=0.0,
            outlier_count=0,
            stroke_count=len(times),
            interval_count=0,
            expected_cadence=expected_cadence,
            cadence_drift=0.0,
        )

    # Classify severity
    if result.jitter_ratio >= threshold:
        result.status = ERRATIC
    elif result.jitter_ratio >= 0.3:
        result.status = ROUGH
    else:
        result.status = SMOOTH

    return result


def format_human(result: JitterResult) -> str:
    """Format JitterResult for human-readable output."""
    if result.status == "insufficient_data":
        return (
            f"cadence jitter: insufficient data "
            f"({result.stroke_count} strokes, need >= 3)"
        )

    lines = [
        f"cadence jitter: {result.status}",
        f"  jitter_ratio:  {result.jitter_ratio:.4f}  "
        f"(0=perfect, 1+=chaotic; threshold for erratic: varies)",
        f"  mean_interval: {result.mean_interval:.1f}s  "
        f"(expected: {result.expected_cadence}s, drift: {result.cadence_drift:+.1f}s)",
        f"  stddev:        {result.stddev_interval:.1f}s",
        f"  gap range:     {result.min_gap:.1f}s — {result.max_gap:.1f}s  "
        f"(spread: {result.gap_spread:.1f}s)",
        f"  outliers:      {result.outlier_count} of {result.interval_count} intervals "
        f"(>2σ from mean)",
        f"  strokes:       {result.stroke_count} analyzed",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure stroke-interval jitter as a leading stall indicator."
    )
    parser.add_argument(
        "--strokes-file",
        type=Path,
        default=DEFAULT_STROKES,
        help=f"path to strokes.jsonl (default: {DEFAULT_STROKES})",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=100,
        help="number of recent strokes to analyze (default: 100)",
    )
    parser.add_argument(
        "--cadence",
        type=int,
        default=15,
        help="expected seconds between strokes (default: 15)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="jitter_ratio above which status is 'erratic' (default: 0.5)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="output machine-readable JSON",
    )

    args = parser.parse_args()

    result = analyze_jitter(
        strokes_file=args.strokes_file,
        tail=args.tail,
        expected_cadence=args.cadence,
        threshold=args.threshold,
    )

    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        print(format_human(result))

    if result.status == "insufficient_data":
        return 2
    elif result.status == ERRATIC:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
