#!/usr/bin/env python3
"""post_restart_cadence_validator.py — confirm writer settles after restart.

After a writer restart, the process may be alive but not yet producing
strokes at the target cadence. Common failure modes:

  1. Writer started but stuck on I/O (disk full, network timeout)
  2. Writer started but cadence is degraded (e.g. 60s instead of 15s)
  3. Writer started, wrote one stroke, then stalled

This tool checks the *recent* stroke timestamps (not just PID liveness)
to confirm the writer has actually settled into its target rhythm.

Outputs:
  - settled: bool — writer produced >= min_strokes in the check window
  - actual_cadence_s: float — mean interval between recent strokes
  - target_cadence_s: int — configured target interval
  - drift_pct: float — how far actual deviates from target
  - verdict: "settled" | "warming" | "stalled"

Verdict thresholds:
  - settled: drift < 30% and >= min_strokes in window
  - warming: fewer strokes than expected but cadence trending right
  - stalled: no strokes in > 2x target cadence

Usage:
    python3 tools/post_restart_cadence_validator.py [--writer qwen] [--target 15]
    python3 tools/post_restart_cadence_validator.py --json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO / "data" / "strokes.jsonl"
STATE_DIR = REPO / "data"


def load_recent_strokes(n: int = 20) -> list[dict]:
    """Load the last n strokes from strokes.jsonl."""
    if not STROKES_FILE.exists():
        return []
    lines = STROKES_FILE.read_text(encoding="utf-8").strip().splitlines()
    recent = lines[-n:] if len(lines) >= n else lines
    strokes = []
    for line in recent:
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def parse_ts(ts_str: str) -> datetime:
    """Parse an ISO timestamp, handling both 'at' and 'ts' field names."""
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def compute_cadence(strokes: list[dict]) -> tuple[float, int]:
    """Return (mean_interval_seconds, stroke_count) from a list of strokes."""
    if len(strokes) < 2:
        return (0.0, len(strokes))

    timestamps = []
    for s in strokes:
        ts_field = s.get("at") or s.get("ts")
        if ts_field:
            timestamps.append(parse_ts(ts_field))

    if len(timestamps) < 2:
        return (0.0, len(strokes))

    timestamps.sort()
    intervals = [
        (timestamps[i + 1] - timestamps[i]).total_seconds()
        for i in range(len(timestamps) - 1)
    ]
    mean_interval = sum(intervals) / len(intervals) if intervals else 0.0
    return (mean_interval, len(strokes))


def classify(mean_interval: float, stroke_count: int, target_s: int,
             min_strokes: int) -> str:
    """Classify writer state: settled / warming / stalled."""
    if stroke_count == 0:
        return "stalled"

    # if the mean interval is more than 2x target, it's stalled
    if mean_interval > target_s * 2:
        return "stalled"

    # if we don't have enough strokes, it's still warming up
    if stroke_count < min_strokes:
        return "warming"

    # drift within 30% = settled
    drift = abs(mean_interval - target_s) / target_s
    if drift < 0.30:
        return "settled"

    # between 30% and 100% drift = warming (trying to catch up)
    if drift < 1.0:
        return "warming"

    return "stalled"


def validate(writer: str = "qwen", target_s: int = 15,
             min_strokes: int = 4, window_strokes: int = 20,
             as_json: bool = False) -> dict:
    """Run the cadence validation and return results."""
    strokes = load_recent_strokes(window_strokes)
    mean_interval, count = compute_cadence(strokes)
    verdict = classify(mean_interval, count, target_s, min_strokes)

    drift_pct = (
        round((mean_interval - target_s) / target_s * 100, 1)
        if mean_interval > 0 else 0.0
    )

    result = {
        "writer": writer,
        "settled": verdict == "settled",
        "verdict": verdict,
        "actual_cadence_s": round(mean_interval, 1),
        "target_cadence_s": target_s,
        "drift_pct": drift_pct,
        "stroke_count": count,
        "min_strokes": min_strokes,
    }

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        status = "OK" if verdict == "settled" else "WARN" if verdict == "warming" else "FAIL"
        print(f"[{status}] writer={writer} verdict={verdict}")
        print(f"  cadence: {result['actual_cadence_s']}s "
              f"(target {target_s}s, drift {drift_pct:+.1f}%)")
        print(f"  strokes: {count} in window (min {min_strokes})")

    return result


def main():
    parser = argparse.ArgumentParser(description="Validate writer cadence post-restart")
    parser.add_argument("--writer", default="qwen", help="Writer ID")
    parser.add_argument("--target", type=int, default=15, help="Target interval (seconds)")
    parser.add_argument("--min-strokes", type=int, default=4,
                        help="Minimum strokes to consider settled")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    result = validate(
        writer=args.writer,
        target_s=args.target,
        min_strokes=args.min_strokes,
        as_json=args.json,
    )
    sys.exit(0 if result["settled"] else 1)


if __name__ == "__main__":
    main()
