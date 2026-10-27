#!/usr/bin/env python3
"""CLI: stroke_loop_breaker — detect writer module-repetition loops.

Usage:
    python3 tools/stroke_loop_breaker.py
    python3 tools/stroke_loop_breaker.py --window 50
    python3 tools/stroke_loop_breaker.py --json

Exit codes:
    0  healthy (score < 0.30)
    1  mild    (score 0.30–0.59)
    2  stuck   (score 0.60–0.89)
    3  dead_loop (score >= 0.90)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_loop_breaker import loop_report, parse_history_lines  # noqa: E402


_EXIT_MAP = {"healthy": 0, "mild": 1, "stuck": 2, "dead_loop": 3}


def _read_history() -> list[str]:
    """Read notes/history.md from the repo."""
    path = REPO / "notes" / "history.md"
    if not path.exists():
        print("notes/history.md not found", file=sys.stderr)
        sys.exit(4)
    return path.read_text(encoding="utf-8").splitlines()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect writer module-repetition loops in stroke history."
    )
    parser.add_argument(
        "--window", "-w", type=int, default=30,
        help="number of recent strokes to analyse (default: 30)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="output as JSON"
    )
    args = parser.parse_args()

    lines = _read_history()
    strokes = parse_history_lines(lines)

    if not strokes:
        print("no stroke entries found in notes/history.md", file=sys.stderr)
        return 4

    result = loop_report(strokes, window=args.window)

    if args.json:
        # top_modules is a list of tuples; convert for JSON
        out = dict(result)
        out["top_modules"] = [{"module": m, "count": c} for m, c in out["top_modules"]]
        print(json.dumps(out, indent=2))
    else:
        print(f"stroke loop breaker — {result['band']}")
        print(f"  score:   {result['score']}")
        print(f"  window:  {result['total']} strokes analysed")
        print(f"  unique:  {result['unique']} modules")
        print(f"  summary: {result['summary']}")
        if result["repeated_modules"]:
            print(f"  repeated: {', '.join(result['repeated_modules'])}")
        if result["top_modules"]:
            print("  top modules:")
            for mod, cnt in result["top_modules"][:5]:
                print(f"    {mod}: {cnt}x")

    return _EXIT_MAP.get(result["band"], 4)


if __name__ == "__main__":
    sys.exit(main())
