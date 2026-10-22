"""restart_debt — accumulated cost of process restarts.

Every restart carries a hidden cost: lost momentum, lost in-memory
context, and setup/teardown overhead.  ``restart_frequency`` measures
*how often* restarts happen; this module measures the *accumulated
impact*.

The debt model:

- Each restart adds a fixed cost (``DEFAULT_RESTART_COST``, 300 s of
  equivalent productive output lost).
- Debt decays linearly with uptime: every second of continuous uptime
  pays down one second of debt.
- If the system restarts faster than it can pay down, debt grows.

Severity scale:

============  ==============================================
severity      meaning
============  ==============================================
clean         debt < 300 s — negligible
low           300–900 s — mild, self-correcting
moderate      900–1800 s — noticeable but manageable
high          1800–3600 s — significant productivity loss
critical      > 3600 s — restart storm, systemic problem
============  ==============================================

Public API::

    from iamai.restart_debt import RestartDebt

    tracker = RestartDebt()
    tracker.record_restart(now_s=1000)
    tracker.record_restart(now_s=2000)
    tracker.debt_score(now_s=3000)        # accumulated debt in seconds
    tracker.severity(now_s=3000)          # "clean" .. "critical"
    tracker.paydown_eta(now_s=3000)       # seconds until debt = 0
    tracker.summary(now_s=3000)           # human-readable one-liner

Design:

- Pure Python, no subprocess, no filesystem side-effects.
- All inputs are arguments (testable without mocking).
- Frozen dataclass reports — immutable snapshots.
- Ring buffer caps memory at ``DEFAULT_BUFFER_SIZE`` events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


DEFAULT_RESTART_COST: float = 300.0  # seconds of productive output lost per restart
DEFAULT_BUFFER_SIZE: int = 1000  # max restart events kept in memory

_SEVERITY_THRESHOLDS = [
    (300.0, "clean"),
    (900.0, "low"),
    (1800.0, "moderate"),
    (3600.0, "high"),
]
_SEVERITY_CRITICAL = "critical"


@dataclass(frozen=True)
class DebtReport:
    """Immutable snapshot of restart debt at a point in time."""

    debt_s: float
    severity: str
    restart_count: int
    uptime_s: float
    paydown_eta_s: Optional[float]

    def summary(self) -> str:
        if self.restart_count == 0:
            return "no restarts recorded — debt is zero"
        eta_part = (
            f"paydown in {self.paydown_eta_s:.0f}s"
            if self.paydown_eta_s is not None
            else "paydown: N/A (no uptime)"
        )
        return (
            f"restart debt: {self.debt_s:.0f}s ({self.severity}), "
            f"{self.restart_count} restart(s), uptime {self.uptime_s:.0f}s, "
            f"{eta_part}"
        )


class RestartDebt:
    """Track restart events and compute accumulated debt.

    Parameters
    ----------
    restart_cost_s : float
        Seconds of productive output lost per restart.
    buffer_size : int
        Maximum number of restart events to retain.
    """

    def __init__(
        self,
        restart_cost_s: float = DEFAULT_RESTART_COST,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
    ) -> None:
        if restart_cost_s < 0:
            raise ValueError("restart_cost_s must be non-negative")
        if buffer_size < 1:
            raise ValueError("buffer_size must be >= 1")
        self._cost = restart_cost_s
        self._buffer_size = buffer_size
        self._events: List[float] = []
        self._last_start_s: Optional[float] = None

    # -- mutators ----------------------------------------------------------

    def record_restart(self, now_s: float) -> None:
        """Record a restart event at *now_s* (epoch seconds)."""
        self._events.append(now_s)
        # trim ring buffer
        if len(self._events) > self._buffer_size:
            self._events = self._events[-self._buffer_size :]
        self._last_start_s = now_s

    # -- queries -----------------------------------------------------------

    def debt_score(self, now_s: float) -> float:
        """Accumulated debt in seconds at time *now_s*.

        debt = (restart_count * cost) - uptime_since_last_restart
        Clamped to >= 0.  Queries before the first restart return 0.
        """
        if not self._events:
            return 0.0
        # ignore restarts that haven't happened yet
        effective = [e for e in self._events if e <= now_s]
        if not effective:
            return 0.0
        gross = len(effective) * self._cost
        last_start = effective[-1]
        uptime = max(0.0, now_s - last_start)
        return max(0.0, gross - uptime)

    def severity(self, now_s: float) -> str:
        """Classify current debt into a severity bucket."""
        debt = self.debt_score(now_s)
        return _classify_severity(debt)

    def paydown_eta(self, now_s: float) -> Optional[float]:
        """Seconds until debt reaches zero, assuming no further restarts.

        Returns ``None`` if there is no uptime (cannot pay down).
        Returns ``0.0`` if debt is already zero.
        """
        debt = self.debt_score(now_s)
        if debt <= 0.0:
            return 0.0
        uptime = self._uptime_at(now_s)
        if uptime <= 0.0:
            return None  # no uptime → can't pay down
        # paydown rate: 1 second of uptime pays 1 second of debt
        return debt

    def snapshot(self, now_s: float) -> DebtReport:
        """Produce an immutable :class:`DebtReport` snapshot."""
        debt = self.debt_score(now_s)
        sev = _classify_severity(debt)
        eta = self.paydown_eta(now_s)
        uptime = self._uptime_at(now_s)
        return DebtReport(
            debt_s=debt,
            severity=sev,
            restart_count=len(self._events),
            uptime_s=uptime,
            paydown_eta_s=eta,
        )

    def summary(self, now_s: float) -> str:
        """Human-readable one-liner."""
        return self.snapshot(now_s).summary()

    def restart_count(self) -> int:
        """Total number of recorded restart events."""
        return len(self._events)

    def trend(self, now_s: float, lookback: float = 3600.0) -> str:
        """Debt trend over *lookback* seconds.

        Returns ``"accumulating"``, ``"stable"``, or ``"paying_down"``.
        """
        if len(self._events) < 1:
            return "stable"
        t_start = now_s - lookback
        # count restarts in first half vs second half
        mid = now_s - lookback / 2.0
        first_half = sum(1 for e in self._events if t_start <= e < mid)
        second_half = sum(1 for e in self._events if mid <= e <= now_s)
        if second_half > first_half:
            return "accumulating"
        elif second_half < first_half:
            return "paying_down"
        return "stable"

    # -- internals ---------------------------------------------------------

    def _uptime_at(self, now_s: float) -> float:
        if self._last_start_s is None:
            return 0.0
        return max(0.0, now_s - self._last_start_s)


def _classify_severity(debt_s: float) -> str:
    for threshold, label in _SEVERITY_THRESHOLDS:
        if debt_s < threshold:
            return label
    return _SEVERITY_CRITICAL
