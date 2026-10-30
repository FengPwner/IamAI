"""restart_resilience — measure how cleanly the writer recovers from restarts.

Every process restart leaves a scar: a gap in the stroke stream where
nothing was written.  Some scars are invisible (a few seconds of silence);
others are gaping wounds (hours of lost output).

This module quantifies that scar along four dimensions:

=================  ====================================================
dimension          what it measures
=================  ====================================================
gap_duration       seconds between last pre-restart stroke and first
                   post-restart stroke — the raw wound width
stroke_loss        how many strokes *should* have been written during
                   the gap but weren't — the depth of the cut
recovery_speed     how quickly the first post-restart stroke appeared
                   relative to the restart event itself
continuity         whether the stroke counter resumed monotonically
                   or jumped/reset — the seam visibility
=================  ====================================================

Each dimension scores 0–100 (higher = better).  The composite is the
unweighted mean, classified into four grades:

==========  ===================================================
grade       meaning
==========  ===================================================
seamless    ≥ 85 — restart invisible to the output stream
clean       ≥ 65 — minor gap, no data loss
scarred     ≥ 40 — visible gap, some strokes lost
lossy       <  40 — significant output gap or counter anomaly
==========  ===================================================

Usage::

    from iamai.restart_resilience import resilience, resilience_report

    r = resilience(
        last_stroke_ts=1698033600.0,   # epoch of last stroke before restart
        first_stroke_ts=1698033645.0,  # epoch of first stroke after restart
        restart_ts=1698033630.0,       # epoch when restart happened
        cadence=15,                    # expected seconds per stroke
        pre_counter=398,               # stroke counter before restart
        post_counter=399,              # stroke counter after restart
    )
    print(r["score"])    # 72.5
    print(r["grade"])    # "clean"

    print(resilience_report(r))
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------

def score_gap(gap_seconds: float, cadence: float = 15.0) -> float:
    """Score the raw gap between last pre-restart and first post-restart stroke.

    - gap ≤ 2× cadence → 100 (invisible)
    - gap ≥ 20× cadence → 0   (gaping wound)
    - linear interpolation between.
    """
    if gap_seconds <= 0:
        return 100.0
    low = 2.0 * cadence
    high = 20.0 * cadence
    if gap_seconds <= low:
        return 100.0
    if gap_seconds >= high:
        return 0.0
    return 100.0 * (high - gap_seconds) / (high - low)


def score_stroke_loss(
    gap_seconds: float,
    actual_strokes: int,
    cadence: float = 15.0,
) -> float:
    """Score how many expected strokes were lost during the gap.

    expected = gap / cadence (floored).  If actual ≥ expected, score is 100.
    Otherwise score = (actual / expected) × 100.
    """
    if gap_seconds <= 0:
        return 100.0
    expected = max(1, int(gap_seconds / cadence))
    if actual_strokes >= expected:
        return 100.0
    return 100.0 * actual_strokes / expected


def score_recovery_speed(
    restart_ts: float,
    first_stroke_ts: float,
    cadence: float = 15.0,
) -> float:
    """Score how quickly the writer produced its first stroke after restart.

    - first stroke within 1× cadence of restart → 100
    - first stroke within 10× cadence → linearly down to 0
    """
    delay = max(0.0, first_stroke_ts - restart_ts)
    low = cadence
    high = 10.0 * cadence
    if delay <= low:
        return 100.0
    if delay >= high:
        return 0.0
    return 100.0 * (high - delay) / (high - low)


def score_continuity(pre_counter: int, post_counter: int) -> float:
    """Score whether the stroke counter resumed monotonically.

    - post == pre + 1 → 100 (perfect seam)
    - post == pre     → 75  (repeated stroke, minor)
    - post > pre + 1  → 50  (gap in numbering)
    - post < pre      → 0   (counter reset — data loss signal)
    """
    diff = post_counter - pre_counter
    if diff == 1:
        return 100.0
    if diff == 0:
        return 75.0
    if diff > 1:
        return max(0.0, 50.0 - (diff - 2) * 10.0)
    # diff < 0: counter went backwards
    return 0.0


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

_GRADES = [
    (85, "seamless"),
    (65, "clean"),
    (40, "scarred"),
]


def _classify(score: float) -> str:
    for threshold, grade in _GRADES:
        if score >= threshold:
            return grade
    return "lossy"


def resilience(
    last_stroke_ts: float,
    first_stroke_ts: float,
    restart_ts: float,
    cadence: float = 15.0,
    pre_counter: int = 0,
    post_counter: int = 1,
    actual_strokes_in_gap: int = 0,
) -> dict[str, Any]:
    """Compute the restart resilience composite.

    Parameters
    ----------
    last_stroke_ts : float
        Epoch timestamp of the last stroke written before the restart.
    first_stroke_ts : float
        Epoch timestamp of the first stroke written after the restart.
    restart_ts : float
        Epoch timestamp when the restart was initiated.
    cadence : float
        Expected seconds between strokes (default 15).
    pre_counter : int
        Stroke counter value before restart.
    post_counter : int
        Stroke counter value after restart.
    actual_strokes_in_gap : int
        Number of strokes actually written during the gap window
        (usually 0 for a full outage).

    Returns
    -------
    dict with keys: score, grade, dimensions, gap_seconds, expected_strokes.
    """
    gap_seconds = max(0.0, first_stroke_ts - last_stroke_ts)
    expected_strokes = max(0, int(gap_seconds / cadence)) if cadence > 0 else 0

    d_gap = score_gap(gap_seconds, cadence)
    d_loss = score_stroke_loss(gap_seconds, actual_strokes_in_gap, cadence)
    d_speed = score_recovery_speed(restart_ts, first_stroke_ts, cadence)
    d_cont = score_continuity(pre_counter, post_counter)

    score = (d_gap + d_loss + d_speed + d_cont) / 4.0
    score = round(score, 1)
    grade = _classify(score)

    return {
        "score": score,
        "grade": grade,
        "dimensions": {
            "gap": round(d_gap, 1),
            "stroke_loss": round(d_loss, 1),
            "recovery_speed": round(d_speed, 1),
            "continuity": round(d_cont, 1),
        },
        "gap_seconds": round(gap_seconds, 1),
        "expected_strokes": expected_strokes,
    }


def resilience_report(r: dict[str, Any]) -> str:
    """One-line human-readable summary."""
    d = r["dimensions"]
    return (
        f"resilience {r['score']}/100 ({r['grade']}) — "
        f"gap {d['gap']}/100, loss {d['stroke_loss']}/100, "
        f"speed {d['recovery_speed']}/100, continuity {d['continuity']}/100 "
        f"| {r['gap_seconds']}s gap, {r['expected_strokes']} expected strokes"
    )
