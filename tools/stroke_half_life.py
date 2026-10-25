#!/usr/bin/env python3
"""CLI: stroke_half_life — topic recurrence interval report.

Usage:
    python3 tools/stroke_half_life.py                  # human-readable
    python3 tools/stroke_half_life.py --json           # machine-readable
    python3 tools/stroke_half_life.py --writer qwen    # filter by writer
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_half_life import TopicHalfLife  # noqa: E402


def load_strokes(repo: Path, writer: str | None = None) -> list[dict]:
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
    ap = argparse.ArgumentParser(description="Topic recurrence intervals.")
    ap.add_argument("--writer", default=None,
                    help="filter strokes by writer identity")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="output JSON instead of text")
    ap.add_argument("--hot", type=float, default=120.0,
                    help="hot threshold in seconds (default: 120)")
    ap.add_argument("--cold", type=float, default=1800.0,
                    help="cold threshold in seconds (default: 1800)")
    args = ap.parse_args()

    strokes = load_strokes(REPO, writer=args.writer)
    if not strokes:
        print("no strokes found")
        return 1

    thl = TopicHalfLife.from_strokes(
        strokes,
        hot_threshold=args.hot,
        cold_threshold=args.cold,
    )

    if args.as_json:
        print(json.dumps(thl.summary(), indent=2, default=str))
    else:
        print(thl.report())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
