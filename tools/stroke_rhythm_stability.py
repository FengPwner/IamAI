#!/usr/bin/env python3
"""stroke_rhythm_stability.py — measure how regular the writing heartbeat really is.

While cadence_drift.py captures *average* pace deviation, this tool looks at
*interval variance* — the moment-to-moment jitter in stroke timing. A writer
can have perfect average cadence but still be rhythmically unhealthy if it
alternates between fast bursts and long pauses.

Core metrics:
  - cv (coefficient of variation): stddev / mean of intervals.
      cv < 0.3 = steady, 0.3–0.7 = wobbly, > 0.7 = erratic
  - micro_stall_count: number of intervals between 2× and 5× cadence
      (too short to be a "stall" but too long to be healthy)
  - micro_stall_rate: fraction of intervals that are micro-stalls
  - stability_class: STEADY / WOBBLY / ERRATIC / BROKEN

Usage:
    python3 tools/stroke_rhythm_stability.py
    python3 tools/stroke_rhythm_stability.py --window 200 --cadence 15
    python3 tools/stroke_rhythm_stability.py --json

Exit codes:
    0 — analysis complete (any stability class)
    2 — unexpected error
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO / "data" / "strokes.jsonl"
DEFAULT_WINDOW = 100
DEFAULT_CADENCE = 15  # seconds


def load_strokes(path: Path = STROKES_FILE) -> list[dict]:
    """Load stroke records from JSONL file."""
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                try:
                    records.append(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
    return records


def parse_timestamp(ts: str) -> datetime | None:
    """Parse an ISO 8601 timestamp string into a timezone-aware datetime."""
    if not ts:
        return None
    try:
        # Handle Z suffix
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def compute_intervals(records: list[dict]) -> list[float]:
    """Compute seconds between consecutive strokes."""
    intervals = []
    prev_dt = None
    for r in records:
        dt = parse_timestamp(r.get("at", ""))
        if dt is None:
            continue
        if prev_dt is not None:
            delta = (dt - prev_dt).total_seconds()
            if delta > 0:
                intervals.append(delta)
        prev_dt = dt
    return intervals


def coefficient_of_variation(intervals: list[float]) -> float:
    """Compute CV = stddev / mean. Returns 0.0 for empty or single-element lists."""
    n = len(intervals)
    if n < 2:
        return 0.0
    mean = sum(intervals) / n
    if mean == 0:
        return 0.0
    variance = sum((x - mean) ** 2 for x in intervals) / (n - 1)
    stddev = math.sqrt(variance)
    return stddev / mean


def count_micro_stalls(intervals: list[float], cadence: float) -> int:
    """Count intervals in the micro-stall zone: 2× to 5× cadence."""
    lo = 2.0 * cadence
    hi = 5.0 * cadence
    return sum(1 for iv in intervals if lo <= iv <= hi)


def micro_stall_rate(intervals: list[float], cadence: float) -> float:
    """Fraction of intervals that are micro-stalls."""
    if not intervals:
        return 0.0
    return count_micro_stalls(intervals, cadence) / len(intervals)


def classify_stability(cv: float) -> str:
    """Map CV to a stability class.

    STEADY:   cv < 0.3  — intervals are consistent
    WOBBLY:   0.3–0.7   — some variation but nothing alarming
    ERRATIC:  0.7–1.5   — large swings, rhythm is unreliable
    BROKEN:   > 1.5     — no discernible rhythm at all
    """
    if cv < 0.3:
        return "STEADY"
    elif cv < 0.7:
        return "WOBBLY"
    elif cv < 1.5:
        return "ERRATIC"
    else:
        return "BROKEN"


def analyze(
    path: Path = STROKES_FILE,
    window: int = DEFAULT_WINDOW,
    cadence: float = DEFAULT_CADENCE,
) -> dict:
    """Run full rhythm stability analysis."""
    records = load_strokes(path)
    tail = records[-window:] if len(records) > window else records
    intervals = compute_intervals(tail)

    cv = coefficient_of_variation(intervals)
    ms_count = count_micro_stalls(intervals, cadence)
    ms_rate = micro_stall_rate(intervals, cadence)
    stability = classify_stability(cv)

    mean_interval = sum(intervals) / len(intervals) if intervals else 0.0
    median_interval = sorted(intervals)[len(intervals) // 2] if intervals else 0.0

    return {
        "stroke_count": len(tail),
        "interval_count": len(intervals),
        "mean_interval_s": round(mean_interval, 2),
        "median_interval_s": round(median_interval, 2),
        "cv": round(cv, 4),
        "stability_class": stability,
        "micro_stall_count": ms_count,
        "micro_stall_rate": round(ms_rate, 4),
        "target_cadence_s": cadence,
    }


def format_text(result: dict) -> str:
    """Produce a human-readable summary."""
    lines = [
        "=== Stroke Rhythm Stability ===",
        f"  strokes analyzed:  {result['stroke_count']}",
        f"  intervals:         {result['interval_count']}",
        f"  mean interval:     {result['mean_interval_s']:.1f}s",
        f"  median interval:   {result['median_interval_s']:.1f}s",
        f"  CV:                {result['cv']:.4f}",
        f"  stability:         {result['stability_class']}",
        f"  micro-stalls:      {result['micro_stall_count']} ({result['micro_stall_rate']:.1%})",
        f"  target cadence:    {result['target_cadence_s']:.0f}s",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    ap.add_argument("--cadence", type=float, default=DEFAULT_CADENCE)
    ap.add_argument("--strokes", type=Path, default=STROKES_FILE)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    try:
        result = analyze(path=args.strokes, window=args.window, cadence=args.cadence)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
