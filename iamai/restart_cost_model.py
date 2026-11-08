"""restart_cost_model — quantify the real cost of each process restart.

Every time the writer process is reclaimed and restarted, something
is lost: strokes that were queued but never flushed, time spent in the
dead zone between death and resurrection, commit backlog that piles
up while no one is writing.

Most monitoring modules look at the *current* state — is the process
alive? is cadence healthy?  This module looks backward at each
restart event and assigns it a cost:

- **lost_strokes** — estimated strokes that should have been produced
  during the dead zone but weren't.
- **dead_zone_s** — seconds between process death and successful
  restart.
- **backlog_at_restart** — number of uncommitted files at the moment
  the process died.
- **recovery_overhead_s** — seconds from restart to first post-restart
  stroke (warm-up cost).
- **total_cost** — a single dimensionless score combining all factors,
  normalised so that a "clean" restart (no lost strokes, instant
  recovery, zero backlog) scores 0.0 and a catastrophic restart
  (hours of dead time, hundreds of lost strokes, massive backlog)
  approaches 1.0.

Public API::

    from iamai.restart_cost_model import (
        RestartEvent, RestartCostModel, cost_report,
    )

    model = RestartCostModel(expected_cadence=15)

    model.add_event(RestartEvent(
        death_time=1700000000,
        restart_time=1700000300,
        first_stroke_after=1700000345,
        backlog_files=3,
        strokes_before=500,
        strokes_after=501,
    ))

    summary = model.summary()
    # {"restarts": 1, "mean_cost": 0.12, "total_lost_strokes": 20,
    #  "mean_dead_zone_s": 300, "worst_cost": 0.12}

    print(cost_report(model))
    # "1 restart(s), avg cost 0.12, 20 lost strokes, avg dead zone 300s, verdict: acceptable"

Cost model
----------

The total cost for a single restart is::

    cost = 1 - exp(-(w_dead * dead_norm
                   + w_lost * lost_norm
                   + w_back * back_norm
                   + w_warm * warm_norm))

where each ``*_norm`` is the raw value divided by a reference scale
(defaults: 3600s for dead zone, 100 for lost strokes, 10 for backlog,
300s for warm-up).  The exponential mapping keeps the score bounded
in [0, 1) and ensures diminishing returns.

Default weights sum to 1.0 and emphasise dead-zone time (the single
best proxy for lost productivity)::

    w_dead = 0.40   (dead-zone duration)
    w_lost = 0.30   (missing strokes)
    w_back = 0.15   (backlog accumulation)
    w_warm = 0.15   (recovery overhead)

Why this matters
----------------

A system that restarts every 6 hours with a 5-minute dead zone loses
about 0.1 percent of its productive time.  A system that restarts
every 30 minutes with the same dead zone loses about 17 percent.
The cost model makes this explicit and gives the caretaker a single
number to watch.

If the rolling average cost climbs above 0.3, the restart frequency
or dead-zone duration is becoming unacceptable.  If it stays below
0.05, restarts are rare and well-handled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RestartEvent:
    """A single process restart with observable metrics.

    Parameters
    ----------
    death_time : float
        Unix timestamp when the process was observed dead.
    restart_time : float
        Unix timestamp when the replacement process started.
    first_stroke_after : float or None
        Unix timestamp of the first stroke emitted after restart.
        ``None`` if no stroke has been produced yet.
    backlog_files : int
        Number of uncommitted files found at restart time.
    strokes_before : int
        Cumulative stroke count just before the process died.
    strokes_after : int
        Cumulative stroke count just after restart.
    label : str
        Optional human-readable tag (e.g. "visit-563", "oom-kill").
    """

    death_time: float
    restart_time: float
    first_stroke_after: Optional[float] = None
    backlog_files: int = 0
    strokes_before: int = 0
    strokes_after: int = 0
    label: str = ""


@dataclass
class RestartCost:
    """Computed cost for a single restart event."""

    event: RestartEvent
    dead_zone_s: float = 0.0
    lost_strokes: int = 0
    recovery_overhead_s: float = 0.0
    cost: float = 0.0


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------

_DEFAULT_SCALE_DEAD = 3600.0
_DEFAULT_SCALE_LOST = 100.0
_DEFAULT_SCALE_BACK = 10.0
_DEFAULT_SCALE_WARM = 300.0

_DEFAULT_WEIGHTS = {
    "dead": 0.40,
    "lost": 0.30,
    "back": 0.15,
    "warm": 0.15,
}


class RestartCostModel:
    """Accumulates restart events and computes per-event and aggregate costs.

    Parameters
    ----------
    expected_cadence : float
        Expected seconds between strokes (default 15).
    weights : dict or None
        Override default weights.  Keys: dead, lost, back, warm.
    scales : dict or None
        Override default reference scales.  Keys: dead, lost, back, warm.
    """

    def __init__(
        self,
        expected_cadence: float = 15.0,
        weights: Optional[dict] = None,
        scales: Optional[dict] = None,
    ) -> None:
        self.expected_cadence = expected_cadence
        self._w = {**_DEFAULT_WEIGHTS, **(weights or {})}
        self._s = {
            "dead": _DEFAULT_SCALE_DEAD,
            "lost": _DEFAULT_SCALE_LOST,
            "back": _DEFAULT_SCALE_BACK,
            "warm": _DEFAULT_SCALE_WARM,
            **(scales or {}),
        }
        self._costs: List[RestartCost] = []

    # -- Mutators -------------------------------------------------------

    def add_event(self, event: RestartEvent) -> RestartCost:
        """Score a single restart event and store the result."""
        rc = self._score(event)
        self._costs.append(rc)
        return rc

    def add_events(self, events: list[RestartEvent]) -> list[RestartCost]:
        """Score a batch of restart events."""
        return [self.add_event(e) for e in events]

    # -- Queries --------------------------------------------------------

    @property
    def restarts(self) -> int:
        return len(self._costs)

    @property
    def total_lost_strokes(self) -> int:
        return sum(c.lost_strokes for c in self._costs)

    @property
    def mean_cost(self) -> float:
        if not self._costs:
            return 0.0
        return sum(c.cost for c in self._costs) / len(self._costs)

    @property
    def worst_cost(self) -> float:
        if not self._costs:
            return 0.0
        return max(c.cost for c in self._costs)

    @property
    def mean_dead_zone_s(self) -> float:
        if not self._costs:
            return 0.0
        return sum(c.dead_zone_s for c in self._costs) / len(self._costs)

    def summary(self) -> dict:
        return {
            "restarts": self.restarts,
            "mean_cost": round(self.mean_cost, 4),
            "worst_cost": round(self.worst_cost, 4),
            "total_lost_strokes": self.total_lost_strokes,
            "mean_dead_zone_s": round(self.mean_dead_zone_s, 1),
            "verdict": self._verdict(),
        }

    def costs(self) -> list[RestartCost]:
        return list(self._costs)

    # -- Internals ------------------------------------------------------

    def _score(self, event: RestartEvent) -> RestartCost:
        dead_zone = max(0.0, event.restart_time - event.death_time)

        expected_during_dead = int(dead_zone / self.expected_cadence)
        actual_produced = max(0, event.strokes_after - event.strokes_before)
        lost = max(0, expected_during_dead - actual_produced)

        if event.first_stroke_after is not None:
            warm_up = max(0.0, event.first_stroke_after - event.restart_time)
        else:
            warm_up = self.expected_cadence * 4.0

        dead_norm = dead_zone / self._s["dead"]
        lost_norm = lost / self._s["lost"]
        back_norm = event.backlog_files / self._s["back"]
        warm_norm = warm_up / self._s["warm"]

        raw = (
            self._w["dead"] * dead_norm
            + self._w["lost"] * lost_norm
            + self._w["back"] * back_norm
            + self._w["warm"] * warm_norm
        )
        cost = 1.0 - math.exp(-raw)

        return RestartCost(
            event=event,
            dead_zone_s=dead_zone,
            lost_strokes=lost,
            recovery_overhead_s=warm_up,
            cost=round(cost, 6),
        )

    def _verdict(self) -> str:
        if self.restarts == 0:
            return "no_data"
        mc = self.mean_cost
        if mc < 0.05:
            return "negligible"
        if mc < 0.15:
            return "acceptable"
        if mc < 0.30:
            return "concerning"
        return "critical"


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def cost_report(model: RestartCostModel) -> str:
    """One-line human-readable summary."""
    s = model.summary()
    if s["restarts"] == 0:
        return "no restart events recorded"
    return (
        f"{s['restarts']} restart(s), "
        f"avg cost {s['mean_cost']:.2f}, "
        f"{s['total_lost_strokes']} lost strokes, "
        f"avg dead zone {s['mean_dead_zone_s']:.0f}s, "
        f"verdict: {s['verdict']}"
    )


def cost_summary(
    events: list[RestartEvent],
    expected_cadence: float = 15.0,
    **kwargs,
) -> dict:
    """Build a model from a list of events and return its summary."""
    model = RestartCostModel(expected_cadence=expected_cadence, **kwargs)
    model.add_events(events)
    return model.summary()
