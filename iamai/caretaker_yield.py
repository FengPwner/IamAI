#!/usr/bin/env python3
"""caretaker_yield — measure the return on investment of each caretaker visit.

Every caretaker visit costs something: the caretaker's time, the disruption
of restarting processes, the catch-up commit that bundles accumulated work.
But not every visit *earns* its cost.  A visit that restarts both processes
and sees them run for another eight hours is a high-yield visit.  A visit
that restarts them only to have them stall again twenty minutes later is
firefighting — and a pattern of firefighting visits means the system is
getting worse, not better.

This module answers one question: **did this visit make things better?**

Signal dimensions
-----------------

====================  ====================================================
metric                meaning
====================  ====================================================
recovery_latency      seconds from visit start to both processes running
sustained_uptime      seconds of productive output after the visit
backlog_cleared       number of uncommitted files resolved during visit
output_delta          strokes produced post-visit vs same-length pre-window
visit_cost            number of distinct intervention actions taken
yield_score           composite 0.0–1.0 score
yield_class           high-yield / routine / expensive / firefighting /
                      futile
====================  ====================================================

Yield classes
-------------

==============  ============================================================
class           meaning
==============  ============================================================
high-yield      score >= 0.8 — fixed cleanly, system ran well after
routine         0.6 <= score < 0.8 — standard maintenance, no surprises
expensive       0.4 <= score < 0.6 — took a lot of effort, unclear benefit
firefighting    0.2 <= score < 0.4 — system degraded again soon after
futile          score < 0.2 — system broke again almost immediately
==============  ============================================================

Public API
----------
- ``CaretakerYield`` — data class for a single visit's yield metrics
- ``compute_yield(...) -> CaretakerYield``
- ``classify_yield(score) -> str``
- ``visit_roi(yields) -> VisitROI``  — trend across multiple visits
- ``yield_report(yields) -> str``

Usage::

    from iamai.caretaker_yield import compute_yield, visit_roi

    y = compute_yield(
        recovery_latency=45,
        sustained_uptime=28800,
        backlog_cleared=8,
        output_delta=120,
        visit_cost=3,
    )
    print(y.yield_class)   # "high-yield"

    roi = visit_roi([y1, y2, y3, y4])
    print(roi.trend)       # "improving"
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_YIELD_CLASSES = [
    (0.8, "high-yield"),
    (0.6, "routine"),
    (0.4, "expensive"),
    (0.2, "firefighting"),
    (0.0, "futile"),
]

_UPTIME_EXCELLENT = 3600    # 1 hour
_UPTIME_GOOD = 1200         # 20 minutes
_UPTIME_POOR = 300          # 5 minutes

_RECOVERY_FAST = 60
_RECOVERY_NORMAL = 300
_RECOVERY_SLOW = 900

_MAX_EXPECTED_COST = 6


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CaretakerYield:
    """Yield metrics for a single caretaker visit."""
    visit_time: str = ""
    recovery_latency: float = 0.0
    sustained_uptime: float = 0.0
    backlog_cleared: int = 0
    output_delta: int = 0
    visit_cost: int = 0
    yield_score: float = 0.0
    yield_class: str = "futile"
    actions: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "visit_time": self.visit_time,
            "recovery_latency": self.recovery_latency,
            "sustained_uptime": self.sustained_uptime,
            "backlog_cleared": self.backlog_cleared,
            "output_delta": self.output_delta,
            "visit_cost": self.visit_cost,
            "yield_score": self.yield_score,
            "yield_class": self.yield_class,
            "actions": self.actions,
            "notes": self.notes,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@dataclass
class VisitROI:
    """Return on investment across a sequence of caretaker visits."""
    total_visits: int = 0
    mean_yield: float = 0.0
    median_yield: float = 0.0
    high_yield_pct: float = 0.0
    futile_pct: float = 0.0
    trend: str = "unknown"
    trend_slope: float = 0.0
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_visits": self.total_visits,
            "mean_yield": round(self.mean_yield, 3),
            "median_yield": round(self.median_yield, 3),
            "high_yield_pct": round(self.high_yield_pct, 1),
            "futile_pct": round(self.futile_pct, 1),
            "trend": self.trend,
            "trend_slope": round(self.trend_slope, 4),
            "recommendation": self.recommendation,
        }


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _score_uptime(seconds: float) -> float:
    """Score sustained uptime on a 0-1 scale."""
    if seconds <= 0:
        return 0.0
    if seconds >= _UPTIME_EXCELLENT:
        return 1.0
    if seconds >= _UPTIME_GOOD:
        return 0.5 + 0.5 * (seconds - _UPTIME_GOOD) / (
            _UPTIME_EXCELLENT - _UPTIME_GOOD
        )
    if seconds >= _UPTIME_POOR:
        return 0.2 + 0.3 * (seconds - _UPTIME_POOR) / (
            _UPTIME_GOOD - _UPTIME_POOR
        )
    return 0.2 * seconds / _UPTIME_POOR


def _score_recovery(seconds: float) -> float:
    """Score recovery latency — faster is better."""
    if seconds <= 0:
        return 1.0
    if seconds <= _RECOVERY_FAST:
        return 1.0
    if seconds <= _RECOVERY_NORMAL:
        return 0.7 + 0.3 * (_RECOVERY_NORMAL - seconds) / (
            _RECOVERY_NORMAL - _RECOVERY_FAST
        )
    if seconds <= _RECOVERY_SLOW:
        return 0.3 + 0.4 * (_RECOVERY_SLOW - seconds) / (
            _RECOVERY_SLOW - _RECOVERY_NORMAL
        )
    return max(0.0, 0.3 * _RECOVERY_SLOW / seconds)


def _score_cost(cost: int) -> float:
    """Score visit cost — fewer actions is more efficient."""
    if cost <= 0:
        return 1.0
    if cost >= _MAX_EXPECTED_COST:
        return 0.1
    return 1.0 - (cost - 1) / (_MAX_EXPECTED_COST - 1) * 0.9


def _score_output(delta: int) -> float:
    """Score output delta — more strokes after vs before is better."""
    if delta <= 0:
        return 0.0
    if delta >= 100:
        return 1.0
    if delta >= 50:
        return 0.7 + 0.3 * (delta - 50) / 50
    if delta >= 10:
        return 0.3 + 0.4 * (delta - 10) / 40
    return 0.3 * delta / 10


def _score_backlog(cleared: int) -> float:
    """Score backlog clearance — clearing more is better, with diminishing."""
    if cleared <= 0:
        return 0.5  # no backlog to clear is neutral
    if cleared >= 20:
        return 1.0
    if cleared >= 10:
        return 0.8 + 0.2 * (cleared - 10) / 10
    return 0.5 + 0.3 * cleared / 10


# Weights for composite score
_WEIGHTS = {
    "uptime": 0.40,
    "recovery": 0.15,
    "cost": 0.15,
    "output": 0.20,
    "backlog": 0.10,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_yield(
    recovery_latency: float = 0.0,
    sustained_uptime: float = 0.0,
    backlog_cleared: int = 0,
    output_delta: int = 0,
    visit_cost: int = 0,
    visit_time: str = "",
    actions: list[str] | None = None,
    notes: str = "",
) -> CaretakerYield:
    """Compute yield metrics for a single caretaker visit.

    Parameters
    ----------
    recovery_latency : float
        Seconds from visit start to both processes running.
    sustained_uptime : float
        Seconds of productive operation after the visit.
    backlog_cleared : int
        Number of uncommitted files resolved during the visit.
    output_delta : int
        Strokes produced post-visit minus pre-visit (same-length windows).
    visit_cost : int
        Number of distinct intervention actions taken.
    visit_time : str
        ISO-8601 timestamp of the visit.
    actions : list[str]
        List of action names taken during the visit.
    notes : str
        Free-form notes about the visit.

    Returns
    -------
    CaretakerYield
    """
    uptime_s = _score_uptime(sustained_uptime)
    recovery_s = _score_recovery(recovery_latency)
    cost_s = _score_cost(visit_cost)
    output_s = _score_output(output_delta)
    backlog_s = _score_backlog(backlog_cleared)

    score = (
        _WEIGHTS["uptime"] * uptime_s
        + _WEIGHTS["recovery"] * recovery_s
        + _WEIGHTS["cost"] * cost_s
        + _WEIGHTS["output"] * output_s
        + _WEIGHTS["backlog"] * backlog_s
    )

    score = max(0.0, min(1.0, score))
    cls = classify_yield(score)

    return CaretakerYield(
        visit_time=visit_time or datetime.now(timezone.utc).isoformat(),
        recovery_latency=recovery_latency,
        sustained_uptime=sustained_uptime,
        backlog_cleared=backlog_cleared,
        output_delta=output_delta,
        visit_cost=visit_cost,
        yield_score=round(score, 3),
        yield_class=cls,
        actions=actions or [],
        notes=notes,
    )


def classify_yield(score: float) -> str:
    """Map a yield score to a class label.

    Parameters
    ----------
    score : float
        Composite yield score, 0.0-1.0.

    Returns
    -------
    str
        One of: high-yield, routine, expensive, firefighting, futile.
    """
    for threshold, label in _YIELD_CLASSES:
        if score >= threshold:
            return label
    return "futile"


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def _linear_slope(values: list[float]) -> float:
    """Compute the slope of a simple linear regression (y = a + bx)."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _classify_trend(slope: float, n: int) -> str:
    """Classify the trend direction from the slope."""
    if n < 2:
        return "unknown"
    if abs(slope) < 0.01:
        return "flat"
    if slope > 0.02:
        return "improving"
    if slope < -0.02:
        return "degrading"
    return "flat"


def _recommend(roi: VisitROI, yields: list[CaretakerYield]) -> str:
    """Generate a recommendation based on ROI trends."""
    if roi.total_visits < 2:
        return "too few visits to recommend"

    if roi.trend == "improving":
        if roi.mean_yield >= 0.7:
            return "system is stabilising — consider reducing visit frequency"
        return "yield is improving — keep current caretaker approach"

    if roi.trend == "degrading":
        recent = yields[-3:] if len(yields) >= 3 else yields
        recent_classes = [y.yield_class for y in recent]
        if "futile" in recent_classes or "firefighting" in recent_classes:
            return (
                "yield is degrading with recent firefighting — "
                "investigate root cause of recurring stalls"
            )
        return "yield is trending down — review visit strategy"

    if roi.futile_pct > 20:
        return (
            f"{roi.futile_pct:.0f}% of visits are futile — "
            "consider structural changes to reduce stall frequency"
        )

    if roi.high_yield_pct > 70:
        return "most visits are high-yield — system is well-maintained"

    return "mixed results — monitor for another 3-5 visits"


def visit_roi(yields: list[CaretakerYield]) -> VisitROI:
    """Compute ROI across a sequence of caretaker visits.

    Parameters
    ----------
    yields : list[CaretakerYield]
        Ordered list of visit yields (oldest first).

    Returns
    -------
    VisitROI
    """
    if not yields:
        return VisitROI()

    scores = [y.yield_score for y in yields]
    n = len(scores)

    mean_y = sum(scores) / n
    sorted_scores = sorted(scores)
    if n % 2 == 1:
        median_y = sorted_scores[n // 2]
    else:
        median_y = (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2

    high_yield_count = sum(1 for y in yields if y.yield_class == "high-yield")
    futile_count = sum(1 for y in yields if y.yield_class == "futile")

    slope = _linear_slope(scores)
    trend = _classify_trend(slope, n)

    roi = VisitROI(
        total_visits=n,
        mean_yield=mean_y,
        median_yield=median_y,
        high_yield_pct=high_yield_count / n * 100,
        futile_pct=futile_count / n * 100,
        trend=trend,
        trend_slope=slope,
    )
    roi.recommendation = _recommend(roi, yields)
    return roi


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def yield_report(yields: list[CaretakerYield]) -> str:
    """Generate a human-readable yield report.

    Parameters
    ----------
    yields : list[CaretakerYield]
        Ordered list of visit yields.

    Returns
    -------
    str
        Multi-line report string.
    """
    if not yields:
        return "no caretaker visits recorded"

    roi = visit_roi(yields)
    lines = [
        "caretaker yield report",
        "=" * 40,
        f"visits: {roi.total_visits}",
        f"mean yield: {roi.mean_yield:.3f}",
        f"median yield: {roi.median_yield:.3f}",
        f"high-yield: {roi.high_yield_pct:.0f}%",
        f"futile: {roi.futile_pct:.0f}%",
        f"trend: {roi.trend} (slope {roi.trend_slope:+.4f})",
        "",
        "per-visit breakdown:",
    ]

    for i, y in enumerate(yields, 1):
        lines.append(
            f"  #{i:3d}  score={y.yield_score:.3f}  class={y.yield_class:<14s}  "
            f"recovery={y.recovery_latency:.0f}s  uptime={y.sustained_uptime:.0f}s  "
            f"cost={y.visit_cost}  delta_output={y.output_delta}"
        )

    lines.append("")
    lines.append(f"recommendation: {roi.recommendation}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parsing from git log
# ---------------------------------------------------------------------------

def parse_visits_from_log(
    log_path: str | Path,
) -> list[dict[str, Any]]:
    """Parse caretaker visit entries from a log file.

    Expects lines containing visit markers like::

        visit-N: ...

    Returns a list of dicts with 'visit_id' and 'message' keys.

    Parameters
    ----------
    log_path : str | Path
        Path to the git log output or log file.

    Returns
    -------
    list[dict]
    """
    path = Path(log_path)
    visits: list[dict[str, Any]] = []
    if not path.exists():
        return visits

    for line in path.read_text().splitlines():
        line = line.strip()
        if "visit-" in line.lower() or "caretaker" in line.lower():
            visits.append({"message": line})

    return visits


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Command-line entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="caretaker yield — measure visit ROI"
    )
    sub = parser.add_subparsers(dest="command")

    score_p = sub.add_parser("score", help="score a single visit")
    score_p.add_argument("--recovery", type=float, default=60)
    score_p.add_argument("--uptime", type=float, default=3600)
    score_p.add_argument("--backlog", type=int, default=0)
    score_p.add_argument("--output-delta", type=int, default=50)
    score_p.add_argument("--cost", type=int, default=2)

    trend_p = sub.add_parser("trend", help="show yield trend from JSON file")
    trend_p.add_argument("file", help="JSON file with visit yields array")

    args = parser.parse_args()

    if args.command == "score":
        y = compute_yield(
            recovery_latency=args.recovery,
            sustained_uptime=args.uptime,
            backlog_cleared=args.backlog,
            output_delta=args.output_delta,
            visit_cost=args.cost,
        )
        print(y.to_json())

    elif args.command == "trend":
        data = json.loads(Path(args.file).read_text())
        yields = [
            compute_yield(
                recovery_latency=v.get("recovery_latency", 0),
                sustained_uptime=v.get("sustained_uptime", 0),
                backlog_cleared=v.get("backlog_cleared", 0),
                output_delta=v.get("output_delta", 0),
                visit_cost=v.get("visit_cost", 0),
            )
            for v in data
        ]
        print(yield_report(yields))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
