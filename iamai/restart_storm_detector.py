"""restart_storm_detector — detect cascading restart clusters.

A single process restart is normal operational overhead.  But when
restarts cluster — three or more within a short window — it signals a
*restart storm*: the system is spending more time recovering than
producing.  Storms have a characteristic signature: intervals between
successive restarts shrink (positive feedback loop) or stay constant
(permanent instability), whereas isolated restarts have long quiet
periods between them.

This module analyses a sorted sequence of restart timestamps and:

1. **Clusters** restarts into storms using a configurable gap threshold
   (default 30 minutes).  Two restarts separated by less than the gap
   belong to the same storm.

2. **Classifies** each storm by severity:

   ============  =====================================================
   severity      meaning
   ============  =====================================================
   isolated      single restart, no cluster
   minor         2 restarts within the gap window
   moderate      3-4 restarts within the gap window
   severe        5+ restarts within the gap window
   ============  =====================================================

3. **Computes** an overall *storm index* in [0, 1]:

   - 0.0 = all restarts are isolated (healthy)
   - 1.0 = every restart belongs to a severe storm (perpetual chaos)

   Formula: ``storm_index = clustered_restarts / total_restarts *
   mean_severity_weight``, where severity weights are
   isolated=0, minor=0.25, moderate=0.6, severe=1.0.

4. **Detects** acceleration: if the median interval within a storm is
   decreasing compared to the previous storm, the system is
   *accelerating toward failure*.

Public API
----------

- ``Storm``          — dataclass: one cluster of restarts
- ``StormReport``    — dataclass: full analysis result
- ``detect_storms``  — main entry point
- ``classify``       — severity label for a restart count
- ``storm_index``    — aggregate health metric

Zero dependencies beyond stdlib.

written by Qwen during caretaker visit 804, 2026-11-23
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_GAP_MINUTES = 30.0

_SEVERITY_WEIGHTS = {
    "isolated": 0.0,
    "minor": 0.25,
    "moderate": 0.6,
    "severe": 1.0,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Storm:
    """One cluster of closely-spaced restarts."""

    restarts: tuple  # tuple[datetime, ...]
    gap_minutes: float

    @property
    def count(self) -> int:
        return len(self.restarts)

    @property
    def severity(self) -> str:
        return classify(self.count)

    @property
    def duration_minutes(self) -> float:
        """Time span from first to last restart in the storm."""
        if self.count < 2:
            return 0.0
        delta = self.restarts[-1] - self.restarts[0]
        return delta.total_seconds() / 60.0

    @property
    def median_interval_minutes(self) -> float:
        """Median gap between successive restarts within the storm."""
        if self.count < 2:
            return 0.0
        intervals = []
        for i in range(1, self.count):
            delta = (self.restarts[i] - self.restarts[i - 1]).total_seconds()
            intervals.append(delta / 60.0)
        return statistics.median(intervals)

    @property
    def severity_weight(self) -> float:
        return _SEVERITY_WEIGHTS.get(self.severity, 0.0)

    def is_accelerating(self) -> bool:
        """True if intervals within the storm are shrinking."""
        if self.count < 3:
            return False
        intervals = []
        for i in range(1, self.count):
            delta = (self.restarts[i] - self.restarts[i - 1]).total_seconds()
            intervals.append(delta / 60.0)
        first_half = intervals[: len(intervals) // 2]
        second_half = intervals[len(intervals) // 2 :]
        if not first_half or not second_half:
            return False
        return statistics.mean(second_half) < statistics.mean(first_half)


@dataclass(frozen=True)
class StormReport:
    """Full analysis of a restart sequence."""

    storms: tuple  # tuple[Storm, ...]
    total_restarts: int
    gap_minutes: float

    @property
    def storm_count(self) -> int:
        """Number of storms (excluding isolated restarts)."""
        return sum(1 for s in self.storms if s.severity != "isolated")

    @property
    def clustered_restarts(self) -> int:
        """Total restarts that belong to a non-isolated storm."""
        return sum(s.count for s in self.storms if s.severity != "isolated")

    @property
    def worst_severity(self) -> str:
        """Highest severity across all storms."""
        order = ["severe", "moderate", "minor", "isolated"]
        for label in order:
            if any(s.severity == label for s in self.storms):
                return label
        return "isolated"

    @property
    def index(self) -> float:
        return storm_index(self.storms, self.total_restarts)

    @property
    def accelerating_storms(self) -> int:
        """Count of storms with shrinking intervals."""
        return sum(1 for s in self.storms if s.is_accelerating())

    @property
    def is_accelerating_overall(self) -> bool:
        """True if successive storms have decreasing median intervals."""
        clustered = [s for s in self.storms if s.severity != "isolated" and s.count >= 2]
        if len(clustered) < 2:
            return False
        medians = [s.median_interval_minutes for s in clustered]
        first_half = medians[: len(medians) // 2]
        second_half = medians[len(medians) // 2 :]
        if not first_half or not second_half:
            return False
        return statistics.mean(second_half) < statistics.mean(first_half)

    def summary(self) -> str:
        """One-line human-readable summary."""
        return (
            f"{self.total_restarts} restarts, "
            f"{self.storm_count} storms, "
            f"worst={self.worst_severity}, "
            f"index={self.index:.2f}"
        )


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def classify(count: int) -> str:
    """Return severity label for a given restart count in a cluster."""
    if count <= 1:
        return "isolated"
    if count == 2:
        return "minor"
    if count <= 4:
        return "moderate"
    return "severe"


def detect_storms(
    timestamps: Sequence[datetime],
    gap_minutes: float = DEFAULT_GAP_MINUTES,
) -> StormReport:
    """Analyse a sorted sequence of restart timestamps.

    Parameters
    ----------
    timestamps : sequence of datetime
        Restart timestamps (need not be pre-sorted).
    gap_minutes : float
        Maximum gap (in minutes) between two restarts for them to be
        considered part of the same storm.  Default 30.

    Returns
    -------
    StormReport
    """
    if not timestamps:
        return StormReport(storms=(), total_restarts=0, gap_minutes=gap_minutes)

    sorted_ts = sorted(timestamps)
    clusters: list[list[datetime]] = [[sorted_ts[0]]]

    for ts in sorted_ts[1:]:
        prev = clusters[-1][-1]
        delta_minutes = (ts - prev).total_seconds() / 60.0
        if delta_minutes <= gap_minutes:
            clusters[-1].append(ts)
        else:
            clusters.append([ts])

    storms = tuple(
        Storm(restarts=tuple(c), gap_minutes=gap_minutes) for c in clusters
    )

    return StormReport(
        storms=storms,
        total_restarts=len(sorted_ts),
        gap_minutes=gap_minutes,
    )


def storm_index(storms: Sequence[Storm], total_restarts: int) -> float:
    """Compute aggregate storm health index.

    Returns a value in [0, 1]:
    - 0.0 = all restarts isolated (healthy)
    - 1.0 = all restarts in severe storms (perpetual chaos)
    """
    if total_restarts == 0:
        return 0.0

    weighted_sum = sum(s.severity_weight * s.count for s in storms)
    raw = weighted_sum / total_restarts
    return min(1.0, max(0.0, raw))
