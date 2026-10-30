"""push_exposure_index — quantify data-loss risk from unpushed commits.

existing tools measure push *debt* (how many commits behind) and push
*blockage* (how long the pipe has been clogged).  but neither answers
the question a caretaker actually needs: **how much work would we lose
if the container were recycled right now?**

this module produces a single score from 0 to 100 that synthesises:

| dimension         | weight | what it captures                        |
|-------------------|--------|-----------------------------------------|
| commit_volume     | 0.35   | raw count of unpushed commits           |
| time_span_hours   | 0.25   | wall-clock hours since oldest unpushed  |
| work_hours_lost   | 0.25   | estimated person-hours trapped          |
| blockage_age      | 0.15   | how long the blockage has persisted      |

score bands:

===========  =======  ======================================
band         score    meaning
===========  =======  ======================================
safe         0–19     minor lag, acceptable operating window
caution      20–49    noticeable debt, monitor closely
warning      50–74    significant risk, push recovery needed
critical     75–100   imminent data-loss exposure
===========  =======  ======================================

usage::

    from iamai.push_exposure_index import exposure_index

    result = exposure_index(
        unpushed_count=117,
        oldest_unpushed_hours=72.0,
        estimated_work_hours=48.0,
        blockage_hours=96.0,
    )
    print(result["score"])    # 87
    print(result["band"])     # "critical"
    print(result["summary"])  # "117 commits / 72h span / 48h work trapped"

design: pure function, no filesystem side-effects.  callers feed it
numbers from git and from push_blockage_tracker.
"""

from __future__ import annotations

from typing import Any, Dict


# ---------------------------------------------------------------------------
# dimension scoring (each 0–100, capped)
# ---------------------------------------------------------------------------

def _score_dimension(value: float, thresholds: list[float]) -> float:
    """map a raw value to a 0–100 sub-score using ascending thresholds.

    thresholds = [low, mid, high]:
        value <= low   → 0–25   (linearly interpolated)
        low < value <= mid → 25–50
        mid < value <= high → 50–75
        value > high   → 75–100 (linearly, capped at 100 when value >= 2*high)
    """
    low, mid, high = thresholds
    if value <= 0:
        return 0.0
    if value <= low:
        return 25.0 * (value / low)
    if value <= mid:
        return 25.0 + 25.0 * ((value - low) / (mid - low))
    if value <= high:
        return 50.0 + 25.0 * ((value - mid) / (high - mid))
    # above high: 75–100, capped at 2*high
    cap = 2 * high
    if value >= cap:
        return 100.0
    return 75.0 + 25.0 * ((value - high) / (cap - high))


# ---------------------------------------------------------------------------
# weights
# ---------------------------------------------------------------------------

WEIGHTS: Dict[str, float] = {
    "commit_volume":     0.35,
    "time_span_hours":   0.25,
    "work_hours_lost":   0.25,
    "blockage_age":      0.15,
}

# thresholds per dimension: [low, mid, high]
THRESHOLDS: Dict[str, list[float]] = {
    "commit_volume":     [10, 50, 150],
    "time_span_hours":   [6, 24, 72],
    "work_hours_lost":   [4, 16, 48],
    "blockage_age":      [12, 48, 120],
}


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def exposure_index(
    unpushed_count: int = 0,
    oldest_unpushed_hours: float = 0.0,
    estimated_work_hours: float = 0.0,
    blockage_hours: float = 0.0,
) -> Dict[str, Any]:
    """compute a composite push-exposure risk score.

    parameters
    ----------
    unpushed_count : int
        number of local commits not yet on the remote.
    oldest_unpushed_hours : float
        wall-clock hours since the oldest unpushed commit was created.
    estimated_work_hours : float
        rough estimate of person-hours represented by the unpushed work.
    blockage_hours : float
        hours since the push pipeline was last healthy.

    returns
    -------
    dict with keys: score (int 0–100), band (str), dimensions (dict of
    sub-scores), summary (str).
    """
    raw = {
        "commit_volume":     float(unpushed_count),
        "time_span_hours":   oldest_unpushed_hours,
        "work_hours_lost":   estimated_work_hours,
        "blockage_age":      blockage_hours,
    }

    sub_scores = {}
    for dim, val in raw.items():
        sub_scores[dim] = round(_score_dimension(val, THRESHOLDS[dim]), 2)

    weighted = sum(
        sub_scores[dim] * WEIGHTS[dim] for dim in WEIGHTS
    )
    score = int(round(weighted))
    score = max(0, min(100, score))

    band = _band(score)
    summary = (
        f"{unpushed_count} commits / "
        f"{oldest_unpushed_hours:.0f}h span / "
        f"{estimated_work_hours:.0f}h work trapped"
    )

    return {
        "score": score,
        "band": band,
        "dimensions": sub_scores,
        "summary": summary,
    }


def _band(score: int) -> str:
    if score < 20:
        return "safe"
    if score < 50:
        return "caution"
    if score < 75:
        return "warning"
    return "critical"
