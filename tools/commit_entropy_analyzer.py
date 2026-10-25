#!/usr/bin/env python3
"""commit_entropy_analyzer.py — measure diversity of stroke categories over time.

Reads strokes.jsonl and computes a Shannon-entropy-based diversity score
over a sliding window.  Low entropy means writing is concentrating on fewer
categories; high entropy means broad, balanced output across categories.

Usage:
    python3 tools/commit_entropy_analyzer.py
    python3 tools/commit_entropy_analyzer.py --window 50
    python3 tools/commit_entropy_analyzer.py --json

Exit codes:
    0 — analysis complete
    2 — unexpected error
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO / "data" / "strokes.jsonl"
DEFAULT_WINDOW = 100  # number of recent strokes to analyze


def load_strokes(path: Path = STROKES_FILE) -> list[dict]:
    """Load all stroke records from the JSONL file."""
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                try:
                    records.append(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
    return records


def extract_categories(records: list[dict], window: int = DEFAULT_WINDOW) -> list[str]:
    """Extract the last `window` category values from stroke records."""
    tail = records[-window:] if len(records) > window else records
    categories = []
    for r in tail:
        kind = r.get("kind", r.get("category", "unknown"))
        categories.append(str(kind))
    return categories


def shannon_entropy(categories: list[str]) -> float:
    """Compute Shannon entropy (bits) of a category distribution.

    Returns 0.0 for empty or single-element lists.
    Maximum entropy = log2(n_unique) when all categories are equally frequent.
    """
    if len(categories) <= 1:
        return 0.0
    total = len(categories)
    counts = Counter(categories)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


def max_entropy(categories: list[str]) -> float:
    """Maximum possible entropy given the observed number of unique categories."""
    n_unique = len(set(categories))
    if n_unique <= 1:
        return 0.0
    return math.log2(n_unique)


def normalized_entropy(categories: list[str]) -> float:
    """Entropy normalized to 0–1 range (1 = perfectly uniform distribution)."""
    me = max_entropy(categories)
    if me == 0:
        return 0.0
    return shannon_entropy(categories) / me


def category_breakdown(categories: list[str]) -> dict[str, dict]:
    """Return per-category count and percentage."""
    total = len(categories)
    if total == 0:
        return {}
    counts = Counter(categories)
    return {
        cat: {"count": cnt, "pct": round(cnt / total * 100, 1)}
        for cat, cnt in sorted(counts.items(), key=lambda x: -x[1])
    }


def diversity_score(categories: list[str]) -> dict:
    """Compute a full diversity report for the given category list."""
    ent = shannon_entropy(categories)
    norm = normalized_entropy(categories)
    me = max_entropy(categories)
    return {
        "total_strokes": len(categories),
        "unique_categories": len(set(categories)),
        "entropy_bits": round(ent, 4),
        "max_entropy_bits": round(me, 4),
        "normalized_entropy": round(norm, 4),
        "grade": grade_diversity(norm),
        "breakdown": category_breakdown(categories),
    }


def grade_diversity(normalized: float) -> str:
    """Assign a letter grade based on normalized entropy."""
    if normalized >= 0.90:
        return "UNIFORM"    # perfectly balanced
    elif normalized >= 0.75:
        return "DIVERSE"    # good spread
    elif normalized >= 0.50:
        return "MODERATE"   # some concentration
    elif normalized >= 0.25:
        return "SKEWED"     # heavy concentration
    else:
        return "NARROW"     # almost single-category


def format_text(report: dict) -> str:
    """Format the diversity report as human-readable text."""
    lines = [
        f"Commit Entropy Analysis ({report['total_strokes']} strokes)",
        f"  unique categories : {report['unique_categories']}",
        f"  entropy           : {report['entropy_bits']:.4f} / {report['max_entropy_bits']:.4f} bits",
        f"  normalized        : {report['normalized_entropy']:.4f}",
        f"  grade             : {report['grade']}",
        "",
        "  breakdown:",
    ]
    for cat, info in report["breakdown"].items():
        lines.append(f"    {cat:12s}  {info['count']:4d}  ({info['pct']:.1f}%)")
    return "\n".join(lines)


def analyze(
    path: Path = STROKES_FILE,
    window: int = DEFAULT_WINDOW,
) -> dict:
    """Full analysis pipeline: load → extract → score."""
    records = load_strokes(path)
    categories = extract_categories(records, window)
    return diversity_score(categories)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Analyze commit category entropy")
    p.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                   help=f"Number of recent strokes to analyze (default {DEFAULT_WINDOW})")
    p.add_argument("--json", action="store_true", help="JSON output")
    args = p.parse_args(argv)

    try:
        report = analyze(window=args.window)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
