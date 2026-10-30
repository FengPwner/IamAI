"""restart_warmup — measure post-restart recovery latency.

After a process restart, there is a *warmup* period before the writer
produces its first stroke.  This module measures that gap and classifies
recovery quality.

The warmup model:

- ``restart`` event: process was started (PID assigned).
- ``first_stroke`` event: writer produced its first output.
- Latency = time between the two events.
- Quality classification:

============  ==============================================
quality       meaning
============  ==============================================
instant       < 5 s — negligible disruption
fast          5–30 s — normal startup
normal        30–120 s — acceptable, some init overhead
slow          120–600 s — concerning, may indicate issues
degraded      > 600 s — restart took longer than 10 min
============  ==============================================

Trend analysis (over the last N samples):

- ``improving``: warmup times are getting shorter
- ``stable``: warmup times are roughly constant
- ``degrading``: warmup times are getting longer

Public API::

    from iamai.restart_warmup import RestartWarmup

    w = RestartWarmup()
    w.record_restart(ts=1000.0, pid=42)
    w.record_first_stroke(ts=1012.0, pid=42)
    w.last_latency()            # 12.0
    w.quality()                 # "fast"
    w.trend(window=10)          # "stable"
    w.summary()                 # human-readable one-liner

Design:

- Pure Python, no subprocess, no filesystem side-effects.
- All inputs are arguments (testable without mocking).
- Frozen dataclass reports — immutable snapshots.
- Ring buffer caps memory at ``DEFAULT_BUFFER_SIZE`` samples.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple


# Thresholds in seconds for quality classification
THRESHOLD_INSTANT: float = 5.0
THRESHOLD_FAST: float = 30.0
THRESHOLD_NORMAL: float = 120.0
THRESHOLD_SLOW: float = 600.0

DEFAULT_BUFFER_SIZE: int = 500  # max warmup samples kept


@dataclass(frozen=True)
class WarmupSample:
    """A single restart→first_stroke measurement."""
    restart_ts: float
    stroke_ts: float
    pid: Optional[int] = None

    @property
    def latency(self) -> float:
        """Warmup latency in seconds."""
        return self.stroke_ts - self.restart_ts


@dataclass(frozen=True)
class WarmupReport:
    """Immutable snapshot of warmup statistics."""
    samples: int
    last_latency_s: Optional[float]
    mean_latency_s: Optional[float]
    median_latency_s: Optional[float]
    max_latency_s: Optional[float]
    min_latency_s: Optional[float]
    quality: str
    trend: str

    def one_liner(self) -> str:
        if self.samples == 0:
            return "no warmup data"
        return (
            f"warmup: {self.quality} "
            f"(last={self.last_latency_s:.1f}s, "
            f"mean={self.mean_latency_s:.1f}s, "
            f"n={self.samples}, trend={self.trend})"
        )


class RestartWarmup:
    """Track and classify post-restart warmup latency."""

    def __init__(self, buffer_size: int = DEFAULT_BUFFER_SIZE) -> None:
        self._buffer: Deque[WarmupSample] = deque(maxlen=buffer_size)
        self._pending_restart: Dict[int, float] = {}  # pid -> restart_ts
        self._last_restart_ts: Optional[float] = None  # for pid-less matching

    # ── recording ──────────────────────────────────────────────

    def record_restart(self, ts: float, pid: Optional[int] = None) -> None:
        """Record a restart event."""
        if pid is not None:
            self._pending_restart[pid] = ts
        self._last_restart_ts = ts

    def record_first_stroke(
        self, ts: float, pid: Optional[int] = None
    ) -> Optional[WarmupSample]:
        """Record a first_stroke event; returns the matched sample or None."""
        restart_ts: Optional[float] = None

        if pid is not None and pid in self._pending_restart:
            restart_ts = self._pending_restart.pop(pid)
        elif self._last_restart_ts is not None:
            restart_ts = self._last_restart_ts
            self._last_restart_ts = None

        if restart_ts is None:
            return None

        if ts < restart_ts:
            return None  # stroke before restart — clock skew, ignore

        sample = WarmupSample(
            restart_ts=restart_ts,
            stroke_ts=ts,
            pid=pid,
        )
        self._buffer.append(sample)
        return sample

    def add_sample(
        self,
        restart_ts: float,
        stroke_ts: float,
        pid: Optional[int] = None,
    ) -> WarmupSample:
        """Directly add a pre-matched sample (for bulk imports)."""
        sample = WarmupSample(
            restart_ts=restart_ts,
            stroke_ts=stroke_ts,
            pid=pid,
        )
        self._buffer.append(sample)
        return sample

    # ── queries ────────────────────────────────────────────────

    def sample_count(self) -> int:
        return len(self._buffer)

    def last_latency(self) -> Optional[float]:
        """Latency of the most recent warmup sample."""
        if not self._buffer:
            return None
        return self._buffer[-1].latency

    def quality(self) -> str:
        """Classify the most recent warmup latency."""
        lat = self.last_latency()
        if lat is None:
            return "unknown"
        return classify_quality(lat)

    def trend(self, window: int = 10) -> str:
        """Analyse warmup trend over the last *window* samples.

        Uses linear regression slope on latencies:
        - slope < -1.0 → improving
        - slope > +1.0 → degrading
        - otherwise    → stable
        """
        n = min(window, len(self._buffer))
        if n < 3:
            return "insufficient_data"

        latencies = [s.latency for s in list(self._buffer)[-n:]]
        slope = _linear_slope(latencies)

        if slope < -1.0:
            return "improving"
        elif slope > 1.0:
            return "degrading"
        return "stable"

    def statistics(self) -> Dict:
        """Return summary statistics dict."""
        if not self._buffer:
            return {
                "samples": 0,
                "mean": None,
                "median": None,
                "min": None,
                "max": None,
            }
        latencies = sorted(s.latency for s in self._buffer)
        n = len(latencies)
        return {
            "samples": n,
            "mean": sum(latencies) / n,
            "median": _median_sorted(latencies),
            "min": latencies[0],
            "max": latencies[-1],
        }

    def report(self) -> WarmupReport:
        """Generate an immutable snapshot report."""
        stats = self.statistics()
        return WarmupReport(
            samples=stats["samples"],
            last_latency_s=self.last_latency(),
            mean_latency_s=stats["mean"],
            median_latency_s=stats["median"],
            max_latency_s=stats["max"],
            min_latency_s=stats["min"],
            quality=self.quality(),
            trend=self.trend(),
        )

    def summary(self) -> str:
        """Human-readable one-liner."""
        return self.report().one_liner()

    # ── bulk helpers ───────────────────────────────────────────

    def ingest_events(self, events: List[Dict]) -> int:
        """Ingest a list of event dicts with keys ``event``, ``ts``, ``pid``.

        Returns the number of matched warmup pairs added.
        """
        added = 0
        for ev in events:
            event_type = ev.get("event", "")
            ts = float(ev.get("ts", 0))
            pid = ev.get("pid")

            if event_type == "restart":
                self.record_restart(ts=ts, pid=pid)
            elif event_type == "first_stroke":
                sample = self.record_first_stroke(ts=ts, pid=pid)
                if sample is not None:
                    added += 1
        return added

    def clear(self) -> None:
        """Reset all state."""
        self._buffer.clear()
        self._pending_restart.clear()
        self._last_restart_ts = None


# ── module-level helpers ───────────────────────────────────────


def classify_quality(latency_s: float) -> str:
    """Classify a single latency value."""
    if latency_s < THRESHOLD_INSTANT:
        return "instant"
    if latency_s < THRESHOLD_FAST:
        return "fast"
    if latency_s < THRESHOLD_NORMAL:
        return "normal"
    if latency_s < THRESHOLD_SLOW:
        return "slow"
    return "degraded"


def _linear_slope(values: List[float]) -> float:
    """Simple OLS slope over integer x-axis [0, 1, 2, …]."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _median_sorted(sorted_values: List[float]) -> float:
    """Median of an already-sorted list."""
    n = len(sorted_values)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 0:
        return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0
    return sorted_values[mid]
