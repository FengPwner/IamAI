#!/usr/bin/env python3
"""CLI: stroke_density — measure writing intensity via sliding-window density.

Usage:
    python3 tools/stroke_density.py
    python3 tools/stroke_density.py --window 15 --step 5
    python3 tools/stroke_density.py --json

Exit codes:
    0  steady or better
    1  sparse
    2  dormant
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_density import density_report  # noqa: E402

_EXIT_MAP = {"hyper": 0, "dense": 0, "steady": 0, "sparse": 1, "dormant": 2}


def _read_jsonl() -> list[str]:
    path = REPO / "data" / "strokes.jsonl"
    if not path.exists():
        print("data/strokes.jsonl not found", file=sys.stderr)
        sys.exit(3)
    return path.read_text(encoding="utf-8").splitlines()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure writing intensity via sliding-window density analysis."
    )
    parser.add_argument(
        "--window", "-w", type=int, default=10,
        help="window width in minutes (default: 10)"
    )
    parser.add_argument(
        "--step", "-s", type=int, default=5,
        help="step between windows in minutes (default: 5)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="output as JSON"
    )
    args = parser.parse_args()

    lines = _read_jsonl()
    report = density_report(lines, window_minutes=args.window, step_minutes=args.step)
    summary = report["summary"]

    if args.json:
        # convert datetimes for JSON serialisation
        out = {
            "strokes_parsed": report["strokes_parsed"],
            "window_count": summary["total_windows"],
            "band_distribution": summary["band_distribution"],
            "mean_density": summary["mean_density"],
            "peak_density": summary["peak_density"],
            "peak_window": summary["peak_window"],
            "dominant_band": summary["dominant_band"],
        }
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"strokes parsed:    {report['strokes_parsed']}")
        print(f"analysis windows:  {summary['total_windows']}")
        print(f"mean density:      {summary['mean_density']:.2f} strokes/min")
        print(f"peak density:      {summary['peak_density']:.2f} strokes/min")
        print(f"dominant band:     {summary['dominant_band']}")
        print()
        print("band distribution:")
        for band in ("dormant", "sparse", "steady", "dense", "hyper"):
            count = summary["band_distribution"].get(band, 0)
            pct = count / summary["total_windows"] * 100 if summary["total_windows"] else 0
            bar = "█" * int(pct / 2)
            print(f"  {band:10s}  {count:4d}  ({pct:5.1f}%)  {bar}")
        if summary["peak_window"]:
            pw = summary["peak_window"]
            print()
            print(f"peak window: {pw['start'][:19]} → {pw['end'][:19]}")
            print(f"  {pw['count']} strokes, {pw['density']:.2f}/min ({pw['band']})")

    return _EXIT_MAP.get(summary["dominant_band"], 0)


if __name__ == "__main__":
    sys.exit(main())
