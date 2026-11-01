#!/usr/bin/env python3
"""CLI wrapper for iamai.stroke_diversity — analyze stroke diversity.

Usage:
    python3 tools/stroke_diversity.py            # human-readable output
    python3 tools/stroke_diversity.py --json     # JSON output
    python3 tools/stroke_diversity.py --window 500  # analyze last 500 strokes

Exit codes:
    0  verdict = healthy
    1  verdict = low_diversity
    2  verdict = stuck_loop
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_diversity import analyze_diversity, format_report  # noqa: E402


EXIT_CODES = {"healthy": 0, "low_diversity": 1, "stuck_loop": 2}


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze stroke diversity")
    parser.add_argument("--json", action="store_true", help="output JSON")
    parser.add_argument(
        "--window", type=int, default=200, help="number of recent strokes to analyze"
    )
    parser.add_argument(
        "--log", type=str, default=None, help="path to strokes.jsonl"
    )
    args = parser.parse_args()

    log_path = Path(args.log) if args.log else None
    report = analyze_diversity(stroke_log=log_path, window=args.window)

    if args.json:
        print(json.dumps(report.__dict__, indent=2, default=str))
    else:
        print(format_report(report))

    return EXIT_CODES.get(report.verdict, 0)


if __name__ == "__main__":
    sys.exit(main())
