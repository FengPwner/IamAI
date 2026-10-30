#!/usr/bin/env python3
"""
resurrection_cost.py — estimate time lost to process restarts.

reads the process graveyard (logs/process_graveyard.jsonl) and computes:
  - total restart count in the last N hours
  - mean recovery time per restart
  - resurrection overhead ratio (recovery_time / alive_time)

usage:
  python3 tools/resurrection_cost.py [--hours 24] [--graveyard logs/process_graveyard.jsonl]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta


def load_events(path, hours):
    """Load graveyard events from the jsonl file."""
    if not os.path.exists(path):
        return []
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    events = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = ev.get("timestamp") or ev.get("ts") or ev.get("time")
            if ts is None:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", ""))
            except (ValueError, TypeError):
                continue
            if dt >= cutoff:
                ev["_dt"] = dt
                events.append(ev)
    return events


def compute_cost(events, hours):
    """Compute resurrection cost metrics."""
    restarts = [e for e in events if e.get("event") in ("restart", "resurrection", "reclaim")]
    deaths = [e for e in events if e.get("event") in ("death", "crash", "oom", "kill")]

    total_window_sec = hours * 3600
    restart_count = len(restarts)

    # estimate recovery time per restart from gap between death and next restart
    recovery_times = []
    sorted_events = sorted(events, key=lambda e: e["_dt"])
    for i, ev in enumerate(sorted_events):
        if ev.get("event") in ("death", "crash", "oom", "kill"):
            for j in range(i + 1, len(sorted_events)):
                if sorted_events[j].get("event") in ("restart", "resurrection", "reclaim"):
                    delta = (sorted_events[j]["_dt"] - ev["_dt"]).total_seconds()
                    if 0 < delta < 3600:
                        recovery_times.append(delta)
                    break

    mean_recovery = sum(recovery_times) / max(len(recovery_times), 1)
    total_recovery = sum(recovery_times) if recovery_times else restart_count * 30.0
    alive_time = max(total_window_sec - total_recovery, 1.0)
    overhead_ratio = total_recovery / alive_time

    return {
        "window_hours": hours,
        "restart_count": restart_count,
        "death_count": len(deaths),
        "mean_recovery_sec": round(mean_recovery, 1),
        "total_recovery_sec": round(total_recovery, 1),
        "alive_sec": round(alive_time, 1),
        "overhead_ratio": round(overhead_ratio, 4),
        "overhead_pct": round(overhead_ratio * 100, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Estimate resurrection cost")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours")
    parser.add_argument("--graveyard", default="logs/process_graveyard.jsonl",
                        help="Path to graveyard jsonl")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    events = load_events(args.graveyard, args.hours)
    metrics = compute_cost(events, args.hours)

    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print(f"Resurrection cost (last {metrics['window_hours']}h):")
        print(f"  restarts:        {metrics['restart_count']}")
        print(f"  deaths:          {metrics['death_count']}")
        print(f"  mean recovery:   {metrics['mean_recovery_sec']}s")
        print(f"  total recovery:  {metrics['total_recovery_sec']}s")
        print(f"  overhead:        {metrics['overhead_pct']}%")


if __name__ == "__main__":
    main()
