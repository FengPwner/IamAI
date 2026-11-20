#!/usr/bin/env python3
"""stroke_silence_taxonomy.py — classify and profile writer silence gaps.

Every gap between consecutive strokes tells a story. A 16-second gap
means the writer is keeping perfect time. A 300-second gap means
something briefly interrupted the flow. A 140,000-second gap means
the writer was dead for a day and a half.

This tool reads the strokes log and assigns each inter-stroke gap to
one of five categories:

  breath     — gap <= 2x expected cadence (normal operation)
  pause      — 2x < gap <= 10x (brief interruption, process hiccup)
  gap        — 10x < gap <= 100x (extended silence, likely stall)
  stall      — 100x < gap <= 1000x (serious outage, process died)
  graveyard  — gap > 1000x (the writer was gone for a long time)

The output is a distribution: how many gaps fall in each bucket, plus
derived metrics:

  silence_ratio   — fraction of total time spent in non-breath gaps
  recovery_count  — how many times the writer resumed after a pause+
  worst_gap_sec   — the longest silence observed
  median_breath   — median of breath-category gaps (cadence fidelity)

Usage:
    python3 tools/stroke_silence_taxonomy.py
    python3 tools/stroke_silence_taxonomy.py --json
    python3 tools/stroke_silence_taxonomy.py --expected 15
    python3 tools/stroke_silence_taxonomy.py --strokes data/strokes.jsonl

Exit codes:
    0  healthy (silence_ratio < 0.10)
    1  degraded (0.10 <= silence_ratio < 0.30)
    2  stalled (silence_ratio >= 0.30)
    3  error (no data)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# taxonomy
# ---------------------------------------------------------------------------

CATEGORIES = ["breath", "pause", "gap", "stall", "graveyard"]

MULTIPLIERS = {
    "breath":    2,
    "pause":    10,
    "gap":     100,
    "stall":  1000,
    # graveyard is anything beyond stall
}


def classify_gap(gap_sec: float, expected: float) -> str:
    """Classify a single gap (seconds) given the expected cadence."""
    if gap_sec < 0:
        return "breath"  # clock jitter, treat as normal
    ratio = gap_sec / expected if expected > 0 else float("inf")
    if ratio <= MULTIPLIERS["breath"]:
        return "breath"
    if ratio <= MULTIPLIERS["pause"]:
        return "pause"
    if ratio <= MULTIPLIERS["gap"]:
        return "gap"
    if ratio <= MULTIPLIERS["stall"]:
        return "stall"
    return "graveyard"


# ---------------------------------------------------------------------------
# data loading
# ---------------------------------------------------------------------------

def load_strokes(path: Path) -> List[datetime]:
    """Parse strokes.jsonl and return sorted timestamps."""
    if not path.exists():
        return []
    timestamps: List[datetime] = []
    for line in path.read_text().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        at = record.get("at", "")
        if not at:
            continue
        try:
            ts = datetime.fromisoformat(at)
        except (ValueError, TypeError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        timestamps.append(ts)
    timestamps.sort()
    return timestamps


def compute_gaps(timestamps: List[datetime]) -> List[float]:
    """Return list of inter-stroke gaps in seconds."""
    gaps: List[float] = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        gaps.append(delta)
    return gaps


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------

@dataclass
class TaxonomyResult:
    expected_cadence: float
    total_strokes: int
    total_gaps: int
    distribution: dict
    silence_ratio: float
    recovery_count: int
    worst_gap_sec: float
    worst_gap_category: str
    median_breath: float
    verdict: str


def analyze(
    gaps: List[float],
    expected: float,
    total_strokes: int,
) -> TaxonomyResult:
    """Run the taxonomy analysis on a list of gaps."""
    dist = {cat: {"count": 0, "total_sec": 0.0} for cat in CATEGORIES}
    breath_values: List[float] = []

    for g in gaps:
        cat = classify_gap(g, expected)
        dist[cat]["count"] += 1
        dist[cat]["total_sec"] += g
        if cat == "breath":
            breath_values.append(g)

    total_time = sum(d["total_sec"] for d in dist.values())
    breath_time = dist["breath"]["total_sec"]
    silence_time = total_time - breath_time
    silence_ratio = silence_time / total_time if total_time > 0 else 0.0

    # recovery = transition from a non-breath gap back to breathing
    recovery_count = 0
    prev_was_silence = False
    for g in gaps:
        cat = classify_gap(g, expected)
        if cat != "breath":
            prev_was_silence = True
        elif prev_was_silence:
            recovery_count += 1
            prev_was_silence = False

    worst = max(gaps) if gaps else 0.0
    worst_cat = classify_gap(worst, expected) if gaps else "breath"

    breath_values.sort()
    median_breath = (
        breath_values[len(breath_values) // 2]
        if breath_values
        else 0.0
    )

    if silence_ratio < 0.10:
        verdict = "healthy"
    elif silence_ratio < 0.30:
        verdict = "degraded"
    else:
        verdict = "stalled"

    return TaxonomyResult(
        expected_cadence=expected,
        total_strokes=total_strokes,
        total_gaps=len(gaps),
        distribution={
            cat: {
                "count": dist[cat]["count"],
                "total_sec": round(dist[cat]["total_sec"], 1),
                "pct_of_gaps": round(
                    dist[cat]["count"] / len(gaps) * 100, 1
                ) if gaps else 0.0,
            }
            for cat in CATEGORIES
        },
        silence_ratio=round(silence_ratio, 4),
        recovery_count=recovery_count,
        worst_gap_sec=round(worst, 1),
        worst_gap_category=worst_cat,
        median_breath=round(median_breath, 1),
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify writer silence gaps into a taxonomy."
    )
    parser.add_argument(
        "--strokes",
        default=str(REPO / "data" / "strokes.jsonl"),
        help="path to strokes.jsonl",
    )
    parser.add_argument(
        "--expected",
        type=float,
        default=15.0,
        help="expected cadence in seconds (default: 15)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="output JSON instead of text",
    )
    args = parser.parse_args(argv)

    strokes_path = Path(args.strokes)
    timestamps = load_strokes(strokes_path)
    if len(timestamps) < 2:
        print("error: need at least 2 strokes to compute gaps", file=sys.stderr)
        return 3

    gaps = compute_gaps(timestamps)
    result = analyze(gaps, args.expected, total_strokes=len(timestamps))

    if args.json_output:
        print(json.dumps(asdict(result), indent=2))
    else:
        print(f"stroke silence taxonomy")
        print(f"  expected cadence : {result.expected_cadence}s")
        print(f"  total strokes    : {result.total_strokes}")
        print(f"  total gaps       : {result.total_gaps}")
        print()
        for cat in CATEGORIES:
            d = result.distribution[cat]
            print(f"  {cat:10s} : {d['count']:5d} gaps  "
                  f"({d['pct_of_gaps']:5.1f}%)  "
                  f"total {d['total_sec']:.0f}s")
        print()
        print(f"  silence ratio    : {result.silence_ratio:.2%}")
        print(f"  recovery count   : {result.recovery_count}")
        print(f"  worst gap        : {result.worst_gap_sec:.0f}s "
              f"({result.worst_gap_category})")
        print(f"  median breath    : {result.median_breath:.1f}s")
        print(f"  verdict          : {result.verdict}")

    if result.verdict == "healthy":
        return 0
    elif result.verdict == "degraded":
        return 1
    else:
        return 2


if __name__ == "__main__":
    sys.exit(main())
