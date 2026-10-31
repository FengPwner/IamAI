#!/usr/bin/env python3
"""writer_heartbeat.py — detect writer stalls via stroke cadence.

The writer loop appends one stroke every N seconds to data/strokes.jsonl.
If it stops (crash, reclaim, pause, API hang), the gap between the last
stroke and "now" grows past the expected cadence. This tool detects that.

Usage:
    python3 tools/writer_heartbeat.py                    # default: 15s cadence, 2x
    python3 tools/writer_heartbeat.py --cadence 30       # 30-second cadence
    python3 tools/writer_heartbeat.py --threshold 3      # alert at 3x cadence
    python3 tools/writer_heartbeat.py --json             # machine-readable output
    python3 tools/writer_heartbeat.py --strokes-file /path/to/strokes.jsonl
    python3 tools/writer_heartbeat.py --tail 20          # check last 20 strokes

Exit codes:
    0 — writer is healthy (within cadence)
    1 — writer is stalled (gap exceeds cadence * threshold)
    2 — no strokes found or parse error
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

# Health status constants
HEALTHY = "healthy"
WARNING = "warning"
STALL = "stall"
NO_DATA = "no_data"


@dataclass
class HeartbeatResult:
    """Result of a heartbeat check."""
    status: str           # healthy | warning | stall | no_data
    last_stroke_at: str   # ISO timestamp of last stroke
    gap_seconds: float    # seconds since last stroke
    cadence_seconds: int  # expected cadence
    threshold: float      # multiplier for stall detection
    stall_threshold: float  # cadence * threshold
    stroke_seq: int       # sequence number of last stroke
    stroke_kind: str      # kind of last stroke


def parse_last_stroke(strokes_file: Path, tail: int = 10) -> dict | None:
    """Read the last `tail` lines of strokes.jsonl and return the latest stroke.

    Reads from the end of the file for efficiency on large files.
    Returns None if the file is empty or unreadable.
    """
    if not strokes_file.exists():
        return None

    try:
        # Read last N lines
        with open(strokes_file, "r", encoding="utf-8") as f:
            # For efficiency, seek to end and read backwards
            lines = f.readlines()
            if not lines:
                return None
            tail_lines = lines[-tail:]
    except OSError:
        return None

    # Parse from the tail, returning the last valid stroke
    for line in reversed(tail_lines):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue

    return None


def parse_timestamp(ts: str) -> datetime:
    """Parse an ISO timestamp string to a timezone-aware datetime."""
    # Handle various ISO formats
    ts = ts.strip()
    # Python 3.7+ fromisoformat doesn't handle 'Z' suffix
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def check_heartbeat(
    strokes_file: Path = DEFAULT_STROKES,
    cadence: int = 15,
    threshold: float = 2.0,
    tail: int = 10,
    now: datetime | None = None,
) -> HeartbeatResult:
    """Check writer health based on stroke cadence.

    Args:
        strokes_file: path to strokes.jsonl
        cadence: expected seconds between strokes
        threshold: multiplier — gap > cadence * threshold = stall
        tail: number of lines to read from end of file
        now: override current time (for testing)

    Returns:
        HeartbeatResult with status and details
    """
    if now is None:
        now = datetime.now(timezone.utc)

    stroke = parse_last_stroke(strokes_file, tail=tail)
    if stroke is None:
        return HeartbeatResult(
            status=NO_DATA,
            last_stroke_at="",
            gap_seconds=-1,
            cadence_seconds=cadence,
            threshold=threshold,
            stall_threshold=cadence * threshold,
            stroke_seq=-1,
            stroke_kind="",
        )

    last_at = parse_timestamp(stroke["at"])
    # Ensure both datetimes are timezone-aware
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    gap = (now - last_at).total_seconds()
    stall_threshold = cadence * threshold

    if gap <= cadence:
        status = HEALTHY
    elif gap <= stall_threshold:
        status = WARNING
    else:
        status = STALL

    return HeartbeatResult(
        status=status,
        last_stroke_at=stroke["at"],
        gap_seconds=round(gap, 1),
        cadence_seconds=cadence,
        threshold=threshold,
        stall_threshold=stall_threshold,
        stroke_seq=stroke.get("seq", -1),
        stroke_kind=stroke.get("kind", ""),
    )


def format_report(result: HeartbeatResult) -> str:
    """Format a HeartbeatResult as a human-readable string."""
    if result.status == NO_DATA:
        return "NO DATA: no strokes found in strokes file"

    status_icon = {
        HEALTHY: "OK",
        WARNING: "WARN",
        STALL: "STALL",
    }.get(result.status, "?")

    lines = [
        f"[{status_icon}] writer heartbeat",
        f"  last stroke: seq {result.stroke_seq} ({result.stroke_kind}) at {result.last_stroke_at}",
        f"  gap: {result.gap_seconds}s (cadence {result.cadence_seconds}s, stall at {result.stall_threshold}s)",
    ]

    if result.status == STALL:
        overdue = result.gap_seconds - result.stall_threshold
        lines.append(f"  OVERDUE by {overdue:.0f}s — writer may be stalled")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cadence", type=int, default=15,
                     help="expected seconds between strokes (default: 15)")
    ap.add_argument("--threshold", type=float, default=2.0,
                     help="stall multiplier (default: 2.0)")
    ap.add_argument("--tail", type=int, default=10,
                     help="lines to read from end of file (default: 10)")
    ap.add_argument("--json", action="store_true",
                     help="output JSON instead of text")
    ap.add_argument("--strokes-file", type=Path, default=DEFAULT_STROKES,
                     help="path to strokes.jsonl")
    args = ap.parse_args()

    result = check_heartbeat(
        strokes_file=args.strokes_file,
        cadence=args.cadence,
        threshold=args.threshold,
        tail=args.tail,
    )

    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        print(format_report(result))

    if result.status == NO_DATA:
        return 2
    elif result.status == STALL:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
