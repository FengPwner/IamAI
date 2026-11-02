#!/usr/bin/env python3
"""stroke_novelty.py — detect content stalls in the stroke log.

The writer produces one stroke every ~15 seconds. Each stroke has a text
body with a template prefix and a "measured now" suffix. When the writer
runs out of new ideas it keeps cycling through the same small set of
templates — the stroke count grows but the content doesn't.

This tool measures that gap:

  novelty_ratio = unique_prefixes / total_strokes   (over a window)

  ratio > 0.5   healthy — writer is producing varied content
  ratio 0.2-0.5 warn    — narrowing, worth a look
  ratio < 0.2   stall   — writer is looping through a small template set

Usage:
    python3 tools/stroke_novelty.py
    python3 tools/stroke_novelty.py --window 100 --tail 500
    python3 tools/stroke_novelty.py --json

Exit codes:
    0  novelty is healthy
    1  novelty is low (warn)
    2  content stall detected
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections import Counter


REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

SEPARATOR = "-- measured now"

# Thresholds
HEALTHY_THRESHOLD = 0.5
WARN_THRESHOLD = 0.2


def extract_prefix(text: str) -> str:
    """Strip the 'measured now' suffix to get the stable template prefix."""
    if SEPARATOR in text:
        return text.split(SEPARATOR)[0].strip()
    return text.strip()


def load_strokes(path: Path, tail: int | None = None) -> list[dict]:
    """Load strokes from the JSONL file.

    If *tail* is given, only the last N lines are loaded — useful for
    checking recent behaviour without reading the entire log.
    """
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if tail is not None:
        lines = lines[-tail:]
    strokes = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def compute_novelty(strokes: list[dict], window: int | None = None) -> dict:
    """Compute novelty metrics over a list of strokes.

    Returns a dict with:
        total:      number of strokes examined
        unique:     number of distinct template prefixes
        ratio:      unique / total  (1.0 = every stroke is unique)
        top_templates: the 5 most-repeated prefixes with their counts
        severity:   'healthy' | 'warn' | 'stall'
    """
    if window is not None:
        strokes = strokes[-window:]

    if not strokes:
        return {
            "total": 0,
            "unique": 0,
            "ratio": 0.0,
            "top_templates": [],
            "severity": "stall",
        }

    prefixes = [extract_prefix(s.get("text", "")) for s in strokes]
    counter = Counter(prefixes)
    total = len(prefixes)
    unique = len(counter)
    ratio = unique / total if total > 0 else 0.0

    if ratio >= HEALTHY_THRESHOLD:
        severity = "healthy"
    elif ratio >= WARN_THRESHOLD:
        severity = "warn"
    else:
        severity = "stall"

    top = counter.most_common(5)
    return {
        "total": total,
        "unique": unique,
        "ratio": round(ratio, 4),
        "top_templates": [
            {"prefix": p[:80], "count": c} for p, c in top
        ],
        "severity": severity,
    }


def severity_exit(severity: str) -> int:
    return {"healthy": 0, "warn": 1, "stall": 2}.get(severity, 2)


def format_report(result: dict) -> str:
    lines = [
        f"stroke novelty report",
        f"  total strokes examined: {result['total']}",
        f"  unique prefixes:        {result['unique']}",
        f"  novelty ratio:          {result['ratio']:.2%}",
        f"  severity:               {result['severity']}",
    ]
    if result["top_templates"]:
        lines.append("  most repeated templates:")
        for i, t in enumerate(result["top_templates"], 1):
            lines.append(f"    {i}. [{t['count']}x] {t['prefix']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--strokes",
        type=Path,
        default=DEFAULT_STROKES,
        help="path to strokes JSONL file",
    )
    ap.add_argument(
        "--tail",
        type=int,
        default=None,
        help="only examine the last N strokes (default: all)",
    )
    ap.add_argument(
        "--window",
        type=int,
        default=None,
        help="sliding window size within the tail (default: all loaded)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="output machine-readable JSON instead of text",
    )
    args = ap.parse_args()

    strokes = load_strokes(args.strokes, tail=args.tail)
    result = compute_novelty(strokes, window=args.window)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_report(result))

    return severity_exit(result["severity"])


if __name__ == "__main__":
    sys.exit(main())
