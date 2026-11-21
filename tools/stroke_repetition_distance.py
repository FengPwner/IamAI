#!/usr/bin/env python3
"""stroke_repetition_distance.py — measure how far apart identical templates recur.

While stroke_novelty.py reports the *ratio* of unique prefixes over a window,
this tool answers a more precise question: when the same template fires again,
how many strokes elapsed since its last appearance?

A tight loop (distance = 6 with 6 templates) means the writer is cycling
through a fixed set with zero variation. A large distance (hundreds of strokes)
means the template pool is big enough that repetition is just a birthday paradox,
not a stall.

Metrics per template prefix:
    last_seen       index of the most recent occurrence
    occurrences     total count in the window
    min_gap         smallest gap between consecutive occurrences
    mean_gap        average gap
    max_gap         largest gap

Summary metrics:
    global_min_gap  smallest gap across all templates
    global_mean_gap average gap across all templates
    tight_loops     templates whose mean_gap < tight_threshold
    severity        'healthy' | 'warn' | 'loop'

Thresholds (tuneable via constants):
    global_mean_gap >= loose_threshold  → healthy
    global_mean_gap >= tight_threshold  → warn  (some cycling)
    global_mean_gap <  tight_threshold  → loop  (tight content loop)

Usage:
    python3 tools/stroke_repetition_distance.py
    python3 tools/stroke_repetition_distance.py --tail 500 --json
    python3 tools/stroke_repetition_distance.py --tight 20 --loose 100

Exit codes:
    0  healthy
    1  warn
    2  loop (tight content cycling detected)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

SEPARATOR = "-- measured now"

# Default thresholds (in stroke-count distance).
# With ~7 templates cycling every 15s, the natural distance is 7.
# A healthy writer producing 200+ unique thoughts should show distances in
# the dozens or hundreds.
DEFAULT_TIGHT = 15   # below this mean gap = tight loop
DEFAULT_LOOSE = 50   # above this mean gap = healthy


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def extract_prefix(text: str) -> str:
    """Strip the 'measured now' suffix to get the stable template prefix."""
    if SEPARATOR in text:
        return text.split(SEPARATOR)[0].strip()
    return text.strip()


def load_strokes(path: Path, tail: int | None = None) -> list[dict]:
    """Load strokes from the JSONL file, optionally keeping only the last N."""
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


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def compute_distances(
    strokes: list[dict],
    window: int | None = None,
) -> dict:
    """Compute per-template repetition distances.

    Returns a dict with:
        total           number of strokes examined
        templates       per-template stats (dict of dicts)
        global_min_gap  smallest gap seen anywhere
        global_mean_gap weighted-average gap across all templates
        tight_loops     list of template prefixes with mean_gap < tight
        severity        'healthy' | 'warn' | 'loop'
    """
    if window is not None:
        strokes = strokes[-window:]

    if not strokes:
        return {
            "total": 0,
            "templates": {},
            "global_min_gap": 0,
            "global_mean_gap": 0.0,
            "tight_loops": [],
            "severity": "loop",
        }

    # Build index: prefix → [indices]
    positions: dict[str, list[int]] = defaultdict(list)
    for idx, s in enumerate(strokes):
        prefix = extract_prefix(s.get("text", ""))
        positions[prefix].append(idx)

    # Per-template stats
    templates: dict[str, dict] = {}
    all_gaps: list[int] = []

    for prefix, indices in positions.items():
        gaps = []
        for i in range(1, len(indices)):
            g = indices[i] - indices[i - 1]
            gaps.append(g)
            all_gaps.append(g)

        templates[prefix] = {
            "occurrences": len(indices),
            "last_seen": indices[-1],
            "min_gap": min(gaps) if gaps else None,
            "mean_gap": round(sum(gaps) / len(gaps), 2) if gaps else None,
            "max_gap": max(gaps) if gaps else None,
        }

    global_min = min(all_gaps) if all_gaps else 0
    global_mean = round(sum(all_gaps) / len(all_gaps), 2) if all_gaps else 0.0

    return {
        "total": len(strokes),
        "templates": templates,
        "global_min_gap": global_min,
        "global_mean_gap": global_mean,
        "tight_loops": [],  # filled in classify()
        "severity": "loop",  # placeholder
    }


def classify(
    result: dict,
    tight: int = DEFAULT_TIGHT,
    loose: int = DEFAULT_LOOSE,
) -> dict:
    """Add severity and tight_loops to a compute_distances result."""
    templates = result["templates"]
    tight_loops = [
        pfx
        for pfx, stats in templates.items()
        if stats["mean_gap"] is not None and stats["mean_gap"] < tight
    ]
    result["tight_loops"] = sorted(tight_loops)

    mean = result["global_mean_gap"]
    if result["total"] == 0:
        result["severity"] = "loop"
    elif mean >= loose:
        result["severity"] = "healthy"
    elif mean >= tight:
        result["severity"] = "warn"
    else:
        result["severity"] = "loop"

    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def severity_exit(severity: str) -> int:
    return {"healthy": 0, "warn": 1, "loop": 2}.get(severity, 2)


def format_report(result: dict) -> str:
    lines = [
        "stroke repetition distance report",
        f"  total strokes examined: {result['total']}",
        f"  global min gap:         {result['global_min_gap']}",
        f"  global mean gap:        {result['global_mean_gap']:.2f}",
        f"  severity:               {result['severity']}",
    ]
    if result["tight_loops"]:
        lines.append(f"  tight loops detected:     {len(result['tight_loops'])}")
        for pfx in result["tight_loops"][:5]:
            stats = result["templates"][pfx]
            lines.append(
                f"    [{stats['occurrences']}x, mean_gap={stats['mean_gap']}] "
                f"{pfx[:70]}"
            )

    # Show the 5 templates with the smallest mean_gap
    ranked = sorted(
        [(pfx, s) for pfx, s in result["templates"].items() if s["mean_gap"] is not None],
        key=lambda x: x[1]["mean_gap"],
    )
    if ranked:
        lines.append("  smallest mean gaps:")
        for pfx, stats in ranked[:5]:
            lines.append(
                f"    min={stats['min_gap']}  mean={stats['mean_gap']:.1f}  "
                f"max={stats['max_gap']}  [{stats['occurrences']}x] "
                f"{pfx[:60]}"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--strokes", type=Path, default=DEFAULT_STROKES,
        help="path to strokes JSONL file",
    )
    ap.add_argument(
        "--tail", type=int, default=None,
        help="only examine the last N strokes (default: all)",
    )
    ap.add_argument(
        "--window", type=int, default=None,
        help="sliding window size within the tail (default: all loaded)",
    )
    ap.add_argument(
        "--tight", type=int, default=DEFAULT_TIGHT,
        help=f"mean gap below this = tight loop (default: {DEFAULT_TIGHT})",
    )
    ap.add_argument(
        "--loose", type=int, default=DEFAULT_LOOSE,
        help=f"mean gap above this = healthy (default: {DEFAULT_LOOSE})",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="output machine-readable JSON",
    )
    args = ap.parse_args()

    strokes = load_strokes(args.strokes, tail=args.tail)
    result = compute_distances(strokes, window=args.window)
    result = classify(result, tight=args.tight, loose=args.loose)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_report(result))

    return severity_exit(result["severity"])


if __name__ == "__main__":
    sys.exit(main())
