#!/usr/bin/env python3
"""CLI: writer_rhythm_score — compute a 0-100 rhythm health score.

Measures how consistently the writer maintains its cadence by analysing
the last N stroke intervals. A perfect score (100) means every interval
was within 1.5x the modal cadence; 0 means the writer has been silent
for more than 10x its expected beat.

Usage:
    python3 tools/writer_rhythm_score.py
    python3 tools/writer_rhythm_score.py --json
    python3 tools/writer_rhythm_score.py --window 30
    python3 tools/writer_rhythm_score.py --expected 900  # 15-min cadence

Exit codes:
    0  healthy (score >= 70)
    1  degraded (30 <= score < 70)
    2  stalled (score < 30)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def load_intervals(strokes_path: str | Path, window: int = 50) -> list[float]:
    """Return the last `window` inter-stroke intervals (seconds)."""
    path = Path(strokes_path)
    if not path.exists():
        return []

    lines = path.read_text().strip().splitlines()
    timestamps: list[float] = []

    for line in lines[-(window + 10):]:
        try:
            rec = json.loads(line)
            at = rec.get("at") or rec.get("at_ts")
            if isinstance(at, str):
                # ISO 8601
                dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
                timestamps.append(dt.timestamp())
            elif isinstance(at, (int, float)):
                timestamps.append(float(at))
        except (json.JSONDecodeError, ValueError, KeyError):
            continue

    intervals = []
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        if 0 < gap < 86400:  # skip absurd gaps (> 1 day)
            intervals.append(gap)

    return intervals[-window:]


def compute_score(
    intervals: list[float],
    expected_cadence: float = 900.0,
) -> dict:
    """Compute rhythm health score from intervals.

    Args:
        intervals: list of inter-stroke gaps in seconds.
        expected_cadence: the target interval in seconds (default 900 = 15 min).

    Returns:
        dict with keys: score, grade, median_gap, max_gap,
        pct_on_time, sample_count.
    """
    if not intervals:
        return {
            "score": 0,
            "grade": "stalled",
            "median_gap": 0,
            "max_gap": 0,
            "pct_on_time": 0.0,
            "sample_count": 0,
        }

    sorted_iv = sorted(intervals)
    median_gap = sorted_iv[len(sorted_iv) // 2]
    max_gap = sorted_iv[-1]
    threshold = expected_cadence * 1.5

    on_time = sum(1 for g in intervals if g <= threshold)
    pct_on_time = on_time / len(intervals) * 100.0

    # Score formula:
    #   base = pct_on_time (0-100)
    #   penalty for max_gap exceeding 5x cadence
    #   bonus for low variance
    base_score = pct_on_time
    gap_ratio = max_gap / expected_cadence if expected_cadence > 0 else 0
    if gap_ratio > 10:
        penalty = 30
    elif gap_ratio > 5:
        penalty = 15
    elif gap_ratio > 3:
        penalty = 5
    else:
        penalty = 0

    # Variance bonus: if most intervals cluster tightly
    if len(intervals) >= 5:
        iqr = sorted_iv[3 * len(sorted_iv) // 4] - sorted_iv[len(sorted_iv) // 4]
        cv = iqr / median_gap if median_gap > 0 else 1.0
        variance_bonus = max(0, 10 - cv * 10)
    else:
        variance_bonus = 0

    raw = base_score - penalty + variance_bonus
    score = max(0, min(100, round(raw)))

    if score >= 70:
        grade = "healthy"
    elif score >= 30:
        grade = "degraded"
    else:
        grade = "stalled"

    return {
        "score": score,
        "grade": grade,
        "median_gap": round(median_gap, 1),
        "max_gap": round(max_gap, 1),
        "pct_on_time": round(pct_on_time, 1),
        "sample_count": len(intervals),
    }


def grade_to_exit(grade: str) -> int:
    return {"healthy": 0, "degraded": 1, "stalled": 2}.get(grade, 2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute writer rhythm health score (0-100).",
    )
    parser.add_argument(
        "--window", "-w", type=int, default=50,
        help="Number of recent intervals to analyse (default: 50)",
    )
    parser.add_argument(
        "--expected", "-e", type=float, default=900.0,
        help="Expected cadence in seconds (default: 900 = 15 min)",
    )
    parser.add_argument(
        "--file", "-f",
        default=str(REPO / "data" / "strokes.jsonl"),
        help="Path to strokes log",
    )
    parser.add_argument(
        "--json", "-j", action="store_true",
        help="Output JSON instead of human-readable text",
    )
    args = parser.parse_args()

    intervals = load_intervals(args.file, args.window)
    report = compute_score(intervals, args.expected)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"rhythm score: {report['score']}/100  [{report['grade']}]")
        print(f"  median gap:   {report['median_gap']}s")
        print(f"  max gap:      {report['max_gap']}s")
        print(f"  on-time:      {report['pct_on_time']}%")
        print(f"  samples:      {report['sample_count']}")

    return grade_to_exit(report["grade"])


if __name__ == "__main__":
    raise SystemExit(main())
