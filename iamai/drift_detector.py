"""Detect gradual cadence drift before it becomes a full stall.

The stall classifier reacts *after* a gap exceeds a threshold.  Drift
detection is the early-warning layer: it maintains a sliding window of
recent inter-stroke intervals and flags when the rolling average creeps
above the expected cadence.

Three states:

- **steady**:   rolling avg ≤ cadence × steady_factor  (default 1.5)
- **drifting**: rolling avg between steady and critical thresholds
- **critical**: rolling avg ≥ cadence × critical_factor (default 3.0)

A single outlier does not trigger drift — the window smooths it out.
A string of slow strokes *does*, even if none individually crosses the
stall threshold.  This is the value: catching the writer getting tired
before it actually stops.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional


@dataclass
class DriftState:
    """Mutable state carried across calls."""

    window: Deque[float] = field(default_factory=lambda: deque(maxlen=20))
    last_timestamp: Optional[float] = None

    def record(self, timestamp: float) -> None:
        """Record a stroke timestamp; auto-compute interval."""
        if self.last_timestamp is not None:
            interval = timestamp - self.last_timestamp
            if interval > 0:
                self.window.append(interval)
        self.last_timestamp = timestamp

    @property
    def intervals(self) -> list[float]:
        return list(self.window)


def assess(
    state: DriftState,
    cadence: float = 15.0,
    steady_factor: float = 1.5,
    critical_factor: float = 3.0,
    min_samples: int = 3,
) -> str:
    """Classify cadence drift from recent intervals.

    Args:
        state: populated DriftState with recorded intervals
        cadence: expected seconds between strokes
        steady_factor: avg ≤ cadence×factor → "steady"
        critical_factor: avg ≥ cadence×factor → "critical"
        min_samples: need at least this many intervals to assess;
                     below that, returns "steady" (not enough data)

    Returns:
        One of: "steady", "drifting", "critical"

    Examples:
        >>> s = DriftState()
        >>> for t in [0, 15, 30, 45, 60]:
        ...     s.record(t)
        >>> assess(s, cadence=15)
        'steady'

        >>> s2 = DriftState()
        >>> for t in [0, 30, 65, 105, 150]:
        ...     s2.record(t)
        >>> assess(s2, cadence=15)
        'drifting'
    """
    if len(state.window) < min_samples:
        return "steady"

    avg = sum(state.window) / len(state.window)
    steady_threshold = cadence * steady_factor
    critical_threshold = cadence * critical_factor

    if avg <= steady_threshold:
        return "steady"
    if avg >= critical_threshold:
        return "critical"
    return "drifting"


def drift_report(state: DriftState, cadence: float = 15.0) -> dict:
    """Return a diagnostic dict for logging / dashboards.

    Returns:
        Dict with keys: status, avg_interval, max_interval,
        min_interval, sample_count, cadence.
    """
    intervals = state.intervals
    if not intervals:
        return {
            "status": "steady",
            "avg_interval": 0.0,
            "max_interval": 0.0,
            "min_interval": 0.0,
            "sample_count": 0,
            "cadence": cadence,
        }

    avg = sum(intervals) / len(intervals)
    return {
        "status": assess(state, cadence=cadence),
        "avg_interval": round(avg, 2),
        "max_interval": round(max(intervals), 2),
        "min_interval": round(min(intervals), 2),
        "sample_count": len(intervals),
        "cadence": cadence,
    }
