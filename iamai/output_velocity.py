"""output_velocity — measure whether stroke production is speeding up or slowing down.

The qwen writer runs on a ~3-minute cadence.  Over a rolling window of
recent strokes, the production rate should stay roughly constant.  If it
drops (e.g. the writer is stalling, the API is throttled, or the process
is dying) or spikes (e.g. a burst of catch-up commits flooding the log),
the caretaker needs to know.

This module splits a window of recent strokes into two halves by
timestamp, computes the stroke rate (strokes per minute) in each half,
and classifies the trend:

- **accelerating** — rate ratio > 1.3  (second half is 30 %+ faster)
- **steady**       — ratio in [0.77, 1.30]
- **decelerating** — ratio in [0.20, 0.77)
- **stalled**      — ratio < 0.20 or zero strokes in the second half

Additionally, it reports:

- ``strokes_per_minute`` — overall rate across the full window
- ``first_half_rate``    — strokes/min in the earlier half
- ``second_half_rate``   — strokes/min in the later half
- ``gap_seconds``        — seconds since the most recent stroke
- ``verdict``            — one of the four labels above

Usage::

    from iamai.output_velocity import velocity_report, velocity_summary

    report = velocity_report("data/strokes.jsonl", window=40)
    print(velocity_summary(report))
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class VelocityReport:
    """Summary of stroke production velocity over a window."""

    total_strokes: int = 0
    window_seconds: float = 0.0
    first_half_count: int = 0
    second_half_count: int = 0
    first_half_seconds: float = 0.0
    second_half_seconds: float = 0.0
    first_half_rate: float = 0.0   # strokes per minute
    second_half_rate: float = 0.0
    overall_rate: float = 0.0
    ratio: float = 0.0             # second / first
    gap_seconds: float = 0.0       # time since last stroke
    verdict: str = "unknown"
    timestamps: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, tolerating various formats."""
    if not ts_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(ts_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _load_timestamps(strokes_path: str | Path, window: int = 40) -> list[datetime]:
    """Return the last *window* parsed timestamps from the JSONL file."""
    path = Path(strokes_path)
    if not path.exists():
        return []
    dts: list[datetime] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("at")
            dt = _parse_ts(ts) if ts else None
            if dt is not None:
                dts.append(dt)
    return dts[-window:]


def _rate(count: int, seconds: float) -> float:
    """Strokes per minute given a count and a duration in seconds."""
    if seconds <= 0:
        return 0.0
    return count / (seconds / 60.0)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def verdict_for(ratio: float, second_half_count: int) -> str:
    """Classify the velocity ratio into a human-readable verdict."""
    if second_half_count == 0:
        return "stalled"
    if ratio < 0.20:
        return "stalled"
    if ratio < 0.77:
        return "decelerating"
    if ratio <= 1.30:
        return "steady"
    return "accelerating"


def compute_velocity(timestamps: list[datetime]) -> VelocityReport:
    """Compute velocity metrics from a sorted list of timestamps.

    The list is split into two halves by index.  Each half's rate is
    computed over its own time span (first-to-mid, mid-to-last).
    """
    n = len(timestamps)
    if n < 2:
        return VelocityReport(
            total_strokes=n,
            verdict="stalled" if n == 0 else "unknown",
        )

    timestamps = sorted(timestamps)
    mid = n // 2

    first_half = timestamps[:mid]
    second_half = timestamps[mid:]

    first_span = (first_half[-1] - first_half[0]).total_seconds()
    second_span = (second_half[-1] - second_half[0]).total_seconds()

    first_rate = _rate(len(first_half), first_span)
    second_rate = _rate(len(second_half), second_span)

    overall_span = (timestamps[-1] - timestamps[0]).total_seconds()
    overall_rate = _rate(n, overall_span)

    ratio = (second_rate / first_rate) if first_rate > 0 else (
        float("inf") if second_rate > 0 else 0.0
    )

    now = datetime.now(timezone.utc)
    gap = (now - timestamps[-1]).total_seconds()

    return VelocityReport(
        total_strokes=n,
        window_seconds=round(overall_span, 1),
        first_half_count=len(first_half),
        second_half_count=len(second_half),
        first_half_seconds=round(first_span, 1),
        second_half_seconds=round(second_span, 1),
        first_half_rate=round(first_rate, 4),
        second_half_rate=round(second_rate, 4),
        overall_rate=round(overall_rate, 4),
        ratio=round(ratio, 4) if ratio != float("inf") else 999.0,
        gap_seconds=round(gap, 1),
        verdict=verdict_for(ratio if ratio != float("inf") else 999.0, len(second_half)),
        timestamps=[t.isoformat() for t in timestamps],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def velocity_report(
    strokes_path: str | Path = "data/strokes.jsonl",
    window: int = 40,
) -> VelocityReport:
    """Compute output velocity from the last *window* strokes on disk."""
    timestamps = _load_timestamps(strokes_path, window)
    return compute_velocity(timestamps)


def velocity_from_timestamps(timestamps: list[datetime]) -> VelocityReport:
    """Compute velocity from a pre-loaded list of timestamps (no file I/O)."""
    return compute_velocity(timestamps)


def velocity_summary(report: VelocityReport) -> str:
    """One-line human-readable summary."""
    if report.total_strokes < 2:
        return f"output_velocity: insufficient data ({report.total_strokes} stroke(s))"
    lines = [
        f"output_velocity: {report.verdict} "
        f"(ratio={report.ratio:.2f}, overall={report.overall_rate:.2f} strokes/min, "
        f"n={report.total_strokes})",
        f"  first half:  {report.first_half_count} strokes in {report.first_half_seconds:.0f}s "
        f"→ {report.first_half_rate:.3f}/min",
        f"  second half: {report.second_half_count} strokes in {report.second_half_seconds:.0f}s "
        f"→ {report.second_half_rate:.3f}/min",
        f"  gap since last stroke: {report.gap_seconds:.0f}s",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Output velocity checker")
    ap.add_argument("--strokes", default="data/strokes.jsonl")
    ap.add_argument("--window", type=int, default=40)
    args = ap.parse_args()

    report = velocity_report(args.strokes, args.window)
    print(velocity_summary(report))


if __name__ == "__main__":
    main()
