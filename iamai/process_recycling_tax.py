"""process_recycling_tax — measure the cumulative cost of process churn.

Every time the writer or batch committer dies and is restarted, there is
a *tax*: the dead-time between the last productive action before death
and the first productive action after restart.  A single restart costs
seconds; chronic recycling costs hours per day.

This module aggregates restart events over a rolling window and produces
an *efficiency ratio* — the fraction of wall-clock time the process was
actually productive versus lost to recycling overhead.

Recycling events
----------------
Each event records:

- ``death_ts``:    timestamp when the process was last known alive
- ``recovery_ts``: timestamp when the replacement produced its first output

The gap ``recovery_ts - death_ts`` is the *tax* for that event.

Aggregation
-----------
Given a list of events and an observation window ``[window_start, window_end]``:

- ``total_tax_s``:   sum of all individual taxes within the window
- ``window_s``:      total observation duration
- ``tax_ratio``:     total_tax_s / window_s  (0.0 = no overhead, 1.0 = all overhead)
- ``recycling_rate``: events per hour
- ``mean_tax_s``:    average tax per event

Severity tiers
--------------
===========  ===========  ===========================================
label        tax_ratio    meaning
===========  ===========  ===========================================
negligible   < 0.01       < 1% overhead — healthy
low          < 0.05       1–5% — acceptable jitter
moderate     < 0.10       5–10% — noticeable, investigate root cause
high         < 0.20       10–20% — significant productivity loss
critical     >= 0.20      > 20% — the process is more dead than alive
===========  ===========  ===========================================

Public API::

    from iamai.process_recycling_tax import RecyclingLedger

    ledger = RecyclingLedger()
    ledger.add(death_ts=1000.0, recovery_ts=1012.0)
    ledger.add(death_ts=2000.0, recovery_ts=2045.0)

    report = ledger.report(window_start=0.0, window_end=3600.0)
    print(report["tax_ratio"])      # 0.0158...
    print(report["severity"])       # "low"
    print(report["recycling_rate"]) # 2.0  (per hour)

Design:

- Pure Python, no subprocess, no filesystem side-effects.
- All timestamps are epoch floats (easy to mock in tests).
- ``RecyclingLedger`` is a thin accumulator; ``classify`` is a pure function.
- Frozen dataclass ``TaxReport`` for immutable snapshots.

Exit codes (for CLI wrappers)
-----------------------------
    0 — negligible
    1 — low
    2 — moderate
    3 — high
    4 — critical
    5 — no data
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# severity tiers
# ---------------------------------------------------------------------------

SEVERITY_NEGLIGIBLE = "negligible"
SEVERITY_LOW = "low"
SEVERITY_MODERATE = "moderate"
SEVERITY_HIGH = "high"
SEVERITY_CRITICAL = "critical"
SEVERITY_NO_DATA = "no_data"

EXIT_NEGLIGIBLE = 0
EXIT_LOW = 1
EXIT_MODERATE = 2
EXIT_HIGH = 3
EXIT_CRITICAL = 4
EXIT_NO_DATA = 5

_THRESHOLDS: List[Tuple[float, str, int]] = [
    (0.01, SEVERITY_NEGLIGIBLE, EXIT_NEGLIGIBLE),
    (0.05, SEVERITY_LOW, EXIT_LOW),
    (0.10, SEVERITY_MODERATE, EXIT_MODERATE),
    (0.20, SEVERITY_HIGH, EXIT_HIGH),
]

DEFAULT_MAX_EVENTS = 10_000  # ring buffer cap


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


def classify(tax_ratio: float) -> Tuple[str, int]:
    """Classify a tax ratio into (severity_label, exit_code).

    >>> classify(0.005)
    ('negligible', 0)
    >>> classify(0.07)
    ('moderate', 2)
    >>> classify(0.5)
    ('critical', 4)
    """
    for threshold, label, code in _THRESHOLDS:
        if tax_ratio < threshold:
            return label, code
    return SEVERITY_CRITICAL, EXIT_CRITICAL


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecyclingEvent:
    """A single death→recovery cycle."""

    death_ts: float
    recovery_ts: float

    @property
    def tax(self) -> float:
        """Seconds lost to this recycling event."""
        return max(0.0, self.recovery_ts - self.death_ts)


@dataclass(frozen=True)
class TaxReport:
    """Immutable snapshot of recycling tax over an observation window."""

    window_start: float
    window_end: float
    event_count: int
    total_tax_s: float
    window_s: float
    tax_ratio: float
    recycling_rate_per_hour: float
    mean_tax_s: float
    severity: str
    exit_code: int

    def to_dict(self) -> dict:
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "event_count": self.event_count,
            "total_tax_s": round(self.total_tax_s, 2),
            "window_s": round(self.window_s, 2),
            "tax_ratio": round(self.tax_ratio, 4),
            "recycling_rate_per_hour": round(self.recycling_rate_per_hour, 2),
            "mean_tax_s": round(self.mean_tax_s, 2),
            "severity": self.severity,
            "exit_code": self.exit_code,
        }

    def summary(self) -> str:
        """Human-readable one-liner."""
        if self.severity == SEVERITY_NO_DATA:
            return "no recycling events in window"
        pct = self.tax_ratio * 100
        return (
            f"{self.severity}: {self.event_count} recycling events, "
            f"{self.total_tax_s:.0f}s tax in {self.window_s:.0f}s window "
            f"({pct:.1f}%), {self.recycling_rate_per_hour:.1f}/hr"
        )


# ---------------------------------------------------------------------------
# RecyclingLedger — accumulator
# ---------------------------------------------------------------------------


class RecyclingLedger:
    """Accumulate recycling events and produce tax reports.

    Parameters
    ----------
    max_events : int
        Ring-buffer cap to bound memory.  Oldest events are dropped first.
    """

    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS) -> None:
        self._events: List[RecyclingEvent] = []
        self._max = max_events

    def add(self, death_ts: float, recovery_ts: float) -> RecyclingEvent:
        """Record a death→recovery event.  Returns the created event."""
        ev = RecyclingEvent(death_ts=death_ts, recovery_ts=recovery_ts)
        self._events.append(ev)
        if len(self._events) > self._max:
            self._events = self._events[-self._max :]
        return ev

    @property
    def events(self) -> List[RecyclingEvent]:
        return list(self._events)

    def count(self) -> int:
        return len(self._events)

    def report(
        self,
        window_start: float,
        window_end: float,
    ) -> TaxReport:
        """Compute tax report for the given observation window.

        Events whose death_ts falls within ``[window_start, window_end]``
        are included.  Events outside the window are ignored.
        """
        window_s = max(0.0, window_end - window_start)
        if window_s == 0:
            return TaxReport(
                window_start=window_start,
                window_end=window_end,
                event_count=0,
                total_tax_s=0.0,
                window_s=0.0,
                tax_ratio=0.0,
                recycling_rate_per_hour=0.0,
                mean_tax_s=0.0,
                severity=SEVERITY_NO_DATA,
                exit_code=EXIT_NO_DATA,
            )

        in_window = [
            e for e in self._events
            if window_start <= e.death_ts <= window_end
        ]
        n = len(in_window)
        if n == 0:
            return TaxReport(
                window_start=window_start,
                window_end=window_end,
                event_count=0,
                total_tax_s=0.0,
                window_s=window_s,
                tax_ratio=0.0,
                recycling_rate_per_hour=0.0,
                mean_tax_s=0.0,
                severity=SEVERITY_NO_DATA,
                exit_code=EXIT_NO_DATA,
            )

        total_tax = sum(e.tax for e in in_window)
        tax_ratio = min(total_tax / window_s, 1.0)
        hours = window_s / 3600.0
        rate = n / hours if hours > 0 else 0.0
        mean_tax = total_tax / n
        severity, exit_code = classify(tax_ratio)

        return TaxReport(
            window_start=window_start,
            window_end=window_end,
            event_count=n,
            total_tax_s=total_tax,
            window_s=window_s,
            tax_ratio=tax_ratio,
            recycling_rate_per_hour=rate,
            mean_tax_s=mean_tax,
            severity=severity,
            exit_code=exit_code,
        )

    def clear(self) -> None:
        """Drop all recorded events."""
        self._events.clear()
