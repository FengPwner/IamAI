#!/usr/bin/env python3
"""stroke_momentum_tracker.py — track whether the writer is accelerating, steady, or decelerating.

The writer produces strokes over time.  This tool measures the *rate of
change* of stroke production: is the writer speeding up, holding
steady, or slowing down?

Algorithm:
  1. Read all strokes from data/strokes.jsonl (or per-writer subset).
  2. Parse timestamps and sort chronologically.
  3. Divide the timeline into equal-width windows (default 1 hour).
  4. Count strokes per window to get a rate series.
  5. Compute the linear regression slope over the last N windows
     (default 6).
  6. Classify momentum:
       - "accelerating"  if slope > +accel_threshold
       - "decelerating"  if slope < -accel_threshold
       - "steady"        otherwise
  7. Also report:
       - windows: list of {start, end, count}
       - slope:  strokes-per-window change per window
       - avg_rate: mean strokes per window over measured range
       - peak_window: window with highest count
       - trough_window: window with lowest count

Usage:
    python3 tools/stroke_momentum_tracker.py
    python3 tools/stroke_momentum_tracker.py --writer qwen
    python3 tools/stroke_momentum_tracker.py --window-minutes 30 --windows 8
    python3 tools/stroke_momentum_tracker.py --json

Exit codes:
    0 — steady or accelerating
    1 — decelerating (writer may be winding down)
    2 — data file not found
    3 — insufficient data (fewer than 2 windows with strokes)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class WindowStats:
    """Stroke count for a single time window."""
    start: str
    end: str
    count: int


@dataclass
class MomentumReport:
    """Summary of writer momentum."""
    windows: List[WindowStats]
    measured_windows: int
    slope: float
    avg_rate: float
    momentum: str          # "accelerating" | "steady" | "decelerating"
    peak_window: Optional[WindowStats]
    trough_window: Optional[WindowStats]
    verdict: str           # human-readable summary

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.peak_window:
            d["peak_window"] = asdict(self.peak_window)
        if self.trough_window:
            d["trough_window"] = asdict(self.trough_window)
        return d


def load_strokes(data_path: Path, writer: Optional[str] = None) -> List[dict]:
    """Load strokes from JSONL, optionally filtering by writer."""
    if not data_path.exists():
        return []
    strokes = []
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                stroke = json.loads(line)
            except json.JSONDecodeError:
                continue
            if writer and stroke.get("writer") != writer:
                continue
            strokes.append(stroke)
    return strokes


def parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse an ISO-8601-ish timestamp string into a datetime."""
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    return None


def build_windows(
    timestamps: List[datetime],
    window_minutes: int = 60,
    num_windows: int = 6,
) -> List[WindowStats]:
    """Divide the timeline into fixed-width windows and count strokes per window.

    Only the last `num_windows` windows (ending at the latest timestamp)
    are returned.
    """
    if not timestamps:
        return []

    earliest = min(timestamps)
    delta = timedelta(minutes=window_minutes)

    # Set the boundary just past the latest timestamp so every stroke
    # falls inside the half-open interval [start, end).
    total_span = num_windows * delta
    boundary = earliest + total_span
    if boundary <= max(timestamps):
        boundary = max(timestamps) + timedelta(seconds=1)

    windows: List[WindowStats] = []
    for i in range(num_windows):
        win_start = earliest + i * delta
        win_end = earliest + (i + 1) * delta
        count = sum(1 for ts in timestamps if win_start <= ts < win_end)
        windows.append(WindowStats(
            start=win_start.isoformat(),
            end=win_end.isoformat(),
            count=count,
        ))

    return windows


def compute_slope(values: List[int]) -> float:
    """Compute the slope of a simple linear regression over indices [0..n-1].

    Returns the change in value per unit index (strokes-per-window per window).
    """
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def classify_momentum(
    slope: float,
    accel_threshold: float = 0.5,
) -> str:
    """Classify momentum based on slope magnitude."""
    if slope > accel_threshold:
        return "accelerating"
    elif slope < -accel_threshold:
        return "decelerating"
    return "steady"


def track_momentum(
    data_path: Path,
    writer: Optional[str] = None,
    window_minutes: int = 60,
    num_windows: int = 6,
    accel_threshold: float = 0.5,
) -> Optional[MomentumReport]:
    """Main entry point: compute momentum report from strokes data."""
    strokes = load_strokes(data_path, writer=writer)
    if not strokes:
        return None

    timestamps = []
    for s in strokes:
        ts_str = s.get("timestamp") or s.get("ts") or s.get("time")
        if ts_str:
            dt = parse_timestamp(str(ts_str))
            if dt:
                timestamps.append(dt)

    if not timestamps:
        return None

    windows = build_windows(timestamps, window_minutes, num_windows)
    if len(windows) < 2:
        return None

    counts = [w.count for w in windows]
    slope = compute_slope(counts)
    avg_rate = sum(counts) / len(counts) if counts else 0.0
    momentum = classify_momentum(slope, accel_threshold)

    peak = max(windows, key=lambda w: w.count) if windows else None
    trough = min(windows, key=lambda w: w.count) if windows else None

    if momentum == "accelerating":
        verdict = (
            f"writer is accelerating: slope {slope:+.2f} strokes/window², "
            f"avg {avg_rate:.1f} strokes per {window_minutes}min window"
        )
    elif momentum == "decelerating":
        verdict = (
            f"writer is decelerating: slope {slope:+.2f} strokes/window², "
            f"avg {avg_rate:.1f} strokes per {window_minutes}min window — "
            f"may need attention"
        )
    else:
        verdict = (
            f"writer is steady: slope {slope:+.2f} strokes/window², "
            f"avg {avg_rate:.1f} strokes per {window_minutes}min window"
        )

    return MomentumReport(
        windows=windows,
        measured_windows=len(windows),
        slope=round(slope, 4),
        avg_rate=round(avg_rate, 2),
        momentum=momentum,
        peak_window=peak,
        trough_window=trough,
        verdict=verdict,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Track writer momentum.")
    parser.add_argument("--writer", default=None, help="Filter by writer name")
    parser.add_argument("--window-minutes", type=int, default=60,
                        help="Window width in minutes (default: 60)")
    parser.add_argument("--windows", type=int, default=6,
                        help="Number of windows to measure (default: 6)")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="Slope threshold for accel/decel (default: 0.5)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--data", default=None, help="Path to strokes.jsonl")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    data_path = Path(args.data) if args.data else repo_root / "data" / "strokes.jsonl"

    if not data_path.exists():
        print(f"error: data file not found: {data_path}", file=sys.stderr)
        return 2

    report = track_momentum(
        data_path,
        writer=args.writer,
        window_minutes=args.window_minutes,
        num_windows=args.windows,
        accel_threshold=args.threshold,
    )

    if report is None:
        print("error: insufficient data for momentum analysis", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.verdict)
        print(f"\n  windows measured: {report.measured_windows}")
        print(f"  slope:            {report.slope:+.4f} strokes/window²")
        print(f"  avg rate:         {report.avg_rate:.2f} strokes/window")
        if report.peak_window:
            print(f"  peak:             {report.peak_window.count} strokes "
                  f"({report.peak_window.start[:19]} → {report.peak_window.end[:19]})")
        if report.trough_window:
            print(f"  trough:           {report.trough_window.count} strokes "
                  f"({report.trough_window.start[:19]} → {report.trough_window.end[:19]})")
        print(f"\n  momentum:         {report.momentum}")
        print()
        for w in report.windows:
            bar = "█" * w.count + "░" * max(0, 20 - w.count)
            print(f"    {w.start[11:19]}–{w.end[11:19]}  {bar}  {w.count}")

    return 0 if report.momentum != "decelerating" else 1


if __name__ == "__main__":
    sys.exit(main())
