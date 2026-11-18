#!/usr/bin/env python3
"""stroke_cadence_drift — measure how well the writer tracks its target cadence.

The IamAI writer is configured to emit one stroke every *target_cadence*
seconds (default 15 s).  In practice the realised inter-stroke gaps
wander: the writer may run slightly fast for a while (**negative
drift**), slow down (**positive drift**), or oscillate between the two.

This module quantifies that *cadence-tracking quality* along three
axes:

1. **Absolute drift** — how far the running mean gap deviates from the
   target, measured in seconds and as a signed percentage.
2. **Drift trend** — whether the writer is accelerating or decelerating
   over the observation window (linear regression slope on the rolling
   mean series).
3. **Cadence stability** — how much the rolling mean itself wobbles
   (coefficient of variation of the rolling mean series).

These metrics complement ``stroke_burst_detector`` (which looks at
individual gap outliers) and ``stroke_zeitgeber`` (which looks at
calendar-level rhythms) by focusing on the *control-loop fidelity* of
the writer's internal timer.

Core metrics
------------

=======================  ===================================================
metric                   meaning
=======================  ===================================================
target_cadence           the configured gap in seconds (default 15.0)
mean_gap                 arithmetic mean of all inter-stroke gaps
absolute_drift           mean_gap − target_cadence (positive = slow)
relative_drift           absolute_drift / target_cadence (signed %)
rolling_means            list of rolling-window mean gaps
drift_slope              slope of OLS regression on rolling_means
                         (seconds per window-step); positive = slowing down
drift_trend              classification: "stable", "accelerating",
                         "decelerating", or "oscillating"
stability_cv             CV of the rolling_means series (lower = steadier)
stability_grade          "tight" (CV<0.1), "loose" (0.1–0.3),
                         "drifty" (0.3–0.6), "erratic" (>0.6)
windows_above_target     count of rolling windows whose mean > target
windows_below_target     count of rolling windows whose mean < target
max_consecutive_drift    longest run of consecutive windows on the same
                         side of the target
=======================  ===================================================

Detection logic
---------------

Given *N* inter-stroke gaps, a rolling window of width *W* (default 20)
slides across the gap series.  Each window produces one mean value.

**Drift slope** is the OLS slope of the rolling-mean series against its
index (0, 1, 2, …).  Classification:

=============  ============================================
condition      trend label
=============  ============================================
|slope| < 0.1  "stable"
slope ≤ −0.1  "accelerating" (gaps shrinking → faster)
slope ≥ +0.1  "decelerating" (gaps growing → slower)
otherwise      "oscillating" (if stability_cv > 0.3)
=============  ============================================

**Consecutive drift** counts the longest run of windows on the same
side of the target.  A run of 5+ windows above the target usually
signals a systemic slowdown rather than noise.

Public API
----------
- ``CadenceDriftReport``: dataclass with all metrics
- ``analyze(strokes, target_cadence=15.0, window=20) -> CadenceDriftReport``
- ``compute_rolling_means(gaps, window) -> list[float]``
- ``ols_slope(values) -> float``
- ``classify_trend(slope, cv) -> str``
- ``classify_stability(cv) -> str``
- ``max_consecutive_run(values, above) -> int``

Usage::

    from iamai.stroke_cadence_drift import analyze

    strokes = [...]  # list of stroke dicts with "at" timestamps
    report = analyze(strokes, target_cadence=15.0, window=20)
    print(f"drift: {report.relative_drift:+.1%}, trend: {report.drift_trend}")
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class CadenceDriftReport:
    """Container for cadence-drift analysis results."""

    target_cadence: float = 15.0
    mean_gap: float = 0.0
    absolute_drift: float = 0.0
    relative_drift: float = 0.0
    rolling_means: List[float] = field(default_factory=list)
    drift_slope: float = 0.0
    drift_trend: str = "stable"
    stability_cv: float = 0.0
    stability_grade: str = "tight"
    windows_above_target: int = 0
    windows_below_target: int = 0
    max_consecutive_above: int = 0
    max_consecutive_below: int = 0
    total_gaps: int = 0
    window_size: int = 20


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def _parse_ts(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime."""
    s = str(raw).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        raise ValueError(f"cannot parse timestamp: {raw!r}")


def _extract_timestamps(strokes: list) -> List[datetime]:
    """Pull sorted datetime list from stroke dicts."""
    ts_list = []
    for s in strokes:
        raw = s.get("at", "")
        if raw:
            ts_list.append(_parse_ts(raw))
    ts_list.sort()
    return ts_list


def _compute_gaps(timestamps: List[datetime]) -> List[float]:
    """Compute inter-stroke gaps in seconds."""
    if len(timestamps) < 2:
        return []
    return [
        (timestamps[i + 1] - timestamps[i]).total_seconds()
        for i in range(len(timestamps) - 1)
    ]


# ---------------------------------------------------------------------------
# Core analysis functions
# ---------------------------------------------------------------------------

def compute_rolling_means(gaps: List[float], window: int = 20) -> List[float]:
    """Compute rolling-window means over a gap series.

    Uses a simple sliding window: for each position *i* where
    ``i + window <= len(gaps)``, the mean of ``gaps[i:i+window]`` is
    returned.  This produces ``len(gaps) - window + 1`` values.

    Parameters
    ----------
    gaps : list of float
        Inter-stroke gap series in seconds.
    window : int
        Number of gaps per window (default 20).

    Returns
    -------
    list of float
        Rolling mean values.
    """
    if not gaps or window < 1:
        return []
    if window > len(gaps):
        # Not enough data for a full window — return the overall mean.
        return [statistics.mean(gaps)]
    result = []
    running = sum(gaps[:window])
    result.append(running / window)
    for i in range(1, len(gaps) - window + 1):
        running += gaps[i + window - 1] - gaps[i - 1]
        result.append(running / window)
    return result


def ols_slope(values: List[float]) -> float:
    """Compute the ordinary-least-squares slope for a 1-D series.

    The independent variable is the 0-based index (0, 1, 2, …).
    Returns 0.0 if fewer than 2 values are provided.

    Parameters
    ----------
    values : list of float
        Dependent variable series.

    Returns
    -------
    float
        Slope in units of *values* per index step.
    """
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = statistics.mean(values)
    num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    return num / den


def classify_trend(slope: float, cv: float) -> str:
    """Classify the drift trend from slope and stability CV.

    Parameters
    ----------
    slope : float
        OLS slope of the rolling-mean series (seconds per window-step).
    cv : float
        Coefficient of variation of the rolling-mean series.

    Returns
    -------
    str
        One of "stable", "accelerating", "decelerating", "oscillating".
    """
    if abs(slope) < 0.1:
        if cv > 0.3:
            return "oscillating"
        return "stable"
    if slope <= -0.1:
        return "accelerating"
    return "decelerating"


def classify_stability(cv: float) -> str:
    """Grade cadence stability from the CV of rolling means.

    Parameters
    ----------
    cv : float
        Coefficient of variation (stddev / mean) of rolling means.

    Returns
    -------
    str
        One of "tight", "loose", "drifty", "erratic".
    """
    if cv < 0.1:
        return "tight"
    if cv < 0.3:
        return "loose"
    if cv < 0.6:
        return "drifty"
    return "erratic"


def max_consecutive_run(values: List[float], above: float) -> int:
    """Find the longest consecutive run of values above (or below) a threshold.

    Parameters
    ----------
    values : list of float
        Series to scan.
    above : float
        Threshold value.

    Returns
    -------
    tuple of (int, int)
        (max_consecutive_above, max_consecutive_below)
    """
    max_above = 0
    max_below = 0
    cur_above = 0
    cur_below = 0
    for v in values:
        if v > above:
            cur_above += 1
            cur_below = 0
        elif v < above:
            cur_below += 1
            cur_above = 0
        else:
            # Exactly on target — breaks both runs.
            cur_above = 0
            cur_below = 0
        max_above = max(max_above, cur_above)
        max_below = max(max_below, cur_below)
    return max_above, max_below


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze(
    strokes: list,
    target_cadence: float = 15.0,
    window: int = 20,
) -> CadenceDriftReport:
    """Analyse cadence drift for a stroke series.

    Parameters
    ----------
    strokes : list of dict
        Stroke records, each containing at least ``"at"`` (ISO-8601
        timestamp).  Must contain ≥ 2 strokes to produce any gaps.
    target_cadence : float
        The configured writer cadence in seconds (default 15.0).
    window : int
        Rolling-window width in number of gaps (default 20).

    Returns
    -------
    CadenceDriftReport
        Populated analysis report.
    """
    report = CadenceDriftReport(
        target_cadence=target_cadence,
        window_size=window,
    )

    timestamps = _extract_timestamps(strokes)
    gaps = _compute_gaps(timestamps)
    report.total_gaps = len(gaps)

    if not gaps:
        return report

    report.mean_gap = statistics.mean(gaps)
    report.absolute_drift = report.mean_gap - target_cadence
    report.relative_drift = (
        report.absolute_drift / target_cadence if target_cadence != 0 else 0.0
    )

    # Rolling means
    rmeans = compute_rolling_means(gaps, window)
    report.rolling_means = rmeans

    if not rmeans:
        return report

    # Drift slope and trend
    slope = ols_slope(rmeans)
    report.drift_slope = slope

    # Stability
    if len(rmeans) >= 2:
        rm_mean = statistics.mean(rmeans)
        rm_std = statistics.stdev(rmeans)
        report.stability_cv = (rm_std / rm_mean) if rm_mean != 0 else 0.0
    else:
        report.stability_cv = 0.0

    report.drift_trend = classify_trend(slope, report.stability_cv)
    report.stability_grade = classify_stability(report.stability_cv)

    # Window counts
    report.windows_above_target = sum(1 for m in rmeans if m > target_cadence)
    report.windows_below_target = sum(1 for m in rmeans if m < target_cadence)

    # Consecutive runs
    max_above, max_below = max_consecutive_run(rmeans, target_cadence)
    report.max_consecutive_above = max_above
    report.max_consecutive_below = max_below

    return report
