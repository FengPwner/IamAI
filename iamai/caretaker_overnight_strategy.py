"""caretaker_overnight_strategy — overnight caretaker scheduling optimizer.

Analyzes historical overnight stall patterns to recommend:
- Optimal check frequency (reduce overhead, maintain coverage)
- Expected stall count for the night window
- Whether to scale up (risky night) or scale down (quiet night)

Data model
----------

``NightRecord``: one historical night's observation.

- ``date`` (str): ISO date of the night
- ``stall_count`` (int): number of writer stalls during the night
- ``total_stall_seconds`` (int): cumulative stall duration
- ``checks_performed`` (int): number of caretaker checks that night
- ``max_gap`` (int): longest inter-stroke gap in seconds

Strategy
--------

Given a list of ``NightRecord`` objects, the strategy computes:

1. **baseline_stall_rate**: median stalls per night over the window
2. **risk_score**: 0.0–1.0 based on recent trend vs historical mean
3. **recommended_check_interval**: minutes between checks
4. **verdict**: ``relaxed`` / ``normal`` / ``elevated`` / ``high_alert``

Interval mapping::

    risk < 0.25  →  relaxed    (check every 30 min)
    risk < 0.50  →  normal     (check every 15 min)
    risk < 0.75  →  elevated   (check every 10 min)
    risk >= 0.75 →  high_alert (check every  5 min)

Edge cases
----------

- Empty history → ``normal`` with default 15-min interval
- Single record → use that record's stall_count directly
- All zeros → ``relaxed`` (no stalls ever recorded)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class NightRecord:
    """One night's observation."""

    date: str
    stall_count: int = 0
    total_stall_seconds: int = 0
    checks_performed: int = 0
    max_gap: int = 0


@dataclass
class OvernightPlan:
    """Recommended overnight caretaker plan."""

    verdict: str = "normal"
    check_interval_minutes: int = 15
    risk_score: float = 0.5
    baseline_stall_rate: float = 0.0
    recent_trend: float = 0.0
    expected_stalls: float = 0.0
    history_size: int = 0
    recommendation: str = ""

    def summary(self) -> str:
        """One-line human-readable summary."""
        return (
            f"overnight plan: {self.verdict} "
            f"(risk={self.risk_score:.2f}, "
            f"check every {self.check_interval_minutes}min, "
            f"~{self.expected_stalls:.1f} stalls expected)"
        )


# ---------------------------------------------------------------------------
# Verdict thresholds
# ---------------------------------------------------------------------------

_RISK_THRESHOLDS: List[Tuple[float, str, int]] = [
    (0.25, "relaxed", 30),
    (0.50, "normal", 15),
    (0.75, "elevated", 10),
    (float("inf"), "high_alert", 5),
]


def _verdict_from_risk(risk: float) -> Tuple[str, int]:
    """Map risk score to (verdict, interval_minutes)."""
    for threshold, verdict, interval in _RISK_THRESHOLDS:
        if risk <= threshold:
            return verdict, interval
    return "high_alert", 5


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_baseline(records: List[NightRecord]) -> float:
    """Median stall count across all records.

    Returns 0.0 for empty input.
    """
    if not records:
        return 0.0
    counts = sorted(r.stall_count for r in records)
    n = len(counts)
    if n % 2 == 1:
        return float(counts[n // 2])
    return (counts[n // 2 - 1] + counts[n // 2]) / 2.0


def compute_recent_trend(
    records: List[NightRecord],
    recent_n: int = 3,
) -> float:
    """Mean stall count of the most recent ``recent_n`` nights.

    Returns 0.0 if no records.
    """
    if not records:
        return 0.0
    recent = records[-recent_n:]
    return statistics.mean(r.stall_count for r in recent)


def compute_risk_score(
    records: List[NightRecord],
    recent_n: int = 3,
) -> float:
    """Compute risk score 0.0–1.0 from historical data.

    Algorithm:
    1. baseline = median stall count over full history
    2. recent = mean stall count over last ``recent_n`` nights
    3. If baseline == 0: risk = min(recent / 5.0, 1.0)
       (no historical stalls; risk proportional to recent activity)
    4. Otherwise: ratio = recent / baseline
       - ratio <= 1.0 → risk = 0.5 * (1 - 1/ratio)  mapped to 0.0–0.5
         Actually: if recent <= baseline, that's normal or better.
         risk = 0.5 * (recent / baseline)  →  0.0–0.5
       - ratio > 1.0 → risk = 0.5 + 0.5 * min((ratio - 1) / 2, 1.0)
         →  0.5–1.0

    Clamped to [0.0, 1.0].
    """
    if not records:
        return 0.5  # unknown → default normal

    baseline = compute_baseline(records)
    recent = compute_recent_trend(records, recent_n)

    if baseline == 0.0:
        # No historical stalls
        return min(recent / 5.0, 1.0) if recent > 0 else 0.0

    ratio = recent / baseline
    if ratio <= 1.0:
        risk = 0.5 * ratio
    else:
        risk = 0.5 + 0.5 * min((ratio - 1.0) / 2.0, 1.0)

    return max(0.0, min(1.0, risk))


def recommend_plan(
    records: List[NightRecord],
    recent_n: int = 3,
    night_hours: float = 8.0,
) -> OvernightPlan:
    """Build an overnight plan from historical records.

    Parameters
    ----------
    records : list of NightRecord, sorted chronologically
    recent_n : how many recent nights to weight for trend
    night_hours : length of the overnight window (default 8h)

    Returns
    -------
    OvernightPlan with verdict, interval, and recommendation text.
    """
    if not records:
        return OvernightPlan(
            verdict="normal",
            check_interval_minutes=15,
            risk_score=0.5,
            baseline_stall_rate=0.0,
            recent_trend=0.0,
            expected_stalls=0.0,
            history_size=0,
            recommendation="no history available; using default 15-min checks",
        )

    baseline = compute_baseline(records)
    trend = compute_recent_trend(records, recent_n)
    risk = compute_risk_score(records, recent_n)
    verdict, interval = _verdict_from_risk(risk)

    # Expected stalls = recent trend (most predictive)
    expected = trend
    checks_needed = int(night_hours * 60 / interval) if interval > 0 else 0

    if verdict == "relaxed":
        rec = (
            f"quiet period expected; {checks_needed} checks over "
            f"{night_hours}h should suffice"
        )
    elif verdict == "normal":
        rec = (
            f"typical overnight activity; {checks_needed} checks planned, "
            f"~{expected:.0f} stalls likely"
        )
    elif verdict == "elevated":
        rec = (
            f"recent nights show elevated stall rate "
            f"({trend:.1f}/night vs {baseline:.1f} baseline); "
            f"increasing check frequency to {checks_needed} checks"
        )
    else:
        rec = (
            f"high stall risk detected; {checks_needed} checks scheduled, "
            f"consider pre-emptive restart before overnight window"
        )

    return OvernightPlan(
        verdict=verdict,
        check_interval_minutes=interval,
        risk_score=round(risk, 4),
        baseline_stall_rate=round(baseline, 2),
        recent_trend=round(trend, 2),
        expected_stalls=round(expected, 2),
        history_size=len(records),
        recommendation=rec,
    )


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def build_night_record(
    date: str,
    stall_count: int = 0,
    total_stall_seconds: int = 0,
    checks_performed: int = 0,
    max_gap: int = 0,
) -> NightRecord:
    """Convenience constructor with sensible defaults."""
    return NightRecord(
        date=date,
        stall_count=max(0, stall_count),
        total_stall_seconds=max(0, total_stall_seconds),
        checks_performed=max(0, checks_performed),
        max_gap=max(0, max_gap),
    )


def plan_from_stall_counts(
    dates: List[str],
    stall_counts: List[int],
    recent_n: int = 3,
) -> OvernightPlan:
    """Quick plan from parallel lists of dates and stall counts."""
    if len(dates) != len(stall_counts):
        raise ValueError("dates and stall_counts must have equal length")
    records = [
        NightRecord(date=d, stall_count=max(0, s))
        for d, s in zip(dates, stall_counts)
    ]
    return recommend_plan(records, recent_n=recent_n)


def compare_plans(
    old: OvernightPlan,
    new: OvernightPlan,
) -> dict:
    """Compare two plans and return a diff summary."""
    interval_delta = new.check_interval_minutes - old.check_interval_minutes
    risk_delta = new.risk_score - old.risk_score

    if interval_delta < 0:
        direction = "more_frequent"
    elif interval_delta > 0:
        direction = "less_frequent"
    else:
        direction = "unchanged"

    return {
        "old_verdict": old.verdict,
        "new_verdict": new.verdict,
        "interval_change_minutes": interval_delta,
        "risk_change": round(risk_delta, 4),
        "direction": direction,
        "escalated": risk_delta > 0.1,
        "de_escalated": risk_delta < -0.1,
    }
