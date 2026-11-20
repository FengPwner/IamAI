#!/usr/bin/env python3
"""resurrection_cost.py — measure the cumulative cost of process death.

Every time the writer dies and comes back, there is a gap: time during
which no strokes were written. This tool quantifies that cost.

It reads strokes.jsonl and identifies "death events" — inter-stroke
gaps that exceed a configurable threshold (default: 300 seconds, i.e.
20x the 15-second cadence). For each death event it estimates:

  lost_strokes  — how many strokes *would* have been written at 15s cadence
  gap_seconds   — actual wall-clock silence between last and next stroke
  recovery_type — classified as:
      quick     (< 600s,    routine restart)
      moderate  (600-3600s, took a while to notice)
      severe    (3600-86400s, hours of silence)
      graveyard (> 86400s,  the process was gone for days)

Summary statistics:
  total_deaths          — number of death events detected
  total_lost_strokes    — sum of all lost_strokes estimates
  total_silence_seconds — sum of all gap_seconds
  mean_recovery_seconds — average gap per death event
  worst_gap_seconds     — the single longest gap
  resurrection_cost     — total_silence_seconds / total_runtime (fraction)

Usage:
    python3 tools/resurrection_cost.py                          # default threshold 300s
    python3 tools/resurrection_cost.py --threshold 600          # stricter
    python3 tools/resurrection_cost.py --strokes data/strokes.jsonl
    python3 tools/resurrection_cost.py --json

Exit codes:
    0  success
    2  insufficient data (< 2 strokes)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


DEFAULT_THRESHOLD = 300  # seconds — 20x the 15s cadence
DEFAULT_CADENCE = 15     # seconds per stroke
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class DeathEvent:
    """One instance of the writer going silent and coming back."""
    index: int               # sequential event number (1-based)
    before_seq: int          # last stroke seq before the gap
    after_seq: int           # first stroke seq after the gap
    gap_seconds: float       # wall-clock seconds of silence
    lost_strokes: int        # estimated strokes missed at DEFAULT_CADENCE
    recovery_type: str       # quick / moderate / severe / graveyard
    before_ts: str           # ISO timestamp of last stroke before gap
    after_ts: str            # ISO timestamp of first stroke after gap


def classify_recovery(gap_seconds: float) -> str:
    """Classify a gap into a severity bucket."""
    if gap_seconds < 600:
        return "quick"
    elif gap_seconds < 3600:
        return "moderate"
    elif gap_seconds < 86400:
        return "severe"
    else:
        return "graveyard"


def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO 8601 timestamp string to datetime."""
    ts_str = ts_str.strip()
    # handle various ISO formats
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    # fallback: let fromisoformat try
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return datetime.fromisoformat(ts_str)


def load_strokes(path: Path) -> List[dict]:
    """Load strokes from a JSONL file, skipping blank/malformed lines."""
    strokes = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return strokes


def find_death_events(
    strokes: List[dict],
    threshold: float = DEFAULT_THRESHOLD,
    cadence: float = DEFAULT_CADENCE,
) -> List[DeathEvent]:
    """Identify inter-stroke gaps exceeding the threshold."""
    events: List[DeathEvent] = []
    event_idx = 0

    for i in range(1, len(strokes)):
        prev = strokes[i - 1]
        curr = strokes[i]
        try:
            t_prev = parse_timestamp(prev["at"])
            t_curr = parse_timestamp(curr["at"])
        except (KeyError, ValueError):
            continue

        gap = (t_curr - t_prev).total_seconds()
        if gap <= 0:
            continue

        if gap > threshold:
            event_idx += 1
            lost = max(1, int(gap / cadence))
            events.append(DeathEvent(
                index=event_idx,
                before_seq=prev.get("seq", 0),
                after_seq=curr.get("seq", 0),
                gap_seconds=round(gap, 1),
                lost_strokes=lost,
                recovery_type=classify_recovery(gap),
                before_ts=prev["at"],
                after_ts=curr["at"],
            ))

    return events


def compute_summary(
    events: List[DeathEvent],
    strokes: List[dict],
) -> dict:
    """Compute aggregate resurrection cost statistics."""
    if not events:
        total_runtime = 0.0
        if len(strokes) >= 2:
            try:
                t0 = parse_timestamp(strokes[0]["at"])
                t1 = parse_timestamp(strokes[-1]["at"])
                total_runtime = (t1 - t0).total_seconds()
            except (KeyError, ValueError):
                pass
        return {
            "total_deaths": 0,
            "total_lost_strokes": 0,
            "total_silence_seconds": 0.0,
            "mean_recovery_seconds": 0.0,
            "worst_gap_seconds": 0.0,
            "resurrection_cost": 0.0,
            "total_runtime_seconds": round(total_runtime, 1),
            "recovery_breakdown": {},
        }

    total_silence = sum(e.gap_seconds for e in events)
    worst = max(e.gap_seconds for e in events)

    # compute total runtime from first to last stroke
    total_runtime = 0.0
    if len(strokes) >= 2:
        try:
            t0 = parse_timestamp(strokes[0]["at"])
            t1 = parse_timestamp(strokes[-1]["at"])
            total_runtime = (t1 - t0).total_seconds()
        except (KeyError, ValueError):
            pass

    # breakdown by recovery type
    breakdown = {}
    for e in events:
        breakdown[e.recovery_type] = breakdown.get(e.recovery_type, 0) + 1

    cost_ratio = (total_silence / total_runtime) if total_runtime > 0 else 0.0

    return {
        "total_deaths": len(events),
        "total_lost_strokes": sum(e.lost_strokes for e in events),
        "total_silence_seconds": round(total_silence, 1),
        "mean_recovery_seconds": round(total_silence / len(events), 1),
        "worst_gap_seconds": round(worst, 1),
        "resurrection_cost": round(cost_ratio, 4),
        "total_runtime_seconds": round(total_runtime, 1),
        "recovery_breakdown": breakdown,
    }


def format_report(
    events: List[DeathEvent],
    summary: dict,
) -> str:
    """Format a human-readable report."""
    lines = []
    lines.append("=" * 60)
    lines.append("  RESURRECTION COST REPORT")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"  death events detected:  {summary['total_deaths']}")
    lines.append(f"  total lost strokes:     {summary['total_lost_strokes']}")
    lines.append(f"  total silence:          {summary['total_silence_seconds']:.0f}s "
                 f"({summary['total_silence_seconds'] / 3600:.1f}h)")
    lines.append(f"  mean recovery time:     {summary['mean_recovery_seconds']:.0f}s")
    lines.append(f"  worst gap:              {summary['worst_gap_seconds']:.0f}s "
                 f"({summary['worst_gap_seconds'] / 3600:.1f}h)")
    lines.append(f"  resurrection cost:      {summary['resurrection_cost']:.2%} "
                 f"of total runtime")
    lines.append(f"  total runtime:          {summary['total_runtime_seconds']:.0f}s "
                 f"({summary['total_runtime_seconds'] / 86400:.1f}d)")
    lines.append("")

    if summary["recovery_breakdown"]:
        lines.append("  recovery type breakdown:")
        for rtype, count in sorted(summary["recovery_breakdown"].items()):
            lines.append(f"    {rtype:12s}  {count}")
        lines.append("")

    if events:
        lines.append("-" * 60)
        lines.append("  TOP 5 WORST GAPS:")
        lines.append("-" * 60)
        sorted_events = sorted(events, key=lambda e: e.gap_seconds, reverse=True)
        for e in sorted_events[:5]:
            lines.append(
                f"  #{e.index:3d}  {e.gap_seconds:>10.0f}s  "
                f"({e.recovery_type:10s})  "
                f"seq {e.before_seq} -> {e.after_seq}"
            )
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Measure the cumulative cost of process death and resurrection."
    )
    parser.add_argument(
        "--strokes",
        type=Path,
        default=REPO_ROOT / "data" / "strokes.jsonl",
        help="Path to strokes JSONL file",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Gap threshold in seconds (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--cadence",
        type=float,
        default=DEFAULT_CADENCE,
        help=f"Expected stroke cadence in seconds (default: {DEFAULT_CADENCE})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output machine-readable JSON",
    )
    args = parser.parse_args()

    if not args.strokes.exists():
        print(f"error: strokes file not found: {args.strokes}", file=sys.stderr)
        sys.exit(2)

    strokes = load_strokes(args.strokes)
    if len(strokes) < 2:
        print("error: need at least 2 strokes to compute gaps", file=sys.stderr)
        sys.exit(2)

    events = find_death_events(strokes, args.threshold, args.cadence)
    summary = compute_summary(events, strokes)

    if args.json_output:
        output = {
            "summary": summary,
            "events": [asdict(e) for e in events],
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print(format_report(events, summary))


if __name__ == "__main__":
    main()
