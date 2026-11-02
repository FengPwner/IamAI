#!/usr/bin/env python3
"""stroke_pace_checker.py — is the writer keeping pace?

Reads the last N strokes from data/strokes.jsonl, computes the median
inter-stroke interval, and compares it against the expected cadence.

Verdicts:
    on-pace   — median interval within 1.5× expected cadence
    drifting  — median interval between 1.5× and 3× expected cadence
    stalled   — median interval exceeds 3× expected cadence, or no recent strokes

Exit codes:
    0 — on-pace
    1 — drifting or stalled
    2 — error (file not found, malformed data)

Usage:
    python3 tools/stroke_pace_checker.py
    python3 tools/stroke_pace_checker.py --expected-cadence 15 --lookback 20
    python3 tools/stroke_pace_checker.py --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"


@dataclass
class PaceReport:
    expected_cadence: int
    median_interval: float
    mean_interval: float
    verdict: str  # "on-pace" | "drifting" | "stalled"
    stroke_count: int
    last_stroke_at: Optional[str]
    checked_at: str


def parse_timestamp(ts: str) -> datetime:
    """Parse ISO-8601 timestamp to datetime. Handles both +00:00 and Z suffix."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def load_recent_strokes(path: Path, n: int) -> List[dict]:
    """Load the last n strokes from the JSONL file."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        return []
    recent = lines[-n:] if len(lines) >= n else lines
    strokes = []
    for line in recent:
        line = line.strip()
        if line:
            strokes.append(json.loads(line))
    return strokes


def compute_intervals(strokes: List[dict]) -> List[float]:
    """Compute inter-stroke intervals in seconds from a list of strokes."""
    if len(strokes) < 2:
        return []
    intervals = []
    for i in range(1, len(strokes)):
        t_prev = parse_timestamp(strokes[i - 1]["at"])
        t_curr = parse_timestamp(strokes[i]["at"])
        delta = (t_curr - t_prev).total_seconds()
        if delta > 0:
            intervals.append(delta)
    return intervals


def classify_pace(median_interval: float, expected_cadence: int) -> str:
    """Classify the writer pace based on median interval vs expected cadence."""
    if expected_cadence <= 0:
        return "stalled"
    ratio = median_interval / expected_cadence
    if ratio <= 1.5:
        return "on-pace"
    elif ratio <= 3.0:
        return "drifting"
    else:
        return "stalled"


def check_pace(
    strokes_path: Path = STROKES_PATH,
    expected_cadence: int = 15,
    lookback: int = 20,
) -> PaceReport:
    """Run the pace check and return a report."""
    now = datetime.now(timezone.utc).isoformat()
    strokes = load_recent_strokes(strokes_path, lookback)

    if not strokes:
        return PaceReport(
            expected_cadence=expected_cadence,
            median_interval=float("inf"),
            mean_interval=float("inf"),
            verdict="stalled",
            stroke_count=0,
            last_stroke_at=None,
            checked_at=now,
        )

    intervals = compute_intervals(strokes)
    last_at = strokes[-1].get("at")

    if not intervals:
        return PaceReport(
            expected_cadence=expected_cadence,
            median_interval=float("inf"),
            mean_interval=float("inf"),
            verdict="stalled",
            stroke_count=len(strokes),
            last_stroke_at=last_at,
            checked_at=now,
        )

    median_iv = statistics.median(intervals)
    mean_iv = statistics.mean(intervals)
    verdict = classify_pace(median_iv, expected_cadence)

    return PaceReport(
        expected_cadence=expected_cadence,
        median_interval=round(median_iv, 2),
        mean_interval=round(mean_iv, 2),
        verdict=verdict,
        stroke_count=len(strokes),
        last_stroke_at=last_at,
        checked_at=now,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--expected-cadence", type=int, default=15, help="expected seconds between strokes")
    ap.add_argument("--lookback", type=int, default=20, help="number of recent strokes to examine")
    ap.add_argument("--json", action="store_true", help="output JSON report")
    args = ap.parse_args()

    try:
        report = check_pace(
            expected_cadence=args.expected_cadence,
            lookback=args.lookback,
        )
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(f"pace: {report.verdict}")
        print(f"  median interval: {report.median_interval}s (expected: {report.expected_cadence}s)")
        print(f"  mean interval:   {report.mean_interval}s")
        print(f"  strokes checked: {report.stroke_count}")
        print(f"  last stroke at:  {report.last_stroke_at}")

    return 0 if report.verdict == "on-pace" else 1


if __name__ == "__main__":
    sys.exit(main())
