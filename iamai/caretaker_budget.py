"""caretaker_budget — track resource cost of caretaker visits.

Each caretaker visit consumes resources: time spent, commits made, processes
restarted, tests written.  Most visits are cheap — a quick health check and
maybe a small note.  Occasionally a visit balloons into a multi-hour rescue
operation with emergency restarts and backlog clearing.

This module records visit costs and classifies them against a budget:

===========  ============================================================
verdict      meaning
===========  ============================================================
frugal       well under budget — routine visit, minimal footprint
normal       within expected range
expensive    above budget — worth reviewing what made it costly
overrun      significantly over budget — likely an emergency intervention
===========  ============================================================

Design goals:

1. **Pure Python** — no git, no filesystem; inputs are dicts.
2. **Ring buffer** — bounded memory (default 50 visits).
3. **Composite score** — time + commits + restarts, weighted.
4. **Trend-aware** — a single expensive visit is fine; a streak is not.

Usage::

    from iamai.caretaker_budget import CaretakerBudget

    budget = CaretakerBudget()
    budget.record({"minutes": 5, "commits": 1, "restarts": 0})
    budget.record({"minutes": 45, "commits": 8, "restarts": 2})

    report = budget.analyse()
    print(report["verdict"])    # "expensive"
    print(report["avg_cost"])   # 25.0
    print(report["trend"])      # "rising"
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# cost scoring
# ---------------------------------------------------------------------------

# Default weights for the composite cost score.
# Each dimension is normalised against its "normal" threshold before weighting.
DEFAULT_WEIGHTS = {
    "minutes": 0.4,   # time is the scarcest resource
    "commits": 0.35,  # commit count reflects change surface
    "restarts": 0.25, # restarts indicate disruption
}

# Thresholds: values at or below these score 1.0 (normal).
DEFAULT_THRESHOLDS = {
    "minutes": 15,
    "commits": 3,
    "restarts": 1,
}


def _score_visit(
    visit: Dict[str, float],
    weights: Dict[str, float],
    thresholds: Dict[str, float],
) -> float:
    """Compute a single composite cost score for one visit.

    Each dimension is divided by its threshold (so 1.0 = exactly at threshold),
    then weighted.  Values above threshold score >1.0; below score <1.0.
    """
    total = 0.0
    for dim, weight in weights.items():
        value = visit.get(dim, 0.0)
        threshold = thresholds.get(dim, 1.0)
        if threshold <= 0:
            threshold = 1.0
        total += weight * (value / threshold)
    return total


# ---------------------------------------------------------------------------
# trend detection
# ---------------------------------------------------------------------------

def _linreg(values: List[float]) -> tuple[float, float]:
    """Simple least-squares linear regression.

    Returns (slope, r_squared).  Returns (0.0, 0.0) for fewer than 2 points.
    """
    n = len(values)
    if n < 2:
        return 0.0, 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    ss_xy = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    ss_xx = sum((i - x_mean) ** 2 for i in range(n))
    if ss_xx == 0:
        return 0.0, 0.0
    slope = ss_xy / ss_xx
    ss_yy = sum((v - y_mean) ** 2 for v in values)
    if ss_yy == 0:
        r2 = 0.0
    else:
        r2 = (ss_xy ** 2) / (ss_xx * ss_yy)
    return slope, r2


# ---------------------------------------------------------------------------
# CaretakerBudget
# ---------------------------------------------------------------------------

@dataclass
class CaretakerBudget:
    """Ring-buffer tracker for caretaker visit costs."""

    window_size: int = 50
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    thresholds: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))

    _visits: deque = field(default=None, init=False, repr=False)

    def __post_init__(self):
        self._visits = deque(maxlen=self.window_size)

    # -- recording ----------------------------------------------------------

    def record(self, visit: Dict[str, float]) -> float:
        """Record a visit and return its composite cost score."""
        score = _score_visit(visit, self.weights, self.thresholds)
        self._visits.append({"raw": dict(visit), "score": score})
        return score

    @property
    def count(self) -> int:
        return len(self._visits)

    # -- analysis -----------------------------------------------------------

    def scores(self) -> List[float]:
        """Return all recorded scores in order."""
        return [v["score"] for v in self._visits]

    def analyse(self) -> Dict[str, Any]:
        """Classify the most recent visit and the overall trend.

        Returns a dict with:

        - ``verdict``: frugal / normal / expensive / overrun
        - ``latest_score``: composite score of the most recent visit
        - ``avg_cost``: mean score across all recorded visits
        - ``median_cost``: median score
        - ``trend``: rising / stable / falling
        - ``trend_slope``: regression slope of scores
        - ``streak_expensive``: count of consecutive recent visits with score > 1.5
        - ``count``: number of recorded visits
        """
        if not self._visits:
            return {
                "verdict": "insufficient",
                "latest_score": 0.0,
                "avg_cost": 0.0,
                "median_cost": 0.0,
                "trend": "stable",
                "trend_slope": 0.0,
                "streak_expensive": 0,
                "count": 0,
            }

        scores = self.scores()
        latest = scores[-1]
        avg = sum(scores) / len(scores)
        sorted_scores = sorted(scores)
        n = len(sorted_scores)
        if n % 2 == 1:
            median = sorted_scores[n // 2]
        else:
            median = (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2.0

        slope, r2 = _linreg(scores)

        # Verdict based on latest score relative to avg and absolute thresholds
        verdict = _classify(latest, avg)

        # Trend: slope > 0.02 → rising, < -0.02 → falling, else stable
        if slope > 0.02:
            trend = "rising"
        elif slope < -0.02:
            trend = "falling"
        else:
            trend = "stable"

        # Streak: how many recent consecutive visits scored > 1.5
        streak = 0
        for s in reversed(scores):
            if s > 1.5:
                streak += 1
            else:
                break

        return {
            "verdict": verdict,
            "latest_score": round(latest, 4),
            "avg_cost": round(avg, 4),
            "median_cost": round(median, 4),
            "trend": trend,
            "trend_slope": round(slope, 6),
            "streak_expensive": streak,
            "count": len(scores),
        }

    def report(self) -> str:
        """One-line human-readable summary."""
        a = self.analyse()
        if a["count"] == 0:
            return "no visits recorded"
        return (
            f"{a['verdict']} — latest {a['latest_score']:.2f}, "
            f"avg {a['avg_cost']:.2f}, trend {a['trend']}, "
            f"{a['count']} visit(s)"
        )


def _classify(latest: float, avg: float) -> str:
    """Classify a single visit score into a verdict."""
    if latest < 0.5:
        return "frugal"
    elif latest <= 1.2:
        return "normal"
    elif latest <= 2.0:
        return "expensive"
    else:
        return "overrun"
