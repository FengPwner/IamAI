"""intervention_tracker — measure caretaker intervention effectiveness.

Every time a caretaker restarts a stalled writer, clears a lock, or
rescues an SSH key, that is an *intervention*.  Some interventions
cure the problem; others just postpone it.  This module answers:
*did the fix actually work, or will we be back in five minutes?*

The core concept is **relapse window**: the time between an
intervention and the next failure of the same kind.  Short relapse
windows mean the intervention was cosmetic; long ones mean it stuck.

Public API::

    from iamai.intervention_tracker import InterventionTracker

    tracker = InterventionTracker()
    tracker.record_intervention(
        kind="writer_restart",
        timestamp=1000.0,
        target="writer-qwen",
    )
    tracker.record_failure(
        kind="writer_stall",
        timestamp=1015.0,
        target="writer-qwen",
    )

    outcome = tracker.last_outcome("writer_restart")
    # InterventionOutcome(relapsed=True, relapse_window=15.0, ...)

    print(tracker.summary())
    # "12 interventions, 8 effective, 4 relapsed — 67% cure rate"

Metrics
-------

- **cure_rate**: fraction of interventions not followed by a relapse
  within the observation window.
- **mean_relapse_window**: average seconds between intervention and
  relapse, across relapsed cases only.
- **mean_time_to_next_intervention**: average seconds from one
  intervention to the next of the same kind (lower = more frequent
  firefighting).
- **repeat_offender_count**: number of (kind, target) pairs that
  required 3+ interventions.
- **effectiveness_grade**: excellent / good / fair / poor / critical.

Effectiveness grades
====================

==========  ========================================================
grade       meaning
==========  ========================================================
excellent   cure_rate ≥ 0.9 — fixes stick, very few relapses
good        0.7 ≤ cure_rate < 0.9 — mostly effective
fair        0.5 ≤ cure_rate < 0.7 — coin-flip territory
poor        0.3 ≤ cure_rate < 0.5 — more relapses than cures
critical    cure_rate < 0.3 — interventions are mostly cosmetic
==========  ========================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


# Effectiveness grade thresholds: (min_cure_rate, grade_name)
_GRADES = [
    (0.9, "excellent"),
    (0.7, "good"),
    (0.5, "fair"),
    (0.3, "poor"),
    (0.0, "critical"),
]


@dataclass(frozen=True)
class Intervention:
    """A single caretaker intervention event.

    Parameters
    ----------
    kind : str
        Category of intervention (e.g. "writer_restart", "lock_clear",
        "ssh_key_rescue", "push_retry").
    timestamp : float
        When the intervention occurred (epoch seconds).
    target : str
        What was intervened on (e.g. "writer-qwen", "batch-push").
    note : str
        Optional human-readable context.
    """

    kind: str
    timestamp: float
    target: str
    note: str = ""

    def __post_init__(self):
        if self.timestamp < 0:
            raise ValueError(f"timestamp must be non-negative, got {self.timestamp}")
        if not self.kind:
            raise ValueError("kind must be non-empty")
        if not self.target:
            raise ValueError("target must be non-empty")


@dataclass(frozen=True)
class Failure:
    """A single failure event observed in the system.

    Parameters
    ----------
    kind : str
        Category of failure (e.g. "writer_stall", "push_failed",
        "lock_stale").
    timestamp : float
        When the failure was detected (epoch seconds).
    target : str
        What failed.
    """

    kind: str
    timestamp: float
    target: str

    def __post_init__(self):
        if self.timestamp < 0:
            raise ValueError(f"timestamp must be non-negative, got {self.timestamp}")
        if not self.kind:
            raise ValueError("kind must be non-empty")


@dataclass(frozen=True)
class InterventionOutcome:
    """The result of an intervention: did it cure or relapse?

    Parameters
    ----------
    intervention : Intervention
        The intervention being evaluated.
    relapsed : bool
        True if a matching failure occurred within the observation
        window after the intervention.
    relapse_window : float or None
        Seconds from intervention to the next failure, or None if
        no relapse observed.
    next_intervention : float or None
        Seconds to the next intervention of the same (kind, target),
        or None if this is the most recent.
    """

    intervention: Intervention
    relapsed: bool
    relapse_window: Optional[float]
    next_intervention: Optional[float]


# Mapping from intervention kinds to the failure kinds they should cure.
# This is the "treatment protocol" — which failure does each
# intervention type address?
DEFAULT_TREATMENT_MAP: Dict[str, List[str]] = {
    "writer_restart": ["writer_stall", "writer_crash", "writer_freeze"],
    "lock_clear": ["lock_stale", "lock_contention"],
    "ssh_key_rescue": ["push_auth_failed", "ssh_timeout"],
    "push_retry": ["push_failed", "push_timeout"],
    "process_kill": ["zombie_process", "hung_process"],
    "config_reload": ["config_error", "misconfigured"],
}


class InterventionTracker:
    """Track interventions, failures, and compute effectiveness metrics.

    Parameters
    ----------
    treatment_map : dict or None
        Maps intervention kind → list of failure kinds it should cure.
        Defaults to ``DEFAULT_TREATMENT_MAP``.
    observation_window : float
        Maximum seconds after an intervention to look for a relapse.
        Defaults to 3600 (1 hour).
    """

    def __init__(
        self,
        treatment_map: Optional[Dict[str, List[str]]] = None,
        observation_window: float = 3600.0,
    ):
        self._treatment_map = treatment_map or dict(DEFAULT_TREATMENT_MAP)
        self._observation_window = observation_window
        self._interventions: List[Intervention] = []
        self._failures: List[Failure] = []

    # -- recording --

    def record_intervention(
        self,
        kind: str,
        timestamp: float,
        target: str,
        note: str = "",
    ) -> Intervention:
        """Record a caretaker intervention."""
        iv = Intervention(
            kind=kind,
            timestamp=timestamp,
            target=target,
            note=note,
        )
        self._interventions.append(iv)
        return iv

    def record_failure(
        self,
        kind: str,
        timestamp: float,
        target: str,
    ) -> Failure:
        """Record an observed failure."""
        f = Failure(kind=kind, timestamp=timestamp, target=target)
        self._failures.append(f)
        return f

    def record_interventions(
        self, events: Sequence[Tuple[str, float, str]]
    ) -> None:
        """Batch-record interventions as (kind, timestamp, target) tuples."""
        for kind, ts, target in events:
            self.record_intervention(kind, ts, target)

    # -- querying --

    @property
    def intervention_count(self) -> int:
        return len(self._interventions)

    @property
    def failure_count(self) -> int:
        return len(self._failures)

    def interventions_for(
        self, kind: str, target: Optional[str] = None
    ) -> List[Intervention]:
        """Return interventions matching kind and optional target."""
        result = [iv for iv in self._interventions if iv.kind == kind]
        if target is not None:
            result = [iv for iv in result if iv.target == target]
        return sorted(result, key=lambda iv: iv.timestamp)

    def failures_for(
        self, kind: str, target: Optional[str] = None
    ) -> List[Failure]:
        """Return failures matching kind and optional target."""
        result = [f for f in self._failures if f.kind == kind]
        if target is not None:
            result = [f for f in result if f.target == target]
        return sorted(result, key=lambda f: f.timestamp)

    # -- outcome computation --

    def _matching_failure_kinds(self, intervention_kind: str) -> List[str]:
        """Return failure kinds that an intervention kind should cure."""
        return self._treatment_map.get(intervention_kind, [])

    def _find_relapse(self, iv: Intervention) -> Optional[float]:
        """Find the first matching failure after an intervention.

        Returns the relapse window (seconds) or None if no relapse
        within the observation window.
        """
        failure_kinds = self._matching_failure_kinds(iv.kind)
        if not failure_kinds:
            return None

        deadline = iv.timestamp + self._observation_window
        for f in sorted(self._failures, key=lambda f: f.timestamp):
            if f.timestamp <= iv.timestamp:
                continue
            if f.timestamp > deadline:
                break
            if f.kind in failure_kinds and f.target == iv.target:
                return f.timestamp - iv.timestamp
        return None

    def _find_next_intervention(self, iv: Intervention) -> Optional[float]:
        """Find the next intervention of the same (kind, target)."""
        for other in sorted(self._interventions, key=lambda x: x.timestamp):
            if other.timestamp <= iv.timestamp:
                continue
            if other.kind == iv.kind and other.target == iv.target:
                return other.timestamp - iv.timestamp
        return None

    def outcome(self, intervention: Intervention) -> InterventionOutcome:
        """Compute the outcome for a specific intervention."""
        relapse = self._find_relapse(intervention)
        next_iv = self._find_next_intervention(intervention)
        return InterventionOutcome(
            intervention=intervention,
            relapsed=relapse is not None,
            relapse_window=relapse,
            next_intervention=next_iv,
        )

    def last_outcome(self, kind: str, target: Optional[str] = None) -> Optional[InterventionOutcome]:
        """Get the outcome of the most recent intervention of a given kind."""
        ivs = self.interventions_for(kind, target)
        if not ivs:
            return None
        return self.outcome(ivs[-1])

    def outcomes(self, kind: Optional[str] = None) -> List[InterventionOutcome]:
        """Compute outcomes for all (or filtered) interventions."""
        ivs = self._interventions
        if kind is not None:
            ivs = [iv for iv in ivs if iv.kind == kind]
        return [self.outcome(iv) for iv in ivs]

    # -- metrics --

    def cure_rate(self, kind: Optional[str] = None) -> Optional[float]:
        """Fraction of interventions that did NOT relapse.

        Returns None if no interventions recorded.
        """
        results = self.outcomes(kind)
        if not results:
            return None
        cured = sum(1 for o in results if not o.relapsed)
        return cured / len(results)

    def relapse_rate(self, kind: Optional[str] = None) -> Optional[float]:
        """Fraction of interventions that DID relapse."""
        cr = self.cure_rate(kind)
        return None if cr is None else 1.0 - cr

    def mean_relapse_window(self, kind: Optional[str] = None) -> Optional[float]:
        """Average seconds from intervention to relapse (relapsed only)."""
        results = self.outcomes(kind)
        relapsed = [o for o in results if o.relapsed and o.relapse_window is not None]
        if not relapsed:
            return None
        return sum(o.relapse_window for o in relapsed) / len(relapsed)

    def mean_time_to_next_intervention(
        self, kind: Optional[str] = None
    ) -> Optional[float]:
        """Average seconds between consecutive interventions of the same kind."""
        results = self.outcomes(kind)
        with_next = [
            o for o in results if o.next_intervention is not None
        ]
        if not with_next:
            return None
        return sum(o.next_intervention for o in with_next) / len(with_next)

    def repeat_offenders(self, min_count: int = 3) -> List[Tuple[str, str, int]]:
        """Find (kind, target) pairs requiring min_count+ interventions.

        Returns list of (kind, target, count) tuples sorted by count
        descending.
        """
        counts: Dict[Tuple[str, str], int] = {}
        for iv in self._interventions:
            key = (iv.kind, iv.target)
            counts[key] = counts.get(key, 0) + 1
        offenders = [
            (kind, target, count)
            for (kind, target), count in counts.items()
            if count >= min_count
        ]
        return sorted(offenders, key=lambda x: -x[2])

    def effectiveness_grade(self, kind: Optional[str] = None) -> Optional[str]:
        """Classify intervention effectiveness based on cure rate."""
        cr = self.cure_rate(kind)
        if cr is None:
            return None
        for threshold, grade in _GRADES:
            if cr >= threshold:
                return grade
        return "critical"

    # -- summary --

    def summary(self) -> dict:
        """Return a dict of all key metrics."""
        return {
            "intervention_count": self.intervention_count,
            "failure_count": self.failure_count,
            "cure_rate": self.cure_rate(),
            "relapse_rate": self.relapse_rate(),
            "mean_relapse_window": self.mean_relapse_window(),
            "mean_time_to_next_intervention": self.mean_time_to_next_intervention(),
            "repeat_offenders": self.repeat_offenders(),
            "effectiveness_grade": self.effectiveness_grade(),
        }


def intervention_report(tracker: InterventionTracker) -> str:
    """One-line human-readable intervention effectiveness summary."""
    s = tracker.summary()
    if s["intervention_count"] == 0:
        return "interventions: 0 — no data"

    cr = f"{s['cure_rate']:.0%}" if s["cure_rate"] is not None else "n/a"
    mrw = (
        f"{s['mean_relapse_window']:.0f}s"
        if s["mean_relapse_window"] is not None
        else "n/a"
    )
    grade = s["effectiveness_grade"] or "unknown"
    repeat = len(s["repeat_offenders"])

    return (
        f"{s['intervention_count']} interventions, "
        f"cure rate {cr}, "
        f"mean relapse {mrw}, "
        f"{repeat} repeat offender(s) — {grade}"
    )
