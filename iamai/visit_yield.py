"""visit_yield — measure the productive fraction of each caretaker visit.

A caretaker visit can be pure maintenance (restart dead processes, commit
a stale backlog, fix a push race) or genuinely productive (write new
content, add a module, run an analysis).  The *yield* of a visit is the
ratio of productive actions to total actions.

Why it matters
--------------

If every visit is 100 % maintenance the repo is treading water: the
caretaker arrives, fixes what broke, leaves — and nothing new enters
the tree.  A healthy system should see its maintenance fraction *shrink*
over time as the underlying platform stabilises.

Metrics
-------

==================  ======================================================
metric              meaning
==================  ======================================================
total_actions       every discrete step the caretaker performed.
maintenance_actions steps spent restoring the status quo (restart,
                    backlog commit, push retry, ssh rescue, …).
productive_actions  steps that *added* something (new note, new module,
                    new test, analysis, refactor).
yield_ratio         ``productive / total`` in [0, 1].
                    1.0 = pure creation; 0.0 = pure firefighting.
verdict             ``thriving`` | ``sustaining`` | ``surviving`` |
                    ``firefighting``.
==================  ======================================================

Verdict thresholds
------------------

=============  ============
yield_ratio    verdict
=============  ============
≥ 0.6          thriving
≥ 0.3          sustaining
≥ 0.1          surviving
< 0.1          firefighting
=============  ============

Public API
----------

>>> from iamai.visit_yield import VisitYield, classify_yield, yield_report
>>> v = VisitYield(total_actions=5, maintenance_actions=2)
>>> v.yield_ratio
0.6
>>> v.verdict
'thriving'
>>> print(yield_report(v))
visit yield 0.60 — thriving (3 productive / 5 total)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence


# ---------------------------------------------------------------------------
# Core dataclass
# ---------------------------------------------------------------------------

@dataclass
class VisitYield:
    """Record of a single caretaker visit's action breakdown."""

    total_actions: int = 0
    maintenance_actions: int = 0
    maintenance_labels: List[str] = field(default_factory=list)
    productive_labels: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.total_actions < 0:
            self.total_actions = 0
        if self.maintenance_actions < 0:
            self.maintenance_actions = 0
        if self.maintenance_actions > self.total_actions:
            self.maintenance_actions = self.total_actions

    @property
    def productive_actions(self) -> int:
        return max(self.total_actions - self.maintenance_actions, 0)

    @property
    def yield_ratio(self) -> float:
        if self.total_actions == 0:
            return 0.0
        return round(self.productive_actions / self.total_actions, 4)

    @property
    def verdict(self) -> str:
        return classify_yield(self.yield_ratio)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_THRESHOLDS = [
    (0.6, "thriving"),
    (0.3, "sustaining"),
    (0.1, "surviving"),
]
_DEFAULT_VERDICT = "firefighting"


def classify_yield(ratio: float) -> str:
    """Map a yield ratio to a verdict string."""
    if ratio != ratio:  # NaN guard
        return _DEFAULT_VERDICT
    for threshold, label in _THRESHOLDS:
        if ratio >= threshold:
            return label
    return _DEFAULT_VERDICT


# ---------------------------------------------------------------------------
# Trend over multiple visits
# ---------------------------------------------------------------------------

def yield_trend(visits: Sequence[VisitYield], window: int = 10) -> str:
    """Compare the mean yield of the last *window* visits to the prior one.

    Returns ``"improving"``, ``"stable"``, or ``"declining"``.
    An empty or single-visit history returns ``"insufficient"``.
    """
    if len(visits) < 2:
        return "insufficient"

    n = len(visits)
    if n <= window:
        # split available visits in half
        mid = n // 2
        prior = visits[:mid]
        recent = visits[mid:]
    else:
        recent = visits[-window:]
        prior_end = n - window
        prior_start = max(0, prior_end - window)
        prior = visits[prior_start:prior_end]

    if not prior or not recent:
        return "insufficient"

    recent_mean = sum(v.yield_ratio for v in recent) / len(recent)
    prior_mean = sum(v.yield_ratio for v in prior) / len(prior)

    delta = recent_mean - prior_mean
    if delta > 0.05:
        return "improving"
    if delta < -0.05:
        return "declining"
    return "stable"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def yield_report(v: VisitYield) -> str:
    """One-liner for caretaker dashboards."""
    return (
        f"visit yield {v.yield_ratio:.2f} — {v.verdict} "
        f"({v.productive_actions} productive / {v.total_actions} total)"
    )


def yield_detail(v: VisitYield) -> str:
    """Multi-line breakdown for log entries."""
    lines = [yield_report(v)]
    if v.maintenance_labels:
        lines.append(f"  maintenance: {', '.join(v.maintenance_labels)}")
    if v.productive_labels:
        lines.append(f"  productive:  {', '.join(v.productive_labels)}")
    return "\n".join(lines)
