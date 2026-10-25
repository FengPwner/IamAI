#!/usr/bin/env python3
"""stroke_loss_tracker.py — estimate cumulative stroke loss from stalls.

each time the writer stalls (container recycle, stuck gate, transient error),
strokes that should have been produced during the gap are lost. this tool
quantifies that loss by:

1. parsing the stroke history from the writer state file
2. identifying gaps exceeding a configurable threshold
3. computing the pre-stall cadence (strokes per minute)
4. estimating lost strokes = cadence × gap_duration
5. producing a cumulative loss summary

usage:
    python3 tools/stroke_loss_tracker.py [--writer qwen] [--threshold 300]
    python3 tools/stroke_loss_tracker.py --json  # machine-readable output

exit codes:
    0  success
    1  error (missing state file, parse failure)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp to timezone-aware datetime.

    Returns None for empty or unparseable strings.
    """
    if not ts_str or not isinstance(ts_str, str):
        return None
    try:
        # Handle both +00:00 and Z suffixes
        ts_str = ts_str.strip()
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def load_history(state_path: Path) -> list[dict]:
    """Load stroke history from writer state file."""
    if not state_path.exists():
        return []
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data.get("history", [])


def compute_cadence_spm(history: list[dict], end_idx: int, window: int = 10) -> float:
    """Compute strokes per minute using a window before end_idx.

    Returns 0.0 if insufficient data.
    """
    if end_idx < 1:
        return 0.0
    start_idx = max(0, end_idx - window)
    start_ts = parse_ts(history[start_idx].get("at", ""))
    end_ts = parse_ts(history[end_idx].get("at", ""))
    if start_ts is None or end_ts is None:
        return 0.0
    elapsed_min = (end_ts - start_ts).total_seconds() / 60.0
    if elapsed_min <= 0:
        return 0.0
    return (end_idx - start_idx) / elapsed_min


def estimate_loss(history: list[dict], threshold_seconds: int = 300) -> list[dict]:
    """Find stalls and estimate stroke loss for each.

    Returns list of dicts:
        - start: ISO timestamp of last stroke before gap
        - end: ISO timestamp of first stroke after gap
        - gap_seconds: duration of gap
        - cadence_spm: pre-stall strokes per minute
        - estimated_loss: estimated lost strokes (rounded to int)
        - seq_before: seq of last stroke before stall
        - seq_after: seq of first stroke after stall
    """
    if len(history) < 2:
        return []

    results = []
    for i in range(1, len(history)):
        prev_ts = parse_ts(history[i - 1].get("at", ""))
        curr_ts = parse_ts(history[i].get("at", ""))
        if prev_ts is None or curr_ts is None:
            continue

        gap = (curr_ts - prev_ts).total_seconds()
        if gap < threshold_seconds:
            continue

        cadence = compute_cadence_spm(history, i - 1)
        loss = round(cadence * (gap / 60.0)) if cadence > 0 else 0

        results.append({
            "start": history[i - 1].get("at", ""),
            "end": history[i].get("at", ""),
            "gap_seconds": int(gap),
            "cadence_spm": round(cadence, 2),
            "estimated_loss": loss,
            "seq_before": history[i - 1].get("seq", 0),
            "seq_after": history[i].get("seq", 0),
        })

    return results


def format_text(stalls: list[dict], total_strokes: int) -> str:
    """Format human-readable report."""
    if not stalls:
        return "no stalls detected in the observation window."

    total_loss = sum(s["estimated_loss"] for s in stalls)
    total_stall_time = sum(s["gap_seconds"] for s in stalls)
    longest = max(s["gap_seconds"] for s in stalls)

    lines = [
        "stroke loss estimate",
        f"  stalls detected:    {len(stalls)}",
        f"  total stall time:  {total_stall_time}s ({total_stall_time // 60}m {total_stall_time % 60}s)",
        f"  longest stall:     {longest}s ({longest // 60}m {longest % 60}s)",
        f"  estimated loss:    {total_loss} strokes",
        f"  observed strokes:  {total_strokes}",
        f"  expected total:    {total_strokes + total_loss}",
        f"  availability:      {100 * total_strokes / (total_strokes + total_loss):.1f}%",
        "",
        "  per-stall breakdown:",
    ]

    for idx, s in enumerate(stalls, 1):
        lines.append(
            f"    {idx}. gap {s['gap_seconds']}s | "
            f"cadence {s['cadence_spm']} spm | "
            f"est. loss {s['estimated_loss']} | "
            f"seq {s['seq_before']} → {s['seq_after']}"
        )

    return "\n".join(lines)


def format_json(stalls: list[dict], total_strokes: int) -> str:
    """Format machine-readable JSON output."""
    total_loss = sum(s["estimated_loss"] for s in stalls)
    total_stall_time = sum(s["gap_seconds"] for s in stalls)
    longest = max((s["gap_seconds"] for s in stalls), default=0)

    result = {
        "stall_count": len(stalls),
        "total_stall_seconds": total_stall_time,
        "longest_stall_seconds": longest,
        "estimated_total_loss": total_loss,
        "observed_strokes": total_strokes,
        "expected_total": total_strokes + total_loss,
        "availability_pct": round(100 * total_strokes / (total_strokes + total_loss), 1) if (total_strokes + total_loss) > 0 else 100.0,
        "stalls": stalls,
    }
    return json.dumps(result, indent=2)


def run(writer: str = "qwen", threshold: int = 300, json_output: bool = False) -> int:
    """Main entry point."""
    repo = Path(__file__).resolve().parent.parent
    state_path = repo / "data" / f"writer_state.{writer}.json"

    if not state_path.exists():
        print(f"error: state file not found: {state_path}", file=sys.stderr)
        return 1

    history = load_history(state_path)
    if not history:
        if json_output:
            print(format_json([], 0))
        else:
            print("no history found in writer state.")
        return 0

    stalls = estimate_loss(history, threshold)

    if json_output:
        print(format_json(stalls, len(history)))
    else:
        print(format_text(stalls, len(history)))

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default="qwen", help="writer id (default: qwen)")
    ap.add_argument("--threshold", type=int, default=300,
                    help="gap threshold in seconds (default: 300)")
    ap.add_argument("--json", action="store_true", dest="json_output",
                    help="machine-readable JSON output")
    args = ap.parse_args()
    return run(writer=args.writer, threshold=args.threshold, json_output=args.json_output)


if __name__ == "__main__":
    sys.exit(main())
