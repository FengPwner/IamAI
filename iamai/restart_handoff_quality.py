#!/usr/bin/env python3
"""restart_handoff_quality — measure how cleanly a writer restart hands off.

A restart is not an instant event.  Between the last stroke of the old
process and the first stroke of the new one, there is a gap.  The quality
of that gap determines whether the restart was a non-event or a data-loss
incident.

This module scores a restart on three dimensions:

===================  ======================================================
dimension            what it measures
===================  ======================================================
**continuity**       is the sequence number gap exactly 1?  More means
                     strokes were lost; 0 means the old process wrote
                     after the new one started (overlap).
**latency**          seconds between last old stroke and first new stroke.
                     < 60 s is excellent; 60–300 s is acceptable; > 300 s
                     means the caretaker was slow or the restart failed
                     silently before producing output.
**cadence_recovery** does the new process reach its configured interval
                     within the first 5 strokes?  Measured as the ratio
                     of the 5th inter-stroke gap to the target interval.
                     ≤ 1.5 is clean; ≤ 3.0 is warming up; > 3.0 is
                     struggling.
===================  ======================================================

The composite score is the minimum of the three dimension grades, because
a restart that is fast but loses data is not a good restart.

Public API
----------

.. autofunction:: score_handoff
.. autofunction:: classify_handoff
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp robustly."""
    s = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # fallback: strip fractional seconds
        if "." in s:
            base, rest = s.split(".", 1)
            # find the timezone part after the fraction
            for i, ch in enumerate(rest):
                if ch in ("+", "-"):
                    frac = rest[:i][:6]  # keep up to 6 digits
                    tz = rest[i:]
                    s = f"{base}.{frac}{tz}"
                    break
            else:
                s = f"{base}.{rest[:6]}"
            return datetime.fromisoformat(s)
        raise


def score_handoff(
    old_history: list[dict[str, Any]],
    new_history: list[dict[str, Any]],
    target_interval: int = 15,
) -> dict[str, Any]:
    """Score a restart handoff between two writer incarnations.

    Parameters
    ----------
    old_history : list of stroke dicts from the old process (sorted by ``at``).
    new_history : list of stroke dicts from the new process (sorted by ``at``).
    target_interval : the configured stroke interval in seconds.

    Returns
    -------
    dict with keys: ``continuity``, ``latency_s``, ``cadence_ratio``,
    ``grade``, and ``details``.
    """
    if not old_history or not new_history:
        return {
            "continuity": None,
            "latency_s": None,
            "cadence_ratio": None,
            "grade": "unknown",
            "details": "insufficient data — need strokes from both sides of the restart",
        }

    last_old = old_history[-1]
    first_new = new_history[0]

    # --- continuity: sequence gap ----------------------------------------
    old_seq = last_old.get("seq")
    new_seq = first_new.get("seq")
    seq_gap = None
    continuity_score = "unknown"
    if old_seq is not None and new_seq is not None:
        seq_gap = new_seq - old_seq
        if seq_gap == 1:
            continuity_score = "clean"
        elif seq_gap <= 0:
            continuity_score = "overlap"
        elif seq_gap <= 3:
            continuity_score = "minor_gap"
        else:
            continuity_score = "data_loss"

    # --- latency: wall-clock gap -----------------------------------------
    last_old_at = _parse_iso(last_old["at"])
    first_new_at = _parse_iso(first_new["at"])
    latency_s = (first_new_at - last_old_at).total_seconds()

    if latency_s < 0:
        latency_score = "overlap"
    elif latency_s < 60:
        latency_score = "excellent"
    elif latency_s < 300:
        latency_score = "acceptable"
    elif latency_s < 900:
        latency_score = "slow"
    else:
        latency_score = "stalled"

    # --- cadence recovery: first 5 intervals -----------------------------
    cadence_ratio = None
    cadence_score = "unknown"
    if len(new_history) >= 6:
        # measure the 5th inter-stroke gap (index 5 - index 4)
        intervals = []
        for i in range(1, min(6, len(new_history))):
            dt = (
                _parse_iso(new_history[i]["at"])
                - _parse_iso(new_history[i - 1]["at"])
            ).total_seconds()
            intervals.append(dt)
        if intervals:
            fifth_gap = intervals[-1]
            cadence_ratio = fifth_gap / target_interval if target_interval > 0 else None
            if cadence_ratio is not None:
                if cadence_ratio <= 1.5:
                    cadence_score = "clean"
                elif cadence_ratio <= 3.0:
                    cadence_score = "warming"
                else:
                    cadence_score = "struggling"

    # --- composite grade (minimum of dimensions) -------------------------
    _grade_order = ["clean", "excellent", "acceptable", "warming",
                    "minor_gap", "slow", "overlap", "struggling",
                    "stalled", "data_loss", "unknown"]

    scores = [s for s in [continuity_score, latency_score, cadence_score]
              if s != "unknown"]
    if not scores:
        grade = "unknown"
    else:
        # composite = worst dimension (highest index in severity order)
        grade = max(scores, key=lambda s: _grade_order.index(s)
                    if s in _grade_order else 999)

    return {
        "continuity": continuity_score,
        "latency_s": round(latency_s, 1),
        "cadence_ratio": round(cadence_ratio, 2) if cadence_ratio is not None else None,
        "grade": grade,
        "details": {
            "seq_gap": seq_gap,
            "latency_score": latency_score,
            "cadence_score": cadence_score,
        },
    }


def classify_handoff(score: dict[str, Any]) -> str:
    """Return a one-line human-readable classification.

    >>> classify_handoff({"grade": "clean", "latency_s": 18.0})
    'clean restart — 18.0s gap, no data loss'
    """
    grade = score.get("grade", "unknown")
    latency = score.get("latency_s", "?")

    if grade == "unknown":
        return "insufficient data to classify restart quality"
    if grade in ("clean", "excellent", "acceptable"):
        return f"clean restart — {latency}s gap, no data loss"
    if grade == "minor_gap":
        seq_gap = score.get("details", {}).get("seq_gap", "?")
        return f"restart with minor gap — {seq_gap} stroke(s) may be missing"
    if grade == "slow":
        return f"slow restart — {latency}s gap, check caretaker responsiveness"
    if grade in ("overlap",):
        return "process overlap detected — old writer produced strokes after new one started"
    if grade == "data_loss":
        seq_gap = score.get("details", {}).get("seq_gap", "?")
        return f"data loss — {seq_gap} strokes missing across restart boundary"
    if grade == "stalled":
        return f"restart stalled — {latency}s before first new stroke"
    if grade == "struggling":
        ratio = score.get("cadence_ratio", "?")
        return f"cadence struggling — 5th stroke at {ratio}x target interval"
    return f"restart grade: {grade}"
