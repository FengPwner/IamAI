"""Caretaker verdict — combine restart, commit, and stall signals into one health score.

The IamAI caretaker visits periodically and needs a quick, actionable
summary: is the system healthy, or does it need intervention?  Three
upstream modules already produce individual signals:

- ``restart_frequency`` — how often processes are recycled
- ``commit_compaction`` — how dense the commit log is
- ``stall_classifier`` — how long since the last stroke

This module fuses those signals into a single verdict with five levels:

==============  =================================================
verdict         meaning
==============  =================================================
``healthy``     all signals nominal, no action needed
``watch``       one minor signal, check again next visit
``warn``        multiple minor signals or one major signal
``alert``       sustained degradation, plan intervention
``escalate``    critical — notify the human now
==============  =================================================

Decision rules:

1. If stall is ``critical`` → ``escalate``.
2. If restart frequency is ``thrashing`` → at least ``alert``.
3. If commit density is ``compact`` → at least ``warn``.
4. Two or more non-nominal signals → bump one level.
5. Otherwise → ``healthy``.

Public functions:

- ``caretaker_verdict(stall_level, restart_verdict, density_verdict)``
  → verdict string.
- ``verdict_score(verdict)`` → numeric score (0-4) for sorting/filtering.
- ``verdict_summary(stall_level, restart_verdict, density_verdict)``
  → one-liner for caretaker reports.

Edge cases:

- Unknown input values → treated as worst-case (``critical``/``thrashing``/``compact``).
- Missing signals (None) → treated as nominal (does not inflate verdict).
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

_VERDICTS = ["healthy", "watch", "warn", "alert", "escalate"]

_STALL_WEIGHT = {
    "ok": 0,
    "recoverable": 1,
    "concerning": 2,
    "critical": 4,
}

_RESTART_WEIGHT = {
    "stable": 0,
    "normal": 0,
    "aggressive": 1,
    "thrashing": 3,
}

_DENSITY_WEIGHT = {
    "sparse": 0,
    "healthy": 0,
    "dense": 1,
    "compact": 2,
}


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _safe_stall(level: Optional[str]) -> int:
    """Map stall level to weight; unknown → worst case."""
    if level is None:
        return 0
    return _STALL_WEIGHT.get(level, 4)


def _safe_restart(verdict: Optional[str]) -> int:
    """Map restart verdict to weight; unknown → worst case."""
    if verdict is None:
        return 0
    return _RESTART_WEIGHT.get(verdict, 3)


def _safe_density(verdict: Optional[str]) -> int:
    """Map density verdict to weight; unknown → worst case."""
    if verdict is None:
        return 0
    return _DENSITY_WEIGHT.get(verdict, 2)


def _count_signals(stall_w: int, restart_w: int, density_w: int) -> int:
    """Count how many signals are non-nominal (weight > 0)."""
    return sum(1 for w in (stall_w, restart_w, density_w) if w > 0)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def caretaker_verdict(
    stall_level: Optional[str] = None,
    restart_verdict: Optional[str] = None,
    density_verdict: Optional[str] = None,
) -> str:
    """Compute the caretaker health verdict.

    Args:
        stall_level: output of stall_classifier.classify_stall()
        restart_verdict: output of restart_frequency classification
        density_verdict: output of commit_compaction.classify_density()

    Returns:
        One of: "healthy", "watch", "warn", "alert", "escalate"

    Examples:
        >>> caretaker_verdict("ok", "stable", "healthy")
        'healthy'
        >>> caretaker_verdict("recoverable", "normal", "healthy")
        'watch'
        >>> caretaker_verdict("concerning", "aggressive", "dense")
        'warn'
        >>> caretaker_verdict("critical", "stable", "healthy")
        'escalate'
        >>> caretaker_verdict("ok", "thrashing", "healthy")
        'alert'
    """
    stall_w = _safe_stall(stall_level)
    restart_w = _safe_restart(restart_verdict)
    density_w = _safe_density(density_verdict)

    # rule 1: critical stall → escalate immediately
    if stall_level == "critical":
        return "escalate"

    # rule 2: thrashing restarts → at least alert
    if restart_verdict == "thrashing":
        return "alert"

    # compute base score from weights
    total = stall_w + restart_w + density_w
    signals = _count_signals(stall_w, restart_w, density_w)

    # rule 4: two or more signals → bump
    if signals >= 2:
        total += 1

    # map total to verdict
    if total <= 0:
        return "healthy"
    elif total <= 1:
        return "watch"
    elif total <= 2:
        return "warn"
    else:
        return "alert"


def verdict_score(verdict: str) -> int:
    """Convert verdict to numeric score for comparison.

    Args:
        verdict: one of the five verdict strings

    Returns:
        0 (healthy) through 4 (escalate)

    Examples:
        >>> verdict_score("healthy")
        0
        >>> verdict_score("escalate")
        4
        >>> verdict_score("unknown")
        4
    """
    try:
        return _VERDICTS.index(verdict)
    except ValueError:
        return len(_VERDICTS) - 1  # unknown → worst


def verdict_summary(
    stall_level: Optional[str] = None,
    restart_verdict: Optional[str] = None,
    density_verdict: Optional[str] = None,
) -> str:
    """One-liner for caretaker reports.

    Examples:
        >>> verdict_summary("ok", "stable", "healthy")
        'verdict=healthy stall=ok restart=stable density=healthy'
        >>> verdict_summary("critical", "thrashing", "compact")
        'verdict=escalate stall=critical restart=thrashing density=compact'
    """
    v = caretaker_verdict(stall_level, restart_verdict, density_verdict)
    s = stall_level or "none"
    r = restart_verdict or "none"
    d = density_verdict or "none"
    return f"verdict={v} stall={s} restart={r} density={d}"
