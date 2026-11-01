#!/usr/bin/env python3
"""stroke_kind_deficit.py — identify underrepresented stroke kinds.

The writer produces ~15 strokes per minute.  Almost all land as "thought"
kind, leaving other kinds (devlog, garden, snippet, note, metrics,
reading, caretaker) starved.  This tool quantifies the deficit.

Usage:
    python3 tools/stroke_kind_deficit.py              # human-readable
    python3 tools/stroke_kind_deficit.py --json       # JSON output
    python3 tools/stroke_kind_deficit.py --target 100 # custom target per kind

Exit code:
    0  all kinds at or above target
    1  at least one kind below target
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"

# Kinds the writer *should* produce, in addition to "thought".
EXPECTED_KINDS = [
    "devlog",
    "garden",
    "snippet",
    "note",
    "metrics",
    "reading",
    "caretaker",
    "thought",
]

# Default: each non-thought kind should have at least this many strokes
# per 1000 total strokes (roughly one per 100, i.e. ~1% each).
DEFAULT_MIN_PER_1K = 10


def load_kind_counts(strokes_path: Path) -> Counter:
    """Read strokes.jsonl and return a Counter of kind -> count."""
    counts: Counter = Counter()
    if not strokes_path.exists():
        return counts
    with open(strokes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                stroke = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = stroke.get("kind", "unknown")
            counts[kind] += 1
    return counts


def compute_deficits(
    counts: Counter,
    expected_kinds: list[str] | None = None,
    min_per_1k: int = DEFAULT_MIN_PER_1K,
) -> list[dict]:
    """Return a list of deficit records, one per expected kind.

    Each record:
        kind:       str
        count:      int   — actual stroke count
        expected:   int   — minimum expected count
        deficit:    int   — expected - count (positive = shortfall)
        pct:        float — count / total * 100
    """
    if expected_kinds is None:
        expected_kinds = EXPECTED_KINDS
    total = max(sum(counts.values()), 1)
    # Scale target proportionally to total strokes
    scale = total / 1000.0
    deficits = []
    for kind in expected_kinds:
        actual = counts.get(kind, 0)
        expected = int(min_per_1k * scale)
        deficit = max(0, expected - actual)
        pct = round(actual / total * 100, 2)
        deficits.append(
            {
                "kind": kind,
                "count": actual,
                "expected": expected,
                "deficit": deficit,
                "pct": pct,
            }
        )
    # Sort: largest deficit first
    deficits.sort(key=lambda d: d["deficit"], reverse=True)
    return deficits


def format_table(deficits: list[dict], total: int) -> str:
    """Render deficits as an aligned text table."""
    lines = [
        f"stroke kind deficit report  (total: {total} strokes)",
        "",
        f"  {'kind':<12} {'count':>7} {'expected':>8} {'deficit':>7} {'pct':>7}",
        f"  {'-'*12} {'-'*7} {'-'*8} {'-'*7} {'-'*7}",
    ]
    for d in deficits:
        flag = " ← STARVED" if d["deficit"] > 0 else ""
        lines.append(
            f"  {d['kind']:<12} {d['count']:>7} {d['expected']:>8} "
            f"{d['deficit']:>7} {d['pct']:>6.2f}%{flag}"
        )
    starved = [d["kind"] for d in deficits if d["deficit"] > 0]
    lines.append("")
    if starved:
        lines.append(
            f"  recommendation: next strokes should favor: "
            f"{', '.join(starved[:3])}"
        )
    else:
        lines.append("  all kinds are at or above target — balanced")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Identify underrepresented stroke kinds"
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument(
        "--target",
        type=int,
        default=DEFAULT_MIN_PER_1K,
        help=f"minimum strokes per kind per 1000 total (default {DEFAULT_MIN_PER_1K})",
    )
    parser.add_argument(
        "--log",
        type=str,
        default=None,
        help="path to strokes.jsonl (default: data/strokes.jsonl)",
    )
    args = parser.parse_args()

    strokes_path = Path(args.log) if args.log else STROKES_PATH
    counts = load_kind_counts(strokes_path)
    total = max(sum(counts.values()), 1)
    deficits = compute_deficits(counts, min_per_1k=args.target)

    if args.json:
        print(json.dumps({"total": total, "deficits": deficits}, indent=2))
    else:
        print(format_table(deficits, total))

    has_deficit = any(d["deficit"] > 0 for d in deficits)
    return 1 if has_deficit else 0


if __name__ == "__main__":
    sys.exit(main())
