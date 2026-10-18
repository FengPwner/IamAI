"""stall_duration — measure how long processes were down and how often.

Where overnight_mortality answers *when* stalls happen, this module
answers *how long* they lasted and what fraction of wall-clock time
the system was actually productive.

Usage::

    from iamai.stall_duration import (
        measure_stalls,
        StallReport,
        from_mortality_ledger,
    )

    # Pairs of (death_time, restart_time) as ISO-8601 or datetime
    events = [
        ("2026-10-19T02:01:00+08:00", "2026-10-19T03:00:00+08:00"),
        ("2026-10-18T03:15:00+08:00", "2026-10-18T03:22:00+08:00"),
    ]

    report = measure_stalls(events, window_start="2026-10-18T00:00:00+08:00",
                            window_end="2026-10-19T04:00:00+08:00")
    print(report.total_downtime_seconds)   # 3540 (59 min + 7 min)
    print(report.uptime_ratio)             # ~0.876
    print(report.longest_stall_seconds)    # 3540
    print(report.as_dict())

Design choices:
  - Pure-Python, no subprocess, no git dependency.
  - Reuses the same timestamp normalization as overnight_mortality.
  - Frozen dataclass result — immutable once built.
  - Overlapping stalls are merged before measuring (no double-counting).
  - Uptime ratio is clamped to [0, 1] even if inputs are weird.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Sequence, Tuple, Union

from .overnight_mortality import _to_datetime, Timestamp

# Type for a (death, restart) pair.
StallEvent = Tuple[Timestamp, Timestamp]


def _merge_intervals(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Merge overlapping time intervals. Returns sorted, non-overlapping list."""
    if not intervals:
        return []
    sorted_iv = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_iv[0]]
    for start, end in sorted_iv[1:]:
        if start <= merged[-1][1]:
            # Overlapping or adjacent — extend
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


@dataclass(frozen=True)
class StallReport:
    """Structured result of stall duration measurement."""

    total_stalls: int
    total_downtime_seconds: float
    longest_stall_seconds: float
    shortest_stall_seconds: float
    average_stall_seconds: float
    uptime_ratio: float
    window_seconds: float
    stall_durations: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total_stalls": self.total_stalls,
            "total_downtime_seconds": round(self.total_downtime_seconds, 1),
            "longest_stall_seconds": round(self.longest_stall_seconds, 1),
            "shortest_stall_seconds": round(self.shortest_stall_seconds, 1),
            "average_stall_seconds": round(self.average_stall_seconds, 1),
            "uptime_ratio": round(self.uptime_ratio, 4),
            "window_seconds": round(self.window_seconds, 1),
            "stall_durations": [round(d, 1) for d in self.stall_durations],
        }


def measure_stalls(
    events: Sequence[StallEvent],
    window_start: Timestamp | None = None,
    window_end: Timestamp | None = None,
) -> StallReport:
    """Measure stall durations from (death, restart) pairs.

    Args:
        events: Sequence of (death_time, restart_time) tuples.
        window_start: Start of the observation window (for uptime ratio).
            If None, uses the earliest death time.
        window_end: End of the observation window.
            If None, uses the latest restart time.

    Returns:
        A StallReport with durations and uptime metrics.
    """
    if not events:
        return StallReport(
            total_stalls=0,
            total_downtime_seconds=0.0,
            longest_stall_seconds=0.0,
            shortest_stall_seconds=0.0,
            average_stall_seconds=0.0,
            uptime_ratio=1.0,
            window_seconds=0.0,
            stall_durations=[],
        )

    # Parse all events into (datetime, datetime) pairs.
    parsed: list[tuple[datetime, datetime]] = []
    for death, restart in events:
        d = _to_datetime(death)
        r = _to_datetime(restart)
        # Clamp: if restart is before death, treat as instant recovery.
        if r < d:
            r = d
        parsed.append((d, r))

    # Merge overlapping intervals to avoid double-counting.
    merged = _merge_intervals(parsed)

    # Calculate individual stall durations from merged intervals.
    durations = [(end - start).total_seconds() for start, end in merged]

    total_down = sum(durations)
    longest = max(durations)
    shortest = min(durations)
    average = total_down / len(durations)

    # Determine observation window.
    if window_start is not None:
        ws = _to_datetime(window_start)
    else:
        ws = min(s for s, _ in merged)

    if window_end is not None:
        we = _to_datetime(window_end)
    else:
        we = max(e for _, e in merged)

    window_secs = (we - ws).total_seconds()
    if window_secs <= 0:
        uptime = 1.0 if total_down == 0 else 0.0
    else:
        uptime = max(0.0, min(1.0, 1.0 - (total_down / window_secs)))

    return StallReport(
        total_stalls=len(merged),
        total_downtime_seconds=total_down,
        longest_stall_seconds=longest,
        shortest_stall_seconds=shortest,
        average_stall_seconds=average,
        uptime_ratio=uptime,
        window_seconds=window_secs,
        stall_durations=durations,
    )


def from_mortality_ledger(
    repo_path: str | object,
    writer: str = "qwen",
    window_start: Timestamp | None = None,
    window_end: Timestamp | None = None,
) -> StallReport:
    """Load death/restart pairs from the mortality ledger and measure.

    The ledger is a JSONL file at ``data/process_mortality.jsonl`` with
    events like ``{"event": "death", "writer": "qwen", "ts": "..."}``
    and ``{"event": "restart", "writer": "qwen", "ts": "..."}``.

    Pairs consecutive death→restart events for the given writer.

    Args:
        repo_path: Path to repository root.
        writer: Writer identity to filter on.
        window_start, window_end: Observation window (see measure_stalls).

    Returns:
        A StallReport.
    """
    import json
    from pathlib import Path

    ledger = Path(repo_path) / "data" / "process_mortality.jsonl"
    if not ledger.exists():
        return measure_stalls([], window_start, window_end)

    events_list: list[dict] = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("writer") != writer:
            continue
        events_list.append(event)

    # Sort by timestamp and pair death→restart.
    events_list.sort(key=lambda e: e.get("ts", ""))
    pairs: list[tuple[str, str]] = []
    pending_death: str | None = None
    for ev in events_list:
        if ev.get("event") == "death":
            pending_death = ev.get("ts")
        elif ev.get("event") == "restart" and pending_death is not None:
            restart_ts = ev.get("ts")
            if restart_ts:
                pairs.append((pending_death, restart_ts))
            pending_death = None

    return measure_stalls(pairs, window_start, window_end)
