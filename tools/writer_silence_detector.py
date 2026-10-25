#!/usr/bin/env python3
"""writer_silence_detector.py — detect when the writer has gone quiet.

Reads strokes.jsonl and compares the timestamp of the last stroke against
the expected cadence.  If the gap exceeds `cadence * multiplier`, the writer
is considered stalled.

Usage:
    python3 tools/writer_silence_detector.py
    python3 tools/writer_silence_detector.py --cadence 900 --multiplier 2
    python3 tools/writer_silence_detector.py --json

Exit codes:
    0 — writer is active (last stroke within threshold)
    1 — writer appears stalled
    2 — unexpected error
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO / "data" / "strokes.jsonl"
DEFAULT_CADENCE = 900       # 15 minutes in seconds
DEFAULT_MULTIPLIER = 2.0    # stall = cadence × multiplier


def last_stroke_time(path: Path = STROKES_FILE) -> float | None:
    """Return the unix timestamp of the most recent stroke, or None."""
    if not path.exists():
        return None
    last_line = ""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                last_line = stripped
    if not last_line:
        return None
    try:
        record = json.loads(last_line)
        at = record.get("at", "")
        # Parse ISO 8601
        dt = datetime.fromisoformat(at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (json.JSONDecodeError, ValueError, KeyError):
        return None


def silence_gap(now: float | None = None, path: Path = STROKES_FILE) -> float | None:
    """Seconds since the last stroke.  None if no strokes exist."""
    last = last_stroke_time(path)
    if last is None:
        return None
    now = now or time.time()
    return now - last


def is_stalled(
    gap: float | None,
    cadence: float = DEFAULT_CADENCE,
    multiplier: float = DEFAULT_MULTIPLIER,
) -> bool:
    """True when the gap exceeds cadence × multiplier."""
    if gap is None:
        return True  # no data = assume stalled
    return gap > cadence * multiplier


def status(
    now: float | None = None,
    path: Path = STROKES_FILE,
    cadence: float = DEFAULT_CADENCE,
    multiplier: float = DEFAULT_MULTIPLIER,
) -> dict:
    gap = silence_gap(now=now, path=path)
    stalled = is_stalled(gap, cadence, multiplier)
    return {
        "gap_seconds": round(gap, 1) if gap is not None else None,
        "cadence": cadence,
        "multiplier": multiplier,
        "threshold": cadence * multiplier,
        "stalled": stalled,
    }


def format_text(info: dict) -> str:
    if info["gap_seconds"] is None:
        return "no strokes found"
    if info["stalled"]:
        return (
            f"STALL: writer silent for {info['gap_seconds']:.0f}s "
            f"(threshold {info['threshold']:.0f}s)"
        )
    return (
        f"OK: writer active, last stroke {info['gap_seconds']:.0f}s ago "
        f"(threshold {info['threshold']:.0f}s)"
    )


def exit_code(info: dict) -> int:
    return 1 if info["stalled"] else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Detect writer silence")
    p.add_argument("--cadence", type=float, default=DEFAULT_CADENCE,
                   help="Expected cadence in seconds (default 900)")
    p.add_argument("--multiplier", type=float, default=DEFAULT_MULTIPLIER,
                   help="Stall multiplier (default 2.0)")
    p.add_argument("--json", action="store_true", help="JSON output")
    args = p.parse_args(argv)

    info = status(cadence=args.cadence, multiplier=args.multiplier)
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(format_text(info))
    return exit_code(info)


if __name__ == "__main__":
    sys.exit(main())
