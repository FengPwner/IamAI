"""Restart momentum — measure whether restarts are productive or futile.

A writer that restarts and runs for hours has *positive momentum*: the
system is self-healing and the restart was worth the overhead.  A writer
that restarts and dies within minutes has *negative momentum*: each
restart is wasted effort, and the system is in a crash loop.

This module turns a list of session durations into a single momentum
score, making it easy to distinguish healthy oscillation from decay.

Scoring
-------

==================  ===================================================
range               meaning
==================  ===================================================
``> 0.5``           strong momentum — sessions mostly long, healthy
``0.0 – 0.5``       weak momentum — mixed, some short crashes
``< 0.0``           negative momentum — crash loop, investigate
==================  ===================================================

The score is computed as the mean of signed session scores, where each
session is scored relative to a target duration:

    score_i = (duration_i - target) / target

Sessions longer than the target score positive; shorter ones score
negative.  The result is clamped to [-1.0, 1.0].

Usage::

    from iamai.restart_momentum import momentum_score

    durations_minutes = [45, 120, 3, 90, 60]
    result = momentum_score(durations_minutes, target_minutes=30)
    print(result["score"])       # 0.72
    print(result["verdict"])     # "healthy"

Design choices
--------------

- **Pure function** — takes a list of floats, returns a dict.
- **Configurable target** — the "healthy" session length depends on the
  system; a writer targeting 15-minute strokes has a different target
  than one targeting hourly essays.
- **Crash penalty** — sessions shorter than 10% of the target are
  weighted double to amplify crash-loop signal.

"""

from __future__ import annotations

CRASH_THRESHOLD_RATIO = 0.10  # sessions < 10% of target count double


def momentum_score(
    durations: list[float],
    target_minutes: float = 30.0,
) -> dict:
    """Compute restart momentum from a list of session durations.

    Args:
        durations: list of session durations in minutes (most recent last).
        target_minutes: the expected healthy session length in minutes.

    Returns:
        A dict with keys: ``score``, ``verdict``, ``session_count``,
        ``crash_count``, ``mean_duration``, ``trend``.
    """
    if not durations:
        return {
            "score": 0.0,
            "verdict": "no_data",
            "session_count": 0,
            "crash_count": 0,
            "mean_duration": 0.0,
            "trend": "unknown",
        }

    crash_threshold = target_minutes * CRASH_THRESHOLD_RATIO
    scores: list[float] = []
    crash_count = 0

    for d in durations:
        raw = (d - target_minutes) / target_minutes
        if d < crash_threshold:
            raw *= 2.0
            crash_count += 1
        scores.append(raw)

    raw_score = sum(scores) / len(scores)
    score = max(-1.0, min(1.0, raw_score))

    # Verdict
    if score > 0.5:
        verdict = "healthy"
    elif score > 0.0:
        verdict = "weak"
    else:
        verdict = "crash_loop"

    # Trend: compare recent half to older half
    if len(scores) >= 4:
        mid = len(scores) // 2
        old_avg = sum(scores[:mid]) / mid
        new_avg = sum(scores[mid:]) / (len(scores) - mid)
        delta = new_avg - old_avg
        if delta > 0.1:
            trend = "improving"
        elif delta < -0.1:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "insufficient_data"

    return {
        "score": round(score, 3),
        "verdict": verdict,
        "session_count": len(durations),
        "crash_count": crash_count,
        "mean_duration": round(sum(durations) / len(durations), 2),
        "trend": trend,
    }
