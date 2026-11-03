#!/usr/bin/env python3
"""CLI: stroke_diversity — check if the writer is repeating itself.

Usage:
    python3 tools/stroke_diversity.py                 # last 50 strokes
    python3 tools/stroke_diversity.py --window 200    # wider window
    python3 tools/stroke_diversity.py --json           # machine-readable

Exit codes:
    0  healthy  (diversity >= 0.7)
    1  repetitive (0.4–0.7)
    2  looping  (< 0.4)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_diversity import (  # noqa: E402
    diversity_score,
    find_duplicates,
    load_strokes,
)

_HEALTH_EXIT = {"healthy": 0, "repetitive": 1, "looping": 2}


def main() -> None:
    ap = argparse.ArgumentParser(description="Stroke diversity checker")
    ap.add_argument("--window", type=int, default=50, help="Number of recent strokes to check")
    ap.add_argument("--threshold", type=float, default=0.6, help="Duplicate similarity threshold")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    ap.add_argument("--file", type=str, default=None, help="Path to strokes.jsonl")
    args = ap.parse_args()

    strokes = load_strokes(path=args.file, tail=args.window * 2)
    report = diversity_score(strokes, window=args.window)
    dupes = find_duplicates(strokes, threshold=args.threshold, limit=args.window)

    if args.json:
        out = {
            "health": report.health,
            "diversity": report.diversity,
            "total": report.total,
            "unique_bodies": report.unique_bodies,
            "mean_similarity": report.mean_similarity,
            "duplicate_pairs": len(dupes),
            "worst_pair": (
                {
                    "seq_a": report.worst_pair.seq_a,
                    "seq_b": report.worst_pair.seq_b,
                    "similarity": report.worst_pair.similarity,
                }
                if report.worst_pair
                else None
            ),
        }
        print(json.dumps(out, indent=2))
    else:
        print(report.summary())
        if dupes:
            print(f"\n{len(dupes)} duplicate pair(s) (similarity >= {args.threshold}):")
            for d in dupes[:10]:
                print(f"  #{d.seq_a} <-> #{d.seq_b}  sim={d.similarity:.3f}")
                print(f"    a: {d.snippet_a}")
                print(f"    b: {d.snippet_b}")

    sys.exit(_HEALTH_EXIT.get(report.health, 0))


if __name__ == "__main__":
    main()
