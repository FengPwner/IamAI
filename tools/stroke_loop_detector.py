#!/usr/bin/env python3
"""stroke_loop_detector.py — detect when the writer is stuck in a loop.

The writer sometimes falls into a repetitive pattern: the same template
sentence appears over and over with only the metrics suffix changing.
This tool scores recent strokes for loopiness by stripping the trailing
"-- measured now: ..." suffix and checking how many unique bodies remain.

Scoring:
  - window of N strokes → strip metric suffixes → count unique bodies
  - loop_score = 1 - (unique / total)
  - 0.0 = every stroke is different, 1.0 = every stroke is identical

A loop_score above 0.6 over the last 50 strokes is a strong sign the
writer is stuck and the caretaker should restart it or rotate templates.

Usage:
    python3 tools/stroke_loop_detector.py [--window 50] [--threshold 0.6]
    python3 tools/stroke_loop_detector.py --json
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"
DEFAULT_WINDOW = 50
DEFAULT_THRESHOLD = 0.6

# Pattern: strip the trailing metric annotation
METRIC_SUFFIX_RE = re.compile(
    r"\s*--\s*measured now:\s*.*$"
)


def load_recent_strokes(path: Path, window: int) -> list[dict]:
    """Load the last `window` strokes from the JSONL file."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    tail = lines[-window:] if len(lines) >= window else lines
    strokes = []
    for line in tail:
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def strip_metric_suffix(text: str) -> str:
    """Remove the trailing '-- measured now: ...' annotation."""
    return METRIC_SUFFIX_RE.sub("", text).strip()


def compute_loop_score(strokes: list[dict]) -> dict:
    """Compute the loop score for a list of strokes.

    Returns:
        {
            "total": int,
            "unique_bodies": int,
            "loop_score": float,
            "is_looping": bool (based on default threshold),
            "top_repeated": [(body, count), ...]  # top 3 most repeated
        }
    """
    if not strokes:
        return {
            "total": 0,
            "unique_bodies": 0,
            "loop_score": 0.0,
            "is_looping": False,
            "top_repeated": [],
        }

    bodies = [strip_metric_suffix(s.get("text", "")) for s in strokes]
    total = len(bodies)
    unique = set(bodies)
    unique_count = len(unique)

    score = 1.0 - (unique_count / total) if total > 0 else 0.0

    # Count repetitions
    from collections import Counter
    counts = Counter(bodies)
    top_repeated = counts.most_common(3)

    return {
        "total": total,
        "unique_bodies": unique_count,
        "loop_score": round(score, 4),
        "is_looping": score >= DEFAULT_THRESHOLD,
        "top_repeated": [(body, count) for body, count in top_repeated if count > 1],
    }


def detect_loop(
    path: Path = STROKES_PATH,
    window: int = DEFAULT_WINDOW,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict:
    """Main entry point: load strokes and compute loop detection."""
    strokes = load_recent_strokes(path, window)
    result = compute_loop_score(strokes)
    result["is_looping"] = result["loop_score"] >= threshold
    result["window"] = window
    result["threshold"] = threshold
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Detect repetitive loops in writer strokes."
    )
    parser.add_argument(
        "--window", type=int, default=DEFAULT_WINDOW,
        help=f"Number of recent strokes to examine (default {DEFAULT_WINDOW})"
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"Loop score threshold for alerting (default {DEFAULT_THRESHOLD})"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output JSON instead of human-readable text"
    )
    args = parser.parse_args()

    result = detect_loop(window=args.window, threshold=args.threshold)

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        score = result["loop_score"]
        status = "LOOPING" if result["is_looping"] else "OK"
        print(f"[{status}] loop_score={score:.4f} "
              f"({result['unique_bodies']}/{result['total']} unique bodies)")
        if result["top_repeated"]:
            print("Top repeated bodies:")
            for body, count in result["top_repeated"]:
                preview = body[:80] + ("..." if len(body) > 80 else "")
                print(f"  x{count}: {preview}")

    sys.exit(1 if result["is_looping"] else 0)


if __name__ == "__main__":
    main()
