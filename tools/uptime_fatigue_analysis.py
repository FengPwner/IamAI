#!/usr/bin/env python3
"""Analyse whether writer stalls correlate with cumulative uptime (fatigue).

Caretaker visit 258 ruled out the batch-interval hypothesis and proposed
two remaining explanations for the overnight stall pattern:

  1. **Fatigue** — stalls become more likely as the writer accumulates
     uptime since its last restart.  Memory leaks, file-descriptor
     exhaustion, or growing in-memory state could cause this.
  2. **Stroke-type** — certain stroke kinds (e.g. ones that hit the
     network or spawn subprocesses) trigger stalls regardless of uptime.

This module addresses hypothesis 1.  It reads ``data/strokes.jsonl``,
detects stalls (gap > threshold), then splits the timeline into
*sessions* separated by stalls.  For each session it records:

  - ``uptime_seconds``: wall-clock duration of the session
  - ``stroke_count``: number of strokes emitted before the stall
  - ``stall_at``: timestamp of the first stroke after recovery

If fatigue is the dominant cause, sessions with longer uptime should
outnumber short sessions among stall events.  The module reports:

  - ``fatigue_score``: Spearman-like rank correlation between uptime and
    stall occurrence (simplified as the fraction of stalls that happen
    in the upper-half of uptime values).
  - ``verdict``:
      fatigue      — fatigue_score >= 0.65
      mixed        — fatigue_score >= 0.50
      independent  — fatigue_score <  0.50

Usage:
    python3 tools/uptime_fatigue_analysis.py
    python3 tools/uptime_fatigue_analysis.py --threshold 300
    python3 tools/uptime_fatigue_analysis.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"


# ---------------------------------------------------------------------------
# pure helpers (no I/O — easy to test)
# ---------------------------------------------------------------------------

def detect_stalls(
    timestamps: List[datetime],
    threshold_seconds: float = 300.0,
) -> List[Dict[str, Any]]:
    """Find stalls in a sorted list of stroke timestamps.

    Returns a list of dicts with keys: index, stall_start, stall_end,
    gap_seconds.
    """
    stalls: List[Dict[str, Any]] = []
    for i in range(1, len(timestamps)):
        gap = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if gap > threshold_seconds:
            stalls.append({
                "index": i,
                "stall_start": timestamps[i - 1],
                "stall_end": timestamps[i],
                "gap_seconds": gap,
            })
    return stalls


def build_sessions(
    timestamps: List[datetime],
    stalls: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Split the timeline into sessions separated by stalls.

    Each session records:
      - session_start: first timestamp in the session
      - session_end:   last timestamp before the stall
      - uptime_seconds: wall-clock duration
      - stroke_count:  number of strokes in the session
      - stall_gap:    the gap that ended the session (seconds)
    """
    if not timestamps:
        return []

    sessions: List[Dict[str, Any]] = []
    boundaries = [0] + [s["index"] for s in stalls] + [len(timestamps)]

    for k in range(len(boundaries) - 1):
        lo, hi = boundaries[k], boundaries[k + 1]
        if lo >= hi:
            continue
        start = timestamps[lo]
        end = timestamps[hi - 1]
        uptime = (end - start).total_seconds()
        stall_gap = 0.0
        if k < len(stalls):
            stall_gap = stalls[k]["gap_seconds"]
        sessions.append({
            "session_start": start,
            "session_end": end,
            "uptime_seconds": uptime,
            "stroke_count": hi - lo,
            "stall_gap": stall_gap,
        })

    return sessions


def compute_fatigue_score(
    sessions: List[Dict[str, Any]],
) -> float:
    """Fraction of stalls occurring in the upper half of uptime values.

    A score near 1.0 means stalls almost always happen after long runs;
    near 0.5 means no relationship; near 0.0 means stalls happen early.
    """
    if len(sessions) <= 1:
        return 0.5

    uptimes = sorted(s["uptime_seconds"] for s in sessions)
    median_uptime = uptimes[len(uptimes) // 2]

    # sessions that ended in a stall (all except possibly the last)
    stalled = [s for s in sessions if s["stall_gap"] > 0]
    if not stalled:
        return 0.5

    above = sum(1 for s in stalled if s["uptime_seconds"] >= median_uptime)
    return above / len(stalled)


def classify_fatigue(score: float) -> str:
    """Map fatigue_score to a human-readable verdict.

    >>> classify_fatigue(0.80)
    'fatigue'
    >>> classify_fatigue(0.55)
    'mixed'
    >>> classify_fatigue(0.35)
    'independent'
    """
    if score >= 0.65:
        return "fatigue"
    if score >= 0.50:
        return "mixed"
    return "independent"


def summarize(
    sessions: List[Dict[str, Any]],
    fatigue_score: float,
    verdict: str,
) -> str:
    """Plain-text summary for the caretaker log."""
    stalled = [s for s in sessions if s["stall_gap"] > 0]
    lines = [
        f"sessions analyzed : {len(sessions)}",
        f"stalls recorded   : {len(stalled)}",
        f"fatigue_score     : {fatigue_score:.4f}",
        f"verdict           : {verdict}",
    ]
    if stalled:
        uptimes = [s["uptime_seconds"] for s in stalled]
        lines.append(f"median uptime     : {sorted(uptimes)[len(uptimes)//2]:.0f}s")
        lines.append(f"max uptime        : {max(uptimes):.0f}s")
        lines.append(f"min uptime        : {min(uptimes):.0f}s")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# I/O layer
# ---------------------------------------------------------------------------

def load_timestamps(path: Path = STROKES_PATH) -> List[datetime]:
    """Parse stroke timestamps from the JSONL file."""
    timestamps: List[datetime] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            at = record.get("at", "")
            try:
                timestamps.append(datetime.fromisoformat(at))
            except (ValueError, TypeError):
                continue
    return timestamps


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyse stall-vs-uptime fatigue correlation."
    )
    parser.add_argument(
        "--threshold", type=float, default=300.0,
        help="stall detection threshold in seconds (default 300)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="emit JSON instead of plain text",
    )
    args = parser.parse_args()

    timestamps = load_timestamps()
    stalls = detect_stalls(timestamps, threshold_seconds=args.threshold)
    sessions = build_sessions(timestamps, stalls)
    score = compute_fatigue_score(sessions)
    verdict = classify_fatigue(score)

    if args.json:
        payload = {
            "sessions_count": len(sessions),
            "stalls_count": len(stalls),
            "fatigue_score": round(score, 4),
            "verdict": verdict,
            "sessions": [
                {
                    "start": s["session_start"].isoformat(),
                    "end": s["session_end"].isoformat(),
                    "uptime_seconds": s["uptime_seconds"],
                    "stroke_count": s["stroke_count"],
                    "stall_gap": s["stall_gap"],
                }
                for s in sessions
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(summarize(sessions, score, verdict))


if __name__ == "__main__":
    main()
