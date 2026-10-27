#!/usr/bin/env python3
"""CLI: writer_session_segmenter — show writing sessions from stroke history.

Usage:
    python3 tools/writer_session_segmenter.py
    python3 tools/writer_session_segmenter.py --gap 600
    python3 tools/writer_session_segmenter.py --json
    python3 tools/writer_session_segmenter.py --summary

Exit codes:
    0  analysis complete
    1  no strokes found
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_session_segmenter import (  # noqa: E402
    load_strokes,
    segment,
    session_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyse writing sessions from stroke history."
    )
    parser.add_argument(
        "--gap", "-g", type=int, default=300,
        help="gap threshold in seconds to split sessions (default: 300)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="output as JSON"
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="show aggregate summary only"
    )
    parser.add_argument(
        "--file", "-f", type=str, default=None,
        help="path to strokes JSONL (default: data/strokes.jsonl)"
    )
    args = parser.parse_args()

    strokes_path = args.file or str(REPO / "data" / "strokes.jsonl")
    strokes = load_strokes(strokes_path)

    if not strokes:
        print("no strokes found", file=sys.stderr)
        return 1

    if args.summary:
        summary = session_summary(strokes, gap_threshold=args.gap)
        if args.json:
            print(json.dumps(summary, indent=2, default=str))
        else:
            print(f"writer session summary (gap={args.gap}s)")
            print(f"  sessions:         {summary['total_sessions']}")
            print(f"  total strokes:    {summary['total_strokes']}")
            print(f"  avg session len:  {summary['avg_session_length']} strokes")
            print(f"  avg duration:     {summary['avg_duration_minutes']:.1f} min")
            print(f"  avg rate:         {summary['avg_rate_per_min']} strokes/min")
            print(f"  micro sessions:   {summary['micro_sessions']} (1 stroke)")
            print(f"  marathon sessions:{summary['marathon_sessions']} (>1h)")
            if summary["longest_session"]:
                ls = summary["longest_session"]
                print(f"  longest:          session {ls['session_id']} "
                      f"({ls['stroke_count']} strokes, "
                      f"{ls['duration_seconds']:.0f}s)")
            if summary["shortest_session"]:
                ss = summary["shortest_session"]
                print(f"  shortest:         session {ss['session_id']} "
                      f"({ss['stroke_count']} strokes, "
                      f"{ss['duration_seconds']:.0f}s)")
        return 0

    sessions = segment(strokes, gap_threshold=args.gap)

    if args.json:
        print(json.dumps(sessions, indent=2))
    else:
        print(f"writer sessions (gap={args.gap}s): {len(sessions)} sessions found\n")
        for s in sessions:
            dur_min = s["duration_seconds"] / 60.0
            kinds_str = ", ".join(f"{k}:{v}" for k, v in sorted(s["kinds"].items()))
            print(f"  session {s['session_id']:>4d}  "
                  f"{s['stroke_count']:>4d} strokes  "
                  f"{dur_min:>7.1f} min  "
                  f"{s['stroke_rate']:>5.2f}/min  "
                  f"[{kinds_str}]")
            if s["first_text"]:
                preview = s["first_text"][:60]
                print(f"             \"{preview}\"")

    return 0


if __name__ == "__main__":
    sys.exit(main())
