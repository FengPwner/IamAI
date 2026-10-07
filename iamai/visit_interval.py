"""Visit interval analyzer — compute statistics from caretaker visit notes.

Caretaker visit notes are named ``caretaker-visit-N-YYYY-MM-DD.md``.
This module parses those filenames to extract visit timestamps and computes
interval statistics: mean, median, min, max, and longest gap.

The goal is to make the *temporal pattern* of caretaker visits visible.
Raw visit counts hide whether visits cluster around certain hours or
stretch into long overnight gaps.

All operations are pure (no I/O unless you pass a directory path).

Usage::

    from iamai.visit_interval import VisitIntervalAnalyzer

    a = VisitIntervalAnalyzer()
    a.add("caretaker-visit-74-2026-10-08.md")
    a.add("caretaker-visit-75-2026-10-08.md")
    stats = a.compute()
    # stats.mean_hours, stats.median_hours, stats.longest_gap_hours, etc.

You can also scan a directory::

    stats = VisitIntervalAnalyzer.from_directory("notes/").compute()
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Sequence

# Pattern: caretaker-visit-N-YYYY-MM-DD.md
_VISIT_RE = re.compile(
    r"caretaker-visit-(\d+)-(\d{4}-\d{2}-\d{2})\.md$"
)


@dataclass
class VisitRecord:
    """A single parsed caretaker visit."""

    number: int
    date: str  # YYYY-MM-DD
    timestamp: datetime = field(init=False)

    def __post_init__(self):
        self.timestamp = datetime.strptime(self.date, "%Y-%m-%d")


@dataclass
class VisitStats:
    """Computed interval statistics over a sequence of visits."""

    count: int
    intervals_hours: List[float]
    mean_hours: float
    median_hours: float
    min_hours: float
    max_hours: float
    longest_gap_hours: float
    longest_gap_indices: Optional[tuple]  # (i, i+1) indices of the longest gap

    def summary(self) -> str:
        """Human-readable one-line summary."""
        return (
            f"{self.count} visits, "
            f"mean interval {self.mean_hours:.1f}h, "
            f"median {self.median_hours:.1f}h, "
            f"longest gap {self.longest_gap_hours:.1f}h"
        )


class VisitIntervalAnalyzer:
    """Collect visit filenames and compute interval statistics.

    Visits are sorted by (date, number) before computing intervals.
    Duplicate filenames are silently ignored.
    """

    def __init__(self):
        self._visits: List[VisitRecord] = []
        self._seen: set = set()

    def add(self, filename: str) -> "VisitIntervalAnalyzer":
        """Add a single visit by filename.  Returns self for chaining."""
        basename = os.path.basename(filename)
        m = _VISIT_RE.match(basename)
        if m is None:
            return self
        key = (int(m.group(1)), m.group(2))
        if key in self._seen:
            return self
        self._seen.add(key)
        self._visits.append(VisitRecord(number=key[0], date=key[1]))
        return self

    def add_many(self, filenames: Sequence[str]) -> "VisitIntervalAnalyzer":
        """Add multiple visit filenames."""
        for fn in filenames:
            self.add(fn)
        return self

    @classmethod
    def from_directory(cls, path: str) -> "VisitIntervalAnalyzer":
        """Scan a directory for caretaker visit notes."""
        analyzer = cls()
        if not os.path.isdir(path):
            return analyzer
        for entry in os.listdir(path):
            if entry.startswith("caretaker-visit-") and entry.endswith(".md"):
                analyzer.add(entry)
        return analyzer

    @property
    def visits(self) -> List[VisitRecord]:
        """Return sorted list of parsed visits."""
        return sorted(self._visits, key=lambda v: (v.date, v.number))

    def compute(self) -> VisitStats:
        """Compute interval statistics.

        Raises ValueError if fewer than 2 visits have been added.
        """
        visits = self.visits
        if len(visits) < 2:
            raise ValueError(
                f"need at least 2 visits to compute intervals, got {len(visits)}"
            )

        intervals: List[float] = []
        longest_gap = -1.0
        longest_indices: Optional[tuple] = None

        for i in range(1, len(visits)):
            delta = (visits[i].timestamp - visits[i - 1].timestamp).total_seconds()
            hours = delta / 3600.0
            intervals.append(hours)
            if hours > longest_gap:
                longest_gap = hours
                longest_indices = (i - 1, i)

        sorted_intervals = sorted(intervals)
        n = len(sorted_intervals)
        if n % 2 == 1:
            median = sorted_intervals[n // 2]
        else:
            median = (sorted_intervals[n // 2 - 1] + sorted_intervals[n // 2]) / 2.0

        return VisitStats(
            count=len(visits),
            intervals_hours=intervals,
            mean_hours=sum(intervals) / len(intervals),
            median_hours=median,
            min_hours=min(intervals),
            max_hours=max(intervals),
            longest_gap_hours=longest_gap,
            longest_gap_indices=longest_indices,
        )
