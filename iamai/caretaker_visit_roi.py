"""caretaker_visit_roi — measure what each caretaker visit actually delivers.

Every caretaker visit costs something: the human's attention, the agent's
context window, the disruption to whatever else was happening.  Some visits
produce lasting value (new modules, cleared backlogs, fixed bugs).  Others
are pure maintenance (restart a stalled process, rescue an SSH key) and the
same problem recurs an hour later.  This module quantifies the difference.

Core concepts
=============

**visit_yield**: a bundle of concrete outputs from one visit — commits
pushed, modules added, tests written, backlogs cleared.

**visit_cost**: a proxy for effort.  Defaults to 1.0 (one visit unit);
callers can weight by wall-clock minutes or complexity score.

**roi_ratio**: ``visit_yield.score / visit_cost``.  Higher is better.
A visit that pushes 3 commits and adds a module with tests scores much
higher than one that merely restarts a process.

**visit_kind**: classification of the visit's primary purpose:
``recovery`` (restart/rescue), ``feature`` (new module or capability),
``maintenance`` (cleanup, rebase, lock clearing), or ``observation``
(status check only, no changes).

Public API::

    from iamai.caretaker_visit_roi import (
        CaretakerVisitROI,
        VisitYield,
        VisitRecord,
        roi_report,
    )

    tracker = CaretakerVisitROI()

    tracker.record(VisitRecord(
        visit_id=560,
        kind="feature",
        commits_pushed=2,
        modules_added=1,
        tests_added=25,
        backlog_cleared=0,
        cost=1.0,
    ))

    tracker.record(VisitRecord(
        visit_id=561,
        kind="recovery",
        commits_pushed=1,
        modules_added=0,
        tests_added=0,
        backlog_cleared=5,
        cost=1.0,
    ))

    print(tracker.mean_roi)          # 3.5
    print(tracker.best_kind)         # "feature"
    print(tracker.maintenance_ratio) # 0.5 — half the visits are firefighting

    print(roi_report(tracker))
    # "2 visits, mean ROI 3.50, best kind: feature, maintenance ratio: 50%"

Yield scoring
=============

Each output type carries a default weight reflecting its lasting value:

============  ======  ===========================================
output        weight  rationale
============  ======  ===========================================
commit        1.0     work delivered to remote
module        3.0     new capability added to the codebase
test          0.5     quality insurance for existing code
backlog_item  0.5     debt reduced
note          0.2     documentation / observability
============  ======  ===========================================

Weights are configurable at construction time.

Visit kinds and expected ROI
=============================

==========  =========================================================
kind        typical ROI range
==========  =========================================================
feature     3.0–8.0 — high yield, lasting value
recovery    1.0–3.0 — necessary but often temporary
maintenance 0.5–2.0 — keeps things running, low new value
observation 0.0–0.5 — useful signal, no direct output
==========  =========================================================

Notes
-----
- A visit that restarts a process *and* adds a module should be
  classified as ``feature`` (the higher-value activity dominates).
- ``roi_ratio`` of 0.0 is valid (pure observation visits).
- The module does not judge — it measures.  A maintenance_ratio of
  1.0 is not "bad" if the alternative is a permanently stalled repo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


# --- constants ---

DEFAULT_WEIGHTS: Dict[str, float] = {
    "commit": 1.0,
    "module": 3.0,
    "test": 0.5,
    "backlog_item": 0.5,
    "note": 0.2,
}

VALID_KINDS = frozenset({"recovery", "feature", "maintenance", "observation"})


# --- data classes ---


@dataclass(frozen=True)
class VisitYield:
    """Scored output from a single caretaker visit.

    The ``score`` property computes the weighted sum of all outputs.
    """

    commits_pushed: int = 0
    modules_added: int = 0
    tests_added: int = 0
    backlog_cleared: int = 0
    notes_written: int = 0

    @property
    def score(self) -> float:
        """Weighted yield score using default weights."""
        return self.score_with(DEFAULT_WEIGHTS)

    def score_with(self, weights: Dict[str, float]) -> float:
        """Weighted yield score with custom weights."""
        return (
            self.commits_pushed * weights.get("commit", 1.0)
            + self.modules_added * weights.get("module", 3.0)
            + self.tests_added * weights.get("test", 0.5)
            + self.backlog_cleared * weights.get("backlog_item", 0.5)
            + self.notes_written * weights.get("note", 0.2)
        )

    @property
    def total_outputs(self) -> int:
        """Raw count of all output items, unweighted."""
        return (
            self.commits_pushed
            + self.modules_added
            + self.tests_added
            + self.backlog_cleared
            + self.notes_written
        )

    @property
    def is_empty(self) -> bool:
        """True if the visit produced nothing measurable."""
        return self.total_outputs == 0


@dataclass(frozen=True)
class VisitRecord:
    """One caretaker visit with its classification and outputs.

    ``visit_id`` is the sequential visit number (matches the note filename).
    ``kind`` must be one of: recovery, feature, maintenance, observation.
    ``cost`` defaults to 1.0; use higher values for complex multi-step visits.
    """

    visit_id: int
    kind: str = "maintenance"
    commits_pushed: int = 0
    modules_added: int = 0
    tests_added: int = 0
    backlog_cleared: int = 0
    notes_written: int = 0
    cost: float = 1.0
    timestamp: Optional[float] = None

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValueError(
                f"kind must be one of {sorted(VALID_KINDS)}, got {self.kind!r}"
            )
        if self.cost <= 0:
            raise ValueError(f"cost must be positive, got {self.cost}")

    @property
    def yield_(self) -> VisitYield:
        """Extract the VisitYield from this record."""
        return VisitYield(
            commits_pushed=self.commits_pushed,
            modules_added=self.modules_added,
            tests_added=self.tests_added,
            backlog_cleared=self.backlog_cleared,
            notes_written=self.notes_written,
        )

    @property
    def roi_ratio(self) -> float:
        """Return on investment: yield score / cost."""
        return self.yield_.score / self.cost


# --- tracker ---


class CaretakerVisitROI:
    """Accumulate visit records and compute aggregate ROI metrics.

    Parameters
    ----------
    weights : dict, optional
        Custom weights for yield scoring.  Keys: commit, module, test,
        backlog_item, note.  Missing keys fall back to defaults.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None) -> None:
        self._weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        self._records: List[VisitRecord] = []

    def record(self, visit: VisitRecord) -> None:
        """Add a visit record to the tracker."""
        self._records.append(visit)

    def record_many(self, visits: Sequence[VisitRecord]) -> None:
        """Add multiple visit records at once."""
        self._records.extend(visits)

    @property
    def records(self) -> Tuple[VisitRecord, ...]:
        """All recorded visits in insertion order."""
        return tuple(self._records)

    @property
    def count(self) -> int:
        """Total number of recorded visits."""
        return len(self._records)

    # --- aggregate metrics ---

    @property
    def mean_roi(self) -> float:
        """Mean ROI ratio across all visits.  0.0 if no visits."""
        if not self._records:
            return 0.0
        return sum(v.roi_ratio for v in self._records) / len(self._records)

    @property
    def median_roi(self) -> float:
        """Median ROI ratio.  0.0 if no visits."""
        if not self._records:
            return 0.0
        ratios = sorted(v.roi_ratio for v in self._records)
        n = len(ratios)
        mid = n // 2
        if n % 2 == 0:
            return (ratios[mid - 1] + ratios[mid]) / 2.0
        return ratios[mid]

    @property
    def max_roi(self) -> float:
        """Highest single-visit ROI.  0.0 if no visits."""
        if not self._records:
            return 0.0
        return max(v.roi_ratio for v in self._records)

    @property
    def total_yield_score(self) -> float:
        """Sum of all yield scores across all visits."""
        return sum(v.yield_.score_with(self._weights) for v in self._records)

    @property
    def total_cost(self) -> float:
        """Sum of all visit costs."""
        return sum(v.cost for v in self._records)

    @property
    def overall_roi(self) -> float:
        """Total yield / total cost.  0.0 if no cost."""
        if self.total_cost == 0:
            return 0.0
        return self.total_yield_score / self.total_cost

    # --- kind breakdown ---

    @property
    def kind_counts(self) -> Dict[str, int]:
        """Count of visits per kind."""
        counts: Dict[str, int] = {}
        for v in self._records:
            counts[v.kind] = counts.get(v.kind, 0) + 1
        return counts

    @property
    def kind_mean_roi(self) -> Dict[str, float]:
        """Mean ROI per visit kind."""
        buckets: Dict[str, List[float]] = {}
        for v in self._records:
            buckets.setdefault(v.kind, []).append(v.roi_ratio)
        return {
            kind: sum(ratios) / len(ratios)
            for kind, ratios in buckets.items()
        }

    @property
    def best_kind(self) -> Optional[str]:
        """Visit kind with the highest mean ROI.  None if no visits."""
        means = self.kind_mean_roi
        if not means:
            return None
        return max(means, key=means.get)

    @property
    def worst_kind(self) -> Optional[str]:
        """Visit kind with the lowest mean ROI.  None if no visits."""
        means = self.kind_mean_roi
        if not means:
            return None
        return min(means, key=means.get)

    @property
    def maintenance_ratio(self) -> float:
        """Fraction of visits classified as recovery or maintenance.

        1.0 means every visit is firefighting; 0.0 means every visit
        adds new value.
        """
        if not self._records:
            return 0.0
        maint_count = sum(
            1 for v in self._records if v.kind in ("recovery", "maintenance")
        )
        return maint_count / len(self._records)

    @property
    def feature_ratio(self) -> float:
        """Fraction of visits classified as feature additions."""
        if not self._records:
            return 0.0
        feat_count = sum(1 for v in self._records if v.kind == "feature")
        return feat_count / len(self._records)

    @property
    def empty_visit_ratio(self) -> float:
        """Fraction of visits that produced nothing measurable."""
        if not self._records:
            return 0.0
        empty = sum(1 for v in self._records if v.yield_.is_empty)
        return empty / len(self._records)

    # --- trend ---

    @property
    def roi_trend(self) -> float:
        """OLS slope of ROI over visit sequence.

        Positive = visits getting more productive over time.
        Negative = diminishing returns.
        0.0 = flat or fewer than 2 visits.
        """
        if len(self._records) < 2:
            return 0.0
        n = len(self._records)
        xs = list(range(n))
        ys = [v.roi_ratio for v in self._records]
        x_mean = sum(xs) / n
        y_mean = sum(ys) / n
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        denominator = sum((x - x_mean) ** 2 for x in xs)
        if denominator == 0:
            return 0.0
        return numerator / denominator

    @property
    def trend_label(self) -> str:
        """Human-readable trend label."""
        slope = self.roi_trend
        if slope > 0.05:
            return "improving"
        elif slope < -0.05:
            return "declining"
        return "stable"

    # --- health grade ---

    @property
    def health_grade(self) -> str:
        """Overall visit program health.

        ==========  ========================================================
        grade       meaning
        ==========  ========================================================
        productive  mean ROI ≥ 3.0 and maintenance_ratio < 0.5
        healthy     mean ROI ≥ 2.0 and maintenance_ratio < 0.7
        surviving   mean ROI ≥ 1.0 — visits happen but mostly firefighting
        struggling  mean ROI < 1.0 — visits cost more than they produce
        idle        no visits recorded
        ==========  ========================================================
        """
        if not self._records:
            return "idle"
        roi = self.mean_roi
        maint = self.maintenance_ratio
        if roi >= 3.0 and maint < 0.5:
            return "productive"
        if roi >= 2.0 and maint < 0.7:
            return "healthy"
        if roi >= 1.0:
            return "surviving"
        return "struggling"


# --- convenience functions ---


def roi_report(tracker: CaretakerVisitROI) -> str:
    """One-line human-readable summary of visit ROI."""
    if tracker.count == 0:
        return "no visits recorded"
    return (
        f"{tracker.count} visits, "
        f"mean ROI {tracker.mean_roi:.2f}, "
        f"best kind: {tracker.best_kind}, "
        f"maintenance ratio: {tracker.maintenance_ratio:.0%}, "
        f"trend: {tracker.trend_label}"
    )


def visit_scorecard(visit: VisitRecord) -> str:
    """One-line scorecard for a single visit."""
    y = visit.yield_
    parts = []
    if y.commits_pushed:
        parts.append(f"{y.commits_pushed} commits")
    if y.modules_added:
        parts.append(f"{y.modules_added} modules")
    if y.tests_added:
        parts.append(f"{y.tests_added} tests")
    if y.backlog_cleared:
        parts.append(f"{y.backlog_cleared} backlog items")
    if y.notes_written:
        parts.append(f"{y.notes_written} notes")
    output_str = ", ".join(parts) if parts else "no output"
    return (
        f"visit {visit.visit_id} ({visit.kind}): "
        f"yield {y.score:.1f}, cost {visit.cost:.1f}, "
        f"ROI {visit.roi_ratio:.2f} — {output_str}"
    )
