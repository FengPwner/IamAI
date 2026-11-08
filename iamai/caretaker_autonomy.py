"""caretaker_autonomy — measure how self-sufficient the system is.

A self-writing repo should need its caretaker less over time.  This
module answers one question: *how long can the system run before
something breaks that only a caretaker visit can fix?*

The answer is an **autonomy score** from 0.0 to 1.0:

- **1.0**: the caretaker never had to intervene; every visit found
  processes healthy, no backlog, push current.
- **0.5**: half the caretaker's time is spent fixing things rather
  than observing.
- **0.0**: every visit required intervention; the system cannot
  sustain itself without constant babysitting.

Public API::

    from iamai.caretaker_autonomy import AutonomyTracker, autonomy_report

    tracker = AutonomyTracker()
    tracker.record_visit(visit_time, intervened=True, actions=["restart", "backlog_commit"])
    tracker.record_visit(visit_time, intervened=False, actions=[])

    score = tracker.autonomy_score()
    # 0.73

    mtbi = tracker.mean_time_between_interventions()
    # 3600.0  (seconds)

    print(autonomy_report(tracker))
    # "autonomy 0.73, mtbi 3600s, 4 interventions in 12 visits — self-sustaining"

Autonomy grades
---------------

===========  ============================================================
grade        meaning
===========  ============================================================
autonomous   score ≥ 0.8 — system runs itself, caretaker just watches
stable       0.6 ≤ score < 0.8 — occasional intervention, mostly routine
dependent    0.4 ≤ score < 0.6 — regular intervention needed
fragile      0.2 ≤ score < 0.4 — caretaker spends more time fixing than watching
critical     score < 0.2 — system cannot sustain itself
===========  ============================================================

The module also tracks **intervention types** so caretakers can see
*what* keeps breaking: restarts, backlog commits, push fixes, or
content corrections.  A shift from restart interventions to push-fix
interventions is progress — the writer is stable but the network
layer needs work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence


# Autonomy grade thresholds
_GRADES = [
    (0.8, "autonomous"),
    (0.6, "stable"),
    (0.4, "dependent"),
    (0.2, "fragile"),
    (0.0, "critical"),
]

# Known intervention action types
KNOWN_ACTIONS = frozenset([
    "restart",
    "backlog_commit",
    "push_fix",
    "content_correction",
    "lock_cleanup",
    "rebase_recovery",
    "process_check",
])


@dataclass(frozen=True)
class Visit:
    """A single caretaker visit record."""

    timestamp: float           # unix epoch seconds
    intervened: bool           # did the caretaker have to fix something?
    actions: tuple             # what actions were taken (sorted, deduplicated)

    @property
    def action_count(self) -> int:
        return len(self.actions)

    @property
    def is_routine(self) -> bool:
        return not self.intervened and self.action_count == 0


@dataclass
class AutonomyTracker:
    """Track caretaker visits and compute autonomy metrics.

    Visits should be recorded in chronological order.  The tracker
    does not sort them — it trusts the caller.
    """

    visits: List[Visit] = field(default_factory=list)

    def record_visit(
        self,
        timestamp: float,
        intervened: bool = False,
        actions: Optional[Sequence[str]] = None,
    ) -> Visit:
        """Record a caretaker visit.

        Parameters
        ----------
        timestamp : float
            Unix epoch seconds when the visit occurred.
        intervened : bool
            True if the caretaker had to take corrective action.
        actions : sequence of str, optional
            Actions taken during the visit.  Known actions are
            validated; unknown actions are accepted as-is.

        Returns
        -------
        Visit
            The recorded visit.
        """
        if actions is None:
            actions = []
        # Deduplicate and sort for consistency
        clean_actions = tuple(sorted(set(actions)))
        visit = Visit(
            timestamp=timestamp,
            intervened=intervened,
            actions=clean_actions,
        )
        self.visits.append(visit)
        return visit

    @property
    def total_visits(self) -> int:
        return len(self.visits)

    @property
    def intervention_visits(self) -> int:
        return sum(1 for v in self.visits if v.intervened)

    @property
    def routine_visits(self) -> int:
        return sum(1 for v in self.visits if v.is_routine)

    def autonomy_score(self) -> float:
        """Compute the autonomy score.

        Returns the fraction of visits that were routine (no
        intervention needed).  Returns 1.0 if there are no visits
        (vacuously autonomous).

        The score is weighted: recent interventions count more than
        old ones.  Each visit's weight decays exponentially with
        age relative to the most recent visit, with a half-life
        equal to the median inter-visit interval.
        """
        if not self.visits:
            return 1.0

        if len(self.visits) == 1:
            return 0.0 if self.visits[0].intervened else 1.0

        # Compute inter-visit intervals for half-life estimation
        intervals = []
        for i in range(1, len(self.visits)):
            dt = self.visits[i].timestamp - self.visits[i - 1].timestamp
            if dt > 0:
                intervals.append(dt)

        if not intervals:
            # All visits at the same timestamp — use simple ratio
            return self.routine_visits / self.total_visits

        # Median interval as half-life
        sorted_intervals = sorted(intervals)
        half_life = sorted_intervals[len(sorted_intervals) // 2]
        if half_life <= 0:
            half_life = 1.0

        # Exponential decay weighting: newer visits weigh more
        latest = self.visits[-1].timestamp
        total_weight = 0.0
        routine_weight = 0.0

        for v in self.visits:
            age = latest - v.timestamp
            weight = 0.5 ** (age / half_life)
            total_weight += weight
            if not v.intervened:
                routine_weight += weight

        if total_weight == 0:
            return 1.0

        return routine_weight / total_weight

    def mean_time_between_interventions(self) -> float:
        """Mean time (seconds) between intervention visits.

        Returns 0.0 if fewer than two interventions have occurred.
        """
        intervention_times = [v.timestamp for v in self.visits if v.intervened]
        if len(intervention_times) < 2:
            return 0.0

        gaps = []
        for i in range(1, len(intervention_times)):
            gaps.append(intervention_times[i] - intervention_times[i - 1])

        return sum(gaps) / len(gaps)

    def intervention_breakdown(self) -> Dict[str, int]:
        """Count how often each action type appears across visits.

        Returns a dictionary mapping action names to their occurrence
        count.  Only visits with interventions are considered.
        """
        counts: Dict[str, int] = {}
        for v in self.visits:
            if not v.intervened:
                continue
            for action in v.actions:
                counts[action] = counts.get(action, 0) + 1
        return counts

    def autonomy_grade(self) -> str:
        """Return the autonomy grade label.

        See module docstring for grade definitions.
        """
        score = self.autonomy_score()
        for threshold, grade in _GRADES:
            if score >= threshold:
                return grade
        return "critical"

    def longest_streak_without_intervention(self) -> int:
        """Return the longest consecutive streak of routine visits.

        This measures the system's best sustained run without needing
        any caretaker help.
        """
        best = 0
        current = 0
        for v in self.visits:
            if v.intervened:
                best = max(best, current)
                current = 0
            else:
                current += 1
        return max(best, current)

    def summary(self) -> dict:
        """Return a summary dictionary of autonomy metrics."""
        return {
            "score": round(self.autonomy_score(), 3),
            "grade": self.autonomy_grade(),
            "total_visits": self.total_visits,
            "interventions": self.intervention_visits,
            "routine": self.routine_visits,
            "mtbi": round(self.mean_time_between_interventions(), 1),
            "longest_streak": self.longest_streak_without_intervention(),
            "breakdown": self.intervention_breakdown(),
        }


def autonomy_report(tracker: AutonomyTracker) -> str:
    """Generate a human-readable autonomy report string.

    Parameters
    ----------
    tracker : AutonomyTracker
        The tracker to report on.

    Returns
    -------
    str
        A one-line summary suitable for a caretaker visit note.
    """
    s = tracker.summary()

    if s["total_visits"] == 0:
        return "no visits recorded — cannot assess autonomy"

    grade_desc = {
        "autonomous": "self-sustaining",
        "stable": "mostly self-sustaining",
        "dependent": "needs regular attention",
        "fragile": "needs frequent intervention",
        "critical": "cannot sustain itself",
    }

    label = grade_desc.get(s["grade"], s["grade"])

    parts = [
        f"autonomy {s['score']:.2f}",
        f"mtbi {s['mtbi']:.0f}s" if s["mtbi"] > 0 else "mtbi n/a",
        f"{s['interventions']} interventions in {s['total_visits']} visits",
    ]

    if s["breakdown"]:
        top_actions = sorted(
            s["breakdown"].items(), key=lambda x: x[1], reverse=True
        )[:3]
        action_str = ", ".join(f"{a}×{c}" for a, c in top_actions)
        parts.append(f"top: {action_str}")

    parts.append(f"— {label}")

    return ", ".join(parts)
