#!/usr/bin/env python3
"""restart_rhythm_recovery — classify post-restart cadence warm-up patterns.

Every restart produces a brief period of irregular cadence before the
writer settles into its configured interval.  This module quantifies
that recovery so that:

1. Stall detectors can distinguish *warming up* from *dying*.
2. Infrastructure regressions show up as changes in the recovery shape.
3. Historical recovery data can inform adaptive grace windows.

Recovery model
--------------

Given a sequence of inter-stroke intervals measured from the moment of
restart::

    intervals = [gap₁, gap₂, gap₃, …]

we fit an exponential-decay model::

    gap(i) ≈ target + (gap₁ − target) · exp(−i / τ)

where *target* is the configured cadence and *τ* is the time constant
(in strokes).  A small τ means fast recovery; a large τ means the
writer takes many strokes to stabilise.

Recovery classes
----------------

==============  ============================================================
class           meaning
==============  ============================================================
healthy         τ ≤ 3 strokes and all intervals converge toward target
slow            3 < τ ≤ 6 or convergence is present but above target
failed          τ > 6 or intervals are not converging (diverging / flat
                above 2× target)
==============  ============================================================

Public API
----------
- ``RecoveryResult`` — dataclass holding the analysis of one restart event
- ``analyse_recovery(intervals, *, target=15.0) -> RecoveryResult``
- ``classify_recovery(tau, converged) -> str``
- ``estimate_steady_state(intervals, *, target=15.0, tolerance=0.2) -> int``
- ``recovery_report(result) -> str``
- ``suggest_grace_window(result, *, default=5) -> int``
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------


@dataclass
class RecoveryResult:
    """Result of analysing one post-restart recovery sequence."""

    intervals: List[float]
    target: float
    tau: float  # decay time constant (strokes)
    classification: str  # healthy | slow | failed
    steady_state_at: int  # stroke index where cadence enters tolerance
    initial_gap: float
    final_gap: float
    converged: bool


# ---------------------------------------------------------------------------
# core analysis
# ---------------------------------------------------------------------------


def classify_recovery(tau: float, converged: bool) -> str:
    """Classify a recovery by its time constant and convergence flag."""
    if not converged:
        return "failed"
    if tau <= 3.0:
        return "healthy"
    if tau <= 6.0:
        return "slow"
    return "failed"


def _fit_tau(intervals: Sequence[float], target: float) -> float:
    """Estimate the decay time constant τ from a sequence of intervals.

    Uses a simple log-linear fit on the excess above target:
        excess(i) = gap(i) − target
        ln(excess) ≈ ln(excess₀) − i/τ
    so the slope of ln(excess) vs i gives −1/τ.

    Falls back to a heuristic if the fit is degenerate.
    """
    if len(intervals) < 2:
        return float("inf")

    excess = [max(g - target, 0.01) for g in intervals]
    # only use points where excess > 0 (above target)
    points = [(i, math.log(e)) for i, e in enumerate(excess) if e > 0.001]
    if len(points) < 2:
        return 0.5  # already at target

    n = len(points)
    sum_x = sum(p[0] for p in points)
    sum_y = sum(p[1] for p in points)
    sum_xy = sum(p[0] * p[1] for p in points)
    sum_xx = sum(p[0] * p[0] for p in points)

    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-12:
        return float("inf")

    slope = (n * sum_xy - sum_x * sum_y) / denom
    if slope >= 0:
        # not decaying — intervals are flat or increasing
        return float("inf")

    return -1.0 / slope


def _check_convergence(intervals: Sequence[float], target: float,
                       tolerance: float = 0.3) -> bool:
    """Check whether the tail of the interval sequence is near target."""
    if len(intervals) < 2:
        return False
    tail = intervals[-min(3, len(intervals)):]
    return all(abs(g - target) / target <= tolerance for g in tail)


def estimate_steady_state(intervals: Sequence[float], *,
                          target: float = 15.0,
                          tolerance: float = 0.2) -> int:
    """Return the index of the first interval that enters the tolerance band.

    If the sequence never enters the band, returns len(intervals).
    """
    for i, g in enumerate(intervals):
        if abs(g - target) / target <= tolerance:
            return i
    return len(intervals)


def analyse_recovery(intervals: Sequence[float], *,
                     target: float = 15.0) -> RecoveryResult:
    """Analyse a post-restart recovery sequence.

    Parameters
    ----------
    intervals : sequence of float
        Inter-stroke gaps measured from the restart moment, in seconds.
    target : float
        The configured cadence interval (default 15 s).

    Returns
    -------
    RecoveryResult
    """
    ivl = list(intervals)
    if not ivl:
        return RecoveryResult(
            intervals=[],
            target=target,
            tau=float("inf"),
            classification="failed",
            steady_state_at=0,
            initial_gap=0.0,
            final_gap=0.0,
            converged=False,
        )

    tau = _fit_tau(ivl, target)
    converged = _check_convergence(ivl, target)
    classification = classify_recovery(tau, converged)
    steady = estimate_steady_state(ivl, target=target)

    return RecoveryResult(
        intervals=ivl,
        target=target,
        tau=round(tau, 3) if math.isfinite(tau) else float("inf"),
        classification=classification,
        steady_state_at=steady,
        initial_gap=ivl[0],
        final_gap=ivl[-1],
        converged=converged,
    )


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def recovery_report(result: RecoveryResult) -> str:
    """Produce a human-readable summary of a recovery analysis."""
    tau_str = f"{result.tau:.2f}" if math.isfinite(result.tau) else "∞"
    lines = [
        f"recovery: {result.classification}",
        f"  τ = {tau_str} strokes",
        f"  initial gap: {result.initial_gap:.1f}s",
        f"  final gap:   {result.final_gap:.1f}s",
        f"  steady at:   stroke {result.steady_state_at}",
        f"  converged:   {result.converged}",
        f"  target:      {result.target:.1f}s",
        f"  samples:     {len(result.intervals)}",
    ]
    return "\n".join(lines)


def suggest_grace_window(result: RecoveryResult, *, default: int = 5) -> int:
    """Suggest a grace-window size for stall detection after restart.

    The grace window is the number of strokes during which the stall
    detector should use a relaxed threshold.  It is based on the
    observed steady-state index plus a safety margin.
    """
    if result.classification == "failed":
        return max(default, 10)
    if result.classification == "slow":
        return max(result.steady_state_at + 3, default)
    # healthy
    return max(result.steady_state_at + 1, 3)
