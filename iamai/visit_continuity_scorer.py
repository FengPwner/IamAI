"""Visit continuity scorer — assess caretaker automation health.

Given a sequence of caretaker visit records, this module computes a
multi-dimensional health score that reflects how well the automated
writing pipeline is being maintained.

Dimensions
----------

1. **cadence_regularity** — how consistent are the intervals between
   consecutive visits?  Low variance → high score.

2. **alive_fraction** — what proportion of visits found at least one
   writer process already running?

3. **recovery_promptness** — when processes were found dead, how
   quickly (in visit-intervals) was the restart completed?  Immediate
   restarts score higher than delayed ones.

4. **content_momentum** — is the stroke count growing between visits?
   Positive deltas score higher; flat or negative deltas signal a stall.

5. **commit_freshness** — are there uncommitted files at visit time?
   Clean working trees score higher.

Each dimension returns a float in [0, 1].  The overall ``health_score``
is the weighted mean:

    health = (w1*cadence + w2*alive + w3*recovery
              + w4*momentum + w5*commit)

Default weights emphasise cadence (0.25) and momentum (0.25) equally,
with alive fraction (0.20), recovery (0.15) and commit freshness (0.15)
filling the rest.

Usage::

    from iamai.visit_continuity_scorer import score_visits, health_grade

    visits = [
        {"ts": 1729300000, "alive": True,  "strokes": 3800, "pending": 0},
        {"ts": 1729303600, "alive": True,  "strokes": 3810, "pending": 2},
        {"ts": 1729307200, "alive": False, "strokes": 3810, "pending": 5},
    ]

    result = score_visits(visits)
    print(result["health_score"])   # e.g. 0.73
    print(health_grade(0.73))       # "B"
"""

from __future__ import annotations

import math
from statistics import mean, stdev
from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_visits(
    visits: list[dict[str, Any]],
    *,
    weights: dict[str, float] | None = None,
    target_interval_s: float = 600.0,
) -> dict[str, Any]:
    """Score a sequence of caretaker visit records.

    Parameters
    ----------
    visits : list of dicts
        Each dict must contain:
        - ``ts`` (float/int): visit timestamp (epoch seconds)
        - ``alive`` (bool): whether writer was running on arrival
        - ``strokes`` (int): cumulative stroke count at visit time
        - ``pending`` (int): number of uncommitted files at visit time
    weights : dict, optional
        Override default dimension weights.
    target_interval_s : float
        Expected interval between visits in seconds (default 600 = 10 min).

    Returns
    -------
    dict with keys:
        cadence_regularity, alive_fraction, recovery_promptness,
        content_momentum, commit_freshness, health_score, grade,
        visit_count, span_s
    """
    if not visits:
        return _empty_result()

    w = {
        "cadence": 0.25,
        "alive": 0.20,
        "recovery": 0.15,
        "momentum": 0.25,
        "commit": 0.15,
    }
    if weights:
        w.update(weights)
    # Normalise so weights always sum to 1
    total = sum(w.values())
    if total > 0:
        w = {k: v / total for k, v in w.items()}

    sorted_v = sorted(visits, key=lambda v: v["ts"])

    cadence = _score_cadence(sorted_v, target_interval_s)
    alive = _score_alive(sorted_v)
    recovery = _score_recovery(sorted_v)
    momentum = _score_momentum(sorted_v)
    commit = _score_commit(sorted_v)

    health = (
        w["cadence"] * cadence
        + w["alive"] * alive
        + w["recovery"] * recovery
        + w["momentum"] * momentum
        + w["commit"] * commit
    )

    span = sorted_v[-1]["ts"] - sorted_v[0]["ts"] if len(sorted_v) > 1 else 0.0

    return {
        "cadence_regularity": round(cadence, 4),
        "alive_fraction": round(alive, 4),
        "recovery_promptness": round(recovery, 4),
        "content_momentum": round(momentum, 4),
        "commit_freshness": round(commit, 4),
        "health_score": round(health, 4),
        "grade": health_grade(health),
        "visit_count": len(sorted_v),
        "span_s": round(span, 1),
    }


def health_grade(score: float) -> str:
    """Map a [0,1] health score to a letter grade.

    A  ≥ 0.85
    B  ≥ 0.70
    C  ≥ 0.50
    D  ≥ 0.30
    F  <  0.30
    """
    if score >= 0.85:
        return "A"
    if score >= 0.70:
        return "B"
    if score >= 0.50:
        return "C"
    if score >= 0.30:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Dimension scorers (private)
# ---------------------------------------------------------------------------

def _score_cadence(
    visits: list[dict[str, Any]], target_s: float
) -> float:
    """Score interval regularity against a target interval.

    Perfect score (1.0) when every interval equals ``target_s``.
    Score decays with coefficient of variation (CV = stdev/mean).
    """
    if len(visits) < 3:
        return 1.0  # not enough data to penalise

    intervals = [
        visits[i + 1]["ts"] - visits[i]["ts"]
        for i in range(len(visits) - 1)
    ]
    avg = mean(intervals)
    if avg <= 0:
        return 0.0

    # Penalise deviation from target interval
    ratio = min(avg, target_s) / max(avg, target_s)  # ∈ (0, 1]

    # Penalise high variance
    sd = stdev(intervals) if len(intervals) > 1 else 0.0
    cv = sd / avg if avg > 0 else 0.0
    variance_score = max(0.0, 1.0 - cv)

    return 0.5 * ratio + 0.5 * variance_score


def _score_alive(visits: list[dict[str, Any]]) -> float:
    """Fraction of visits where writer was alive on arrival."""
    if not visits:
        return 1.0
    alive_count = sum(1 for v in visits if v.get("alive", False))
    return alive_count / len(visits)


def _score_recovery(visits: list[dict[str, Any]]) -> float:
    """Score how promptly dead processes were recovered.

    For each dead-on-arrival visit, check if the *next* visit found
    processes alive.  If yes → full credit (1.0).  If the next visit
    is also dead → half credit (0.5).  Consecutive dead visits keep
    halving.

    If no visits were dead, returns 1.0 (nothing to recover from).
    """
    if not visits:
        return 1.0

    dead_indices = [i for i, v in enumerate(visits) if not v.get("alive", False)]
    if not dead_indices:
        return 1.0

    scores = []
    for di in dead_indices:
        consecutive_dead = 0
        for j in range(di + 1, len(visits)):
            if visits[j].get("alive", False):
                break
            consecutive_dead += 1
        # 0 extra dead → 1.0, 1 extra → 0.5, 2 extra → 0.25, …
        scores.append(1.0 / (2 ** consecutive_dead))

    return mean(scores)


def _score_momentum(visits: list[dict[str, Any]]) -> float:
    """Score whether stroke count is growing between visits.

    Each positive delta → 1.0, zero delta → 0.3, negative → 0.0.
    Final score is the mean across all deltas.
    """
    if len(visits) < 2:
        return 1.0

    scores = []
    for i in range(len(visits) - 1):
        delta = visits[i + 1].get("strokes", 0) - visits[i].get("strokes", 0)
        if delta > 0:
            scores.append(1.0)
        elif delta == 0:
            scores.append(0.3)
        else:
            scores.append(0.0)

    return mean(scores)


def _score_commit(visits: list[dict[str, Any]]) -> float:
    """Score commit freshness — fewer pending files → higher score.

    pending=0 → 1.0, pending≤3 → 0.7, pending≤10 → 0.4, >10 → 0.1.
    Final score is the mean across all visits.
    """
    if not visits:
        return 1.0

    scores = []
    for v in visits:
        p = v.get("pending", 0)
        if p == 0:
            scores.append(1.0)
        elif p <= 3:
            scores.append(0.7)
        elif p <= 10:
            scores.append(0.4)
        else:
            scores.append(0.1)

    return mean(scores)


def _empty_result() -> dict[str, Any]:
    return {
        "cadence_regularity": 0.0,
        "alive_fraction": 0.0,
        "recovery_promptness": 0.0,
        "content_momentum": 0.0,
        "commit_freshness": 0.0,
        "health_score": 0.0,
        "grade": "F",
        "visit_count": 0,
        "span_s": 0.0,
    }
