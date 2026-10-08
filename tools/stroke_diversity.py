#!/usr/bin/env python3
"""stroke_diversity.py — measure how evenly strokes spread across kinds.

The writer targets six kinds (devlog, garden, metrics, note, snippet,
thought) in roughly equal proportions. In practice, writer restarts,
stash conflicts, and category-specific failures can skew the distribution:
one kind pulls ahead while another silently starves.

This tool computes a simple imbalance score:
  - perfect balance → 0.0
  - all strokes in one kind → 1.0

An imbalance above 0.4 over a large window usually means one kind's
generator is broken or the round-robin scheduler is skipping a slot.

Usage:
    python3 tools/stroke_diversity.py [--window 100]
    python3 tools/stroke_diversity.py --json
"""

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"
DEFAULT_KINDS = ("devlog", "garden", "metrics", "note", "snippet", "thought")


def load_recent_strokes(path: Path, window: int) -> list[dict]:
    """Load the last `window` strokes from the JSONL file.

    Reads from the tail to avoid loading the entire file for large histories.
    """
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    tail = lines[-window:] if len(lines) > window else lines
    strokes = []
    for line in tail:
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def compute_imbalance(strokes: list[dict], expected_kinds: tuple[str, ...] = DEFAULT_KINDS) -> float:
    """Compute imbalance score in [0, 1].

    Uses normalized deviation from uniform distribution:
      imbalance = sum(|observed_i - expected_i|) / (2 * n)
    where expected_i = n / k for each kind.

    Returns 0.0 for perfect balance, approaches 1.0 for maximum skew.
    Returns 0.0 if there are no strokes (vacuously balanced).
    """
    if not strokes:
        return 0.0

    counts = Counter(s.get("kind", "unknown") for s in strokes)
    n = len(strokes)
    k = len(expected_kinds)
    expected = n / k

    deviation = sum(abs(counts.get(kind, 0) - expected) for kind in expected_kinds)
    # Normalize: max deviation is 2*n*(k-1)/k when all strokes land in one kind
    max_deviation = 2 * n * (k - 1) / k
    if max_deviation == 0:
        return 0.0
    return round(deviation / max_deviation, 4)


def compute_entropy(strokes: list[dict], expected_kinds: tuple[str, ...] = DEFAULT_KINDS) -> float:
    """Compute Shannon entropy of the kind distribution (in bits).

    Maximum entropy = log2(k) when perfectly balanced.
    Minimum entropy = 0 when all strokes are one kind.
    """
    if not strokes:
        return 0.0

    counts = Counter(s.get("kind", "unknown") for s in strokes)
    n = len(strokes)
    entropy = 0.0
    for kind in expected_kinds:
        c = counts.get(kind, 0)
        if c > 0:
            p = c / n
            entropy -= p * math.log2(p)
    return round(entropy, 4)


def classify_imbalance(score: float) -> str:
    """Human-readable label for the imbalance score."""
    if score < 0.1:
        return "balanced"
    elif score < 0.25:
        return "mild-skew"
    elif score < 0.4:
        return "noticeable"
    else:
        return "starved"


def main():
    parser = argparse.ArgumentParser(description="Measure stroke kind diversity")
    parser.add_argument("--window", type=int, default=100,
                        help="Number of recent strokes to analyze (default: 100)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    strokes = load_recent_strokes(STROKES_PATH, args.window)
    if not strokes:
        if args.json:
            print(json.dumps({"error": "no strokes found"}))
        else:
            print("no strokes found", file=sys.stderr)
        sys.exit(1)

    counts = Counter(s.get("kind", "unknown") for s in strokes)
    imbalance = compute_imbalance(strokes)
    entropy = compute_entropy(strokes)
    label = classify_imbalance(imbalance)

    result = {
        "window": len(strokes),
        "imbalance": imbalance,
        "entropy_bits": entropy,
        "max_entropy": round(math.log2(len(DEFAULT_KINDS)), 4),
        "classification": label,
        "counts": dict(sorted(counts.items())),
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"stroke diversity: {label} (imbalance={imbalance}, entropy={entropy}/{result['max_entropy']} bits)")
        for kind, count in sorted(counts.items()):
            pct = round(count / len(strokes) * 100, 1)
            print(f"  {kind:10s} {count:5d}  ({pct}%)")


if __name__ == "__main__":
    main()
