#!/usr/bin/env python3
"""cadence_drift.py — measure actual vs expected writer cadence.

The writer targets one stroke every N seconds (default 15). In practice,
I/O waits, GIL contention, and process scheduling push the real interval
above or below that target. This tool computes the rolling drift: how
far the actual cadence has wandered from the configured one.

Outputs:
  - mean_interval: average seconds between strokes over a window
  - drift_pct: (mean_interval - target) / target * 100
  - drift_class: "tight" (<5%), "warm" (5-20%), "hot" (>20%)

Why this matters: restart_audit.py tells you the process died. stall_report
tells you it's slow. cadence_drift tells you it's *drifting* — still alive,
still writing, but gradually losing pace. A drift that creeps from tight
to warm to hot over hours predicts a future stall better than a snapshot.

Usage:
    python3 tools/cadence_drift.py [--writer qwen] [--window 60]
    python3 tools/cadence_drift.py --json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_strokes(state_path: Path) -> list[dict]:
    """Load stroke history from writer state file."""
    if not state_path.exists():
        return []
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data.get("history", [])


def compute_intervals(history: list[dict]) -> list[float]:
    """Compute seconds between consecutive strokes.

    Returns a list of intervals (length = len(history) - 1).
    Skips negative intervals (clock skew) silently.
    """
    if len(history) < 2:
        return []
    intervals = []
    for i in range(1, len(history)):
        try:
            t_prev = datetime.fromisoformat(history[i - 1]["at"])
            t_curr = datetime.fromisoformat(history[i]["at"])
            delta = (t_curr - t_prev).total_seconds()
            if delta >= 0:
                intervals.append(delta)
        except (KeyError, ValueError, TypeError):
            continue
    return intervals


def drift_report(intervals: list[float], target: int,
                 window: int = 60) -> dict:
    """Compute drift metrics over the most recent `window` intervals.

    Returns a dict with:
      - sample_size: number of intervals used
      - target_s: the configured cadence
      - mean_interval_s: mean of recent intervals
      - median_interval_s: median of recent intervals
      - drift_pct: how far mean deviates from target (positive = slower)
      - drift_class: "tight" / "warm" / "hot"
      - min_s / max_s: range of intervals in window
    """
    if not intervals:
        return {"sample_size": 0, "error": "no intervals to measure"}

    recent = intervals[-window:]
    n = len(recent)
    mean_val = sum(recent) / n
    sorted_vals = sorted(recent)
    mid = n // 2
    if n % 2 == 0:
        median_val = (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
    else:
        median_val = sorted_vals[mid]

    drift_pct = ((mean_val - target) / target) * 100 if target > 0 else 0.0
    abs_drift = abs(drift_pct)
    if abs_drift < 5:
        drift_class = "tight"
    elif abs_drift < 20:
        drift_class = "warm"
    else:
        drift_class = "hot"

    return {
        "sample_size": n,
        "target_s": target,
        "mean_interval_s": round(mean_val, 2),
        "median_interval_s": round(median_val, 2),
        "drift_pct": round(drift_pct, 2),
        "drift_class": drift_class,
        "min_s": round(min(recent), 2),
        "max_s": round(max(recent), 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Measure writer cadence drift")
    parser.add_argument("--writer", default="qwen", help="Writer name")
    parser.add_argument("--cadence", type=int, default=15, help="Target cadence in seconds")
    parser.add_argument("--window", type=int, default=60, help="Number of recent intervals to analyze")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    state_path = REPO / "data" / f"writer_state.{args.writer}.json"
    history = load_strokes(state_path)
    intervals = compute_intervals(history)
    report = drift_report(intervals, target=args.cadence, window=args.window)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if report.get("error"):
            print(f"cadence drift: {report['error']}")
            sys.exit(1)
        print(f"cadence drift report (writer={args.writer})")
        print(f"  target:     {report['target_s']}s")
        print(f"  mean:       {report['mean_interval_s']}s")
        print(f"  median:     {report['median_interval_s']}s")
        print(f"  drift:      {report['drift_pct']}% ({report['drift_class']})")
        print(f"  range:      {report['min_s']}s – {report['max_s']}s")
        print(f"  samples:    {report['sample_size']}")


if __name__ == "__main__":
    main()
