#!/usr/bin/env python3
"""restart_interval_analyzer.py — find patterns in restart timing.

When a long-running writer process keeps dying and coming back, the
*intervals* between deaths carry signal.  Are restarts clustered around
specific hours?  Is the mean interval shrinking (degrading stability)
or growing (improving)?  Do restarts follow a circadian rhythm tied
to container scheduling or human activity?

This module reads strokes.jsonl, detects death events (inter-stroke
gaps exceeding a threshold), then analyzes the temporal pattern of
those events.

Outputs:
  intervals        — list of seconds between consecutive death events
  mean_interval_s  — average gap between restarts
  median_interval_s — median gap (robust to outliers)
  std_interval_s   — standard deviation
  trend            — "improving" | "degrading" | "stable"
                     (linear regression slope on intervals)
  hour_histogram   — dict mapping hour (0-23) to death count
  peak_hour        — hour with most deaths
  cluster_coeff    — fraction of intervals < mean/2 (burstiness)

Usage:
    python3 tools/restart_interval_analyzer.py
    python3 tools/restart_interval_analyzer.py --threshold 600
    python3 tools/restart_interval_analyzer.py --strokes data/strokes.jsonl --json

Exit codes:
    0  success
    2  insufficient data (< 2 death events)
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

DEFAULT_THRESHOLD = 300  # seconds — 20x the 15s cadence
DEFAULT_CADENCE = 15
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class DeathEvent:
    """One gap exceeding the threshold."""
    index: int
    gap_seconds: float
    timestamp_after: str  # ISO timestamp of the first stroke after the gap
    hour_utc: int         # hour of day (UTC) when the writer came back


def detect_deaths(
    strokes: List[dict],
    threshold: float = DEFAULT_THRESHOLD,
) -> List[DeathEvent]:
    """Find inter-stroke gaps exceeding the threshold."""
    deaths: List[DeathEvent] = []
    if len(strokes) < 2:
        return deaths

    idx = 0
    for i in range(1, len(strokes)):
        try:
            t_prev = datetime.fromisoformat(strokes[i - 1]["at"])
            t_curr = datetime.fromisoformat(strokes[i]["at"])
        except (KeyError, ValueError):
            continue

        gap = (t_curr - t_prev).total_seconds()
        if gap >= threshold:
            idx += 1
            deaths.append(DeathEvent(
                index=idx,
                gap_seconds=gap,
                timestamp_after=strokes[i]["at"],
                hour_utc=t_curr.hour,
            ))

    return deaths


def compute_intervals(deaths: List[DeathEvent]) -> List[float]:
    """Compute seconds between consecutive death events."""
    intervals: List[float] = []
    for i in range(1, len(deaths)):
        try:
            t_prev = datetime.fromisoformat(deaths[i - 1].timestamp_after)
            t_curr = datetime.fromisoformat(deaths[i].timestamp_after)
            intervals.append((t_curr - t_prev).total_seconds())
        except (ValueError,):
            continue
    return intervals


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _median(xs: List[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    if n % 2 == 1:
        return float(s[n // 2])
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _linear_slope(xs: List[float]) -> float:
    """Simple OLS slope: y = xs[i], x = i (0-indexed)."""
    n = len(xs)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = _mean(xs)
    num = sum((i - x_mean) * (xs[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den else 0.0


def classify_trend(slope: float, mean_val: float) -> str:
    """Classify the trend based on slope relative to mean."""
    if mean_val == 0:
        return "stable"
    ratio = slope / mean_val
    if ratio > 0.05:
        return "improving"   # intervals growing — fewer restarts
    elif ratio < -0.05:
        return "degrading"   # intervals shrinking — more frequent deaths
    return "stable"


def hour_histogram(deaths: List[DeathEvent]) -> dict:
    """Count deaths per hour (0-23 UTC)."""
    hist = {h: 0 for h in range(24)}
    for d in deaths:
        hist[d.hour_utc] += 1
    return hist


def analyze(strokes: List[dict], threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Run the full analysis pipeline, return a summary dict."""
    deaths = detect_deaths(strokes, threshold)
    if len(deaths) < 2:
        return {
            "death_count": len(deaths),
            "intervals": [],
            "mean_interval_s": 0.0,
            "median_interval_s": 0.0,
            "std_interval_s": 0.0,
            "trend": "stable",
            "hour_histogram": hour_histogram(deaths),
            "peak_hour": None,
            "cluster_coeff": 0.0,
        }

    intervals = compute_intervals(deaths)
    m = _mean(intervals)
    med = _median(intervals)
    sd = _std(intervals)
    slope = _linear_slope(intervals)
    trend = classify_trend(slope, m)
    hist = hour_histogram(deaths)

    # cluster_coeff: fraction of intervals < mean/2 → bursty deaths
    if m > 0 and intervals:
        burst_count = sum(1 for iv in intervals if iv < m / 2)
        cluster_coeff = burst_count / len(intervals)
    else:
        cluster_coeff = 0.0

    peak_hour = max(hist, key=hist.get)  # type: ignore[arg-type]

    return {
        "death_count": len(deaths),
        "intervals": [round(iv, 1) for iv in intervals],
        "mean_interval_s": round(m, 1),
        "median_interval_s": round(med, 1),
        "std_interval_s": round(sd, 1),
        "trend": trend,
        "slope": round(slope, 2),
        "hour_histogram": hist,
        "peak_hour": peak_hour,
        "peak_hour_deaths": hist[peak_hour],
        "cluster_coeff": round(cluster_coeff, 3),
    }


def load_strokes(path: str) -> List[dict]:
    """Load strokes from a JSONL file."""
    strokes: List[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    strokes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return strokes


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze restart interval patterns.")
    parser.add_argument(
        "--strokes",
        default=str(REPO_ROOT / "data" / "strokes.jsonl"),
        help="Path to strokes JSONL file",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Gap threshold in seconds (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    strokes = load_strokes(args.strokes)
    result = analyze(strokes, args.threshold)

    if result["death_count"] < 2:
        print(f"Insufficient data: only {result['death_count']} death event(s) found.", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"=== Restart Interval Analysis ===")
        print(f"Death events detected: {result['death_count']}")
        print(f"Intervals between deaths: {len(result['intervals'])}")
        print(f"  Mean:   {result['mean_interval_s']:.0f}s ({result['mean_interval_s']/3600:.1f}h)")
        print(f"  Median: {result['median_interval_s']:.0f}s ({result['median_interval_s']/3600:.1f}h)")
        print(f"  Std:    {result['std_interval_s']:.0f}s")
        print(f"Trend:    {result['trend']} (slope={result.get('slope', 0):.2f})")
        print(f"Peak hour (UTC): {result['peak_hour']:02d}:00 ({result['peak_hour_deaths']} deaths)")
        print(f"Cluster coeff:   {result['cluster_coeff']:.3f} (higher = burstier)")
        print()
        print("Hour histogram (UTC):")
        hist = result["hour_histogram"]
        max_count = max(hist.values()) if hist else 1
        for h in range(24):
            bar = "#" * hist.get(h, 0)
            if hist.get(h, 0) > 0:
                print(f"  {h:02d}:00  {bar} ({hist[h]})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
