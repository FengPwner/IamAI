"""overnight_mortality — classify stalls by time-of-day pattern.

The IamAI sandbox reclaims idle processes, and reclamation happens
more often at night when nothing external keeps the sandbox warm.
This module quantifies that pattern so caretakers can distinguish
"sandbox ate the process again" from "the code is actually broken."

Usage::

    from iamai.overnight_mortality import classify_stalls, OvernightReport

    # Timestamps when stalls were detected (ISO-8601 strings or datetimes)
    stalls = ["2026-10-19T02:01:00+08:00", "2026-10-18T03:15:00+08:00", ...]

    report = classify_stalls(stalls, night_start=0, night_end=6)
    print(report.overnight_ratio)       # e.g. 0.82
    print(report.is_overnight_pattern)  # True if ratio >= threshold
    print(report.as_dict())

Design choices:
  - Pure-Python, no subprocess, no git dependency.
  - Accepts ISO-8601 strings, datetime objects, or epoch floats.
  - Night window is configurable (default 00:00–06:00 local time).
  - Threshold for overnight pattern: 70% by default.
  - Returns a frozen dataclass so callers can't accidentally mutate it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Sequence, Union

# Type alias for flexible timestamp input.
Timestamp = Union[str, datetime, float, int]

# Default thresholds.
DEFAULT_NIGHT_START = 0   # midnight (hour, 0–23)
DEFAULT_NIGHT_END = 6     # 6 AM
DEFAULT_THRESHOLD = 0.70  # 70% of stalls in night window


def _to_datetime(ts: Timestamp) -> datetime:
    """Normalize a timestamp to a timezone-aware datetime."""
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str):
        # Handle ISO-8601 with or without timezone
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            # Fallback: try common formats
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(ts, fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Cannot parse timestamp: {ts!r}")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    raise TypeError(f"Unsupported timestamp type: {type(ts)}")


def _is_night_hour(dt: datetime, night_start: int, night_end: int) -> bool:
    """Check if a datetime falls within the night window (local hour)."""
    h = dt.hour
    if night_start < night_end:
        # Simple range: e.g. 0–6 means hours 0,1,2,3,4,5
        return night_start <= h < night_end
    else:
        # Wrapping range: e.g. 22–6 means 22,23,0,1,2,3,4,5
        return h >= night_start or h < night_end


@dataclass(frozen=True)
class OvernightReport:
    """Structured result of overnight mortality classification."""

    total_stalls: int
    overnight_stalls: int
    overnight_ratio: float
    is_overnight_pattern: bool
    threshold: float
    night_window: str  # e.g. "00:00-06:00"
    hour_distribution: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "total_stalls": self.total_stalls,
            "overnight_stalls": self.overnight_stalls,
            "overnight_ratio": round(self.overnight_ratio, 3),
            "is_overnight_pattern": self.is_overnight_pattern,
            "threshold": self.threshold,
            "night_window": self.night_window,
            "hour_distribution": self.hour_distribution,
        }


def classify_stalls(
    stalls: Sequence[Timestamp],
    night_start: int = DEFAULT_NIGHT_START,
    night_end: int = DEFAULT_NIGHT_END,
    threshold: float = DEFAULT_THRESHOLD,
) -> OvernightReport:
    """Classify a sequence of stall timestamps by time-of-day pattern.

    Args:
        stalls: Timestamps when stalls were detected.
        night_start: Start hour of the night window (inclusive, 0–23).
        night_end: End hour of the night window (exclusive, 0–23).
        threshold: Ratio above which the overnight pattern is confirmed.

    Returns:
        An OvernightReport with the classification result.
    """
    if not stalls:
        return OvernightReport(
            total_stalls=0,
            overnight_stalls=0,
            overnight_ratio=0.0,
            is_overnight_pattern=False,
            threshold=threshold,
            night_window=f"{night_start:02d}:00-{night_end:02d}:00",
            hour_distribution={},
        )

    dts = [_to_datetime(s) for s in stalls]
    night_count = sum(1 for dt in dts if _is_night_hour(dt, night_start, night_end))
    total = len(dts)
    ratio = night_count / total

    # Build hour distribution
    hour_dist: dict[int, int] = {}
    for dt in dts:
        h = dt.hour
        hour_dist[h] = hour_dist.get(h, 0) + 1

    return OvernightReport(
        total_stalls=total,
        overnight_stalls=night_count,
        overnight_ratio=ratio,
        is_overnight_pattern=ratio >= threshold,
        threshold=threshold,
        night_window=f"{night_start:02d}:00-{night_end:02d}:00",
        hour_distribution=hour_dist,
    )


def from_mortality_ledger(
    repo_path: str | object,
    writer: str = "qwen",
    night_start: int = DEFAULT_NIGHT_START,
    night_end: int = DEFAULT_NIGHT_END,
    threshold: float = DEFAULT_THRESHOLD,
) -> OvernightReport:
    """Load stall events from the process mortality ledger and classify.

    This is a convenience wrapper for caretakers who want a one-liner::

        report = from_mortality_ledger(repo, writer="qwen")
        if report.is_overnight_pattern:
            print("Overnight reclamation — add keep-alive heartbeat")

    Args:
        repo_path: Path to the repository root (or Path-like).
        writer: Writer identity to filter on.
        night_start, night_end, threshold: Same as classify_stalls.

    Returns:
        An OvernightReport.
    """
    import json
    from pathlib import Path

    ledger = Path(repo_path) / "data" / "process_mortality.jsonl"
    if not ledger.exists():
        return classify_stalls([], night_start, night_end, threshold)

    stall_times = []
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
        if event.get("event") != "death":
            continue
        ts = event.get("ts")
        if ts:
            stall_times.append(ts)

    return classify_stalls(stall_times, night_start, night_end, threshold)
