#!/usr/bin/env python3
"""CLI: stroke_entropy — information-theoretic diversity analysis.

Usage:
    python3 tools/stroke_entropy.py
    python3 tools/stroke_entropy.py --window 100
    python3 tools/stroke_entropy.py --json

Exit codes:
    0  exploring (entropy >= 4.5 bits)
    1  routine   (entropy 3.0–4.5 bits)
    2  looping   (entropy < 3.0 bits)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_entropy import (  # noqa: E402
    analyze,
    entropy_report,
)


_EXIT_MAP = {"exploring": 0, "routine": 1, "looping": 2}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Information-theoretic diversity analysis of stroke texts.",
    )
    parser.add_argument(
        "--window", type=int, default=50,
        help="Number of recent strokes to analyze (default: 50).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--path", type=str, default=None,
        help="Path to strokes JSONL file.",
    )
    args = parser.parse_args(argv)

    strokes_path = Path(args.path) if args.path else REPO / "data" / "strokes.jsonl"
    result = analyze(path=strokes_path, window=args.window)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(entropy_report(result))

    if "error" in result:
        return 1
    return _EXIT_MAP.get(result.get("verdict", "routine"), 1)


if __name__ == "__main__":
    sys.exit(main())
