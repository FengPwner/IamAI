#!/usr/bin/env python3
"""CLI: stall_loss_estimator — find stalls in the stroke log and estimate
how many strokes were lost.

Usage:
    python3 tools/stall_loss_estimator.py
    python3 tools/stall_loss_estimator.py --cadence 15 --threshold 1200
    python3 tools/stall_loss_estimator.py --json

Exit codes:
    0  no stalls detected, or all minor
    1  moderate stalls found (100–500 expected strokes lost each)
    2  severe stalls found (> 500 expected strokes lost)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stall_loss_estimator import estimate_losses  # noqa: E402

STROKES_FILE = REPO / "data" / "strokes.jsonl"

_EXIT_MAP = {None: 0, "minor": 0, "moderate": 1, "severe": 2}


def _load_timestamps(path: Path) -> list[float]:
    """Parse ISO-8601 timestamps from the strokes JSONL file."""
    epochs: list[float] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                ts_str = obj.get("at", "")
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                epochs.append(dt.timestamp())
            except (json.JSONDecodeError, ValueError, KeyError):
                continue
    return sorted(epochs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cadence", type=float, default=15.0,
                    help="expected seconds between strokes (default: 15)")
    ap.add_argument("--threshold", type=float, default=1200.0,
                    help="minimum gap seconds to flag as stall (default: 1200)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="output JSON instead of human-readable text")
    ap.add_argument("--file", type=str, default=None,
                    help="path to strokes JSONL (default: data/strokes.jsonl)")
    args = ap.parse_args()

    strokes_path = Path(args.file) if args.file else STROKES_FILE
    if not strokes_path.exists():
        print(f"strokes file not found: {strokes_path}", file=sys.stderr)
        return 3

    timestamps = _load_timestamps(strokes_path)
    if not timestamps:
        print("no timestamps found in strokes file", file=sys.stderr)
        return 3

    report = estimate_losses(timestamps, cadence=args.cadence, gap_threshold=args.threshold)

    if args.as_json:
        output = report.as_dict()
        output["stalls"] = [s.as_dict() for s in report.stalls]
        print(json.dumps(output, indent=2))
    else:
        print(f"strokes analysed: {report.total_strokes}")
        print(f"stalls detected:  {report.stall_count}")
        print(f"total gap time:   {report.total_gap_seconds:.0f}s ({report.total_gap_seconds / 3600:.1f}h)")
        print(f"expected lost:    {report.total_expected_lost} strokes")
        print(f"health score:     {report.health_score:.4f} (0=perfect, 1=catastrophic)")
        print(f"worst severity:   {report.worst_severity or 'none'}")
        if report.stalls:
            print()
            print("recent stalls (last 10):")
            for s in report.stalls[-10:]:
                print(f"  gap={s.gap_seconds:.0f}s  lost={s.expected_strokes}  "
                      f"recovery={s.recovery_seconds:.0f}s  severity={s.loss_severity}")

    return _EXIT_MAP.get(report.worst_severity, 0)


if __name__ == "__main__":
    sys.exit(main())
