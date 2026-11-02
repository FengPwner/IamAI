#!/usr/bin/env python3
"""stroke_vitality.py — composite health score for the writing process.

Reads ``data/strokes.jsonl`` and computes a single 0–100 vitality score
combining four dimensions:

    rate          strokes/hour vs. target
    novelty       token-level freshness against a sliding window
    kind_balance  Shannon entropy of kind distribution
    coherence     pairwise similarity between consecutive strokes

Verdicts: thriving (>=80), healthy (>=60), struggling (>=40), stagnant (<40).

Usage:
    python3 tools/stroke_vitality.py                  # default: last 200 strokes
    python3 tools/stroke_vitality.py --window 500     # last 500 strokes
    python3 tools/stroke_vitality.py --target 240     # target 240 strokes/hr
    python3 tools/stroke_vitality.py --json           # machine-readable output

Exit code: 0 (always succeeds)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_vitality import (  # noqa: E402
    VitalityScorer,
    format_report,
)

STROKES_PATH = REPO / "data" / "strokes.jsonl"


def load_strokes(path: Path, window: int) -> list[dict]:
    """Read the last *window* strokes from the JSONL file."""
    if not path.exists():
        return []
    strokes: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return strokes[-window:]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--window", type=int, default=200, help="number of recent strokes to assess"
    )
    ap.add_argument(
        "--target",
        type=float,
        default=300.0,
        help="target strokes per hour (default: 300)",
    )
    ap.add_argument(
        "--novelty-window",
        type=int,
        default=10,
        help="sliding window for novelty comparison (default: 10)",
    )
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    strokes = load_strokes(STROKES_PATH, args.window)
    if not strokes:
        if args.json:
            print(json.dumps({"error": "no strokes found", "score": 0}))
        else:
            print("no strokes found in", STROKES_PATH)
        return 0

    scorer = VitalityScorer(
        novelty_window=args.novelty_window,
        target_rate=args.target,
    )
    report = scorer.assess_from_strokes(strokes, window=args.window)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report))
        # Show weakest dimension for actionable insight
        weakest = report.weakest_dimension
        print(f"  weakest: {weakest} ({report.breakdown.get(weakest, 0):.2f})")
        if report.details.get("kind_counts"):
            kc = report.details["kind_counts"]
            sorted_kinds = sorted(kc.items(), key=lambda x: -x[1])
            print(f"  kinds: {', '.join(f'{k}={v}' for k, v in sorted_kinds)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
