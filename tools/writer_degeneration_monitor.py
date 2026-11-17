#!/usr/bin/env python3
"""CLI: monitor writer content degeneration over time.

Reads strokes.jsonl and analyses the most recent N strokes for content
quality decay — duplicate loops, template cycling, and vocabulary
collapse — across successive windows.

Usage:
    python3 tools/writer_degeneration_monitor.py
    python3 tools/writer_degeneration_monitor.py --tail 200 --window 50
    python3 tools/writer_degeneration_monitor.py --json
    python3 tools/writer_degeneration_monitor.py --min-strokes 20

Exit codes:
    0  writer is fresh or cycling (score < 0.50)
    1  writer is degenerate (score 0.50–0.75)
    2  writer is exhausted (score ≥ 0.75)
    3  insufficient data
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_degeneration_monitor import monitor  # noqa: E402

_EXIT_CODES = {"fresh": 0, "cycling": 0, "degenerate": 1, "exhausted": 2}


def _load_strokes(path: Path, tail: int) -> list:
    """Load the last *tail* strokes from strokes.jsonl."""
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    recent = lines[-tail:]
    strokes = []
    for line in recent:
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--tail",
        type=int,
        default=500,
        help="number of recent strokes to analyse (default: 500)",
    )
    ap.add_argument(
        "--window",
        type=int,
        default=50,
        help="strokes per analysis window (default: 50)",
    )
    ap.add_argument(
        "--min-strokes",
        type=int,
        default=10,
        help="minimum strokes to produce a report (default: 10)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="output JSON instead of human-readable text",
    )
    args = ap.parse_args()

    strokes_path = REPO / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        print(f"error: {strokes_path} not found", file=sys.stderr)
        return 3

    strokes = _load_strokes(strokes_path, args.tail)

    report = monitor(
        strokes,
        window_size=args.window,
        min_strokes=args.min_strokes,
    )

    if report.window_count == 0:
        if args.json:
            print(json.dumps({"error": "insufficient data"}))
        else:
            print(
                f"insufficient data: {report.total_strokes} strokes "
                f"(need ≥ {args.min_strokes} per window)"
            )
        return 3

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"=== Writer Degeneration Monitor ===")
        print(f"total strokes analysed: {report.total_strokes}")
        print(f"windows: {report.window_count} × {args.window} strokes")
        print()
        for w in report.windows:
            print(
                f"  window {w.index}: {w.stage:12s}  "
                f"score={w.score:.3f}  "
                f"dup={w.duplicate_ratio:.2f}  "
                f"nov={w.novelty_ratio:.2f}  "
                f"rich={w.vocabulary_richness:.2f}  "
                f"({w.stroke_count} strokes)"
            )
        print()
        print(f"overall: {report.overall_stage}  "
              f"score={report.overall_score:.3f}  "
              f"trend={report.trend}")
        print()
        print(report.summary())

    return _EXIT_CODES.get(report.overall_stage, 0)


if __name__ == "__main__":
    sys.exit(main())
