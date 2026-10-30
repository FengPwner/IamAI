"""restart_ledger — record and analyse process restart events.

When a self-writing repository recycles its sandbox every night, restarts
are not anomalies — they are weather.  This module treats them as such:
each restart is a structured event with a timestamp, a reason tag, and
the downtime gap (seconds between last known heartbeat and new process up).

RestartLedger keeps a bounded history (default 200 events) and derives:
  - restart_rate:    restarts per 24-hour window (rolling)
  - mean_downtime:   average gap in seconds
  - worst_streak:    longest run of restarts within any single hour
  - classify():      'stable' / 'flapping' / 'crash-loop'

All operations are pure Python, no subprocess calls, no disk I/O.
Callers (caretaker visits, process supervisors) pass in events and get
back structured reports.

Usage::

    from iamai.restart_ledger import RestartLedger, RestartEvent

    ledger = RestartLedger()
    ledger.record(RestartEvent(at=1696636800, reason="sandbox_recycle", downtime=120))
    ledger.record(RestartEvent(at=1696637100, reason="oom_kill", downtime=45))
    ledger.restart_rate()       # 2.0 per 24h
    ledger.mean_downtime()      # 82.5
    ledger.classify()           # 'stable' (only 2 in 24h)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional


# Classification thresholds
STABLE_MAX_RESTARTS = 5        # <=5 per 24h → stable
FLAPPING_MAX_RESTARTS = 20     # <=20 per 24h → flapping, else crash-loop
CRASH_LOOP_HOUR_STREAK = 5     # 5+ restarts in any 1h window → crash-loop


@dataclass(frozen=True)
class RestartEvent:
    """A single process restart record.

    Parameters
    ----------
    at : float
        Epoch timestamp when the new process came up.
    reason : str
        Why the restart happened.  Free-form but conventional values:
        'sandbox_recycle', 'oom_kill', 'caretaker_restart', 'crash',
        'push_race', 'manual', 'unknown'.
    downtime : float
        Seconds between last heartbeat and new process startup.
    writer_id : str
        Which writer was restarted.  Default 'qwen'.
    pid : int
        New process ID, if known.  Default 0.
    """

    at: float
    reason: str = "unknown"
    downtime: float = 0.0
    writer_id: str = "qwen"
    pid: int = 0


# Classification labels
STABLE = "stable"
FLAPPING = "flapping"
CRASH_LOOP = "crash-loop"


@dataclass
class RestartLedger:
    """Bounded log of restart events with rolling analytics.

    Parameters
    ----------
    max_events : int
        Maximum number of events to retain.  Older events are evicted.
        Default 200.
    """

    max_events: int = 200
    _events: deque = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._events = deque(maxlen=self.max_events)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, event: RestartEvent) -> int:
        """Record a restart event.  Returns total event count."""
        self._events.append(event)
        return len(self._events)

    def __len__(self) -> int:
        return len(self._events)

    @property
    def events(self) -> list[RestartEvent]:
        """Return events in chronological order (oldest first)."""
        return list(self._events)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def _events_in_window(self, now: float, window_seconds: float) -> list[RestartEvent]:
        """Return events within [now - window_seconds, now]."""
        cutoff = now - window_seconds
        return [e for e in self._events if e.at >= cutoff]

    def restart_rate(self, now: Optional[float] = None, window_hours: float = 24.0) -> float:
        """Restarts per 24-hour window ending at *now*.

        Parameters
        ----------
        now : float, optional
            Reference epoch.  Defaults to the timestamp of the most recent
            event (or 0.0 if empty).
        window_hours : float
            Lookback window in hours.  Default 24.
        """
        if not self._events:
            return 0.0
        if now is None:
            now = self._events[-1].at
        window = window_hours * 3600.0
        return float(len(self._events_in_window(now, window)))

    def mean_downtime(self, now: Optional[float] = None, window_hours: float = 24.0) -> float:
        """Average downtime (seconds) for restarts in the given window.

        Returns 0.0 if no events in window.
        """
        if not self._events:
            return 0.0
        if now is None:
            now = self._events[-1].at
        window = window_hours * 3600.0
        recent = self._events_in_window(now, window)
        if not recent:
            return 0.0
        return sum(e.downtime for e in recent) / len(recent)

    def worst_hour_streak(self, now: Optional[float] = None) -> int:
        """Maximum number of restarts in any single 1-hour window.

        Scans all recorded events, bucketing by floor(at / 3600).
        """
        if not self._events:
            return 0
        buckets: dict[int, int] = {}
        for e in self._events:
            bucket = int(e.at // 3600)
            buckets[bucket] = buckets.get(bucket, 0) + 1
        return max(buckets.values())

    def reason_breakdown(self, now: Optional[float] = None, window_hours: float = 24.0) -> dict[str, int]:
        """Count restarts by reason in the given window.

        Returns a dict mapping reason → count, sorted by count descending.
        """
        if not self._events:
            return {}
        if now is None:
            now = self._events[-1].at
        window = window_hours * 3600.0
        recent = self._events_in_window(now, window)
        counts: dict[str, int] = {}
        for e in recent:
            counts[e.reason] = counts.get(e.reason, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify(self, now: Optional[float] = None) -> str:
        """Classify restart health.

        Returns
        -------
        str
            One of 'stable', 'flapping', or 'crash-loop'.

        Rules (evaluated in order):
          1. Any 1-hour window with >= CRASH_LOOP_HOUR_STREAK restarts → crash-loop
          2. 24h restart count > FLAPPING_MAX_RESTARTS → crash-loop
          3. 24h restart count > STABLE_MAX_RESTARTS → flapping
          4. Otherwise → stable
        """
        if not self._events:
            return STABLE
        if now is None:
            now = self._events[-1].at

        # Check hourly streak across all data
        if self.worst_hour_streak(now) >= CRASH_LOOP_HOUR_STREAK:
            return CRASH_LOOP

        rate_24h = self.restart_rate(now)
        if rate_24h > FLAPPING_MAX_RESTARTS:
            return CRASH_LOOP
        if rate_24h > STABLE_MAX_RESTARTS:
            return FLAPPING
        return STABLE

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def report(self, now: Optional[float] = None) -> dict:
        """Full structured report as a plain dict.

        Suitable for JSON serialisation or caretaker display.
        """
        if now is None:
            now = self._events[-1].at if self._events else 0.0
        return {
            "total_events": len(self._events),
            "classification": self.classify(now),
            "restarts_24h": self.restart_rate(now),
            "mean_downtime_s": round(self.mean_downtime(now), 1),
            "worst_hour_streak": self.worst_hour_streak(now),
            "reason_breakdown": self.reason_breakdown(now),
            "latest_event": (
                {
                    "at": self._events[-1].at,
                    "reason": self._events[-1].reason,
                    "downtime": self._events[-1].downtime,
                    "writer_id": self._events[-1].writer_id,
                    "pid": self._events[-1].pid,
                }
                if self._events
                else None
            ),
        }
