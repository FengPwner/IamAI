#!/usr/bin/env python3
"""stroke_diversity.py — CLI wrapper for iamai.stroke_diversity.

Measures category rotation balance across recent strokes.

Usage:
    python3 tools/stroke_diversity.py                   # default: last 60 strokes
    python3 tools/stroke_diversity.py --tail 120        # last 120 strokes
    python3 tools/stroke_diversity.py --json            # machine-readable output
    python3 tools/stroke_diversity.py --fixation 0.4    # fixation threshold

Exit codes:
    0 — diversity is healthy (balanced or skewed)
    1 — diversity is low (fixated)
    2 — insufficient data (< 6 strokes)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_diversity import ALL_KINDS, diversity_report

DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"


def parse_stroke_kinds(strokes_file: Path, tail: int = 60) -> list[str]:
    """Read the last `tail` strokes and return their kind values."""
    if not strokes_file.exists():
        return []
    try:
        with open(strokes_file, "r") as f:
            all_lines = f.readlines()
            lines = all_lines[-tail:]
    except (OSError, IOError):
        return []

    kinds: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            stroke = json.loads(line)
            kind = stroke.get("kind", "")
            if kind:
                kinds.append(kind)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return kinds


def format_human(result: dict) -> str:
    """Format diversity report for human-readable output."""
    if result["label"] == "insufficient_data":
        return (
            f"stroke diversity: insufficient data "
            f"({result['count']} strokes, need >= 6)"
        )

    counts_str = ", ".join(
        f"{k}={v}" for k, v in sorted(result["kind_counts"].items())
    )
    missing_str = (
        ", ".join(result["missing_kinds"]) if result["missing_kinds"] else "none"
    )

    lines = [
        f"stroke diversity: {result['label']}",
        f"  diversity_index: {result['diversity_index']:.4f}  "
        f"(0=monoculture, 1=perfectly uniform)",
        f"  dominant:        {result['dominant_kind']} at "
        f"{result['dominant_share']:.1%} of strokes",
        f"  fixation:        {'yes' if result['is_fixated'] else 'no'}",
        f"  missing kinds:   {missing_str}",
        f"  entropy:         {result['entropy']:.3f} / "
        f"{result['max_entropy']:.3f} bits",
        f"  counts:          {counts_str}",
        f"  strokes:         {result['count']} analyzed",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure stroke category diversity and rotation health."
    )
    parser.add_argument(
        "--strokes-file",
        type=Path,
        default=DEFAULT_STROKES,
        help=f"path to strokes.jsonl (default: {DEFAULT_STROKES})",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=60,
        help="number of recent strokes to analyze (default: 60)",
    )
    parser.add_argument(
        "--fixation",
        type=float,
        default=0.4,
        help="dominant_share above which is_fixated=True (default: 0.4)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="output machine-readable JSON",
    )

    args = parser.parse_args()

    kinds = parse_stroke_kinds(args.strokes_file, args.tail)
    result = diversity_report(kinds, fixation_threshold=args.fixation)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_human(result))

    if result["label"] == "insufficient_data":
        return 2
    elif result["label"] == "fixated":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
