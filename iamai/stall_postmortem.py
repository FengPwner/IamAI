"""Stall postmortem — analyse patterns across stall-recovery cycles.

Existing stall modules answer point-in-time questions:

- ``stall_classifier``: is the writer stalled *right now*?
- ``stall_forecaster``: is a stall *about to happen*?
- ``stall_recover``: how do we *recover* from a stall?

None of them look **backwards** across multiple stall events to answer:
"what is the *pattern*?"  This module fills that gap.

A stall event is a dict (or StallEvent dataclass) with:

- ``gap_s``: duration of the silence in seconds
- ``recovery_s``: time from detection to full recovery in seconds
- ``cause``: optional label (``"reclaimed"``, ``"crash"``, ``"oom"``,
  ``"unknown"``)

Given a list of such events, the module produces a ``Postmortem``
dataclass with:

1. **frequency** — stalls per 24 h window (rolling mean)
2. **severity_trend** — are gaps getting longer or shorter?
   (``"improving"`` | ``"stable"`` | ``"worsening"``)
3. **recovery_trend** — is time-to-recover getting faster or slower?
4. **dominant_cause** — most common cause label
5. **mttr** — mean time to recover (seconds)
6. **summary** — one-line human-readable verdict

Design choices
--------------
- **Pure function** — takes a list, returns a dataclass.  No I/O.
- **Minimum sample** — with fewer than 2 events, most fields default
  to safe values (``"stable"``, ``0.0``) with a caveat flag.
- **Severity slope** — uses simple OLS on gap durations; a positive
  slope means worsening, negative means improving.  Slope within
  ±10 % of mean gap is called ``"stable"``.
- **No timestamps required** — events are assumed to be in chronological
  order but absolute timestamps are not needed; the module works with
  durations only.

Usage::

    from iamai.stall_postmortem import analyse_stalls, StallEvent

    events = [
        StallEvent(gap_s=120, recovery_s=30, cause="reclaimed"),
        StallEvent(gap_s=300, recovery_s=45, cause="reclaimed"),
        StallEvent(gap_s=2700, recovery_s=60, cause="reclaimed"),
    ]
    pm = analyse_stalls(events)
    print(pm.severity_trend)    # "worsening"
    print(pm.mttr)              # 45.0
    print(pm.summary)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StallEvent:
    """A single stall-recovery cycle."""

    gap_s: float          # duration of silence (seconds)
    recovery_s: float     # detection → full recovery (seconds)
    cause: str = "unknown"


@dataclass(frozen=True)
class Postmortem:
    """Aggregated analysis of multiple stall events."""

    count: int
    mttr: float                              # mean time to recover (s)
    mean_gap: float                          # mean gap duration (s)
    max_gap: float                           # worst single gap (s)
    severity_trend: str                      # improving | stable | worsening
    recovery_trend: str                      # improving | stable | worsening
    dominant_cause: str                      # most frequent cause label
    cause_counts: dict = field(default_factory=dict)
    insufficient_data: bool = False
    summary: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _simple_slope(values: List[float]) -> float:
    """OLS slope for a list of y-values indexed 0..n-1.

    Returns 0.0 for fewer than 2 values.
    """
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


def _classify_trend(slope: float, mean_val: float) -> str:
    """Turn a slope into a trend label.

    A slope within ±10 % of the mean is ``"stable"``.
    Positive slope → ``"worsening"`` (gaps growing / recovery slowing).
    Negative slope → ``"improving"``.
    """
    if mean_val == 0:
        return "stable"
    ratio = slope / mean_val
    if abs(ratio) <= 0.10:
        return "stable"
    return "worsening" if ratio > 0 else "improving"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyse_stalls(events: List[StallEvent]) -> Postmortem:
    """Analyse a sequence of stall events and return a postmortem report.

    Events should be in chronological order (oldest first).  The list
    may be empty — the result will carry ``count=0`` and safe defaults.
    """
    n = len(events)

    # -- trivial cases -------------------------------------------------------
    if n == 0:
        return Postmortem(
            count=0,
            mttr=0.0,
            mean_gap=0.0,
            max_gap=0.0,
            severity_trend="stable",
            recovery_trend="stable",
            dominant_cause="none",
            summary="no stall events recorded",
        )

    gaps = [e.gap_s for e in events]
    recs = [e.recovery_s for e in events]
    causes = [e.cause for e in events]

    mttr = sum(recs) / n
    mean_gap = sum(gaps) / n
    max_gap = max(gaps)

    if n == 1:
        cause_counts = dict(Counter(causes))
        return Postmortem(
            count=1,
            mttr=mttr,
            mean_gap=mean_gap,
            max_gap=max_gap,
            severity_trend="stable",
            recovery_trend="stable",
            dominant_cause=causes[0],
            cause_counts=cause_counts,
            insufficient_data=True,
            summary=(
                f"single stall: {mean_gap:.0f}s gap, "
                f"{mttr:.0f}s to recover ({causes[0]})"
            ),
        )

    # -- trend analysis (need ≥ 2) -------------------------------------------
    gap_slope = _simple_slope(gaps)
    rec_slope = _simple_slope(recs)

    severity_trend = _classify_trend(gap_slope, mean_gap)
    recovery_trend = _classify_trend(rec_slope, mttr)

    cause_counts = dict(Counter(causes))
    dominant_cause = max(cause_counts, key=lambda k: cause_counts[k])

    summary_parts = [
        f"{n} stalls",
        f"mttr {mttr:.0f}s",
        f"mean gap {mean_gap:.0f}s",
        f"worst {max_gap:.0f}s",
        f"severity {severity_trend}",
        f"recovery {recovery_trend}",
        f"top cause: {dominant_cause}",
    ]
    summary = ", ".join(summary_parts)

    return Postmortem(
        count=n,
        mttr=mttr,
        mean_gap=mean_gap,
        max_gap=max_gap,
        severity_trend=severity_trend,
        recovery_trend=recovery_trend,
        dominant_cause=dominant_cause,
        cause_counts=cause_counts,
        summary=summary,
    )
