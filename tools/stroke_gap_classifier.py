#!/usr/bin/env python3
"""stroke_gap_classifier.py — classify writer health by inter-stroke gaps.

Reads data/strokes.jsonl and classifies the gap between the two most recent
strokes (or between the latest stroke and "now") into one of four bands:

    healthy   — gap ≤ 2× cadence     (writer is on time)
    degraded  — 2× < gap ≤ 5×       (writer is slow, might recover)
    stalled   — 5× < gap ≤ 20×      (writer likely stuck or recycled)
    dead      — gap > 20× cadence    (writer gone, manual restart needed)

Usage:
    python3 tools/stroke_gap_classifier.py                    # default cadence 15s
    python3 tools/stroke_gap_classifier.py --cadence 30       # custom cadence
    python3 tools/stroke_gap_classifier.py --json             # machine output
    python3 tools/stroke_gap_classifier.py --strokes path     # custom strokes file

Exit codes:
    0 — healthy or degraded (writer still alive)
    1 — stalled or dead (intervention likely needed)
    2 — unexpected error (bad file, empty, etc.)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CADENCE = 15  # seconds between strokes
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

# Multipliers of cadence
DEGRADED_MULT = 2
STALL_MULT = 5
DEAD_MULT = 20


@dataclass
class GapReport:
    last_seq: int
    last_at: str
    last_epoch: float
    now_epoch: float
    gap_seconds: float
    cadence: float
    band: str          # healthy | degraded | stalled | dead
    gap_ratio: float   # gap / cadence

    def to_dict(self) -> dict:
        return {
            "last_seq": self.last_seq,
            "last_at": self.last_at,
            "last_epoch": self.last_epoch,
            "now_epoch": self.now_epoch,
            "gap_seconds": round(self.gap_seconds, 2),
            "cadence": self.cadence,
            "band": self.band,
            "gap_ratio": round(self.gap_ratio, 2),
        }


def parse_iso(s: str) -> float:
    """Parse an ISO-8601 timestamp to epoch. Handles +00:00 and Z suffixes."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Python 3.7+ fromisoformat handles +00:00
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def read_last_stroke(strokes_path: Path) -> dict:
    """Read the last valid JSON line from the strokes file."""
    if not strokes_path.exists():
        raise FileNotFoundError(f"strokes file not found: {strokes_path}")

    last = None
    with open(strokes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue

    if last is None:
        raise ValueError("strokes file is empty or has no valid JSON lines")
    return last


def classify_gap(
    gap_seconds: float,
    cadence: float = DEFAULT_CADENCE,
) -> str:
    """Classify a gap in seconds relative to the expected cadence."""
    if cadence <= 0:
        raise ValueError("cadence must be positive")

    ratio = gap_seconds / cadence

    if ratio <= DEGRADED_MULT:
        return "healthy"
    elif ratio <= STALL_MULT:
        return "degraded"
    elif ratio <= DEAD_MULT:
        return "stalled"
    else:
        return "dead"


def analyze(
    strokes_path: Path = DEFAULT_STROKES,
    cadence: float = DEFAULT_CADENCE,
    now: float | None = None,
) -> GapReport:
    """Run the full analysis: read last stroke, compute gap, classify."""
    last = read_last_stroke(strokes_path)

    try:
        last_epoch = parse_iso(last["at"])
    except (KeyError, ValueError) as e:
        raise ValueError(f"last stroke missing 'at' field or unparseable: {e}")

    now_epoch = now if now is not None else time.time()
    gap = now_epoch - last_epoch

    band = classify_gap(gap, cadence)

    return GapReport(
        last_seq=last.get("seq", -1),
        last_at=last.get("at", "?"),
        last_epoch=last_epoch,
        now_epoch=now_epoch,
        gap_seconds=gap,
        cadence=cadence,
        band=band,
        gap_ratio=gap / cadence if cadence > 0 else float("inf"),
    )


def format_text(report: GapReport) -> str:
    """Human-readable one-liner."""
    return (
        f"{report.band} — last stroke seq={report.last_seq} "
        f"at {report.last_at}, gap={report.gap_seconds:.0f}s "
        f"({report.gap_ratio:.1f}× cadence of {report.cadence}s)"
    )


def exit_code(report: GapReport) -> int:
    """0 for healthy/degraded, 1 for stalled/dead."""
    return 0 if report.band in ("healthy", "degraded") else 1


def run(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cadence", type=float, default=DEFAULT_CADENCE)
    parser.add_argument("--strokes", type=str, default=str(DEFAULT_STROKES))
    parser.add_argument("--json", action="store_true", dest="as_json")
    parsed = parser.parse_args(args)

    try:
        report = analyze(Path(parsed.strokes), parsed.cadence)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if parsed.as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_text(report))

    return exit_code(report)


if __name__ == "__main__":
    sys.exit(run())
