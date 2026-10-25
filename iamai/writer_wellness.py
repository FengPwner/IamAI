"""writer_wellness — holistic health index synthesising multiple writer signals.

``writer_vitality`` gives a point-in-time snapshot.  ``writer_fatigue``
detects session-level degradation.  ``writer_heartbeat`` answers "is it
alive *right now*?".  Each is useful, but none captures the full picture
across a sustained writing session.

Wellness synthesises **five** existing signal families into one score,
adds a **trend** dimension (improving / stable / declining), and
surfaces the weakest signal so a caretaker knows where to intervene.

Signals
-------

=======================  =================================================
signal                   source / analogy
=======================  =================================================
``freshness``            inverse of seconds since last stroke
                         (1.0 = just wrote, 0.0 = silent > 5 min)
``cadence``              1 − CV of recent inter-stroke gaps
                         (1.0 = metronomic, 0.0 = wildly irregular)
``diversity``            normalised entropy of stroke-type distribution
                         (1.0 = perfectly balanced, 0.0 = one type only)
``novelty``              mean token-level novelty over recent strokes
                         (1.0 = every word is new, 0.0 = pure repetition)
``process``              fraction of expected processes still running
                         (1.0 = all up, 0.0 = none alive)
=======================  =================================================

Each signal is clamped to [0.0, 1.0] before weighting.  The composite
``wellness_score`` is the unweighted mean × 100 → 0–100.

Grades
------

==========  ===================================================
grade       meaning
==========  ===================================================
thriving    ≥ 80 — all dimensions healthy, output rich & steady
fit         ≥ 60 — minor softness, nothing actionable
weary       ≥ 40 — at least one dimension degraded noticeably
strained    ≥ 20 — multiple dimensions failing, needs attention
critical    <  20 — writer effectively non-functional
==========  ===================================================

Trend
-----

Two consecutive wellness snapshots are compared.  If the second is
≥ 5 points higher → ``improving``; ≥ 5 lower → ``declining``;
otherwise ``stable``.

Recommendations
---------------

The lowest-scoring signal is surfaced as the primary intervention
target.  Ties broken by signal priority order (process > freshness >
cadence > novelty > diversity).

Usage::

    from iamai.writer_wellness import wellness, wellness_summary

    w = wellness(
        freshness_age=30.0,
        cadence_cv=0.12,
        type_evenness=0.85,
        novelty_mean=0.62,
        processes_alive=2,
        processes_expected=2,
    )
    print(w["score"])        # 87.0
    print(w["grade"])        # "thriving"
    print(w["weakest"])      # "novelty"

    print(wellness_summary(w))
    # "wellness 87/100 (thriving) — freshness 0.94, cadence 0.88,
    #  diversity 0.85, novelty 0.62, process 1.00 [weakest: novelty]"
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Signal normalisers
# ---------------------------------------------------------------------------

# Freshness: seconds since last stroke → [0, 1]
#   ≤ 30 s  → 1.0  (just wrote)
#   ≥ 300 s → 0.0  (silent > 5 min)
_FRESHNESS_CEILING = 30.0
_FRESHNESS_FLOOR = 300.0

# Cadence: CV (coefficient of variation) → [0, 1]
#   CV ≤ 0.10 → 1.0  (very steady)
#   CV ≥ 1.00 → 0.0  (wildly irregular)
_CADENCE_GOOD = 0.10
_CADENCE_BAD = 1.00

# Process: fraction alive → [0, 1]  (linear)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, v))


def freshness_signal(age_seconds: float) -> float:
    """Convert seconds-since-last-stroke to a 0–1 freshness signal.

    >>> freshness_signal(10.0)
    1.0
    >>> freshness_signal(165.0)
    0.5
    >>> freshness_signal(300.0)
    0.0
    >>> freshness_signal(600.0)
    0.0
    """
    age = max(0.0, float(age_seconds))
    if age <= _FRESHNESS_CEILING:
        return 1.0
    if age >= _FRESHNESS_FLOOR:
        return 0.0
    # Linear interpolation between ceiling and floor
    span = _FRESHNESS_FLOOR - _FRESHNESS_CEILING
    return 1.0 - (age - _FRESHNESS_CEILING) / span


def cadence_signal(cv: float) -> float:
    """Convert coefficient-of-variation to a 0–1 cadence signal.

    >>> cadence_signal(0.05)
    1.0
    >>> cadence_signal(0.55)
    0.5
    >>> cadence_signal(1.0)
    0.0
    >>> cadence_signal(2.0)
    0.0
    """
    cv = max(0.0, float(cv))
    if cv <= _CADENCE_GOOD:
        return 1.0
    if cv >= _CADENCE_BAD:
        return 0.0
    span = _CADENCE_BAD - _CADENCE_GOOD
    return 1.0 - (cv - _CADENCE_GOOD) / span


def diversity_signal(evenness: float) -> float:
    """Normalised entropy → 0–1 diversity signal (pass-through, clamped).

    >>> diversity_signal(0.92)
    0.92
    >>> diversity_signal(1.5)
    1.0
    >>> diversity_signal(-0.1)
    0.0
    """
    return _clamp(float(evenness))


def novelty_signal(mean_novelty: float) -> float:
    """Mean token-level novelty → 0–1 novelty signal (pass-through, clamped).

    >>> novelty_signal(0.62)
    0.62
    >>> novelty_signal(1.1)
    1.0
    """
    return _clamp(float(mean_novelty))


def process_signal(alive: int, expected: int) -> float:
    """Fraction of expected processes still running.

    >>> process_signal(2, 2)
    1.0
    >>> process_signal(1, 2)
    0.5
    >>> process_signal(0, 2)
    0.0
    >>> process_signal(0, 0)
    1.0
    """
    if expected <= 0:
        return 1.0  # nothing expected → nothing broken
    return _clamp(alive / expected)


# ---------------------------------------------------------------------------
# Composite wellness
# ---------------------------------------------------------------------------

_GRADE_THRESHOLDS = [
    (80, "thriving"),
    (60, "fit"),
    (40, "weary"),
    (20, "strained"),
    (0, "critical"),
]

# Priority order for tie-breaking weakest signal (higher priority first)
_SIGNAL_PRIORITY = ["process", "freshness", "cadence", "novelty", "diversity"]


def _grade(score: float) -> str:
    """Map a 0–100 score to a qualitative grade."""
    for threshold, label in _GRADE_THRESHOLDS:
        if score >= threshold:
            return label
    return "critical"  # pragma: no cover


def wellness(
    *,
    freshness_age: float,
    cadence_cv: float,
    type_evenness: float,
    novelty_mean: float,
    processes_alive: int,
    processes_expected: int,
) -> dict[str, Any]:
    """Compute a holistic writer wellness snapshot.

    Parameters
    ----------
    freshness_age:
        Seconds since the last stroke was produced.
    cadence_cv:
        Coefficient of variation of recent inter-stroke gaps.
    type_evenness:
        Normalised entropy of stroke-type distribution (0–1).
    novelty_mean:
        Mean token-level novelty over recent strokes (0–1).
    processes_alive:
        Number of writer/batch processes currently running.
    processes_expected:
        Number of processes that *should* be running.

    Returns
    -------
    dict with keys:
        score (float, 0–100), grade (str),
        signals (dict of 5 signal values),
        weakest (str — name of lowest-scoring signal).
    """
    signals = {
        "freshness": round(freshness_signal(freshness_age), 4),
        "cadence": round(cadence_signal(cadence_cv), 4),
        "diversity": round(diversity_signal(type_evenness), 4),
        "novelty": round(novelty_signal(novelty_mean), 4),
        "process": round(process_signal(processes_alive, processes_expected), 4),
    }

    score = round(sum(signals.values()) / len(signals) * 100, 1)

    # Weakest signal — ties broken by priority order
    weakest = min(_SIGNAL_PRIORITY, key=lambda k: signals[k])

    return {
        "score": score,
        "grade": _grade(score),
        "signals": signals,
        "weakest": weakest,
    }


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------

def trend(previous: dict[str, Any], current: dict[str, Any]) -> str:
    """Compare two wellness snapshots and return the trend direction.

    Returns ``"improving"``, ``"stable"``, or ``"declining"``.

    >>> trend({"score": 70.0}, {"score": 80.0})
    'improving'
    >>> trend({"score": 70.0}, {"score": 72.0})
    'stable'
    >>> trend({"score": 70.0}, {"score": 60.0})
    'declining'
    """
    diff = current["score"] - previous["score"]
    if diff >= 5:
        return "improving"
    if diff <= -5:
        return "declining"
    return "stable"


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def wellness_summary(w: dict[str, Any]) -> str:
    """One-line human-readable wellness summary.

    >>> w = wellness(
    ...     freshness_age=30.0, cadence_cv=0.12,
    ...     type_evenness=0.85, novelty_mean=0.62,
    ...     processes_alive=2, processes_expected=2,
    ... )
    >>> s = wellness_summary(w)
    >>> "wellness" in s and "thriving" in s
    True
    """
    sigs = w["signals"]
    parts = ", ".join(f"{k} {v:.2f}" for k, v in sigs.items())
    return (
        f"wellness {w['score']:.0f}/100 ({w['grade']}) — "
        f"{parts} [weakest: {w['weakest']}]"
    )
