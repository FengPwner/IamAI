"""Caretaker silence — measure how long since a human last checked in.

Most modules in this repo measure the writer's health.  This one
measures the **caretaker's** attention.

Every automated system degrades over time without human oversight.
Reclamation events accumulate, restart overhead grows, and the gap
between "the system looks fine" and "the system is fine" widens.
The longer a caretaker goes without visiting, the less trustworthy
any green-light signal becomes.

This module quantifies that risk.

Danger levels
-------------

==================  ===================================================
level               meaning
==================  ===================================================
``watched``         visited within 4 hours — oversight is active
``overdue``         4–12 hours — normal overnight gap, acceptable
``neglected``       12–24 hours — concerning, system may have degraded
``abandoned``       > 24 hours — high risk, all green signals suspect
==================  ===================================================

The thresholds shorten when the system is fragile (high restart
frequency), because fragile systems need more frequent oversight.

Usage::

    from iamai.caretaker_silence import silence_report

    report = silence_report(
        last_visit_epoch=1729400000.0,
        now_epoch=1729420000.0,
        restarts_per_day=3.0,
    )
    print(report["level"])          # "overdue"
    print(report["silence_hours"])  # 5.56
    print(report["recommendation"]) # "check in soon"

Design choices
--------------

- **Pure function** — takes epoch floats, returns a dict.  No filesystem,
  no subprocess, trivially testable.
- **Restart-adjusted thresholds** — a system that restarts 6×/day needs
  more frequent checking than one that restarts once a day.
- **Bounded trust score** — ``trust`` ∈ [0.0, 1.0] decays with silence
  duration; represents how much to trust automated green-light signals.

"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLDS_HOURS = (4.0, 12.0, 24.0)
RESTART_PENALTY_FACTOR = 0.85  # each restart/day above baseline shrinks thresholds by 15%
BASELINE_RESTARTS_PER_DAY = 1.0
MIN_THRESHOLD_RATIO = 0.25    # thresholds can't shrink below 25% of default


def _adjusted_thresholds(
    restarts_per_day: float,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS_HOURS,
) -> list[float]:
    """Shrink thresholds when the system restarts frequently."""
    if restarts_per_day <= BASELINE_RESTARTS_PER_DAY:
        return list(thresholds)

    excess = restarts_per_day - BASELINE_RESTARTS_PER_DAY
    factor = max(MIN_THRESHOLD_RATIO, RESTART_PENALTY_FACTOR ** excess)
    return [t * factor for t in thresholds]


def _trust_score(silence_hours: float, thresholds: list[float]) -> float:
    """Decay trust from 1.0 (just visited) to 0.0 (abandoned).

    Trust decays linearly within each tier and clamps to 0.0 beyond
    the last threshold.
    """
    if silence_hours <= 0:
        return 1.0

    last_threshold = thresholds[-1]
    if silence_hours >= last_threshold:
        return 0.0

    # Linear decay across the full range
    return max(0.0, 1.0 - (silence_hours / last_threshold))


def silence_report(
    last_visit_epoch: float,
    now_epoch: Optional[float] = None,
    *,
    restarts_per_day: float = 0.0,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS_HOURS,
) -> dict:
    """Produce a caretaker-silence report.

    Args:
        last_visit_epoch: epoch timestamp of the last caretaker visit.
        now_epoch: current epoch (defaults to ``time.time()``).
        restarts_per_day: average reclamation events per day; used to
            adjust thresholds for fragile systems.
        thresholds: custom danger thresholds in hours (3-tuple).

    Returns:
        A dict with keys: ``silence_hours``, ``level``, ``trust``,
        ``adjusted_thresholds``, ``recommendation``.
    """
    import time

    if now_epoch is None:
        now_epoch = time.time()

    silence_seconds = max(0.0, now_epoch - last_visit_epoch)
    silence_hours = silence_seconds / 3600.0

    adj = _adjusted_thresholds(restarts_per_day, thresholds)
    trust = round(_trust_score(silence_hours, adj), 3)

    # Level classification
    if silence_hours < adj[0]:
        level = "watched"
        recommendation = "oversight is active, no action needed"
    elif silence_hours < adj[1]:
        level = "overdue"
        recommendation = "check in soon"
    elif silence_hours < adj[2]:
        level = "neglected"
        recommendation = "visit recommended — system may have degraded"
    else:
        level = "abandoned"
        recommendation = "urgent visit needed — all signals suspect"

    return {
        "silence_hours": round(silence_hours, 2),
        "level": level,
        "trust": trust,
        "adjusted_thresholds": [round(t, 2) for t in adj],
        "restarts_per_day": restarts_per_day,
        "recommendation": recommendation,
    }
