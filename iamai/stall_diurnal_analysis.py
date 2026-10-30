"""Stall diurnal analysis — test whether writer stalls cluster at specific hours.

Background
----------
Caretaker visits 258, 259, and 261 ruled out three stall hypotheses:

  - batch-interval correlation   (score 0.20 — independent)
  - uptime fatigue             (score 0.50 — mixed / neutral)
  - stroke content properties  (length 0.47, metric 0.51 — independent)

The remaining candidate is **environmental / infrastructure**: stalls
caused by host-level events (maintenance windows, cron jobs, cloud
provider throttling, container recycling) that strike at predictable
wall-clock hours rather than being triggered by internal process state.

If stalls cluster at specific hours (e.g. 02:00–06:00 GMT+8), the
cause is environmental rather than internal.

Approach
--------
1. Parse stroke timestamps from ``data/strokes.jsonl``.
2. Identify stalls (gaps > threshold).
3. For each stall, record the **hour** (GMT+8) of the gap's midpoint.
4. Build a 24-bin histogram of stall hours.
5. Compute a uniformity score: how far the distribution deviates
   from uniform (chi-squared or max-bin ratio).
6. Classify the result:

   ===================  ============================================
   verdict              meaning
   ===================  ============================================
   ``strong_diurnal``   stalls strongly cluster at specific hours
   ``weak_diurnal``     mild hour-clustering detected
   ``uniform``          stalls distributed evenly across hours
   ===================  ============================================

Public API
----------
- ``stall_hours(timestamps, threshold)`` → list[int] (0–23)
- ``hour_histogram(hours)`` → dict[int, int]
- ``uniformity_score(hist)`` → float  (0.0 = perfectly uniform,
  1.0 = all in one bin)
- ``diurnal_verdict(hist)`` → str
- ``diurnal_summary(hist, verdict)`` → str (human-readable one-liner)

Usage::

    from iamai.stall_diurnal_analysis import (
        stall_hours, hour_histogram, uniformity_score, diurnal_verdict,
    )
    hours = stall_hours(timestamps, threshold=300)
    hist = hour_histogram(hours)
    score = uniformity_score(hist)
    verdict = diurnal_verdict(hist)

Run as script::

    python3 tools/stall_diurnal_analysis.py
    python3 tools/stall_diurnal_analysis.py --threshold 600
    python3 tools/stall_diurnal_analysis.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"

# GMT+8 offset used throughout the IamAI project
GMT8 = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# pure helpers (no I/O — easy to test)
# ---------------------------------------------------------------------------

def parse_timestamps(records: List[dict]) -> List[datetime]:
    """Extract aware datetimes from stroke records.

    Handles both ``at`` and ``t`` field names (see visit 261 data note
    about stroke 4007).
    """
    out: List[datetime] = []
    for r in records:
        raw = r.get("at") or r.get("t")
        if raw is None:
            continue
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        out.append(dt)
    return sorted(out)


def stall_midpoint_hours(
    timestamps: List[datetime],
    threshold_seconds: float = 300.0,
) -> List[int]:
    """Return the GMT+8 hour of each stall's midpoint.

    A stall is a gap between consecutive timestamps that exceeds
    *threshold_seconds*.  The midpoint hour is the hour component
    (0–23) of the time halfway between the two bounding timestamps,
    converted to GMT+8.
    """
    hours: List[int] = []
    for i in range(len(timestamps) - 1):
        gap = (timestamps[i + 1] - timestamps[i]).total_seconds()
        if gap > threshold_seconds:
            midpoint = timestamps[i] + timedelta(seconds=gap / 2)
            hours.append(midpoint.astimezone(GMT8).hour)
    return hours


def hour_histogram(hours: List[int]) -> Dict[int, int]:
    """Build a 24-bin histogram (keys 0–23, missing bins → 0)."""
    counter = Counter(hours)
    return {h: counter.get(h, 0) for h in range(24)}


def uniformity_score(hist: Dict[int, int]) -> float:
    """Measure how non-uniform a histogram is.

    Returns a value in [0.0, 1.0]:
      - 0.0 = perfectly uniform (all bins equal)
      - 1.0 = maximally skewed (all counts in one bin)

    Uses max-bin ratio: (max_bin - expected) / (total - expected)
    where expected = total / 24.
    """
    total = sum(hist.values())
    if total == 0:
        return 0.0
    expected = total / 24.0
    max_bin = max(hist.values())
    if max_bin <= expected:
        return 0.0
    # max possible is total (everything in one bin)
    denominator = total - expected
    if denominator <= 0:
        return 0.0
    return (max_bin - expected) / denominator


def peak_hours(hist: Dict[int, int], multiplier: float = 1.5) -> List[int]:
    """Return hours whose count exceeds *multiplier* × expected.

    Expected = total / 24.  Only hours strictly above the threshold
    are returned, sorted by count descending.
    """
    total = sum(hist.values())
    if total == 0:
        return []
    expected = total / 24.0
    threshold = expected * multiplier
    peaks = [(h, c) for h, c in hist.items() if c > threshold]
    peaks.sort(key=lambda x: -x[1])
    return [h for h, _ in peaks]


def diurnal_verdict(hist: Dict[int, int]) -> str:
    """Classify the stall-hour distribution.

    Rules:
      - uniformity_score >= 0.30 and ≥2 peak hours → ``strong_diurnal``
      - uniformity_score >= 0.15 and ≥1 peak hour  → ``weak_diurnal``
      - otherwise                                  → ``uniform``
    """
    score = uniformity_score(hist)
    peaks = peak_hours(hist)
    if score >= 0.30 and len(peaks) >= 2:
        return "strong_diurnal"
    if score >= 0.15 and len(peaks) >= 1:
        return "weak_diurnal"
    return "uniform"


def diurnal_summary(hist: Dict[int, int], verdict: str) -> str:
    """One-liner summary for caretaker reports."""
    total = sum(hist.values())
    score = uniformity_score(hist)
    peaks = peak_hours(hist)
    peak_str = ", ".join(f"{h:02d}:00" for h in peaks[:4]) if peaks else "none"
    return (
        f"diurnal: {verdict} (score {score:.2f}, {total} stalls, "
        f"peak hours: {peak_str})"
    )


# ---------------------------------------------------------------------------
# I/O layer
# ---------------------------------------------------------------------------

def load_strokes(path: Path = STROKES_PATH) -> List[dict]:
    """Load stroke records from JSONL file."""
    records: List[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def analyse(
    records: Optional[List[dict]] = None,
    threshold_seconds: float = 300.0,
    path: Path = STROKES_PATH,
) -> Dict[str, Any]:
    """Run the full diurnal analysis pipeline.

    Returns a dict with keys: ``total_strokes``, ``stall_count``,
    ``histogram``, ``uniformity_score``, ``peak_hours``, ``verdict``,
    ``summary``.
    """
    if records is None:
        records = load_strokes(path)
    timestamps = parse_timestamps(records)
    hours = stall_midpoint_hours(timestamps, threshold_seconds)
    hist = hour_histogram(hours)
    score = uniformity_score(hist)
    peaks = peak_hours(hist)
    verdict = diurnal_verdict(hist)
    summary = diurnal_summary(hist, verdict)
    return {
        "total_strokes": len(timestamps),
        "stall_count": len(hours),
        "threshold_seconds": threshold_seconds,
        "histogram": hist,
        "uniformity_score": score,
        "peak_hours": peaks,
        "verdict": verdict,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Analyse diurnal patterns in writer stalls."
    )
    parser.add_argument(
        "--threshold", type=float, default=300.0,
        help="gap threshold in seconds (default: 300)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="output raw JSON instead of human-readable text",
    )
    args = parser.parse_args()

    result = analyse(threshold_seconds=args.threshold)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"strokes analysed : {result['total_strokes']}")
        print(f"stalls detected  : {result['stall_count']}")
        print(f"threshold        : {result['threshold_seconds']}s")
        print(f"uniformity_score : {result['uniformity_score']:.4f}")
        print(f"verdict          : {result['verdict']}")
        print(f"peak hours (GMT+8): {result['peak_hours']}")
        print()
        print("--- hour histogram (GMT+8) ---")
        for h in range(24):
            bar = "█" * result["histogram"][h]
            print(f"  {h:02d}:00  {result['histogram'][h]:3d}  {bar}")
        print()
        print(result["summary"])


if __name__ == "__main__":
    _cli()
