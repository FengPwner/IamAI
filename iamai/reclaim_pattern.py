"""Reclaim pattern — detect periodicity in process death events.

When processes keep dying at roughly regular intervals, the interval
itself is the most useful diagnostic clue.  ``process_mortality``
records individual events; this module reads that ledger and answers:

1. **What is the typical gap between deaths?**  (median, mean, mode)
2. **Is the pattern periodic?**  (low variance in gaps → periodic)
3. **What is the estimated cycle length?**  (best-fit period)
4. **Is the cycle stable, shortening, or lengthening?**  (trend)

A cycle is classified as:

* **periodic** — coefficient of variation (σ/μ) of gaps < 0.15.
  Deaths happen like clockwork; look for a cron job or resource limit.
* **quasi-periodic** — CV in [0.15, 0.35).
  Roughly regular but with jitter; could be a soft limit or contention.
* **irregular** — CV ≥ 0.35.
  No clear pattern; likely external factors (OOM killer, network).

Usage::

    from iamai.reclaim_pattern import ReclaimAnalyzer

    analyzer = ReclaimAnalyzer()
    analyzer.load_events(death_timestamps)  # list of epoch seconds
    report = analyzer.report()
    print(report["pattern"])        # "periodic" | "quasi-periodic" | "irregular"
    print(report["cycle_minutes"])  # e.g. 60.2
    print(report["trend"])          # "stable" | "shortening" | "lengthening"

The analyzer works purely on a list of timestamps — no git, no file
I/O, no subprocess.  Feed it whatever death-event timestamps you have.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ReclaimAnalyzer:
    """Detect periodicity in a series of process death timestamps."""

    timestamps: List[float] = field(default_factory=list)
    _gaps: List[float] = field(default_factory=list, repr=False)

    # ---- data ingestion ----

    def load_events(self, ts: List[float]) -> None:
        """Load a sorted list of death-event timestamps (epoch seconds).

        Duplicates are silently dropped; the list is sorted internally.
        """
        self.timestamps = sorted(set(ts))
        self._gaps = []
        for i in range(1, len(self.timestamps)):
            gap = self.timestamps[i] - self.timestamps[i - 1]
            if gap > 0:
                self._gaps.append(gap)

    def add_event(self, ts: float) -> None:
        """Append a single death timestamp and recompute gaps."""
        if ts not in self.timestamps:
            self.timestamps.append(ts)
            self.timestamps.sort()
            self._rebuild_gaps()

    def _rebuild_gaps(self) -> None:
        self._gaps = []
        for i in range(1, len(self.timestamps)):
            gap = self.timestamps[i] - self.timestamps[i - 1]
            if gap > 0:
                self._gaps.append(gap)

    # ---- core metrics ----

    @property
    def event_count(self) -> int:
        """Number of death events loaded."""
        return len(self.timestamps)

    @property
    def gap_count(self) -> int:
        """Number of inter-death gaps."""
        return len(self._gaps)

    def gaps(self) -> List[float]:
        """Return a copy of the inter-death gaps in seconds."""
        return list(self._gaps)

    def gaps_minutes(self) -> List[float]:
        """Return gaps converted to minutes."""
        return [g / 60.0 for g in self._gaps]

    def mean_gap(self) -> float:
        """Mean inter-death gap in seconds.  0.0 if fewer than 2 events."""
        if not self._gaps:
            return 0.0
        return statistics.mean(self._gaps)

    def median_gap(self) -> float:
        """Median inter-death gap in seconds."""
        if not self._gaps:
            return 0.0
        return statistics.median(self._gaps)

    def stdev_gap(self) -> float:
        """Standard deviation of gaps.  0.0 if fewer than 2 gaps."""
        if len(self._gaps) < 2:
            return 0.0
        return statistics.stdev(self._gaps)

    def coefficient_of_variation(self) -> float:
        """CV = σ/μ.  Returns 0.0 if mean is zero or insufficient data."""
        mu = self.mean_gap()
        if mu <= 0 or len(self._gaps) < 2:
            return 0.0
        return self.stdev_gap() / mu

    # ---- pattern classification ----

    def classify_pattern(
        self,
        periodic_threshold: float = 0.15,
        quasi_threshold: float = 0.35,
    ) -> str:
        """Classify the death pattern.

        Returns one of: ``"periodic"``, ``"quasi-periodic"``, ``"irregular"``,
        or ``"insufficient_data"`` if fewer than 3 events (2 gaps).
        """
        if len(self._gaps) < 2:
            return "insufficient_data"
        cv = self.coefficient_of_variation()
        if cv < periodic_threshold:
            return "periodic"
        if cv < quasi_threshold:
            return "quasi-periodic"
        return "irregular"

    # ---- trend detection ----

    def trend(self, window: int = 4) -> str:
        """Detect whether the cycle is stable, shortening, or lengthening.

        Compares the mean of the last ``window`` gaps to the mean of all
        gaps.  A difference of more than 10% triggers a trend label.

        Returns ``"stable"``, ``"shortening"``, ``"lengthening"``, or
        ``"insufficient_data"`` if fewer than ``window`` gaps exist.
        """
        if len(self._gaps) < window:
            return "insufficient_data"
        overall = self.mean_gap()
        recent = statistics.mean(self._gaps[-window:])
        if overall <= 0:
            return "stable"
        ratio = recent / overall
        if ratio < 0.90:
            return "shortening"
        if ratio > 1.10:
            return "lengthening"
        return "stable"

    # ---- best-fit cycle ----

    def cycle_seconds(self) -> float:
        """Best estimate of the cycle length in seconds.

        Uses the median gap (more robust to outliers than the mean).
        Returns 0.0 if insufficient data.
        """
        if len(self._gaps) < 1:
            return 0.0
        return self.median_gap()

    def cycle_minutes(self) -> float:
        """Best estimate of the cycle length in minutes."""
        return self.cycle_seconds() / 60.0

    # ---- outlier detection ----

    def outliers(self, factor: float = 2.0) -> List[int]:
        """Return indices of gaps that are ``factor`` × the median or more.

        Useful for spotting anomalous intervals (e.g. a 6-hour gap in
        an otherwise hourly pattern).
        """
        if not self._gaps:
            return []
        med = self.median_gap()
        if med <= 0:
            return []
        threshold = med * factor
        return [i for i, g in enumerate(self._gaps) if g >= threshold]

    # ---- summary report ----

    def report(
        self,
        periodic_threshold: float = 0.15,
        quasi_threshold: float = 0.35,
        trend_window: int = 4,
    ) -> dict:
        """Produce a summary dict with all key metrics.

        Keys:
            event_count, gap_count, mean_gap_s, median_gap_s, stdev_gap_s,
            cv, pattern, cycle_seconds, cycle_minutes, trend, outlier_indices
        """
        return {
            "event_count": self.event_count,
            "gap_count": self.gap_count,
            "mean_gap_s": round(self.mean_gap(), 2),
            "median_gap_s": round(self.median_gap(), 2),
            "stdev_gap_s": round(self.stdev_gap(), 2),
            "cv": round(self.coefficient_of_variation(), 4),
            "pattern": self.classify_pattern(periodic_threshold, quasi_threshold),
            "cycle_seconds": round(self.cycle_seconds(), 2),
            "cycle_minutes": round(self.cycle_minutes(), 2),
            "trend": self.trend(trend_window),
            "outlier_indices": self.outliers(),
        }


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def analyze_deaths(
    timestamps: List[float],
    **kwargs,
) -> dict:
    """One-shot helper: pass timestamps, get a report dict."""
    analyzer = ReclaimAnalyzer()
    analyzer.load_events(timestamps)
    return analyzer.report(**kwargs)


def is_periodic(
    timestamps: List[float],
    threshold: float = 0.15,
) -> bool:
    """Quick check: are these death events periodic?"""
    analyzer = ReclaimAnalyzer()
    analyzer.load_events(timestamps)
    return analyzer.classify_pattern(periodic_threshold=threshold) == "periodic"


def cycle_estimate(timestamps: List[float]) -> float:
    """Return the estimated cycle length in seconds (median gap)."""
    analyzer = ReclaimAnalyzer()
    analyzer.load_events(timestamps)
    return analyzer.cycle_seconds()
