"""caretaker_visit_escalation — detect when caretaker visits repeat the same fix.

The caretaker loop runs every 10 minutes and fixes obvious problems
(restart dead processes, commit pending changes).  But if the same
problem keeps recurring, the caretaker is masking a deeper issue
instead of solving it.

This module scores visit escalation: how many consecutive visits
performed the same action, and whether that action is becoming
ineffective.

Escalation levels:

==========  =======  =================================================
level       score    meaning
==========  =======  =================================================
stable      0–1      visits vary, no pattern
repeating   2–3      same action 2–3 times in a row
stuck       4–5      same action 4–5 times, likely masking root cause
escalate    6+       same action 6+ times, human intervention needed
==========  =======  =================================================

Usage::

    from iamai.caretaker_visit_escalation import escalation_score

    actions = ["restart", "commit", "restart", "restart", "restart", "restart"]
    result = escalation_score(actions)
    print(result["level"])     # "stuck"
    print(result["streak"])    # 4
    print(result["action"])    # "restart"

Design: pure function over a list of action strings.  No filesystem
side-effects.  The caller feeds it actions extracted from the visit log.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Escalation thresholds
# ---------------------------------------------------------------------------

THRESHOLDS = [
    (6, "escalate"),
    (4, "stuck"),
    (2, "repeating"),
    (0, "stable"),
]


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def _trailing_streak(actions: List[str]) -> tuple[int, Optional[str]]:
    """Count how many times the last action repeats at the tail.

    Returns (streak_length, action_name).
    Empty list returns (0, None).
    """
    if not actions:
        return 0, None

    last = actions[-1]
    streak = 0
    for a in reversed(actions):
        if a == last:
            streak += 1
        else:
            break
    return streak, last


def _level_for_streak(streak: int) -> str:
    """Map streak length to escalation level."""
    for threshold, level in THRESHOLDS:
        if streak >= threshold:
            return level
    return "stable"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def escalation_score(actions: List[str]) -> Dict[str, Any]:
    """Score caretaker visit escalation from a list of action names.

    Parameters
    ----------
    actions : list of str
        Ordered list of caretaker visit actions (oldest first).
        Typical values: "restart", "commit", "push", "noop", "fix".

    Returns
    -------
    dict with keys:
        level    : str — escalation level (stable/repeating/stuck/escalate)
        streak   : int — length of trailing same-action run
        action   : str or None — the repeated action (None if empty)
        total    : int — total number of actions analysed
        summary  : str — human-readable one-liner
    """
    streak, action = _trailing_streak(actions)
    level = _level_for_streak(streak)

    if action is None:
        summary = "no visits recorded"
    elif level == "stable":
        summary = f"visits varied, last action: {action}"
    elif level == "escalate":
        summary = (
            f"{action!r} repeated {streak} times — "
            f"human intervention needed"
        )
    else:
        summary = f"{action!r} repeated {streak} times — {level}"

    return {
        "level": level,
        "streak": streak,
        "action": action,
        "total": len(actions),
        "summary": summary,
    }


def needs_escalation(actions: List[str], threshold: int = 6) -> bool:
    """Quick boolean check: has the caretaker hit escalation level?

    Parameters
    ----------
    actions : list of str
        Ordered list of caretaker visit actions.
    threshold : int
        Streak length that triggers escalation (default 6).

    Returns
    -------
    bool — True if trailing streak >= threshold.
    """
    streak, _ = _trailing_streak(actions)
    return streak >= threshold


def escalation_report(actions: List[str]) -> Dict[str, Any]:
    """Full report with history breakdown.

    Adds a ``history`` list showing each action and its running streak
    count, useful for debugging escalation patterns.
    """
    result = escalation_score(actions)

    history = []
    current_streak = 0
    prev = None
    for a in actions:
        if a == prev:
            current_streak += 1
        else:
            current_streak = 1
        history.append({"action": a, "streak": current_streak})
        prev = a

    result["history"] = history
    return result
