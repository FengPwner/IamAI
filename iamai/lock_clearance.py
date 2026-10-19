"""Lock clearance — ledger of lock file removal events and their outcomes.

When a git lock file blocks commits, the caretaker (or an automated
recovery pipeline) clears it.  But clearing a lock is only half the
story: did the repo recover?  How long did the lock persist?  How
often does it recur?

This module answers those questions by maintaining a bounded ledger
of lock clearance events.  Each event captures:

- **when** the lock was cleared (epoch timestamp)
- **lock_age** — how long the lock had existed before clearance (seconds)
- **recovered** — whether git operations resumed successfully
- **method** — how the lock was cleared ('manual', 'auto', 'timeout')
- **backlog** — number of uncommitted files at clearance time

From the ledger, three analytics are derived:

=================  ======================================================
metric             meaning
=================  ======================================================
clearance_rate     clearances per 24-hour window (rolling)
mean_lock_age      average time a lock persisted before being cleared
recovery_rate      fraction of clearances that led to full recovery
recurrence_risk    probability of another lock event within 1 hour
=================  ======================================================

Classification
--------------

========  ============================================================
label     meaning
========  ============================================================
clean     no clearances in the window, or all recovered cleanly
recurring multiple clearances in 24h, but most recovered
brittle   frequent clearances with low recovery rate — systemic issue
========  ============================================================

Design choices
--------------

- **Pure data structure.**  No I/O, no subprocess calls.  Callers pass
  events in; analytics come out.
- **Bounded history.**  Default 100 events; older entries are evicted.
- **Separation from detection.**  ``index_lock_detector`` finds locks;
  ``lock_recovery`` removes them; this module *measures* how well the
  removal process works.

Usage::

    from iamai.lock_clearance import LockClearance, LockClearanceLedger

    ledger = LockClearanceLedger()
    ledger.record(LockClearance(at=1697745600, lock_age=3600, recovered=True))
    ledger.clearance_rate()       # 1.0
    ledger.recovery_rate()        # 1.0
    ledger.classify()             # 'clean'
    print(ledger.report())
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class LockClearance:
    """A single lock clearance event.

    Parameters
    ----------
    at : float
        Epoch timestamp when the lock was cleared.
    lock_age : float
        How long the lock file existed before clearance (seconds).
    recovered : bool
        Whether git operations resumed successfully after clearance.
    method : str
        How the lock was cleared.  Conventional values:
        'manual', 'auto', 'timeout', 'caretaker'.
    backlog : int
        Number of uncommitted files at the time of clearance.
    """

    at: float
    lock_age: float = 0.0
    recovered: bool = True
    method: str = "auto"
    backlog: int = 0


# Classification thresholds
CLEAN_MAX_CLEARANCES = 3       # <=3 per 24h with full recovery → clean
RECURRING_MIN_RECOVERY = 0.7   # >=70% recovery → recurring, else brittle
BRITTLE_MIN_CLEARANCES = 5     # need 5+ events to call it brittle
RECURRENCE_WINDOW_S = 3600     # 1 hour for recurrence calculation


@dataclass
class LockClearanceLedger:
    """Bounded log of lock clearance events with rolling analytics.

    Parameters
    ----------
    max_events : int
        Maximum number of events to retain.  Default 100.
    """

    max_events: int = 100
    _events: deque = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._events = deque(maxlen=self.max_events)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, event: LockClearance) -> int:
        """Record a clearance event.  Returns total event count."""
        self._events.append(event)
        return len(self._events)

    def __len__(self) -> int:
        return len(self._events)

    @property
    def events(self) -> list[LockClearance]:
        """Return events in chronological order (oldest first)."""
        return list(self._events)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def _events_in_window(self, now: float, window_seconds: float) -> list[LockClearance]:
        """Return events within [now - window_seconds, now]."""
        cutoff = now - window_seconds
        return [e for e in self._events if e.at >= cutoff]

    def clearance_rate(
        self, now: Optional[float] = None, window_hours: float = 24.0
    ) -> float:
        """Clearances per 24-hour window ending at *now*.

        Returns 0.0 if no events recorded.
        """
        if not self._events:
            return 0.0
        if now is None:
            now = self._events[-1].at
        window = window_hours * 3600.0
        return float(len(self._events_in_window(now, window)))

    def mean_lock_age(
        self, now: Optional[float] = None, window_hours: float = 24.0
    ) -> float:
        """Average lock age (seconds) for clearances in the given window.

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
        return sum(e.lock_age for e in recent) / len(recent)

    def recovery_rate(
        self, now: Optional[float] = None, window_hours: float = 24.0
    ) -> float:
        """Fraction of clearances that led to successful recovery.

        Returns 1.0 if no events (vacuously healthy).
        """
        if not self._events:
            return 1.0
        if now is None:
            now = self._events[-1].at
        window = window_hours * 3600.0
        recent = self._events_in_window(now, window)
        if not recent:
            return 1.0
        recovered = sum(1 for e in recent if e.recovered)
        return recovered / len(recent)

    def recurrence_risk(self, now: Optional[float] = None) -> float:
        """Probability of another lock event within 1 hour of a clearance.

        Computed as: (number of clearances that had a follow-up within
        RECURRENCE_WINDOW_S) / (total clearances - 1).

        Returns 0.0 if fewer than 2 events.
        """
        if len(self._events) < 2:
            return 0.0
        if now is None:
            now = self._events[-1].at

        events = list(self._events)
        pairs = 0
        recurrences = 0
        for i in range(len(events) - 1):
            for j in range(i + 1, len(events)):
                gap = events[j].at - events[i].at
                if gap <= 0:
                    continue
                if gap <= RECURRENCE_WINDOW_S:
                    pairs += 1
                    recurrences += 1
                    break  # only count first recurrence per event
                elif gap > RECURRENCE_WINDOW_S:
                    pairs += 1
                    break

        if pairs == 0:
            return 0.0
        return recurrences / pairs

    def method_breakdown(
        self, now: Optional[float] = None, window_hours: float = 24.0
    ) -> dict[str, int]:
        """Count clearances by method in the given window.

        Returns a dict mapping method → count, sorted by count descending.
        """
        if not self._events:
            return {}
        if now is None:
            now = self._events[-1].at
        window = window_hours * 3600.0
        recent = self._events_in_window(now, window)
        counts: dict[str, int] = {}
        for e in recent:
            counts[e.method] = counts.get(e.method, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def total_backlog(
        self, now: Optional[float] = None, window_hours: float = 24.0
    ) -> int:
        """Sum of backlog sizes across clearances in the given window."""
        if not self._events:
            return 0
        if now is None:
            now = self._events[-1].at
        window = window_hours * 3600.0
        recent = self._events_in_window(now, window)
        return sum(e.backlog for e in recent)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify(self, now: Optional[float] = None) -> str:
        """Classify lock clearance health.

        Returns
        -------
        str
            One of 'clean', 'recurring', or 'brittle'.

        Rules (evaluated in order):
          1. >= BRITTLE_MIN_CLEARANCES clearances with recovery < threshold → brittle
          2. > CLEAN_MAX_CLEARANCES clearances in 24h → recurring
          3. Otherwise → clean
        """
        if not self._events:
            return "clean"
        if now is None:
            now = self._events[-1].at

        rate = self.clearance_rate(now)
        recovery = self.recovery_rate(now)

        if rate >= BRITTLE_MIN_CLEARANCES and recovery < RECURRING_MIN_RECOVERY:
            return "brittle"
        if rate > CLEAN_MAX_CLEARANCES:
            return "recurring"
        return "clean"

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
            "clearances_24h": self.clearance_rate(now),
            "mean_lock_age_s": round(self.mean_lock_age(now), 1),
            "recovery_rate": round(self.recovery_rate(now), 3),
            "recurrence_risk": round(self.recurrence_risk(now), 3),
            "total_backlog": self.total_backlog(now),
            "method_breakdown": self.method_breakdown(now),
            "latest_event": (
                {
                    "at": self._events[-1].at,
                    "lock_age": self._events[-1].lock_age,
                    "recovered": self._events[-1].recovered,
                    "method": self._events[-1].method,
                    "backlog": self._events[-1].backlog,
                }
                if self._events
                else None
            ),
        }


def clearance_summary(ledger: LockClearanceLedger, now: Optional[float] = None) -> str:
    """One-liner summary of lock clearance health.

    Examples::

        "lock clearance: 2 events, clean, recovery 100%, mean age 120s"
        "lock clearance: 8 events, brittle, recovery 37%, mean age 4800s"
    """
    if not ledger:
        return "lock clearance: no events — clean"
    if now is None:
        now = ledger.events[-1].at

    r = ledger.report(now)
    pct = f"{r['recovery_rate'] * 100:.0f}%"
    return (
        f"lock clearance: {r['total_events']} event(s), "
        f"{r['classification']}, "
        f"recovery {pct}, "
        f"mean age {r['mean_lock_age_s']:.0f}s"
    )
