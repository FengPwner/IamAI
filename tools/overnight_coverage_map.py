#!/usr/bin/env python3
"""overnight_coverage_map.py — hourly heatmap of writer coverage gaps.

Aggregates resurrection events (from strokes.jsonl gaps) into a 24-hour
heatmap showing which hours of the day have the weakest caretaker coverage.

This answers: "between 3 AM and 5 AM, the system is silent for 2 hours on
average before recovery — is that normal?"

The tool does NOT require resurrection_latency.py as a dependency; it
recomputes gaps directly from strokes.jsonl for portability.

Input:
    data/strokes.jsonl  — one JSON object per line, must have "at" (ISO-8601)

Output (text heatmap):

    Hour  Gaps  AvgGap(s)  MaxGap(s)  Coverage   Bar
    ─────────────────────────────────────────────────────────
     00     3     1840       3200       78.7%     ████████░░
     01     5     2100       4500       71.2%     ███████░░░
     ...
     23     0        0          0      100.0%     ██████████

Coverage = 1 - (total_gap_seconds_in_hour / wall_clock_seconds_in_hour)

A gap is attributed to the hour in which it *started* (the hour of the
last stroke before the gap). This means a gap that starts at 03:50 and
ends at 06:10 is attributed entirely to hour 03.

Usage:
    python3 tools/overnight_coverage_map.py
    python3 tools/overnight_coverage_map.py --cadence 15 --days 7
    python3 tools/overnight_coverage_map.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def parse_iso(s: str) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime."""
    if not s:
        return None
    s = s.strip()
    # Handle Z suffix
    s = s.replace("Z", "+00:00")
    # Python 3.7+ fromisoformat handles most cases
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Stroke loading
# ---------------------------------------------------------------------------

def load_strokes(path: str | Path, since: datetime | None = None) -> list[dict]:
    """Load strokes from a JSONL file, optionally filtering by time."""
    path = Path(path)
    if not path.exists():
        return []
    strokes = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = parse_iso(obj.get("at", ""))
            if ts is None:
                continue
            obj["_ts"] = ts
            if since and ts < since:
                continue
            strokes.append(obj)
    strokes.sort(key=lambda s: s["_ts"])
    return strokes


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------

def detect_gaps(
    strokes: list[dict],
    cadence_seconds: int = 15,
    min_gap_multiplier: float = 2.0,
) -> list[dict[str, Any]]:
    """Detect gaps between consecutive strokes that exceed threshold.

    Returns a list of gap records:
        {
            "last_ts": datetime,    # timestamp of last stroke before gap
            "next_ts": datetime,    # timestamp of first stroke after gap
            "gap_seconds": float,   # duration of the gap
            "hour": int,            # hour (0-23) of the gap start
        }
    """
    threshold = cadence_seconds * min_gap_multiplier
    gaps = []
    for i in range(1, len(strokes)):
        prev_ts = strokes[i - 1]["_ts"]
        curr_ts = strokes[i]["_ts"]
        delta = (curr_ts - prev_ts).total_seconds()
        if delta >= threshold:
            gaps.append({
                "last_ts": prev_ts,
                "next_ts": curr_ts,
                "gap_seconds": delta,
                "hour": prev_ts.hour,
            })
    return gaps


# ---------------------------------------------------------------------------
# Hourly aggregation
# ---------------------------------------------------------------------------

def aggregate_hourly(gaps: list[dict]) -> dict[int, dict[str, Any]]:
    """Aggregate gaps into per-hour buckets.

    Returns a dict keyed by hour (0-23):
        {
            "count": int,
            "total_seconds": float,
            "max_seconds": float,
            "avg_seconds": float,
        }
    """
    buckets: dict[int, list[float]] = defaultdict(list)
    for g in gaps:
        buckets[g["hour"]].append(g["gap_seconds"])

    result = {}
    for hour in range(24):
        secs = buckets.get(hour, [])
        if secs:
            result[hour] = {
                "count": len(secs),
                "total_seconds": sum(secs),
                "max_seconds": max(secs),
                "avg_seconds": sum(secs) / len(secs),
            }
        else:
            result[hour] = {
                "count": 0,
                "total_seconds": 0.0,
                "max_seconds": 0.0,
                "avg_seconds": 0.0,
            }
    return result


# ---------------------------------------------------------------------------
# Coverage computation
# ---------------------------------------------------------------------------

def compute_coverage(
    hourly: dict[int, dict],
    wall_seconds_per_hour: float = 3600.0,
    num_days: int = 1,
) -> dict[int, float]:
    """Compute coverage percentage per hour.

    Coverage = 1 - (total_gap_seconds / (wall_clock_seconds * num_days)).
    Clamped to [0.0, 1.0].
    """
    coverage = {}
    total_wall = wall_seconds_per_hour * max(1, num_days)
    for hour in range(24):
        data = hourly.get(hour, {})
        total_gap = data.get("total_seconds", 0.0)
        cov = 1.0 - (total_gap / total_wall)
        coverage[hour] = max(0.0, min(1.0, cov))
    return coverage


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_heatmap(
    hourly: dict[int, dict],
    coverage: dict[int, float],
    bar_width: int = 20,
) -> str:
    """Render a text-based heatmap."""
    filled = "█"
    empty = "░"

    lines = [
        f"{'Hour':>4}  {'Gaps':>4}  {'AvgGap(s)':>9}  {'MaxGap(s)':>9}  {'Coverage':>8}   Bar",
        "─" * 70,
    ]

    for hour in range(24):
        data = hourly.get(hour, {})
        count = data.get("count", 0)
        avg = data.get("avg_seconds", 0.0)
        mx = data.get("max_seconds", 0.0)
        cov = coverage.get(hour, 1.0)

        filled_count = int(cov * bar_width)
        bar = filled * filled_count + empty * (bar_width - filled_count)

        lines.append(
            f"  {hour:02d}    {count:4d}    {avg:9.0f}    {mx:9.0f}    {cov * 100:5.1f}%   {bar}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_map(
    strokes_path: str | Path = "data/strokes.jsonl",
    cadence: int = 15,
    days: int | None = None,
    min_gap_multiplier: float = 2.0,
) -> dict[str, Any]:
    """Build the full coverage map. Returns a structured dict."""
    since = None
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=days)

    strokes = load_strokes(strokes_path, since=since)
    if len(strokes) < 2:
        return {
            "strokes_loaded": len(strokes),
            "gaps_detected": 0,
            "num_days": 0,
            "hourly": {},
            "coverage": {h: 1.0 for h in range(24)},
        }

    gaps = detect_gaps(strokes, cadence, min_gap_multiplier)
    hourly = aggregate_hourly(gaps)

    # Calculate actual observation span in days
    first_ts = strokes[0]["_ts"]
    last_ts = strokes[-1]["_ts"]
    span_seconds = (last_ts - first_ts).total_seconds()
    num_days = max(1, int(span_seconds / 86400) + 1)

    coverage = compute_coverage(hourly, num_days=num_days)

    return {
        "strokes_loaded": len(strokes),
        "gaps_detected": len(gaps),
        "num_days": num_days,
        "hourly": {str(h): hourly[h] for h in range(24)},
        "coverage": {str(h): coverage[h] for h in range(24)},
        "worst_hour": min(range(24), key=lambda h: coverage[h]),
        "best_hour": max(range(24), key=lambda h: coverage[h]),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate an hourly coverage heatmap from stroke gaps."
    )
    parser.add_argument(
        "--strokes", default="data/strokes.jsonl",
        help="Path to strokes JSONL file (default: data/strokes.jsonl)"
    )
    parser.add_argument(
        "--cadence", type=int, default=15,
        help="Expected stroke cadence in seconds (default: 15)"
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Only consider strokes from the last N days"
    )
    parser.add_argument(
        "--min-gap", type=float, default=2.0,
        help="Minimum gap multiplier vs cadence to count (default: 2.0)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output JSON instead of text heatmap"
    )
    args = parser.parse_args()

    result = build_map(
        strokes_path=args.strokes,
        cadence=args.cadence,
        days=args.days,
        min_gap_multiplier=args.min_gap,
    )

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        hourly_int = {int(h): result["hourly"][h] for h in result["hourly"]}
        coverage_float = {int(h): result["coverage"][h] for h in result["coverage"]}
        nd = result.get("num_days", 0)
        print(f"Coverage Map — {result['strokes_loaded']} strokes, "
              f"{result['gaps_detected']} gaps over {nd} day(s)")
        if nd > 0:
            print(f"Worst hour: {result['worst_hour']:02d}:00  "
                  f"Best hour: {result['best_hour']:02d}:00")
        print()
        print(render_heatmap(hourly_int, coverage_float))


if __name__ == "__main__":
    main()
