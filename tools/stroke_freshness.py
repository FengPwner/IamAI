#!/usr/bin/env python3
"""CLI wrapper for iamai.stroke_freshness — how stale is the repo right now?

Reads the last line of data/strokes.jsonl and classifies freshness:

    fresh   last stroke < 2× cadence
    warm    last stroke < 5× cadence
    stale   last stroke < 20× cadence
    dead    last stroke ≥ 20× cadence

Usage:
    python3 tools/stroke_freshness.py              # human-readable
    python3 tools/stroke_freshness.py --json        # machine-readable
    python3 tools/stroke_freshness.py --cadence 10  # override cadence

Exit codes:
    0  fresh or warm
    1  stale or dead — caretaker should investigate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_freshness import freshness, freshness_report  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--cadence",
        type=float,
        default=15.0,
        help="expected seconds between strokes (default 15)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit JSON instead of a human-readable line",
    )
    args = ap.parse_args()

    info = freshness(REPO, cadence_seconds=args.cadence)

    if args.json_output:
        # Replace inf with a large number for JSON serialisation
        out = dict(info)
        if out["age_seconds"] == float("inf"):
            out["age_seconds"] = -1
        print(json.dumps(out, indent=2))
    else:
        print(freshness_report(REPO, cadence_seconds=args.cadence))

    return 0 if info["verdict"] in ("fresh", "warm") else 1


if __name__ == "__main__":
    sys.exit(main())
