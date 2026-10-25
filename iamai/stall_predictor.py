"""stall_predictor — estimate stall risk from recent commit gaps.

A self-writing repo stalls when the writer process dies silently
and nobody notices until the next caretaker visit.  This module
looks at the trailing commit intervals and estimates how likely
a stall is *right now*, based on how long it has been since the
last commit relative to recent history.

Design
------

Stall risk is computed as::

    elapsed = seconds since last commit
    baseline = median of last N intervals
    ratio = elapsed / baseline

    risk = clamp(ratio - 1.0, 0.0, 1.0)

A ratio of 1.0 means we are exactly at the expected next-commit
time — risk is 0.  A ratio of 2.0 means we are one full interval
past due — risk is 1.0.  Values between are linearly interpolated.

Risk tiers
==========

========  =============================================
tier      meaning
========  =============================================
low       risk < 0.25 — within normal jitter
medium    risk 0.25–0.60 — overdue, worth checking
high      risk 0.60–0.85 — likely stalled
critical  risk >= 0.85 — almost certainly stalled
========  =============================================
"""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, List, Optional


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


def stall_risk(
    intervals: List[float],
    elapsed: float,
) -> float:
    """Compute stall risk in [0.0, 1.0].

    Parameters
    ----------
    intervals : list[float]
        Recent commit intervals (seconds).  Must have ≥ 3 values.
    elapsed : float
        Seconds since the most recent commit.

    Returns
    -------
    float
        Risk score: 0 = on schedule, 1 = certainly stalled.

    Raises
    ------
    ValueError
        If fewer than 3 intervals or baseline is zero.
    """
    if len(intervals) < 3:
        raise ValueError(f"need >= 3 intervals, got {len(intervals)}")
    base = median(intervals)
    if base <= 0:
        raise ValueError(f"baseline must be > 0, got {base}")
    ratio = elapsed / base
    return _clamp(ratio - 1.0, 0.0, 1.0)


def risk_tier(risk: float) -> str:
    """Map a risk score to a human-readable tier."""
    if risk < 0.25:
        return "low"
    if risk < 0.60:
        return "medium"
    if risk < 0.85:
        return "high"
    return "critical"


def stall_assessment(
    intervals: List[float],
    elapsed: float,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Full stall assessment combining risk score with context.

    Returns a dict with:
      - risk: float [0, 1]
      - tier: str (low / medium / high / critical)
      - baseline: median interval (seconds)
      - elapsed: seconds since last commit
      - ratio: elapsed / baseline
      - recommendation: str
    """
    risk = stall_risk(intervals, elapsed)
    tier = risk_tier(risk)
    base = median(intervals)
    ratio = elapsed / base if base > 0 else float("inf")

    if tier == "low":
        rec = "writer is on schedule; no action needed"
    elif tier == "medium":
        rec = "commit overdue; check writer process health"
    elif tier == "high":
        rec = "writer likely stalled; restart recommended"
    else:
        rec = "writer almost certainly dead; immediate restart required"

    return {
        "risk": round(risk, 4),
        "tier": tier,
        "baseline": round(base, 1),
        "elapsed": round(elapsed, 1),
        "ratio": round(ratio, 3),
        "recommendation": rec,
        "assessed_at": (now or datetime.now(timezone.utc)).isoformat(),
    }
