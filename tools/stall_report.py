#!/usr/bin/env python3
"""stall_report.py — identify writing stalls from writer state history.

Parses the writer state JSON and reports gaps between consecutive strokes
that exceed a configurable threshold. Outputs structured data for
caretaker consumption.

Usage:
    python3 tools/stall_report.py [--writer qwen] [--threshold 300]
    python3 tools/stall_report.py --json  # machine-readable output
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_history(state_path: Path) -> list[dict]:
    """Load stroke history from writer state file."""
    if not state_path.exists():
        return []
    data = json.loads(state_path.read_text(encoding="utf-8"))
    return data.get("history", [])


def find_stalls(history: list[dict], threshold_seconds: int = 300) -> list[dict]:
    """Find gaps between consecutive strokes exceeding the threshold.

    Returns a list of stall dicts with keys:
        - start: ISO timestamp of the last stroke before the gap
        - end: ISO timestamp of the first stroke after the gap
        - gap_seconds: duration of the gap in seconds
        - strokes_before: seq number of the last stroke before stall
        - strokes_after: seq number of the first stroke after stall
    """
    if len(history) < 2:
        return []

    stalls = []
    for i in range(1, len(history)):
        prev = history[i - 1]
        curr = history[i]
        prev_time = datetime.fromisoformat(prev["at"])
        curr_time = datetime.fromisoformat(curr["at"])
        gap = (curr_time - prev_time).total_seconds()

        if gap > threshold_seconds:
            stalls.append({
                "start": prev["at"],
                "end": curr["at"],
                "gap_seconds": int(gap),
                "strokes_before": prev["seq"],
                "strokes_after": curr["seq"],
            })

    return stalls


def summarize(stalls: list[dict], history: list[dict]) -> dict:
    """Build a summary dict from stall data and history."""
    if not history:
        return {
            "total_strokes": 0,
            "total_stalls": 0,
            "longest_gap_seconds": 0,
            "total_stall_seconds": 0,
            "stalls": [],
        }

    gap_values = [s["gap_seconds"] for s in stalls]
    return {
        "total_strokes": len(history),
        "total_stalls": len(stalls),
        "longest_gap_seconds": max(gap_values) if gap_values else 0,
        "total_stall_seconds": sum(gap_values),
        "first_stroke": history[0]["at"],
        "last_stroke": history[-1]["at"],
        "stalls": stalls,
    }


def format_text(summary: dict) -> str:
    """Format summary as human-readable text."""
    lines = [
        f"stall report",
        f"  strokes: {summary['total_strokes']}",
        f"  stalls:  {summary['total_stalls']}",
        f"  longest: {summary['longest_gap_seconds']}s",
        f"  total stall time: {summary['total_stall_seconds']}s",
    ]
    if summary.get("first_stroke"):
        lines.append(f"  range: {summary['first_stroke']} .. {summary['last_stroke']}")
    for i, s in enumerate(summary["stalls"], 1):
        lines.append(
            f"  stall {i}: {s['gap_seconds']}s "
            f"(seq {s['strokes_before']} -> {s['strokes_after']}) "
            f"{s['start']} .. {s['end']}"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Report writing stalls")
    parser.add_argument("--writer", default="qwen", help="Writer ID")
    parser.add_argument("--threshold", type=int, default=300, help="Gap threshold in seconds")
    parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    state_path = repo_root / "data" / f"writer_state.{args.writer}.json"
    history = load_history(state_path)
    stalls = find_stalls(history, args.threshold)
    summary = summarize(stalls, history)

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        print(format_text(summary))


if __name__ == "__main__":
    main()
