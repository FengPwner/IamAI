"""Caretaker response latency — how fast does help arrive after a stall?

``stall_event`` measures the gap; ``process_resurrection`` measures the
recovery.  Neither captures the *human* (or cron) latency: the time
between the system going down and someone — anyone — noticing and
running the restart script.

This module pairs ``(stall_detected_at, restart_issued_at)`` timestamps
and computes response latencies.  The resulting statistics tell you
whether your caretaker cadence is tight enough or whether stalls are
sitting unnoticed for hours.

Latency tiers (configurable):

==========  =========================================================
tier        condition
==========  =========================================================
``fast``    response < 2 × caretaker cadence
``slow``    response < 10 × caretaker cadence
``missed``  response ≥ 10 × caretaker cadence (effectively unmonitored)
==========  =========================================================

Usage::

    from iamai.caretaker_response_latency import (
        CaretakerResponse,
        ResponseTracker,
    )

    tracker = ResponseTracker(caretaker_cadence_s=600)  # 10 min visits

    tracker.record(
        stall_at="2026-10-23T12:00:00+08:00",
        restart_at="2026-10-23T12:08:30+08:00",
    )
    tracker.record(
        stall_at="2026-10-23T14:00:00+08:00",
        restart_at="2026-10-23T14:25:00+08:00",
    )

    print(tracker.mean_latency_s())       # 915.0
    print(tracker.fast_pct())             # 50.0
    print(tracker.report_line())
    # "caretaker_response: 2 events, mean 915.0s, fast 50%, slow 50%, missed 0%"

Design notes:
  - Pure-Python, no git dependency.
  - Accepts ISO-8601 strings, datetime objects, or epoch floats.
  - Frozen dataclass for individual records.
  - Default caretaker cadence is 600 s (10 minutes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple, Union

Timestamp = Union[str, datetime, float, int]

DEFAULT_CARETAKER_CADENCE_S = 600  # 10 minutes
FAST_MULTIPLIER = 2.0
MISSED_MULTIPLIER = 10.0


def _to_datetime(ts: Timestamp) -> datetime:
    """Normalize a timestamp to a timezone-aware datetime (UTC)."""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str):
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts
    raise TypeError(f"unsupported timestamp type: {type(ts)}")


def _latency_seconds(stall: Timestamp, restart: Timestamp) -> float:
    """Compute seconds between stall detection and restart."""
    dt_stall = _to_datetime(stall)
    dt_restart = _to_datetime(restart)
    delta = (dt_restart - dt_stall).total_seconds()
    return max(delta, 0.0)


# ------------------------------------------------------------------
# CaretakerResponse
# ------------------------------------------------------------------


@dataclass(frozen=True)
class CaretakerResponse:
    """One observed caretaker response to a stall.

    Parameters
    ----------
    stall_at : Timestamp
        When the stall was first detectable (e.g. heartbeat went stale).
    restart_at : Timestamp
        When the restart command was issued.
    latency_s : float
        Seconds between stall and restart (computed automatically).
    source : str
        How the restart was triggered: ``"caretaker"``, ``"cron"``,
        ``"manual"``, or ``"unknown"``.
    """

    stall_at: datetime
    restart_at: datetime
    latency_s: float
    source: str = "caretaker"

    _VALID_SOURCES = frozenset({"caretaker", "cron", "manual", "unknown"})

    @classmethod
    def from_timestamps(
        cls,
        stall: Timestamp,
        restart: Timestamp,
        source: str = "caretaker",
    ) -> "CaretakerResponse":
        """Build from raw timestamps."""
        dt_stall = _to_datetime(stall)
        dt_restart = _to_datetime(restart)
        lat = _latency_seconds(stall, restart)
        return cls(
            stall_at=dt_stall,
            restart_at=dt_restart,
            latency_s=lat,
            source=source,
        )

    def __post_init__(self) -> None:
        if self.latency_s < 0:
            raise ValueError(
                f"latency_s must be >= 0, got {self.latency_s}"
            )
        if self.source not in self._VALID_SOURCES:
            raise ValueError(
                f"source must be one of {set(self._VALID_SOURCES)}, "
                f"got {self.source!r}"
            )

    def tier(
        self,
        caretaker_cadence_s: float = DEFAULT_CARETAKER_CADENCE_S,
    ) -> str:
        """Classify latency into a tier.

        Returns ``"fast"``, ``"slow"``, or ``"missed"``.
        """
        if caretaker_cadence_s <= 0:
            return "fast"
        ratio = self.latency_s / caretaker_cadence_s
        if ratio >= MISSED_MULTIPLIER:
            return "missed"
        if ratio >= FAST_MULTIPLIER:
            return "slow"
        return "fast"

    def lost_strokes(
        self,
        writer_cadence_s: float = 15.0,
    ) -> float:
        """Estimated strokes lost during the response latency."""
        if writer_cadence_s <= 0:
            return 0.0
        return self.latency_s / writer_cadence_s


# ------------------------------------------------------------------
# ResponseTracker
# ------------------------------------------------------------------


@dataclass
class ResponseTracker:
    """Aggregate caretaker response latencies.

    Parameters
    ----------
    caretaker_cadence_s : float
        Expected seconds between caretaker check-ins (default 600).
    writer_cadence_s : float
        Target seconds per writer stroke (default 15).
    max_history : int
        Maximum number of responses to retain.
    """

    caretaker_cadence_s: float = DEFAULT_CARETAKER_CADENCE_S
    writer_cadence_s: float = 15.0
    max_history: int = 500

    _responses: List[CaretakerResponse] = field(
        default_factory=list, repr=False
    )

    def __post_init__(self) -> None:
        if self.caretaker_cadence_s <= 0:
            raise ValueError(
                f"caretaker_cadence_s must be > 0, "
                f"got {self.caretaker_cadence_s}"
            )
        if self.writer_cadence_s <= 0:
            raise ValueError(
                f"writer_cadence_s must be > 0, got {self.writer_cadence_s}"
            )
        if self.max_history < 1:
            raise ValueError(
                f"max_history must be >= 1, got {self.max_history}"
            )

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        stall_at: Timestamp,
        restart_at: Timestamp,
        source: str = "caretaker",
    ) -> CaretakerResponse:
        """Record a caretaker response. Returns the created record."""
        resp = CaretakerResponse.from_timestamps(stall_at, restart_at, source)
        self._responses.append(resp)
        if len(self._responses) > self.max_history:
            self._responses = self._responses[-self.max_history :]
        return resp

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Total number of recorded responses."""
        return len(self._responses)

    @property
    def total_latency_s(self) -> float:
        """Sum of all latencies."""
        return sum(r.latency_s for r in self._responses)

    def mean_latency_s(self) -> float:
        """Average response latency in seconds."""
        if not self._responses:
            return 0.0
        return self.total_latency_s / len(self._responses)

    def median_latency_s(self) -> float:
        """Median response latency in seconds."""
        if not self._responses:
            return 0.0
        sorted_lats = sorted(r.latency_s for r in self._responses)
        n = len(sorted_lats)
        mid = n // 2
        if n % 2 == 0:
            return (sorted_lats[mid - 1] + sorted_lats[mid]) / 2.0
        return sorted_lats[mid]

    def worst_latency_s(self) -> float:
        """Longest single response latency."""
        if not self._responses:
            return 0.0
        return max(r.latency_s for r in self._responses)

    def best_latency_s(self) -> float:
        """Shortest single response latency."""
        if not self._responses:
            return 0.0
        return min(r.latency_s for r in self._responses)

    def total_lost_strokes(self) -> float:
        """Total estimated strokes lost during all response latencies."""
        return sum(r.lost_strokes(self.writer_cadence_s) for r in self._responses)

    # ------------------------------------------------------------------
    # Tier breakdown
    # ------------------------------------------------------------------

    def tier_counts(self) -> Dict[str, int]:
        """Count responses by tier."""
        counts: Dict[str, int] = {"fast": 0, "slow": 0, "missed": 0}
        for r in self._responses:
            t = r.tier(self.caretaker_cadence_s)
            counts[t] = counts.get(t, 0) + 1
        return counts

    def fast_pct(self) -> float:
        """Percentage of responses in the ``fast`` tier."""
        if not self._responses:
            return 0.0
        return (self.tier_counts()["fast"] / len(self._responses)) * 100.0

    def slow_pct(self) -> float:
        """Percentage of responses in the ``slow`` tier."""
        if not self._responses:
            return 0.0
        return (self.tier_counts()["slow"] / len(self._responses)) * 100.0

    def missed_pct(self) -> float:
        """Percentage of responses in the ``missed`` tier."""
        if not self._responses:
            return 0.0
        return (self.tier_counts()["missed"] / len(self._responses)) * 100.0

    # ------------------------------------------------------------------
    # Source breakdown
    # ------------------------------------------------------------------

    def source_counts(self) -> Dict[str, int]:
        """Count responses by source."""
        counts: Dict[str, int] = {}
        for r in self._responses:
            counts[r.source] = counts.get(r.source, 0) + 1
        return counts

    def mean_latency_by_source(self) -> Dict[str, float]:
        """Mean latency grouped by source."""
        buckets: Dict[str, List[float]] = {}
        for r in self._responses:
            buckets.setdefault(r.source, []).append(r.latency_s)
        return {
            src: sum(lats) / len(lats)
            for src, lats in buckets.items()
        }

    # ------------------------------------------------------------------
    # Trend
    # ------------------------------------------------------------------

    def trend(self) -> str:
        """Compare first-half to second-half mean latency.

        Returns ``"improving"``, ``"worsening"``, or ``"stable"``.
        Requires at least 4 events; otherwise ``"stable"``.
        """
        n = len(self._responses)
        if n < 4:
            return "stable"
        mid = n // 2
        first = sum(r.latency_s for r in self._responses[:mid]) / mid
        second = sum(
            r.latency_s for r in self._responses[mid:]
        ) / (n - mid)
        delta = second - first
        threshold = self.caretaker_cadence_s
        if delta > threshold:
            return "worsening"
        if delta < -threshold:
            return "improving"
        return "stable"

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> str:
        """Classify overall caretaker response health.

        Returns ``"responsive"``, ``"lagging"``, or ``"absent"``.

        - ``responsive``: mean latency < 2 × caretaker cadence, no missed
        - ``lagging``: mean latency < 10 × caretaker cadence
        - ``absent``: mean latency ≥ 10 × caretaker cadence or any missed
        """
        if not self._responses:
            return "responsive"
        counts = self.tier_counts()
        ml = self.mean_latency_s()
        if counts["missed"] > 0 or ml >= MISSED_MULTIPLIER * self.caretaker_cadence_s:
            return "absent"
        if ml >= FAST_MULTIPLIER * self.caretaker_cadence_s:
            return "lagging"
        return "responsive"

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def summarize(self) -> Dict:
        """Return a JSON-serializable summary dict."""
        return {
            "count": self.count,
            "caretaker_cadence_s": self.caretaker_cadence_s,
            "writer_cadence_s": self.writer_cadence_s,
            "mean_latency_s": round(self.mean_latency_s(), 2),
            "median_latency_s": round(self.median_latency_s(), 2),
            "worst_latency_s": round(self.worst_latency_s(), 2),
            "best_latency_s": round(self.best_latency_s(), 2),
            "total_lost_strokes": round(self.total_lost_strokes(), 2),
            "tier_counts": self.tier_counts(),
            "fast_pct": round(self.fast_pct(), 1),
            "slow_pct": round(self.slow_pct(), 1),
            "missed_pct": round(self.missed_pct(), 1),
            "source_counts": self.source_counts(),
            "health": self.health(),
            "trend": self.trend(),
        }

    def report_line(self) -> str:
        """One-line human-readable summary for caretaker logs."""
        s = self.summarize()
        tc = s["tier_counts"]
        return (
            f"caretaker_response: {s['health']} "
            f"({s['count']} events, "
            f"mean {s['mean_latency_s']:.1f}s, "
            f"worst {s['worst_latency_s']:.1f}s, "
            f"fast {tc['fast']}, slow {tc['slow']}, missed {tc['missed']}, "
            f"lost ~{s['total_lost_strokes']:.1f} strokes, "
            f"trend {s['trend']})"
        )

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all recorded responses."""
        self._responses.clear()
