#!/usr/bin/env python3
"""CLI: content_loop_detector — detect periodic patterns in writer output.

Checks if the writer is stuck in a structural loop (e.g. cycling through
the same stroke kinds or file targets in a fixed order).

Usage:
    python3 tools/content_loop_detector.py                    # last 100 strokes, kind labels
    python3 tools/content_loop_detector.py --window 300       # wider window
    python3 tools/content_loop_detector.py --label file       # use file paths as labels
    python3 tools/content_loop_detector.py --label text       # use text prefixes
    python3 tools/content_loop_detector.py --json             # machine-readable output

Exit codes:
    0  no loop detected
    1  mild loop (confidence 0.6–0.8)
    2  moderate loop (confidence 0.8–0.95)
    3  severe loop (confidence ≥ 0.95)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.content_loop_detector import (  # noqa: E402
    detect_loop,
    extract_file_labels,
    extract_kind_labels,
    extract_text_prefix_labels,
    load_strokes,
)

_SEVERITY_EXIT = {"NONE": 0, "MILD": 1, "MODERATE": 2, "SEVERE": 3}


def main() -> None:
    ap = argparse.ArgumentParser(description="Content loop detector")
    ap.add_argument("--window", type=int, default=100, help="Number of recent strokes to check")
    ap.add_argument(
        "--label", choices=["kind", "file", "text"], default="kind",
        help="Which label type to analyse (default: kind)",
    )
    ap.add_argument("--confidence", type=float, default=0.6, help="Minimum confidence to declare a loop")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    ap.add_argument("--file", type=str, default=None, help="Path to strokes.jsonl")
    args = ap.parse_args()

    strokes = load_strokes(path=args.file, tail=args.window * 2)
    if not strokes:
        print("no strokes found")
        sys.exit(0)

    # Extract labels
    if args.label == "kind":
        labels = extract_kind_labels(strokes[-args.window:])
    elif args.label == "file":
        labels = extract_file_labels(strokes[-args.window:])
    else:
        labels = extract_text_prefix_labels(strokes[-args.window:])

    report = detect_loop(labels, min_confidence=args.confidence)

    if args.json:
        out = {
            "has_loop": report.has_loop,
            "severity": report.severity,
            "period": report.period,
            "confidence": round(report.confidence, 4),
            "cycle": list(report.cycle),
            "total_labels": report.total_labels,
            "explained": report.explained,
            "label_type": args.label,
        }
        print(json.dumps(out, indent=2))
    else:
        print(report.summary())
        if report.has_loop:
            print(f"  severity: {report.severity}")
            print(f"  {report.explained}/{report.total_labels} positions match the cycle")
            print(f"  cycle: {' → '.join(report.cycle)}")

    sys.exit(_SEVERITY_EXIT.get(report.severity, 0))


if __name__ == "__main__":
    main()
