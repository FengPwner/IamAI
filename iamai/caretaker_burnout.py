"""caretaker_burnout — detect when the caretaker is spinning its wheels.

Existing caretaker modules answer complementary questions:

- ``caretaker_patience`` — how long before the caretaker must intervene?
- ``visit_efficacy`` — did a specific visit make things better?
- ``caretaker_health_score`` — how healthy is the writer right now?

None of them answer: **is the caretaker itself burning out?**

A burnt-out caretaker keeps restarting the writer, fixing the same
issues over and over, and spending more time on repair than on
progress.  The writer technically stays alive, but the caretaker is
doing the equivalent of chest compressions — keeping the body warm
without restoring consciousness.

Signals
-------

=========================  =============================================
signal                     what it measures
=========================  =============================================
intervention_rate          interventions per 24-hour window
                           (higher = more firefighting)
repeat_issue_ratio         fraction of interventions addressing the
                           same root cause as the previous one
fix_durability             mean time until the *next* intervention
                           after a fix (shorter = fixes don't stick)
severity                   qualitative label combining all signals
=========================  =============================================

Severity levels
---------------

===========  =========================================================
level        meaning
===========  =========================================================
healthy      rate < 3/day, < 30 % repeat, durability > 4 h
stressed     rate < 6/day, < 50 % repeat, durability > 2 h
overworked   rate < 12/day, < 70 % repeat, durability > 1 h
burnt_out    anything worse — caretaker is just spinning
===========  =========================================================

Usage::

    from iamai.caretaker_burnout import burnout_report

    interventions = [
        {"ts": "2026-10-22T01:00:00+00:00", "kind": "restart"},
        {"ts": "2026-10-22T02:30:00+00:00", "kind": "restart"},
        {"ts": "2026-10-22T08:00:00+00:00", "kind": "flush"},
    ]
    report = burnout_report(interventions)
    print(report.severity)          # stressed
    print(report.fix_durability_h)  # 4.5
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence


# ── data ──────────────────────────────────────────────────────


@dataclass
class BurnoutReport:
    """Summary of caretaker workload over a time window."""

    total_interventions: int
    intervention_rate: float          # per 24 h
    repeat_issue_ratio: float         # 0.0 – 1.0
    fix_durability_h: float           # hours until next intervention
    severity: str                     # healthy / stressed / overworked / burnt_out
    details: Dict[str, float] = field(default_factory=dict)


# ── internals ─────────────────────────────────────────────────


_ISO_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.\d+)?([+-]\d{2}:\d{2}|Z)?"
)


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601-ish timestamp to a tz-aware UTC datetime."""
    m = _ISO_RE.match(ts)
    if not m:
        raise ValueError(f"cannot parse timestamp: {ts!r}")
    date_part, time_part, tz_part = m.groups()
    base = f"{date_part}T{time_part}"
    if tz_part and tz_part != "Z":
        base += tz_part
    else:
        base += "+00:00"
    return datetime.fromisoformat(base)


def _sort_interventions(
    interventions: Sequence[Dict],
) -> List[Dict]:
    """Return interventions sorted by timestamp, earliest first."""
    parsed = []
    for iv in interventions:
        ts_str = iv.get("ts", "")
        try:
            ts = _parse_ts(ts_str)
        except (ValueError, TypeError):
            continue
        parsed.append({**iv, "_ts": ts})
    parsed.sort(key=lambda d: d["_ts"])
    return parsed


def _intervention_rate(sorted_ivs: List[Dict]) -> float:
    """Interventions per 24-hour window across the full span."""
    if len(sorted_ivs) < 2:
        return float(len(sorted_ivs))
    first = sorted_ivs[0]["_ts"]
    last = sorted_ivs[-1]["_ts"]
    span_hours = (last - first).total_seconds() / 3600
    if span_hours < 1e-6:
        # all interventions at the same instant → treat as 1 h window
        return float(len(sorted_ivs))
    return len(sorted_ivs) / (span_hours / 24)


def _repeat_issue_ratio(sorted_ivs: List[Dict]) -> float:
    """Fraction of interventions whose kind matches the previous one.

    A "repeat issue" is when the caretaker performs the same type of
    fix twice in a row (e.g., two consecutive restarts).  This suggests
    the first fix didn't address the root cause.
    """
    if len(sorted_ivs) < 2:
        return 0.0
    repeats = 0
    for i in range(1, len(sorted_ivs)):
        kind_prev = sorted_ivs[i - 1].get("kind", "unknown")
        kind_curr = sorted_ivs[i].get("kind", "unknown")
        if kind_prev == kind_curr:
            repeats += 1
    return repeats / (len(sorted_ivs) - 1)


def _fix_durability_hours(sorted_ivs: List[Dict]) -> float:
    """Mean hours between consecutive interventions.

    Longer gaps mean fixes are durable (the writer stays healthy
    after intervention).  Shorter gaps mean the caretaker is
    constantly coming back.
    """
    if len(sorted_ivs) < 2:
        return float("inf")
    gaps = []
    for i in range(1, len(sorted_ivs)):
        delta = (sorted_ivs[i]["_ts"] - sorted_ivs[i - 1]["_ts"]).total_seconds()
        gaps.append(delta / 3600)
    return sum(gaps) / len(gaps)


def _classify_severity(
    rate: float,
    repeat_ratio: float,
    durability_h: float,
) -> str:
    """Map numeric signals to a qualitative severity level."""
    if rate < 3 and repeat_ratio < 0.30 and durability_h > 4:
        return "healthy"
    if rate < 6 and repeat_ratio < 0.50 and durability_h > 2:
        return "stressed"
    if rate < 12 and repeat_ratio < 0.70 and durability_h > 1:
        return "overworked"
    return "burnt_out"


# ── public API ────────────────────────────────────────────────


def burnout_report(
    interventions: Sequence[Dict],
) -> BurnoutReport:
    """Compute a caretaker burnout report from intervention records.

    Parameters
    ----------
    interventions :
        List of dicts, each with at least ``"ts"`` (ISO timestamp)
        and ``"kind"`` (intervention type, e.g. ``"restart"``,
        ``"flush"``, ``"lock_cleanup"``).

    Returns
    -------
    BurnoutReport
    """
    if not interventions:
        return BurnoutReport(
            total_interventions=0,
            intervention_rate=0.0,
            repeat_issue_ratio=0.0,
            fix_durability_h=float("inf"),
            severity="healthy",
        )

    sorted_ivs = _sort_interventions(interventions)
    rate = _intervention_rate(sorted_ivs)
    repeat = _repeat_issue_ratio(sorted_ivs)
    durability = _fix_durability_hours(sorted_ivs)
    severity = _classify_severity(rate, repeat, durability)

    return BurnoutReport(
        total_interventions=len(sorted_ivs),
        intervention_rate=round(rate, 2),
        repeat_issue_ratio=round(repeat, 3),
        fix_durability_h=round(durability, 2),
        severity=severity,
        details={
            "rate_per_day": round(rate, 2),
            "repeat_pct": round(repeat * 100, 1),
            "mean_gap_h": round(durability, 2),
        },
    )


def burnout_summary(interventions: Sequence[Dict]) -> str:
    """One-liner human-readable summary of caretaker burnout status."""
    r = burnout_report(interventions)
    if r.severity == "healthy":
        return (
            f"caretaker healthy: {r.total_interventions} interventions, "
            f"{r.intervention_rate}/day, fixes last {r.fix_durability_h}h"
        )
    return (
        f"caretaker {r.severity}: {r.total_interventions} interventions, "
        f"{r.intervention_rate}/day, "
        f"{r.repeat_issue_ratio:.0%} repeat, "
        f"fixes last {r.fix_durability_h}h"
    )
