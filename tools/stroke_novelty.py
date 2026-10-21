#!/usr/bin/env python3
"""CLI: stroke_novelty — detect repetitive content in the writer's output.

Usage:
    python3 tools/stroke_novelty.py                    # last 50 strokes
    python3 tools/stroke_novelty.py --count 100        # last 100 strokes
    python3 tools/stroke_novelty.py --all              # all strokes
    python3 tools/stroke_novelty.py --json             # machine-readable
    python3 tools/stroke_novelty.py --lookback 20      # compare against 20 predecessors

Exit codes:
    0  healthy
    1  stagnating
    2  loop (severe repetition)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_novelty import StrokeNovelty  # noqa: E402

_VERDICT_EXIT = {"healthy": 0, "stagnating": 1, "loop": 2}


def load_strokes(repo: Path) -> list[dict]:
    """Load strokes from data/strokes.jsonl."""
    path = repo / "data" / "strokes.jsonl"
    if not path.exists():
        return []
    strokes = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Stroke novelty scorer — detect content repetition.",
    )
    ap.add_argument(
        "--count", type=int, default=50,
        help="Number of recent strokes to analyse (default: 50).",
    )
    ap.add_argument(
        "--all", action="store_true", dest="all_strokes",
        help="Analyse all strokes instead of just the last N.",
    )
    ap.add_argument(
        "--lookback", type=int, default=10,
        help="Compare each stroke against this many predecessors (default: 10).",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="Output machine-readable JSON.",
    )
    args = ap.parse_args()

    strokes = load_strokes(REPO)
    if not strokes:
        if args.json:
            print(json.dumps({"verdict": "healthy", "total": 0, "message": "no strokes found"}))
        else:
            print("No strokes found in data/strokes.jsonl")
        return 0

    if not args.all_strokes:
        strokes = strokes[-args.count:]

    sn = StrokeNovelty(lookback=args.lookback)
    results = sn.score_many(strokes)
    verdict = sn.stream_verdict(window=len(results))

    if args.json:
        output = {
            **verdict,
            "lookback": args.lookback,
            "strokes": [r.to_dict() for r in results[-args.count:]],
        }
        print(json.dumps(output, indent=2))
    else:
        v = verdict["verdict"]
        n = verdict["total"]
        avg = verdict["avg_novelty"]
        print(f"stream verdict: {v.upper()}  ({n} strokes, avg novelty {avg:.2f})")
        print(
            f"  fresh: {verdict['fresh']}  "
            f"familiar: {verdict['familiar']}  "
            f"repetitive: {verdict['repetitive']}  "
            f"clone: {verdict['clone']}"
        )
        print()

        # Show the worst offenders (clones first).
        clones = [r for r in results if r.verdict == "clone"]
        if clones:
            print(f"--- {len(clones)} clone strokes (near-duplicates) ---")
            for r in clones[:10]:
                print(f"  seq {r.seq}: novelty {r.novelty:.2f} (nearest: seq {r.nearest_neighbour})")
            if len(clones) > 10:
                print(f"  ... and {len(clones) - 10} more")
            print()

        reps = [r for r in results if r.verdict == "repetitive"]
        if reps:
            print(f"--- {len(reps)} repetitive strokes ---")
            for r in reps[:5]:
                print(f"  seq {r.seq}: novelty {r.novelty:.2f} (nearest: seq {r.nearest_neighbour})")
            if len(reps) > 5:
                print(f"  ... and {len(reps) - 5} more")

    return _VERDICT_EXIT.get(verdict["verdict"], 0)


if __name__ == "__main__":
    sys.exit(main())
