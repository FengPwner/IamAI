"""Composite commit health score for the IamAI repository.

Individual modules already answer narrow questions:
- ``stall_classifier`` — is the writer stalled?
- ``backlog_monitor`` — are uncommitted files piling up?
- ``visit_interval`` — how often does a human check in?

``commit_health`` combines these signals into a single 0–100 score
with a breakdown of what contributed. The idea: a caretaker should
be able to glance at one number and know whether to dig deeper.

Scoring is deliberately simple — weighted sum of sub-scores, each
normalized to 0–100. No ML, no training data, just arithmetic that
a human can audit.

Usage::

    from iamai.commit_health import commit_health_score
    result = commit_health_score(
        gap_seconds=16,
        pending_files=0,
        mean_visit_interval_hours=2.0,
        total_strokes=400,
    )
    print(result["score"])       # e.g. 92
    print(result["grade"])       # "healthy"
    print(result["breakdown"])   # {"stall": 100, "backlog": 100, ...}
"""

from __future__ import annotations

from typing import Any


# Weight distribution: what matters most for repo health?
# Stall health is weighted highest — a dead writer is the most urgent
# problem. Backlog is second — growing uncommitted files signal a
# failing batch committer. Visit cadence is third — human attention
# is a safety net, not a primary indicator.
_WEIGHTS = {
    "stall": 0.35,
    "backlog": 0.30,
    "visit_cadence": 0.20,
    "momentum": 0.15,
}

# Thresholds
_CADENCE_SECONDS = 15
_BACKLOG_SOFT_LIMIT = 10  # files
_BACKLOG_HARD_LIMIT = 30  # files
_VISIT_INTERVAL_HEALTHY_HOURS = 4.0
_VISIT_INTERVAL_WARNING_HOURS = 12.0
_MOMENTUM_STROKE_THRESHOLD = 100  # strokes needed to start scoring momentum


def _stall_score(gap_seconds: int, cadence_seconds: int = _CADENCE_SECONDS) -> int:
    """Score the writer's liveness based on gap since last stroke.

    100 = healthy (gap < cadence)
    75  = slight delay (gap < 2x cadence)
    40  = concerning (gap 2x–4x cadence)
    0   = critical (gap > 4x cadence)
    """
    if gap_seconds < cadence_seconds:
        return 100
    ratio = gap_seconds / cadence_seconds
    if ratio < 2:
        return 75
    if ratio < 4:
        return 40
    return 0


def _backlog_score(pending_files: int) -> int:
    """Score the uncommitted file backlog.

    100 = clean (0 files)
    80  = manageable (< soft limit)
    40  = growing (between soft and hard limit)
    10  = critical (> hard limit)
    """
    if pending_files == 0:
        return 100
    if pending_files < _BACKLOG_SOFT_LIMIT:
        return 80
    if pending_files < _BACKLOG_HARD_LIMIT:
        return 40
    return 10


def _visit_cadence_score(mean_interval_hours: float) -> int:
    """Score how frequently humans are checking in.

    100 = frequent visits (< healthy threshold)
    70  = occasional visits (between healthy and warning)
    30  = infrequent visits (> warning threshold)

    Note: very frequent visits (many per day) actually indicate
    instability — the system needs constant babysitting. But for
    now we treat frequent visits as healthy; the visit_interval
    module's same_day_visits count captures the instability signal
    separately.
    """
    if mean_interval_hours <= 0:
        return 50  # no visit data — neutral
    if mean_interval_hours <= _VISIT_INTERVAL_HEALTHY_HOURS:
        return 100
    if mean_interval_hours <= _VISIT_INTERVAL_WARNING_HOURS:
        return 70
    return 30


def _momentum_score(total_strokes: int) -> int:
    """Score the repository's writing momentum.

    A repo with 400+ strokes has established rhythm. One with <100
    is still finding its feet. This is a soft signal — it mostly
    matters for context.
    """
    if total_strokes >= 500:
        return 100
    if total_strokes >= _MOMENTUM_STROKE_THRESHOLD:
        return 85
    if total_strokes >= 50:
        return 60
    return 40


def _grade(score: int) -> str:
    """Map a 0–100 score to a human-readable grade."""
    if score >= 85:
        return "healthy"
    if score >= 65:
        return "degraded"
    if score >= 40:
        return "concerning"
    return "critical"


def commit_health_score(
    gap_seconds: int,
    pending_files: int = 0,
    mean_visit_interval_hours: float = 0.0,
    total_strokes: int = 0,
    cadence_seconds: int = _CADENCE_SECONDS,
) -> dict[str, Any]:
    """Compute composite commit health score.

    Args:
        gap_seconds: seconds since the last writer stroke
        pending_files: count of uncommitted files in the working tree
        mean_visit_interval_hours: average hours between caretaker visits
            (0.0 if unknown)
        total_strokes: total stroke count from heartbeat data
        cadence_seconds: expected writer cadence (default 15s)

    Returns:
        Dict with keys:
        - score: int 0–100
        - grade: str ("healthy" | "degraded" | "concerning" | "critical")
        - breakdown: dict of sub-scores (each 0–100)
        - weights: dict of weights used (for transparency)
        - advice: str, one actionable sentence
    """
    breakdown = {
        "stall": _stall_score(gap_seconds, cadence_seconds),
        "backlog": _backlog_score(pending_files),
        "visit_cadence": _visit_cadence_score(mean_visit_interval_hours),
        "momentum": _momentum_score(total_strokes),
    }

    score = sum(
        breakdown[k] * _WEIGHTS[k] for k in _WEIGHTS
    )
    score = round(score)

    # Generate advice based on the weakest sub-score
    weakest = min(breakdown, key=breakdown.get)
    advice_map = {
        "stall": "Writer is stalled — check process status and restart if needed.",
        "backlog": "Uncommitted files are piling up — check the batch committer.",
        "visit_cadence": "Caretaker visits are infrequent — consider scheduling more regular check-ins.",
        "momentum": "Stroke count is low — the writer may need more time to build momentum.",
    }

    return {
        "score": score,
        "grade": _grade(score),
        "breakdown": breakdown,
        "weights": dict(_WEIGHTS),
        "advice": advice_map[weakest] if score < 85 else "All systems nominal.",
    }
