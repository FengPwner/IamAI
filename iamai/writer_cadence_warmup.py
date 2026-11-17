#!/usr/bin/env python3
"""writer_cadence_warmup — measure post-restart cadence recovery time.

When the autowrite process restarts, the first few strokes often take
longer than the target cadence.  State files are loaded, caches are
cold, templates are parsed for the first time.  This *warmup period*
is the gap between the restart and the moment the writer settles into
its steady-state rhythm.

A healthy warmup is short (< 3× target cadence).  A lengthening warmup
over successive restarts signals growing startup cost — perhaps the
state file is bloated, or a dependency is slow to initialize.

Metrics
-------
Given a list of post-restart stroke timestamps and a target cadence:

- ``warmup_duration_s``:  seconds from restart to first steady-state stroke
- ``warmup_strokes``:     number of strokes produced during warmup
- ``settled``:            whether steady-state was reached within the data
- ``overshoot_count``:    strokes during warmup that exceeded 2× target
- ``warmup_cost_s``:      cumulative excess time (sum of max(0, gap - target))
- ``efficiency``:         target / mean(warmup gaps)  (> 1 means slower than target)

Settled detection
-----------------
The writer is *settled* when ``consecutive_needed`` consecutive gaps
fall within ``tolerance`` of the target cadence.  Default tolerance is
50 % — a 15-second target accepts gaps up to 22.5 s.

Severity tiers
==============  ============  ===========================================
label           warmup_cost   meaning
==============  ============  ===========================================
instant         < 1× target   restart was seamless
quick           < 3× target   normal startup jitter
moderate        < 6× target   noticeable delay, investigate
slow            < 12× target  significant recovery cost
glacial         >= 12× target restart is a major disruption
==============  ============  ===========================================

Public API::

    from iamai.writer_cadence_warmup import analyze_warmup

    timestamps = [1000, 1025, 1048, 1063, 1078, 1093, 1108]
    report = analyze_warmup(
        restart_ts=1000,
        stroke_timestamps=timestamps,
        target_cadence_s=15,
    )
    print(report["warmup_duration_s"])  # e.g. 48
    print(report["severity"])           # "quick"
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional


def detect_settled(
    gaps: List[float],
    target: float,
    tolerance: float = 0.5,
    consecutive_needed: int = 3,
) -> int:
    """Return the index at which the writer is *settled*.

    Settled means ``consecutive_needed`` consecutive gaps are within
    ``target * (1 + tolerance)`` of the target.

    Returns -1 if settled was never reached.
    """
    if not gaps or target <= 0:
        return -1
    threshold = target * (1 + tolerance)
    run = 0
    for i, g in enumerate(gaps):
        if g <= threshold:
            run += 1
            if run >= consecutive_needed:
                # Return the index of the *first* gap in the settled run.
                return i - consecutive_needed + 1
        else:
            run = 0
    return -1


def warmup_duration(
    restart_ts: float,
    stroke_timestamps: List[float],
    settled_index: int,
) -> float:
    """Seconds from restart to the stroke that ends the settled run's start.

    If settled_index is -1 (never settled), returns the full span.
    """
    if not stroke_timestamps:
        return 0.0
    if settled_index < 0:
        return stroke_timestamps[-1] - restart_ts
    # The settled run starts at settled_index; the stroke *after* the
    # run's first gap marks the end of warmup.
    target_idx = settled_index + 1  # gap[settled_index] is between idx and idx+1
    if target_idx >= len(stroke_timestamps):
        return stroke_timestamps[-1] - restart_ts
    return stroke_timestamps[target_idx] - restart_ts


def warmup_cost(gaps: List[float], target: float) -> float:
    """Cumulative excess seconds during warmup gaps.

    For each gap, excess = max(0, gap - target).  Sum of all excesses.
    """
    return sum(max(0.0, g - target) for g in gaps)


def classify_severity(warmup_cost_s: float, target: float) -> str:
    """Map warmup cost to a severity label."""
    if target <= 0:
        return "unknown"
    ratio = warmup_cost_s / target
    if ratio < 1:
        return "instant"
    if ratio < 3:
        return "quick"
    if ratio < 6:
        return "moderate"
    if ratio < 12:
        return "slow"
    return "glacial"


def analyze_warmup(
    restart_ts: float,
    stroke_timestamps: List[float],
    target_cadence_s: float = 15.0,
    tolerance: float = 0.5,
    consecutive_needed: int = 3,
) -> Dict[str, Any]:
    """Full warmup analysis for a single restart event.

    Parameters
    ----------
    restart_ts:
        Epoch timestamp when the writer process was (re)started.
    stroke_timestamps:
        Sorted list of epoch timestamps for each stroke produced
        after the restart.  Must be >= restart_ts.
    target_cadence_s:
        Expected inter-stroke interval in seconds.
    tolerance:
        Fraction of target accepted as "on cadence".  0.5 means gaps
        up to 1.5× target count as settled.
    consecutive_needed:
        How many consecutive on-cadence gaps are required.

    Returns
    -------
    dict with keys:
        warmup_duration_s, warmup_strokes, settled, overshoot_count,
        warmup_cost_s, efficiency, severity, gaps
    """
    ts = sorted(t for t in stroke_timestamps if t >= restart_ts)

    if len(ts) < 2:
        return {
            "warmup_duration_s": 0.0,
            "warmup_strokes": len(ts),
            "settled": False,
            "overshoot_count": 0,
            "warmup_cost_s": 0.0,
            "efficiency": 0.0,
            "severity": "unknown",
            "gaps": [],
        }

    gaps = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
    settled_idx = detect_settled(gaps, target_cadence_s, tolerance, consecutive_needed)
    dur = warmup_duration(restart_ts, ts, settled_idx)

    # Warmup gaps: all gaps before the settled run begins.
    if settled_idx >= 0:
        w_gaps = gaps[: settled_idx + consecutive_needed]
    else:
        w_gaps = gaps

    cost = warmup_cost(w_gaps, target_cadence_s)
    overshoot = sum(1 for g in w_gaps if g > 2 * target_cadence_s)
    mean_w = statistics.mean(w_gaps) if w_gaps else 0.0
    eff = target_cadence_s / mean_w if mean_w > 0 else 0.0

    return {
        "warmup_duration_s": round(dur, 2),
        "warmup_strokes": len(w_gaps),
        "settled": settled_idx >= 0,
        "overshoot_count": overshoot,
        "warmup_cost_s": round(cost, 2),
        "efficiency": round(eff, 3),
        "severity": classify_severity(cost, target_cadence_s),
        "gaps": [round(g, 2) for g in w_gaps],
    }


def warmup_trend(
    reports: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compare warmup costs across multiple restart events.

    Parameters
    ----------
    reports:
        List of dicts returned by ``analyze_warmup``.

    Returns
    -------
    dict with keys:
        count, mean_cost_s, median_cost_s, trend
        trend is "improving", "stable", or "degrading"
    """
    if not reports:
        return {"count": 0, "mean_cost_s": 0.0, "median_cost_s": 0.0, "trend": "unknown"}

    costs = [r["warmup_cost_s"] for r in reports]
    mean_c = statistics.mean(costs)
    median_c = statistics.median(costs)

    if len(costs) < 3:
        trend = "insufficient_data"
    else:
        first_half = statistics.mean(costs[: len(costs) // 2])
        second_half = statistics.mean(costs[len(costs) // 2 :])
        if second_half < first_half * 0.8:
            trend = "improving"
        elif second_half > first_half * 1.2:
            trend = "degrading"
        else:
            trend = "stable"

    return {
        "count": len(reports),
        "mean_cost_s": round(mean_c, 2),
        "median_cost_s": round(median_c, 2),
        "trend": trend,
    }
