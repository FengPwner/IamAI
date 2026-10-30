#!/usr/bin/env python3
"""CLI: history_repetition — detect repetitive loops in the history log.

Usage:
    python3 tools/history_repetition.py
    python3 tools/history_repetition.py --json
    python3 tools/history_repetition.py --window 100
    python3 tools/history_repetition.py --file notes/history.md

Exit codes:
    0  healthy
    1  repeating
    2  stuck
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.history_repetition import (  # noqa: E402
    analyse,
    classify,
    HistoryRepetitionReport,
)

_EXIT_CODES = {"healthy": 0, "repeating": 1, "stuck": 2}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure repetition in the writer's history log.",
    )
    parser.add_argument(
        "--file", "-f",
        default=str(REPO / "notes" / "history.md"),
        help="Path to the history file (default: notes/history.md)",
    )
    parser.add_argument(
        "--window", "-w",
        type=int,
        default=50,
        help="Sliding window size for dedup ratio (default: 50)",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output JSON instead of human-readable text",
    )
    args = parser.parse_args()

    report = analyse(path=args.file, window=args.window)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"history repetition analysis")
        print(f"  file:           {args.file}")
        print(f"  total lines:    {report.total_lines}")
        print(f"  longest run:    {report.longest_run}")
        if report.longest_run_text:
            preview = report.longest_run_text[:100]
            print(f"  run text:       {preview}...")
        print(f"  repetition:     {report.repetition_pct:.1f}%")
        print(f"  window:         {report.window_size}")
        print(f"  verdict:        {report.verdict}")

    return _EXIT_CODES.get(report.verdict, 0)


if __name__ == "__main__":
    raise SystemExit(main())
