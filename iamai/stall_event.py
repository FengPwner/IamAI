"""Stall event — record and classify writer stall episodes.

A *stall* is any inter-stroke gap that exceeds a configurable multiple
of the target cadence.  ``cadence_adherence`` counts how many there
are; ``restart_overhead`` measures process-level downtime.  Neither
captures the full lifecycle of a single stall: when it started, how
long it lasted, whether the writer recovered on its own or needed a
restart, and how quickly it returned to normal cadence afterwards.

This module fills that gap.  Each ``StallEvent`` captures one episode.
``StallTracker`` aggregates events and produces health verdicts.

Severity tiers (configurable):

============  ===================================================
severity      condition
============  ===================================================
``minor``     gap < 4 × cadence
``moderate``  gap < 10 × cadence
``severe``    gap ≥ 10 × cadence
============  ===================================================

Recovery modes:

==============  =================================================
mode            meaning
==============  =================================================
``self``        writer resumed on its own (no restart)
``restart``     a process restart ended the stall
``ongoing``     stall has not ended yet
==============  =================================================

Usage::

    from iamai.stall_event import StallEvent, StallTracker

    t = StallTracker(cadence_s=15)
    t.record(gap_s=120, recovery="self", recovery_s=30)
    t.record(gap_s=600, recovery="restart", recovery_s=45)

    t.severity_counts()       # {"minor": 0, "moderate": 1, "severe": 1}
    t.mean_gap()           # 360.0
    t.self_recovery_pct()  # 50.0
    t.report_line()        # one-liner for caretaker logs
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ------------------------------------------------------------------
# StallEvent
# ------------------------------------------------------------------


@dataclass
class StallEvent:
    """One observed stall episode.

    Parameters
    ----------
    gap_s : float
        Duration of the stall in seconds (time between the last
        stroke before the stall and the first stroke after recovery,
        or time elapsed so far if ongoing).
    recovery : str
        How the stall ended: ``"self"``, ``"restart"``, or
        ``"ongoing"``.
    recovery_s : float
        Seconds from the end of the stall gap until the writer
        resumed its normal cadence.  0 for ongoing stalls.
    commit_debt : int
        Number of uncommitted files at stall detection time.
    timestamp : float or None
        Unix timestamp when the stall was detected.
    """

    gap_s: float
    recovery: str = "ongoing"
    recovery_s: float = 0.0
    commit_debt: int = 0
    timestamp: Optional[float] = field(default_factory=time.time)

    _VALID_RECOVERY = {"self", "restart", "ongoing"}

    def __post_init__(self) -> None:
        if self.gap_s < 0:
            raise ValueError(f"gap_s must be >= 0, got {self.gap_s}")
        if self.recovery_s < 0:
            raise ValueError(
                f"recovery_s must be >= 0, got {self.recovery_s}"
            )
        if self.commit_debt < 0:
            raise ValueError(
                f"commit_debt must be >= 0, got {self.commit_debt}"
            )
        if self.recovery not in self._VALID_RECOVERY:
            raise ValueError(
                f"recovery must be one of {self._VALID_RECOVERY}, "
                f"got {self.recovery!r}"
            )

    @property
    def total_impact_s(self) -> float:
        """Total seconds impacted: gap + recovery lag."""
        return self.gap_s + self.recovery_s

    def severity(self, cadence_s: float) -> str:
        """Classify severity relative to cadence.

        Returns ``"minor"``, ``"moderate"``, or ``"severe"``.
        """
        if cadence_s <= 0:
            return "minor"
        ratio = self.gap_s / cadence_s
        if ratio >= 10:
            return "severe"
        if ratio >= 4:
            return "moderate"
        return "minor"

    def lost_strokes(self, cadence_s: float) -> float:
        """Estimated strokes lost during the gap."""
        if cadence_s <= 0:
            return 0.0
        return self.gap_s / cadence_s

    def is_ongoing(self) -> bool:
        """Whether the stall has not yet resolved."""
        return self.recovery == "ongoing"


# ------------------------------------------------------------------
# StallTracker
# ------------------------------------------------------------------


@dataclass
class StallTracker:
    """Aggregate stall events and produce health reports.

    Parameters
    ----------
    cadence_s : float
        Target seconds per stroke (default 15).
    minor_threshold : float
        Multiplier of cadence_s for ``minor`` → ``moderate`` boundary.
    severe_threshold : float
        Multiplier of cadence_s for ``moderate`` → ``severe`` boundary.
    max_history : int
        Maximum number of stall events to retain.
    """

    cadence_s: float = 15.0
    minor_threshold: float = 4.0
    severe_threshold: float = 10.0
    max_history: int = 500

    _events: List[StallEvent] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.cadence_s <= 0:
            raise ValueError(
                f"cadence_s must be > 0, got {self.cadence_s}"
            )
        if self.minor_threshold <= 0:
            raise ValueError(
                f"minor_threshold must be > 0, got {self.minor_threshold}"
            )
        if self.severe_threshold <= self.minor_threshold:
            raise ValueError(
                f"severe_threshold ({self.severe_threshold}) must exceed "
                f"minor_threshold ({self.minor_threshold})"
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
        gap_s: float,
        recovery: str = "ongoing",
        recovery_s: float = 0.0,
        commit_debt: int = 0,
        timestamp: Optional[float] = None,
    ) -> StallEvent:
        """Record a stall event.  Returns the created ``StallEvent``."""
        ev = StallEvent(
            gap_s=gap_s,
            recovery=recovery,
            recovery_s=recovery_s,
            commit_debt=commit_debt,
            timestamp=timestamp or time.time(),
        )
        self._events.append(ev)
        if len(self._events) > self.max_history:
            self._events = self._events[-self.max_history:]
        return ev

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def event_count(self) -> int:
        """Total number of recorded stall events."""
        return len(self._events)

    @property
    def ongoing_count(self) -> int:
        """Number of currently unresolved stalls."""
        return sum(1 for e in self._events if e.is_ongoing())

    @property
    def resolved_count(self) -> int:
        """Number of resolved stalls."""
        return self.event_count - self.ongoing_count

    @property
    def total_gap_s(self) -> float:
        """Sum of all gap durations."""
        return sum(e.gap_s for e in self._events)

    @property
    def total_recovery_s(self) -> float:
        """Sum of all recovery durations."""
        return sum(e.recovery_s for e in self._events)

    @property
    def total_impact_s(self) -> float:
        """Sum of all total impacts (gap + recovery)."""
        return sum(e.total_impact_s for e in self._events)

    @property
    def total_commit_debt(self) -> int:
        """Sum of commit debts at detection time."""
        return sum(e.commit_debt for e in self._events)

    def mean_gap(self) -> float:
        """Average gap duration."""
        if not self._events:
            return 0.0
        return self.total_gap_s / len(self._events)

    def mean_recovery_s(self) -> float:
        """Average recovery time (resolved events only)."""
        resolved = [e for e in self._events if not e.is_ongoing()]
        if not resolved:
            return 0.0
        return sum(e.recovery_s for e in resolved) / len(resolved)

    def mean_impact(self) -> float:
        """Average total impact per event."""
        if not self._events:
            return 0.0
        return self.total_impact_s / len(self._events)

    def worst_gap(self) -> float:
        """Largest single gap observed."""
        if not self._events:
            return 0.0
        return max(e.gap_s for e in self._events)

    def total_lost_strokes(self) -> float:
        """Total estimated strokes lost across all stalls."""
        return sum(e.lost_strokes(self.cadence_s) for e in self._events)

    # ------------------------------------------------------------------
    # Severity
    # ------------------------------------------------------------------

    def severity_counts(self) -> Dict[str, int]:
        """Count events by severity tier."""
        counts: Dict[str, int] = {"minor": 0, "moderate": 0, "severe": 0}
        for ev in self._events:
            sev = ev.severity(self.cadence_s)
            counts[sev] = counts.get(sev, 0) + 1
        return counts

    def dominant_severity(self) -> str:
        """The severity tier with the most events.

        Ties broken: severe > moderate > minor.
        """
        counts = self.severity_counts()
        if not self._events:
            return "minor"
        if counts["severe"] >= counts["moderate"] and counts["severe"] >= counts["minor"]:
            return "severe"
        if counts["moderate"] >= counts["minor"]:
            return "moderate"
        return "minor"

    # ------------------------------------------------------------------
    # Recovery analysis
    # ------------------------------------------------------------------

    def self_recovery_pct(self) -> float:
        """Percentage of resolved stalls that recovered without restart."""
        resolved = [e for e in self._events if not e.is_ongoing()]
        if not resolved:
            return 0.0
        self_count = sum(1 for e in resolved if e.recovery == "self")
        return (self_count / len(resolved)) * 100.0

    def restart_recovery_pct(self) -> float:
        """Percentage of resolved stalls that required a restart."""
        resolved = [e for e in self._events if not e.is_ongoing()]
        if not resolved:
            return 0.0
        restart_count = sum(
            1 for e in resolved if e.recovery == "restart"
        )
        return (restart_count / len(resolved)) * 100.0

    def mean_self_recovery_s(self) -> float:
        """Average recovery time for self-recovered stalls."""
        self_events = [
            e for e in self._events if e.recovery == "self"
        ]
        if not self_events:
            return 0.0
        return sum(e.recovery_s for e in self_events) / len(self_events)

    def mean_restart_recovery_s(self) -> float:
        """Average recovery time for restart-recovered stalls."""
        restart_events = [
            e for e in self._events if e.recovery == "restart"
        ]
        if not restart_events:
            return 0.0
        return sum(e.recovery_s for e in restart_events) / len(
            restart_events
        )

    # ------------------------------------------------------------------
    # Trend
    # ------------------------------------------------------------------

    def trend(self) -> str:
        """Compare first-half to second-half mean gap.

        Returns ``"improving"``, ``"worsening"``, or ``"stable"``.
        Requires at least 4 events; otherwise ``"stable"``.
        """
        n = len(self._events)
        if n < 4:
            return "stable"
        mid = n // 2
        first = sum(e.gap_s for e in self._events[:mid]) / mid
        second = sum(e.gap_s for e in self._events[mid:]) / (n - mid)
        delta = second - first
        if delta > self.cadence_s:
            return "worsening"
        if delta < -self.cadence_s:
            return "improving"
        return "stable"

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> str:
        """Classify overall stall health.

        Returns one of: ``"clean"``, ``"degraded"``, ``"critical"``.

        - ``clean``: no severe stalls, mean gap < 4 × cadence
        - ``degraded``: some moderate stalls, mean gap < 10 × cadence
        - ``critical``: severe stalls present or mean gap ≥ 10 × cadence
        """
        if not self._events:
            return "clean"
        counts = self.severity_counts()
        mg = self.mean_gap()
        if counts["severe"] > 0 or mg >= self.severe_threshold * self.cadence_s:
            return "critical"
        if counts["moderate"] > 0 or mg >= self.minor_threshold * self.cadence_s:
            return "degraded"
        return "clean"

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def summarize(self) -> Dict:
        """Return a JSON-serializable summary dict."""
        return {
            "event_count": self.event_count,
            "ongoing": self.ongoing_count,
            "cadence_s": self.cadence_s,
            "total_gap_s": round(self.total_gap_s, 2),
            "total_recovery_s": round(self.total_recovery_s, 2),
            "total_impact_s": round(self.total_impact_s, 2),
            "mean_gap_s": round(self.mean_gap(), 2),
            "worst_gap_s": round(self.worst_gap(), 2),
            "mean_impact_s": round(self.mean_impact(), 2),
            "total_lost_strokes": round(self.total_lost_strokes(), 2),
            "total_commit_debt": self.total_commit_debt,
            "severity_counts": self.severity_counts(),
            "dominant_severity": self.dominant_severity(),
            "self_recovery_pct": round(self.self_recovery_pct(), 1),
            "restart_recovery_pct": round(self.restart_recovery_pct(), 1),
            "mean_self_recovery_s": round(self.mean_self_recovery_s(), 2),
            "mean_restart_recovery_s": round(
                self.mean_restart_recovery_s(), 2
            ),
            "health": self.health(),
            "trend": self.trend(),
        }

    def report_line(self) -> str:
        """One-line human-readable summary for caretaker logs."""
        s = self.summarize()
        return (
            f"stall_events: {s['health']} "
            f"({s['event_count']} events, "
            f"{s['ongoing']} ongoing, "
            f"mean gap {s['mean_gap_s']:.1f}s, "
            f"worst {s['worst_gap_s']:.1f}s, "
            f"lost ~{s['total_lost_strokes']:.1f} strokes, "
            f"self-recovery {s['self_recovery_pct']:.0f}%, "
            f"trend {s['trend']})"
        )

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all recorded events."""
        self._events.clear()
