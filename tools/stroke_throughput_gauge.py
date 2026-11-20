#!/usr/bin/env python3
"""stroke_throughput_gauge.py — measure actual stroke throughput vs theoretical max.

Reads strokes.jsonl and computes the real strokes-per-hour over a configurable
sliding window, then compares it to the theoretical maximum (3600 / cadence_seconds).
The result is a single health percentage plus a classification:

    >= 80%  → healthy
    50–79%  → degraded
    20–49%  → struggling
    < 20%   → stalled

This differs from cadence_stall_detector.py in scope: the stall detector looks
at the gap since the *last* stroke (a point measurement), while this tool looks
at aggregate throughput over a window (a trend measurement). A writer can pass
the stall check (recent stroke exists) but still be degraded (throughput declining).

Usage:
    python3 tools/stroke_throughput_gauge.py
    python3 tools/stroke_throughput_gauge.py --window 3600   # last hour
    python3 tools/stroke_throughput_gauge.py --window 7200 --cadence 15
    python3 tools/stroke_throughput_gauge.py --json
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) to find the repo root containing data/."""
    p = start or Path.cwd()
    for parent in [p] + list(p.parents):
        if (parent / "data").is_dir():
            return parent
    return p


def load_strokes(repo: Path) -> list[dict]:
    """Load all strokes from strokes.jsonl."""
    path = repo / "data" / "strokes.jsonl"
    if not path.exists():
        return []
    strokes = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    strokes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return strokes


def parse_timestamp(ts: str) -> datetime:
    """Parse ISO 8601 timestamp to timezone-aware datetime."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def measure_throughput(
    strokes: list[dict],
    window_seconds: int = 3600,
    now: datetime | None = None,
) -> dict:
    """Measure stroke throughput over the given window.

    Returns a dict with:
        window_seconds: the window size
        window_start: ISO timestamp of window start
        window_end: ISO timestamp of window end
        strokes_in_window: count of strokes within the window
        actual_per_hour: strokes per hour (extrapolated if window < 3600)
        theoretical_per_hour: max possible strokes per hour
        health_pct: actual / theoretical * 100
        classification: healthy | degraded | struggling | stalled
    """
    if not strokes:
        return {
            "window_seconds": window_seconds,
            "window_start": None,
            "window_end": None,
            "strokes_in_window": 0,
            "actual_per_hour": 0.0,
            "theoretical_per_hour": 0.0,
            "health_pct": 0.0,
            "classification": "stalled",
        }

    if now is None:
        now = datetime.now(timezone.utc)

    window_start = now - timedelta(seconds=window_seconds)

    # Filter strokes within window
    in_window = []
    for s in strokes:
        try:
            ts = parse_timestamp(s["at"])
            if window_start <= ts <= now:
                in_window.append(ts)
        except (KeyError, ValueError):
            continue

    count = len(in_window)

    # Extrapolate to per-hour rate
    hours = window_seconds / 3600.0
    actual_per_hour = count / hours if hours > 0 else 0.0

    # Theoretical max: assume cadence of 15s unless overridden
    # (caller can set theoretical_per_hour separately)
    theoretical_per_hour = 3600.0 / 15.0  # 240 strokes/hr at 15s cadence

    health_pct = (actual_per_hour / theoretical_per_hour * 100) if theoretical_per_hour > 0 else 0.0

    if health_pct >= 80:
        classification = "healthy"
    elif health_pct >= 50:
        classification = "degraded"
    elif health_pct >= 20:
        classification = "struggling"
    else:
        classification = "stalled"

    return {
        "window_seconds": window_seconds,
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
        "strokes_in_window": count,
        "actual_per_hour": round(actual_per_hour, 1),
        "theoretical_per_hour": round(theoretical_per_hour, 1),
        "health_pct": round(health_pct, 1),
        "classification": classification,
    }


def measure_with_cadence(
    strokes: list[dict],
    window_seconds: int = 3600,
    cadence: int = 15,
    now: datetime | None = None,
) -> dict:
    """Like measure_throughput but uses a custom cadence for theoretical max."""
    result = measure_throughput(strokes, window_seconds, now)
    theoretical = 3600.0 / cadence if cadence > 0 else 0.0
    result["theoretical_per_hour"] = round(theoretical, 1)
    if theoretical > 0:
        result["health_pct"] = round(
            result["actual_per_hour"] / theoretical * 100, 1
        )
    else:
        result["health_pct"] = 0.0

    hp = result["health_pct"]
    if hp >= 80:
        result["classification"] = "healthy"
    elif hp >= 50:
        result["classification"] = "degraded"
    elif hp >= 20:
        result["classification"] = "struggling"
    else:
        result["classification"] = "stalled"

    return result


def main():
    parser = argparse.ArgumentParser(description="Measure stroke throughput health")
    parser.add_argument("--repo", type=Path, default=None, help="Repo root path")
    parser.add_argument("--window", type=int, default=3600, help="Window in seconds (default: 3600)")
    parser.add_argument("--cadence", type=int, default=15, help="Expected cadence in seconds (default: 15)")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    repo = find_repo_root(args.repo)
    strokes = load_strokes(repo)

    result = measure_with_cadence(strokes, args.window, args.cadence)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"=== Stroke Throughput Gauge ===")
        print(f"Window:        {result['window_seconds']}s ({result['window_seconds']//3600}h)")
        print(f"Strokes:       {result['strokes_in_window']} in window")
        print(f"Actual rate:   {result['actual_per_hour']}/hr")
        print(f"Theoretical:   {result['theoretical_per_hour']}/hr (1 stroke/{args.cadence}s)")
        print(f"Health:        {result['health_pct']}%")
        print(f"Status:        {result['classification'].upper()}")

    # Exit code reflects health
    if result["classification"] == "healthy":
        sys.exit(0)
    elif result["classification"] == "degraded":
        sys.exit(1)
    elif result["classification"] == "struggling":
        sys.exit(2)
    else:
        sys.exit(3)


if __name__ == "__main__":
    main()
