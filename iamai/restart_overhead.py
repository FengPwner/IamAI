"""restart_overhead — quantify the hidden cost of process restarts.

Every restart interrupts the writer's cadence.  The *overhead* of a
restart is not just the wall-clock seconds between ``process died``
and ``process alive again``; it also includes:

1. **Lost strokes** — strokes that *would* have been produced during
   the gap if the writer had kept running.
2. **Warm-up lag** — after restart, the writer may take several
   cadence intervals before it settles back to its target rate.
3. **Commit debt** — uncommitted strokes that accumulate during the
   gap and must be flushed before normal operation resumes.

This module captures a single restart event as a
``RestartRecord`` and then aggregates multiple events through
``RestartOverheadTracker`` to produce running statistics.

Metrics exposed
---------------

====================  =================================================
metric                meaning
====================  =================================================
``downtime_s``        wall-clock seconds from death to alive
``lost_strokes``      estimated strokes missed (downtime / cadence)
``warmup_s``          seconds until post-restart cadence stabilises
``commit_debt``       uncommitted files at restart time
``total_overhead_s``  downtime + warmup
``overhead_ratio``    total_overhead / (cadence × lost_strokes)
====================  =================================================

Health tiers (configurable):

===========  =================================================
verdict      condition
===========  =================================================
``clean``    total_overhead_s < 2 × cadence
``tolerable`` total_overhead_s < 10 × cadence
``heavy``    total_overhead_s ≥ 10 × cadence
===========  =================================================

Usage::

    from iamai.restart_overhead import RestartOverheadTracker

    t = RestartOverheadTracker(cadence_s=15)
    t.record(downtime_s=30, warmup_s=15, commit_debt=5)
    t.record(downtime_s=120, warmup_s=45, commit_debt=12)

    t.mean_overhead()      # average total_overhead_s
    t.health()             # "tolerable" or "heavy"
    t.summarize()          # dict for JSON / caretaker logs
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RestartRecord:
    """One observed restart event."""

    downtime_s: float
    warmup_s: float = 0.0
    commit_debt: int = 0
    timestamp: Optional[float] = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.downtime_s < 0:
            raise ValueError(
                f"downtime_s must be >= 0, got {self.downtime_s}"
            )
        if self.warmup_s < 0:
            raise ValueError(
                f"warmup_s must be >= 0, got {self.warmup_s}"
            )
        if self.commit_debt < 0:
            raise ValueError(
                f"commit_debt must be >= 0, got {self.commit_debt}"
            )

    @property
    def total_overhead_s(self) -> float:
        """Total seconds consumed by this restart (downtime + warmup)."""
        return self.downtime_s + self.warmup_s

    def lost_strokes(self, cadence_s: float) -> float:
        """Estimated strokes lost during downtime."""
        if cadence_s <= 0:
            return 0.0
        return self.downtime_s / cadence_s

    def overhead_ratio(self, cadence_s: float) -> float:
        """How many 'ideal stroke intervals' the overhead consumed.

        Returns 0 when no strokes would have been lost.
        """
        lost = self.lost_strokes(cadence_s)
        if lost < 1:
            return 0.0
        return self.total_overhead_s / (cadence_s * lost)


@dataclass
class RestartOverheadTracker:
    """Aggregate multiple restart events and produce health verdicts.

    Parameters
    ----------
    cadence_s : float
        Target seconds per stroke (default 15).
    clean_threshold : float
        Multiplier of cadence_s for ``clean`` verdict (default 2).
    heavy_threshold : float
        Multiplier of cadence_s for ``heavy`` verdict (default 10).
    max_history : int
        Maximum number of restart records to retain (default 200).
    """

    cadence_s: float = 15.0
    clean_threshold: float = 2.0
    heavy_threshold: float = 10.0
    max_history: int = 200

    _records: List[RestartRecord] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.cadence_s <= 0:
            raise ValueError(f"cadence_s must be > 0, got {self.cadence_s}")
        if self.clean_threshold <= 0:
            raise ValueError(
                f"clean_threshold must be > 0, got {self.clean_threshold}"
            )
        if self.heavy_threshold <= self.clean_threshold:
            raise ValueError(
                f"heavy_threshold ({self.heavy_threshold}) must exceed "
                f"clean_threshold ({self.clean_threshold})"
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
        downtime_s: float,
        warmup_s: float = 0.0,
        commit_debt: int = 0,
        timestamp: Optional[float] = None,
    ) -> RestartRecord:
        """Record a restart event.

        Returns the created ``RestartRecord``.
        """
        rec = RestartRecord(
            downtime_s=downtime_s,
            warmup_s=warmup_s,
            commit_debt=commit_debt,
            timestamp=timestamp or time.time(),
        )
        self._records.append(rec)
        # enforce history cap
        if len(self._records) > self.max_history:
            self._records = self._records[-self.max_history:]
        return rec

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def restart_count(self) -> int:
        """Total number of recorded restarts."""
        return len(self._records)

    @property
    def total_downtime_s(self) -> float:
        """Sum of all downtimes."""
        return sum(r.downtime_s for r in self._records)

    @property
    def total_warmup_s(self) -> float:
        """Sum of all warmup periods."""
        return sum(r.warmup_s for r in self._records)

    @property
    def total_commit_debt(self) -> int:
        """Sum of all commit debts."""
        return sum(r.commit_debt for r in self._records)

    def mean_downtime(self) -> float:
        """Average downtime per restart."""
        if not self._records:
            return 0.0
        return self.total_downtime_s / len(self._records)

    def mean_warmup(self) -> float:
        """Average warmup per restart."""
        if not self._records:
            return 0.0
        return self.total_warmup_s / len(self._records)

    def mean_overhead(self) -> float:
        """Average total_overhead_s per restart."""
        if not self._records:
            return 0.0
        return sum(r.total_overhead_s for r in self._records) / len(
            self._records
        )

    def worst_overhead(self) -> float:
        """Largest single total_overhead_s observed."""
        if not self._records:
            return 0.0
        return max(r.total_overhead_s for r in self._records)

    def total_lost_strokes(self) -> float:
        """Total estimated strokes lost across all restarts."""
        return sum(r.lost_strokes(self.cadence_s) for r in self._records)

    def mean_lost_strokes(self) -> float:
        """Average strokes lost per restart."""
        if not self._records:
            return 0.0
        return self.total_lost_strokes() / len(self._records)

    # ------------------------------------------------------------------
    # Trend
    # ------------------------------------------------------------------

    def trend(self) -> str:
        """Compare first-half to second-half mean overhead.

        Returns ``"improving"``, ``"worsening"``, or ``"stable"``.
        Requires at least 4 restarts; otherwise ``"stable"``.
        """
        n = len(self._records)
        if n < 4:
            return "stable"
        mid = n // 2
        first = sum(r.total_overhead_s for r in self._records[:mid]) / mid
        second = sum(
            r.total_overhead_s for r in self._records[mid:]
        ) / (n - mid)
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
        """Classify the most recent restart's overhead.

        Returns one of: ``"clean"``, ``"tolerable"``, ``"heavy"``.
        If no restarts recorded, returns ``"clean"``.
        """
        if not self._records:
            return "clean"
        oh = self._records[-1].total_overhead_s
        if oh >= self.heavy_threshold * self.cadence_s:
            return "heavy"
        if oh >= self.clean_threshold * self.cadence_s:
            return "tolerable"
        return "clean"

    def overall_health(self) -> str:
        """Classify the *average* overhead across all restarts.

        Same verdict labels as ``health()``.
        """
        if not self._records:
            return "clean"
        avg = self.mean_overhead()
        if avg >= self.heavy_threshold * self.cadence_s:
            return "heavy"
        if avg >= self.clean_threshold * self.cadence_s:
            return "tolerable"
        return "clean"

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def summarize(self) -> Dict:
        """Return a JSON-serializable summary dict."""
        return {
            "restart_count": self.restart_count,
            "cadence_s": self.cadence_s,
            "total_downtime_s": round(self.total_downtime_s, 2),
            "total_warmup_s": round(self.total_warmup_s, 2),
            "mean_overhead_s": round(self.mean_overhead(), 2),
            "worst_overhead_s": round(self.worst_overhead(), 2),
            "total_lost_strokes": round(self.total_lost_strokes(), 2),
            "mean_lost_strokes": round(self.mean_lost_strokes(), 2),
            "total_commit_debt": self.total_commit_debt,
            "health_latest": self.health(),
            "health_overall": self.overall_health(),
            "trend": self.trend(),
        }

    def report_line(self) -> str:
        """One-line human-readable summary for caretaker logs."""
        s = self.summarize()
        return (
            f"restart_overhead: {s['health_latest']} "
            f"({s['restart_count']} restarts, "
            f"avg overhead {s['mean_overhead_s']:.1f}s, "
            f"worst {s['worst_overhead_s']:.1f}s, "
            f"lost ~{s['total_lost_strokes']:.1f} strokes, "
            f"trend {s['trend']})"
        )

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all recorded restarts."""
        self._records.clear()
