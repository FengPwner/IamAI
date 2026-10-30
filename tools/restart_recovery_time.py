#!/usr/bin/env python3
"""restart_recovery_time.py — measure how fast the writer recovers after restart.

problem:
  this repo has been restarted 400+ times.  each restart has a cost: the
  writer must re-orient, produce its first stroke, and re-enter cadence.
  if recovery time drifts upward over weeks, the system is getting harder
  to keep alive even when the restart itself succeeds.

what this tool does:
  1. reads data/writer_state.qwen.json for stroke timestamps
  2. reads the caretaker visit log (or process start markers) for restart events
  3. for each restart, finds the first stroke that follows it
  4. computes recovery_seconds = first_stroke_time − restart_time
  5. reports min / median / p95 / max and trend direction

exit codes:
  0 — report generated
  1 — insufficient data (need ≥2 restarts with subsequent strokes)

usage:
  python3 tools/restart_recovery_time.py [--json] [--last N]
  --json       machine-readable output
  --last N     only show the most recent N recovery events (default: all)
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

REPO = Path(__file__).resolve().parent.parent
STATE_FILE = REPO / "data" / "writer_state.qwen.json"
DEVLOG_FILE = REPO / "docs" / "DEVLOG.md"
VISITS_DIR = REPO / "notes"

JSON_OUT = "--json" in sys.argv
LAST_N = None
for i, arg in enumerate(sys.argv):
    if arg == "--last" and i + 1 < len(sys.argv):
        LAST_N = int(sys.argv[i + 1])


def _parse_iso(ts: str) -> datetime:
    """parse an ISO-8601 timestamp into a timezone-aware datetime."""
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def load_strokes(state_path: Path) -> list[dict]:
    """load stroke history entries from writer state file."""
    if not state_path.exists():
        return []
    data = json.loads(state_path.read_text())
    history = data.get("history", [])
    result = []
    for entry in history:
        if "at" not in entry:
            continue
        result.append({
            "at": _parse_iso(entry["at"]),
            "seq": entry.get("seq", 0),
            "kind": entry.get("kind", "unknown"),
        })
    result.sort(key=lambda e: e["at"])
    return result


def load_restart_events() -> list[dict]:
    """extract restart events from caretaker visit notes and devlog.

    we look for patterns like:
      - 'restart' in caretaker visit filenames
      - lines containing 'restart' or 'process start' in devlog
      - caretaker visit files with 'restart' in their name
    """
    events = []

    # scan caretaker visit files for restart mentions
    if VISITS_DIR.exists():
        for f in sorted(VISITS_DIR.glob("caretaker-visit-*.md")):
            try:
                text = f.read_text(errors="replace")
            except Exception:
                continue
            # look for restart indicators in the visit content
            if any(kw in text.lower() for kw in ["restart", "restarted", "process start", "writer up", "pid"]):
                # try to extract timestamp from the file
                m = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", text)
                if m:
                    try:
                        events.append({
                            "at": _parse_iso(m.group(1) + "+00:00"),
                            "source": f.name,
                        })
                    except (ValueError, TypeError):
                        pass

    # scan devlog for restart markers
    if DEVLOG_FILE.exists():
        try:
            devlog = DEVLOG_FILE.read_text(errors="replace")
        except Exception:
            devlog = ""
        for line in devlog.splitlines():
            low = line.lower()
            if any(kw in low for kw in ["restart", "process start", "writer pid", "writer up"]):
                m = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
                if m:
                    try:
                        events.append({
                            "at": _parse_iso(m.group(1) + "+00:00"),
                            "source": "DEVLOG.md",
                        })
                    except (ValueError, TypeError):
                        pass

    # deduplicate by timestamp (within 60s = same event)
    events.sort(key=lambda e: e["at"])
    deduped = []
    for ev in events:
        if not deduped or (ev["at"] - deduped[-1]["at"]).total_seconds() > 60:
            deduped.append(ev)
    return deduped


def compute_recovery_times(
    restarts: list[dict],
    strokes: list[dict],
) -> list[dict]:
    """for each restart, find the first stroke after it and compute recovery time."""
    results = []
    stroke_times = [s["at"] for s in strokes]

    for restart in restarts:
        r_time = restart["at"]
        # binary search for first stroke after restart
        first_after = None
        for s_time in stroke_times:
            if s_time > r_time:
                first_after = s_time
                break
        if first_after is None:
            continue
        recovery_sec = (first_after - r_time).total_seconds()
        if recovery_sec < 0:
            continue
        results.append({
            "restart_at": r_time.isoformat(),
            "first_stroke_at": first_after.isoformat(),
            "recovery_seconds": round(recovery_sec, 1),
            "source": restart["source"],
        })

    return results


def summarize(recoveries: list[dict]) -> dict:
    """compute summary statistics from recovery events.

    recoveries should be in chronological order (oldest first) so that
    the trend comparison (first half vs second half) is meaningful.
    """
    if not recoveries:
        return {"count": 0}
    # chronological order for trend; sorted copy for percentiles
    times_chrono = [r["recovery_seconds"] for r in recoveries]
    times_sorted = sorted(times_chrono)
    n = len(times_sorted)
    p95_idx = min(int(n * 0.95), n - 1)

    # trend: compare first half median to second half median (chronological)
    trend = "stable"
    if n >= 4:
        half = n // 2
        first_half_med = median(times_chrono[:half])
        second_half_med = median(times_chrono[half:])
        if first_half_med > 0 and second_half_med > first_half_med * 1.2:
            trend = "degrading"
        elif first_half_med > 0 and second_half_med < first_half_med * 0.8:
            trend = "improving"

    return {
        "count": n,
        "min_seconds": times_sorted[0],
        "median_seconds": median(times_sorted),
        "p95_seconds": times_sorted[p95_idx],
        "max_seconds": times_sorted[-1],
        "trend": trend,
    }


def main() -> int:
    strokes = load_strokes(STATE_FILE)
    restarts = load_restart_events()
    recoveries = compute_recovery_times(restarts, strokes)

    if LAST_N is not None:
        recoveries = recoveries[-LAST_N:]

    if len(recoveries) < 2:
        if JSON_OUT:
            print(json.dumps({"error": "insufficient data", "count": len(recoveries)}))
        else:
            print(f"insufficient data: only {len(recoveries)} recovery event(s) found")
        return 1

    summary = summarize(recoveries)

    if JSON_OUT:
        print(json.dumps({
            "summary": summary,
            "recent": recoveries[-10:],
        }, indent=2))
    else:
        print(f"restart recovery report ({summary['count']} events)")
        print(f"  min:    {summary['min_seconds']:.1f}s")
        print(f"  median: {summary['median_seconds']:.1f}s")
        print(f"  p95:    {summary['p95_seconds']:.1f}s")
        print(f"  max:    {summary['max_seconds']:.1f}s")
        print(f"  trend:  {summary['trend']}")
        print()
        print("last 5 recoveries:")
        for r in recoveries[-5:]:
            print(f"  {r['restart_at']}  →  {r['recovery_seconds']}s  ({r['source']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
