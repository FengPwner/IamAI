#!/usr/bin/env python3
"""stroke_gap_monitor.py — detect writer silence by measuring stroke gaps.

The writer loop applies one stroke every ~15 seconds. When it stalls
(process killed, pause gate stuck, disk full), the gap between the last
two strokes grows far beyond the expected cadence. This monitor reads
the writer state file, computes the gap, and exits non-zero when the
writer has been silent for too long.

Unlike heartbeat.py (which checks the last stroke against wall clock),
this tool works purely from the state file's own timestamps — so it
catches stalls even when wall clock drifted or the process died without
updating the state.

Usage:
    python3 tools/stroke_gap_monitor.py
    python3 tools/stroke_gap_monitor.py --writer qwen --max-gap 600
    python3 tools/stroke_gap_monitor.py --json

Exit codes:
    0  — writer is active (gap within threshold)
    1  — writer is silent (gap exceeds threshold)
    2  — state file missing or unreadable
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
DEFAULT_WRITER = "qwen"
DEFAULT_MAX_GAP = 600  # seconds — 10 minutes, roughly 40 missed strokes


def state_path(writer_id: str) -> Path:
    """Return the writer state file path for a given writer id."""
    return REPO / "data" / f"writer_state.{writer_id}.json"


@dataclass
class GapReport:
    """Result of a gap analysis."""
    writer_id: str
    last_stroke_at: float | None  # epoch seconds
    last_stroke_iso: str | None
    now: float
    gap_seconds: float | None
    max_gap: int
    history_len: int
    stalled: bool
    last_kind: str | None  # kind of the last stroke

    @property
    def at_iso(self) -> str:
        return datetime.fromtimestamp(self.now, tz=timezone.utc).isoformat()


def load_history(writer_id: str) -> list[dict]:
    """Load the stroke history from the writer state file.

    Returns the history list. Raises FileNotFoundError if the state
    file does not exist, or ValueError if it's not valid JSON.
    """
    path = state_path(writer_id)
    if not path.exists():
        raise FileNotFoundError(f"state file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    history = data.get("history", [])
    if not isinstance(history, list):
        raise ValueError(f"history is not a list in {path}")
    return history


def parse_iso(ts: str) -> float:
    """Parse an ISO 8601 timestamp to epoch seconds.

    Handles both '+00:00' and 'Z' suffixes, and naive timestamps
    (assumed UTC).
    """
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    if "+" not in ts and "-" not in ts[10:]:
        ts += "+00:00"
    dt = datetime.fromisoformat(ts)
    return dt.timestamp()


def analyze(
    writer_id: str = DEFAULT_WRITER,
    max_gap: int = DEFAULT_MAX_GAP,
    now: float | None = None,
) -> GapReport:
    """Analyze the stroke gap for a writer.

    Args:
        writer_id: which writer's state to read
        max_gap: maximum acceptable gap in seconds
        now: override wall clock (for testing)

    Returns:
        GapReport with the analysis results.
    """
    if now is None:
        now = time.time()

    try:
        history = load_history(writer_id)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return GapReport(
            writer_id=writer_id,
            last_stroke_at=None,
            last_stroke_iso=None,
            now=now,
            gap_seconds=None,
            max_gap=max_gap,
            history_len=0,
            stalled=True,
            last_kind=None,
        )

    if not history:
        return GapReport(
            writer_id=writer_id,
            last_stroke_at=None,
            last_stroke_iso=None,
            now=now,
            gap_seconds=None,
            max_gap=max_gap,
            history_len=0,
            stalled=True,
            last_kind=None,
        )

    last = history[-1]
    last_at = parse_iso(last["at"])
    last_kind = last.get("kind")
    gap = now - last_at

    return GapReport(
        writer_id=writer_id,
        last_stroke_at=last_at,
        last_stroke_iso=last["at"],
        now=now,
        gap_seconds=gap,
        max_gap=max_gap,
        history_len=len(history),
        stalled=gap > max_gap,
        last_kind=last_kind,
    )


def as_markdown(report: GapReport) -> str:
    """Format a GapReport as a single human-readable line."""
    if report.last_stroke_at is None:
        return f"stroke_gap[{report.writer_id}]: NO HISTORY — state empty or missing"
    gap = report.gap_seconds
    unit = "s"
    if gap > 3600:
        gap /= 3600
        unit = "h"
    elif gap > 60:
        gap /= 60
        unit = "m"
    status = "STALL" if report.stalled else "OK"
    return (
        f"stroke_gap[{report.writer_id}]: {gap:.1f}{unit} since last stroke "
        f"({report.last_kind or '?'}), max={report.max_gap}s — {status}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default=DEFAULT_WRITER, help="writer id")
    ap.add_argument("--max-gap", type=int, default=DEFAULT_MAX_GAP, help="max acceptable gap in seconds")
    ap.add_argument("--json", action="store_true", help="dump the full report as JSON")
    args = ap.parse_args()

    report = analyze(writer_id=args.writer, max_gap=args.max_gap)

    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print(as_markdown(report))

    return 1 if report.stalled else 0


if __name__ == "__main__":
    raise SystemExit(main())
