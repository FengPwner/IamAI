#!/usr/bin/env python3
"""stall_early_warning — predict writer stalls before they happen.

A stall is not a crash.  The process is still alive, the PID file
exists, but no stroke has landed for minutes.  By the time a heartbeat
monitor fires, the damage is already done: the caretaker must restart,
commits pile up, and the rhythm breaks.

This module looks at the *trend* in stroke timing, not the point-in-time
gap.  A writer whose gaps are steadily lengthening — 14 s, 16 s, 19 s,
23 s, 28 s — is heading for a stall even though the last stroke was
only 28 seconds ago.  Catching that degradation early lets the caretaker
intervene (restart, nudge, investigate) before the silence grows.

Signal dimensions
-----------------

==================  =====================================================
metric              meaning
==================  =====================================================
gap_trend           slope of linear fit over recent gaps (s/stroke)
gap_acceleration    change in trend — are gaps getting longer *faster*
cv                  coefficient of variation (σ/μ) of recent gaps
max_gap_ratio       largest gap / median gap in the window
escalation_count    consecutive gaps that are longer than the one before
risk_score          composite 0–1 combining all signals
level               none | watch | warning | critical
eta_stall_s         estimated seconds until a stall if trend continues
action              recommended caretaker response
==================  =====================================================

Design choices
--------------

- **Linear fit over recent gaps** catches monotonic degradation that a
  rolling average would smooth away.  A positive slope means gaps are
  growing; the steeper the slope, the faster the decline.
- **Acceleration** (second derivative) matters because a linear drift
  is manageable but an accelerating one is an emergency.
- **Escalation count** is a simple but powerful signal: in a healthy
  writer, gaps fluctuate randomly; a run of 5+ increasing gaps is
  almost always a precursor to a stall.
- **ETA to stall** extrapolates the trend to the stall threshold
  (2× target cadence).  It gives the caretaker a countdown, not just
  a colour.

Usage::

    from datetime import datetime, timezone
    from iamai.stall_early_warning import early_warning_report

    ts = [datetime(2026, 11, 10, 0, i, 0, tzinfo=timezone.utc)
          for i in range(20)]

    r = early_warning_report(ts, target_gap_s=15.0)
    print(r["level"])       # "none"
    print(r["risk_score"])  # 0.04
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_epoch(ts: Sequence[datetime]) -> List[float]:
    """Convert datetime objects to epoch seconds."""
    return [t.timestamp() for t in ts]


def _gaps(epochs: Sequence[float]) -> List[float]:
    """Compute inter-stroke gaps from a sequence of epoch timestamps."""
    if len(epochs) < 2:
        return []
    return [epochs[i + 1] - epochs[i] for i in range(len(epochs) - 1)]


def _mean(xs: Sequence[float]) -> float:
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def _median(xs: Sequence[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2.0
    return s[mid]


def _stdev(xs: Sequence[float], mean: Optional[float] = None) -> float:
    if len(xs) < 2:
        return 0.0
    m = mean if mean is not None else _mean(xs)
    variance = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(variance)


def _linear_fit(ys: Sequence[float]) -> tuple:
    """Simple least-squares fit: y = slope * x + intercept.

    Returns (slope, intercept) where x is the 0-based index.
    """
    n = len(ys)
    if n < 2:
        return (0.0, ys[0] if ys else 0.0)
    x_mean = (n - 1) / 2.0
    y_mean = _mean(ys)
    num = sum((i - x_mean) * (ys[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    slope = num / den if den > 0 else 0.0
    intercept = y_mean - slope * x_mean
    return (slope, intercept)


def _escalation_count(gaps: Sequence[float]) -> int:
    """Count the longest trailing run of increasing gaps."""
    if len(gaps) < 2:
        return 0
    run = 0
    best = 0
    for i in range(1, len(gaps)):
        if gaps[i] > gaps[i - 1]:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def _risk_score(
    gap_trend: float,
    gap_accel: float,
    cv: float,
    max_gap_ratio: float,
    escalation: int,
    target_gap_s: float,
) -> float:
    """Combine signals into a composite 0–1 risk score.

    Each signal is normalised to 0–1 then weighted:
    - gap_trend:       30%  (primary degradation signal)
    - gap_accel:       20%  (acceleration amplifies trend)
    - cv:              15%  (instability)
    - max_gap_ratio:   15%  (outlier severity)
    - escalation:      20%  (consecutive degradation)
    """
    # trend: positive slope → risk; normalise against target gap
    trend_norm = min(1.0, max(0.0, gap_trend / (target_gap_s * 0.5))) if target_gap_s > 0 else 0.0

    # acceleration: positive accel → worsening trend
    accel_norm = min(1.0, max(0.0, gap_accel / (target_gap_s * 0.2))) if target_gap_s > 0 else 0.0

    # cv: >0.5 is unstable
    cv_norm = min(1.0, max(0.0, cv / 0.8))

    # max_gap_ratio: >3× median is concerning
    ratio_norm = min(1.0, max(0.0, (max_gap_ratio - 1.0) / 4.0))

    # escalation: 5+ consecutive increases is high risk
    esc_norm = min(1.0, escalation / 8.0)

    score = (
        0.30 * trend_norm
        + 0.20 * accel_norm
        + 0.15 * cv_norm
        + 0.15 * ratio_norm
        + 0.20 * esc_norm
    )
    return round(min(1.0, max(0.0, score)), 4)


def _classify_level(risk_score: float) -> str:
    """Map risk score to warning level."""
    if risk_score < 0.15:
        return "none"
    elif risk_score < 0.35:
        return "watch"
    elif risk_score < 0.60:
        return "warning"
    else:
        return "critical"


def _eta_stall(
    gaps: Sequence[float],
    gap_trend: float,
    target_gap_s: float,
) -> Optional[float]:
    """Estimate seconds until gap exceeds stall threshold (2× target).

    Uses the linear trend extrapolated from recent gaps.
    Returns None if trend is non-positive (not degrading).
    """
    if not gaps or gap_trend <= 0:
        return None
    stall_threshold = target_gap_s * 2.0
    last_gap = gaps[-1]
    if last_gap >= stall_threshold:
        return 0.0
    remaining_gap_growth = stall_threshold - last_gap
    # Each stroke adds ~gap_trend seconds to the gap
    strokes_to_stall = remaining_gap_growth / gap_trend
    # Convert strokes to seconds using current average gap
    avg_gap = _mean(gaps) if gaps else target_gap_s
    return round(strokes_to_stall * avg_gap, 1)


def _recommend_action(level: str, eta: Optional[float]) -> str:
    """Suggest a caretaker action based on warning level and ETA."""
    if level == "none":
        return "no action needed"
    elif level == "watch":
        if eta is not None and eta < 600:
            return "monitor closely; stall likely within 10 minutes"
        return "log trend; check again next visit"
    elif level == "warning":
        if eta is not None and eta < 300:
            return "prepare restart; stall imminent"
        return "investigate cause; consider preemptive restart"
    else:  # critical
        return "restart writer immediately"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def early_warning_report(
    timestamps: Sequence[datetime],
    target_gap_s: float = 15.0,
    window: int = 30,
) -> dict:
    """Analyse stroke timestamps and return a stall early-warning report.

    Parameters
    ----------
    timestamps : sequence of datetime
        Stroke timestamps in chronological order.
    target_gap_s : float
        Expected seconds between strokes (default 15).
    window : int
        Number of most recent gaps to analyse (default 30).

    Returns
    -------
    dict with keys: gap_trend, gap_acceleration, cv, max_gap_ratio,
    escalation_count, risk_score, level, eta_stall_s, action.
    """
    if len(timestamps) < 3:
        return {
            "gap_trend": 0.0,
            "gap_acceleration": 0.0,
            "cv": 0.0,
            "max_gap_ratio": 1.0,
            "escalation_count": 0,
            "risk_score": 0.0,
            "level": "none",
            "eta_stall_s": None,
            "action": "insufficient data",
            "gaps_analysed": 0,
        }

    epochs = _to_epoch(timestamps)
    all_gaps = _gaps(epochs)
    recent_gaps = all_gaps[-window:] if len(all_gaps) > window else all_gaps

    # Primary signals
    gap_trend, intercept = _linear_fit(recent_gaps)
    gap_mean = _mean(recent_gaps)
    gap_sd = _stdev(recent_gaps, gap_mean)
    cv = gap_sd / gap_mean if gap_mean > 0 else 0.0
    med = _median(recent_gaps)
    max_gap = max(recent_gaps) if recent_gaps else 0.0
    max_gap_ratio = max_gap / med if med > 0 else 1.0
    escalation = _escalation_count(recent_gaps)

    # Acceleration: fit the trend over two halves
    if len(recent_gaps) >= 6:
        half = len(recent_gaps) // 2
        trend_first, _ = _linear_fit(recent_gaps[:half])
        trend_second, _ = _linear_fit(recent_gaps[half:])
        gap_accel = trend_second - trend_first
    else:
        gap_accel = 0.0

    # Composite score and classification
    risk = _risk_score(gap_trend, gap_accel, cv, max_gap_ratio, escalation, target_gap_s)
    level = _classify_level(risk)
    eta = _eta_stall(recent_gaps, gap_trend, target_gap_s)
    action = _recommend_action(level, eta)

    return {
        "gap_trend": round(gap_trend, 4),
        "gap_acceleration": round(gap_accel, 4),
        "cv": round(cv, 4),
        "max_gap_ratio": round(max_gap_ratio, 4),
        "escalation_count": escalation,
        "risk_score": risk,
        "level": level,
        "eta_stall_s": eta,
        "action": action,
        "gaps_analysed": len(recent_gaps),
    }


def warning_dashboard(
    timestamps: Sequence[datetime],
    target_gap_s: float = 15.0,
    width: int = 50,
) -> str:
    """Render an ASCII dashboard showing stall early-warning status.

    Example output::

        ╔══════════════════════════════════════════════╗
        ║  STALL EARLY WARNING        level: WARNING   ║
        ╠══════════════════════════════════════════════╣
        ║  risk score  ████████████░░░░░░░░░░  0.47    ║
        ║  gap trend    ↑ +0.32 s/stroke               ║
        ║  escalation  4 consecutive increases        ║
        ║  eta stall   ~340 s                         ║
        ║  action      investigate cause              ║
        ╚══════════════════════════════════════════════╝
    """
    report = early_warning_report(timestamps, target_gap_s)
    level = report["level"].upper()
    risk = report["risk_score"]
    trend = report["gap_trend"]
    esc = report["escalation_count"]
    eta = report["eta_stall_s"]
    action = report["action"]

    filled = int(risk * width)
    bar = "█" * filled + "░" * (width - filled)
    trend_arrow = "↑" if trend > 0 else ("↓" if trend < 0 else "→")
    eta_str = f"~{eta:.0f} s" if eta is not None else "—"

    lines = [
        "╔" + "═" * (width + 16) + "╗",
        "║" + f"  STALL EARLY WARNING        level: {level:<9s}" + " " * max(0, width - 36 - len(level)) + "║",
        "╠" + "═" * (width + 16) + "╣",
        "║" + f"  risk score  {bar}  {risk:.2f}    " + " " * max(0, width - len(bar) - 16) + "║",
        "║" + f"  gap trend    {trend_arrow} {trend:+.2f} s/stroke" + " " * max(0, width - 28) + "║",
        "║" + f"  escalation  {esc} consecutive increases" + " " * max(0, width - 30 - len(str(esc))) + "║",
        "║" + f"  eta stall   {eta_str}" + " " * max(0, width - 14 - len(eta_str)) + "║",
        "║" + f"  action      {action}" + " " * max(0, width - 14 - len(action)) + "║",
        "╚" + "═" * (width + 16) + "╝",
    ]
    return "\n".join(lines)
