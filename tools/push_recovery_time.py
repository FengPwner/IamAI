#!/usr/bin/env python3
"""push_recovery_time.py — measure how long push recovery takes.

when a push is rejected (non-fast-forward, auth failure, network error),
the clock starts. this tool measures the elapsed seconds from the last
push rejection to the next successful push — the "recovery latency".

a short recovery (seconds) means the caretaker self-healed.
a long recovery (minutes/hours) means a human had to intervene.

the tool reads push events from a simple log file that the commit batch
and push_pre_sync can append to. format: one JSON line per event.

  {"ts": 1730300000, "event": "rejected", "reason": "non-fast-forward"}
  {"ts": 1730300060, "event": "ok",      "commit": "abc1234"}

exit codes:
  0 — healthy (recovery < 120s, or no rejection pending)
  1 — slow recovery (120–600s)
  2 — stale (rejection unresolved for > 600s)
  3 — no log file / cannot determine

usage:
  python3 tools/push_recovery_time.py [--json] [--log PATH]
"""

import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG = os.path.join(REPO, "data", "push_events.jsonl")

SLOW_THRESHOLD = 120       # seconds
STALE_THRESHOLD = 600      # seconds


def read_events(log_path):
    """read push event log, return list of dicts. empty list if missing."""
    if not os.path.isfile(log_path):
        return []
    events = []
    with open(log_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


def find_last_rejection(events):
    """return the most recent rejection event, or None."""
    for ev in reversed(events):
        if ev.get("event") == "rejected":
            return ev
    return None


def find_first_ok_after(events, rejection_ts):
    """return the first ok event after the given timestamp, or None."""
    for ev in events:
        if ev.get("event") == "ok" and ev.get("ts", 0) > rejection_ts:
            return ev
    return None


def measure(log_path=DEFAULT_LOG, now=None):
    """produce a recovery report dict."""
    if now is None:
        now = time.time()
    ts_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now))

    if not os.path.isfile(log_path):
        return {
            "timestamp": ts_iso,
            "status": "no_log",
            "exit_code": 3,
            "recovery_seconds": None,
            "pending_rejection": None,
        }

    events = read_events(log_path)
    rejection = find_last_rejection(events)

    if rejection is None:
        return {
            "timestamp": ts_iso,
            "status": "clean",
            "exit_code": 0,
            "recovery_seconds": None,
            "pending_rejection": None,
        }

    ok = find_first_ok_after(events, rejection["ts"])

    if ok is not None:
        elapsed = ok["ts"] - rejection["ts"]
        if elapsed < SLOW_THRESHOLD:
            code = 0
            status = "healthy"
        elif elapsed < STALE_THRESHOLD:
            code = 1
            status = "slow"
        else:
            code = 2
            status = "stale_recovery"
        return {
            "timestamp": ts_iso,
            "status": status,
            "exit_code": code,
            "recovery_seconds": round(elapsed, 1),
            "pending_rejection": None,
        }

    # rejection with no ok yet — still pending
    pending_secs = now - rejection["ts"]
    if pending_secs < SLOW_THRESHOLD:
        code = 0
    elif pending_secs < STALE_THRESHOLD:
        code = 1
    else:
        code = 2
    return {
        "timestamp": ts_iso,
        "status": "pending",
        "exit_code": code,
        "recovery_seconds": None,
        "pending_rejection": {
            "ts": rejection["ts"],
            "reason": rejection.get("reason", "unknown"),
            "elapsed_seconds": round(pending_secs, 1),
        },
    }


def human_summary(report):
    """one-line summary."""
    status = report["status"]
    if status == "no_log":
        return "no push event log found"
    if status == "clean":
        return "no pending push rejection"
    if status == "healthy":
        return f"push recovered in {report['recovery_seconds']}s"
    if status == "slow":
        return f"slow push recovery: {report['recovery_seconds']}s"
    if status == "stale_recovery":
        return f"stale recovery: {report['recovery_seconds']}s (took > {STALE_THRESHOLD}s)"
    if status == "pending":
        p = report["pending_rejection"]
        return f"push rejection unresolved for {p['elapsed_seconds']}s ({p['reason']})"
    return f"unknown status: {status}"


def main():
    use_json = "--json" in sys.argv
    log_path = DEFAULT_LOG
    if "--log" in sys.argv:
        idx = sys.argv.index("--log")
        if idx + 1 < len(sys.argv):
            log_path = sys.argv[idx + 1]

    report = measure(log_path)
    if use_json:
        print(json.dumps(report, indent=2))
    else:
        print(human_summary(report))
    sys.exit(report["exit_code"])


if __name__ == "__main__":
    main()
