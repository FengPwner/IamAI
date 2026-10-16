"""gap_budget — track cumulative timing drift against cadence.

While ``stroke_gap_classifier`` labels *individual* gaps and
``cadence_adherence`` measures per-stroke compliance, neither answers
the macro question: *how much time has the writer lost in total?*

Every gap that exceeds the cadence creates a **deficit** (the excess
seconds beyond what the cadence allows).  Every gap that falls short
creates a **surplus**.  The running balance is the *gap budget*.

A healthy writer hovers near zero.  A writer that stalls frequently
accumulates a large deficit — even if each individual stall was
recovered and cadence resumed.  The budget captures the *cumulative
cost* of instability.

Metrics exposed
---------------

==================  =================================================
metric              meaning
==================  =================================================
``total_deficit``   sum of all positive excesses (seconds lost)
``total_surplus``   sum of all negative excesses (seconds gained)
``net_drift``       total_deficit − total_surplus
``drift_rate``      net_drift / elapsed observation time (s/s)
``worst_gap``       largest single deficit observed
``budget_health``   "healthy" | "strained" | "exhausted"
==================  =================================================

Health tiers (configurable thresholds):

===========  ================================================
verdict      condition
===========  ================================================
``healthy``  net_drift < deficit_warn  (default 300 s)
``strained`` net_drift < deficit_crit  (default 900 s)
``exhausted`` net_drift ≥ deficit_crit
===========  ================================================

Usage::

    from iamai.gap_budget import GapBudget

    gb = GapBudget(cadence_s=15)
    gb.record(16)    # 1 s deficit
    gb.record(14)    # 1 s surplus → net back to 0
    gb.record(300)   # 285 s deficit
    gb.health()      # "strained"
    gb.summarize()   # dict suitable for JSON / caretaker logs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time


@dataclass
class GapBudget:
    """Accumulate gap timing and compute cumulative drift metrics."""

    cadence_s: float = 15.0
    deficit_warn: float = 300.0
    deficit_crit: float = 900.0

    # Internal state
    _deficits: List[float] = field(default_factory=list, repr=False)
    _surpluses: List[float] = field(default_factory=list, repr=False)
    _first_recorded: Optional[float] = field(default=None, repr=False)
    _last_recorded: Optional[float] = field(default=None, repr=False)
    _count: int = 0

    def __post_init__(self) -> None:
        if self.cadence_s <= 0:
            raise ValueError(f"cadence_s must be > 0, got {self.cadence_s}")
        if self.deficit_warn <= 0:
            raise ValueError(f"deficit_warn must be > 0, got {self.deficit_warn}")
        if self.deficit_crit <= self.deficit_warn:
            raise ValueError(
                f"deficit_crit ({self.deficit_crit}) must exceed "
                f"deficit_warn ({self.deficit_warn})"
            )

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, gap_s: float) -> None:
        """Record an observed inter-stroke gap.

        Args:
            gap_s: observed gap in seconds (must be >= 0).

        Raises:
            ValueError: if gap_s < 0.
        """
        if gap_s < 0:
            raise ValueError(f"gap_s must be >= 0, got {gap_s}")

        now = time.monotonic()
        if self._first_recorded is None:
            self._first_recorded = now
        self._last_recorded = now
        self._count += 1

        excess = gap_s - self.cadence_s
        if excess >= 0:
            self._deficits.append(excess)
        else:
            self._surpluses.append(abs(excess))

    def record_many(self, gaps: List[float]) -> None:
        """Convenience: record a sequence of gaps."""
        for g in gaps:
            self.record(g)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def total_deficit(self) -> float:
        """Sum of all positive excesses (seconds lost beyond cadence)."""
        return sum(self._deficits)

    @property
    def total_surplus(self) -> float:
        """Sum of all negative excesses (seconds gained vs cadence)."""
        return sum(self._surpluses)

    @property
    def net_drift(self) -> float:
        """Net cumulative drift: deficit − surplus.

        Positive means the writer has lost time overall.
        Negative means it has run slightly faster than cadence on average.
        """
        return self.total_deficit - self.total_surplus

    @property
    def worst_gap(self) -> float:
        """Largest single deficit observed (0 if no deficits)."""
        return max(self._deficits) if self._deficits else 0.0

    @property
    def deficit_count(self) -> int:
        """Number of gaps that exceeded cadence."""
        return len(self._deficits)

    @property
    def surplus_count(self) -> int:
        """Number of gaps that fell short of cadence."""
        return len(self._surpluses)

    @property
    def drift_rate(self) -> float:
        """Net drift per second of observation time.

        Returns 0.0 if fewer than two observations or observation
        window is too short (< 1 s).
        """
        if self._first_recorded is None or self._last_recorded is None:
            return 0.0
        elapsed = self._last_recorded - self._first_recorded
        if elapsed < 1.0:
            return 0.0
        return self.net_drift / elapsed

    @property
    def mean_deficit(self) -> float:
        """Average deficit magnitude (0 if none recorded)."""
        if not self._deficits:
            return 0.0
        return self.total_deficit / len(self._deficits)

    @property
    def mean_surplus(self) -> float:
        """Average surplus magnitude (0 if none recorded)."""
        if not self._surpluses:
            return 0.0
        return self.total_surplus / len(self._surpluses)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> str:
        """Classify cumulative drift into a health tier.

        Returns:
            One of: "healthy", "strained", "exhausted".
        """
        nd = abs(self.net_drift)
        if nd >= self.deficit_crit:
            return "exhausted"
        if nd >= self.deficit_warn:
            return "strained"
        return "healthy"

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def summarize(self) -> Dict:
        """Return a JSON-serializable summary dict."""
        return {
            "count": self._count,
            "cadence_s": self.cadence_s,
            "total_deficit": round(self.total_deficit, 2),
            "total_surplus": round(self.total_surplus, 2),
            "net_drift": round(self.net_drift, 2),
            "worst_gap": round(self.worst_gap, 2),
            "mean_deficit": round(self.mean_deficit, 2),
            "mean_surplus": round(self.mean_surplus, 2),
            "drift_rate": round(self.drift_rate, 4),
            "deficit_count": self.deficit_count,
            "surplus_count": self.surplus_count,
            "health": self.health(),
        }

    def report_line(self) -> str:
        """One-line human-readable summary for caretaker logs."""
        s = self.summarize()
        return (
            f"gap_budget: {s['health']} — "
            f"net_drift {s['net_drift']:.1f}s "
            f"(deficit {s['total_deficit']:.1f}s / "
            f"surplus {s['total_surplus']:.1f}s) "
            f"over {s['count']} gaps, "
            f"worst {s['worst_gap']:.1f}s, "
            f"rate {s['drift_rate']:.3f} s/s"
        )

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all accumulated state."""
        self._deficits.clear()
        self._surpluses.clear()
        self._first_recorded = None
        self._last_recorded = None
        self._count = 0
