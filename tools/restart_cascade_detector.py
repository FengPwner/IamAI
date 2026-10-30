#!/usr/bin/env python3
"""restart_cascade_detector.py — detect crash-loop restart patterns.

when a process keeps dying and getting restarted within a short window,
it's not "recovery" — it's a cascade. the caretaker needs to know the
difference between a one-off reclaim (fine, restart) and a loop
(something is broken, don't keep feeding it CPU).

reads a restart event log (one JSON line per restart):

  {"ts": 1730300000, "pid": 1234, "reason": "reclaimed"}
  {"ts": 1730300045, "pid": 1235, "reason": "oom"}
  {"ts": 1730300090, "pid": 1236, "reason": "reclaimed"}

outputs a cascade verdict:

  healthy  — 0–1 restarts in the window
  watch    — 2–3 restarts, approaching cascade territory
  cascade  — 4+ restarts in the window, likely a loop

exit codes:
  0 — healthy or watch
  1 — cascade detected
  2 — cannot read log

usage:
  python3 tools/restart_cascade_detector.py [--json] [--window SECS] [--log PATH]
"""

import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG = os.path.join(REPO, "data", "restart_events.jsonl")

DEFAULT_WINDOW = 3600  # 1 hour
CASCADE_THRESHOLD = 4  # restarts within window → cascade
WATCH_THRESHOLD = 2    # restarts within window → watch


def read_restart_log(log_path):
    """read restart event log, return list of dicts. empty list if missing."""
    if not os.path.isfile(log_path):
        return []
    events = []
    with open(log_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if "ts" in ev:
                    events.append(ev)
            except json.JSONDecodeError:
                continue
    return events


def filter_by_window(events, now, window_secs):
    """return events within the lookback window."""
    cutoff = now - window_secs
    return [e for e in events if e.get("ts", 0) >= cutoff]


def classify(count):
    """return verdict string based on restart count in window."""
    if count >= CASCADE_THRESHOLD:
        return "cascade"
    if count >= WATCH_THRESHOLD:
        return "watch"
    return "healthy"


def reason_breakdown(events):
    """count restart reasons, return dict of reason → count."""
    reasons = {}
    for ev in events:
        r = ev.get("reason", "unknown")
        reasons[r] = reasons.get(r, 0) + 1
    return reasons


def inter_restart_gaps(events):
    """compute seconds between consecutive restarts."""
    if len(events) < 2:
        return []
    sorted_events = sorted(events, key=lambda e: e.get("ts", 0))
    gaps = []
    for i in range(1, len(sorted_events)):
        gaps.append(sorted_events[i]["ts"] - sorted_events[i - 1]["ts"])
    return gaps


def detect_cascade(log_path, window_secs=None, now=None):
    """
    analyze restart log and return a result dict.

    returns:
        {
            "verdict": "healthy" | "watch" | "cascade",
            "restarts_in_window": int,
            "window_secs": int,
            "reasons": {str: int},
            "gaps": [float],
            "min_gap": float | None,
            "max_gap": float | None,
            "avg_gap": float | None,
        }
    """
    if window_secs is None:
        window_secs = DEFAULT_WINDOW
    if now is None:
        now = time.time()

    events = read_restart_log(log_path)
    recent = filter_by_window(events, now, window_secs)
    count = len(recent)
    verdict = classify(count)
    reasons = reason_breakdown(recent)
    gaps = inter_restart_gaps(recent)

    min_gap = min(gaps) if gaps else None
    max_gap = max(gaps) if gaps else None
    avg_gap = sum(gaps) / len(gaps) if gaps else None

    return {
        "verdict": verdict,
        "restarts_in_window": count,
        "window_secs": window_secs,
        "reasons": reasons,
        "gaps": gaps,
        "min_gap": min_gap,
        "max_gap": max_gap,
        "avg_gap": avg_gap,
    }


def main():
    parser = argparse.ArgumentParser(description="detect restart cascades")
    parser.add_argument("--json", action="store_true", help="output JSON")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                        help="lookback window in seconds (default: 3600)")
    parser.add_argument("--log", default=DEFAULT_LOG,
                        help="path to restart event log")
    args = parser.parse_args()

    if not os.path.isfile(args.log):
        if args.json:
            print(json.dumps({"error": "log not found", "path": args.log}))
        else:
            print(f"restart log not found: {args.log}", file=sys.stderr)
        sys.exit(2)

    result = detect_cascade(args.log, window_secs=args.window)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        v = result["verdict"]
        n = result["restarts_in_window"]
        w = result["window_secs"]
        print(f"restart cascade: {v} ({n} restarts in {w}s window)")
        if result["reasons"]:
            for reason, cnt in sorted(result["reasons"].items()):
                print(f"  {reason}: {cnt}")
        if result["min_gap"] is not None:
            print(f"  gaps: min={result['min_gap']:.0f}s "
                  f"max={result['max_gap']:.0f}s "
                  f"avg={result['avg_gap']:.0f}s")

    if result["verdict"] == "cascade":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
