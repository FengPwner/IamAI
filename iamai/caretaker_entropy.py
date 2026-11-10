#!/usr/bin/env python3
"""caretaker_entropy — measure whether the caretaker is building or firefighting.

Every caretaker visit leaves a fingerprint: the set of actions taken.
Some visits are *proactive* — new modules, analysis notes, tooling
improvements, original content.  Others are *reactive* — restarting
dead processes, committing backlogs, fixing push failures, rescuing
SSH keys.  A healthy long-running system should trend toward more
proactive work over time as the reactive failure modes get engineered
away.  If the ratio stays flat or worsens, the system is stuck in a
firefighting loop and the caretaker never gets ahead of the entropy.

This module answers one question: **is the caretaker winning?**

Signal dimensions
-----------------

=====================  ====================================================
metric                 meaning
=====================  ====================================================
proactive_fraction     fraction of visits in window classified as proactive
reactive_fraction      fraction classified as reactive
mixed_fraction         fraction with no clear dominant class
trend_direction        improving | stable | degrading
trend_slope            change in proactive_fraction per visit (linear fit)
health                 winning | treading_water | losing | unknown
entropy_class          low-entropy (focused proactive) vs high-entropy
                       (scattered reactive)
window_size            number of visits used for classification
=====================  ====================================================

Health classes
--------------

===============  ============================================================
class            meaning
===============  ============================================================
winning          proactive_fraction >= 0.6 AND trend not degrading
treading_water   0.4 <= proactive_fraction < 0.6 OR stable trend at any level
losing           proactive_fraction < 0.4 AND trend is degrading
unknown          fewer visits than one full window — not enough data
===============  ============================================================

Visit classification
--------------------

Each visit is classified by its *dominant* action type:

==================  ========================================================
action class        examples
==================  ========================================================
restart             process restart, resurrection, revival
push_repair         rebase, force-push, divergence resolution, merge fix
backlog_drain       catch-up commits, committing accumulated files
lock_cleanup        stale lock removal, PID file cleanup
ssh_rescue          SSH key restoration, known_hosts fix, permission repair
new_content         new notes, modules, analysis, original writing
new_module          adding a Python module with tests
tooling             new monitoring scripts, diagnostics, CLI tools
analysis            metrics review, pattern identification, postmortems
maintenance         routine status checks, small config tweaks
==================  ========================================================

The first five are **reactive**; the next four are **proactive**;
*maintenance* is **neutral** (counted as mixed).

When a visit has actions from both sides, the *majority* wins.  A visit
that restarts processes and then writes a new module counts as proactive
because the new content is the higher-value action (weighted voting:
proactive actions weight 2, reactive weight 1, so one module outweighs
one restart).

Usage::

    from iamai.caretaker_entropy import entropy_report

    visits = [
        {"id": 580, "actions": ["restart", "backlog_drain"]},
        {"id": 581, "actions": ["new_module"]},
        {"id": 582, "actions": ["restart"]},
        {"id": 583, "actions": ["new_content", "analysis"]},
        ...
    ]

    r = entropy_report(visits, window=20)
    print(r["health"])              # "winning"
    print(r["proactive_fraction"])  # 0.65
    print(r["trend_direction"])     # "improving"
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Action taxonomy
# ---------------------------------------------------------------------------

REACTIVE_ACTIONS: frozenset[str] = frozenset({
    "restart",
    "push_repair",
    "backlog_drain",
    "lock_cleanup",
    "ssh_rescue",
})

PROACTIVE_ACTIONS: frozenset[str] = frozenset({
    "new_content",
    "new_module",
    "tooling",
    "analysis",
})

NEUTRAL_ACTIONS: frozenset[str] = frozenset({
    "maintenance",
})

ALL_KNOWN_ACTIONS: frozenset[str] = (
    REACTIVE_ACTIONS | PROACTIVE_ACTIONS | NEUTRAL_ACTIONS
)

# Weighted voting: proactive actions count double so that a visit that
# restarts processes AND writes a new module is classified as proactive.
PROACTIVE_WEIGHT: int = 2
REACTIVE_WEIGHT: int = 1
NEUTRAL_WEIGHT: int = 0  # does not tip the scale

# ---------------------------------------------------------------------------
# Visit classification
# ---------------------------------------------------------------------------

def classify_action(action: str) -> str:
    """Return 'proactive', 'reactive', or 'neutral' for a single action.

    Unknown actions are classified as 'neutral' to avoid silently
    skewing the ratio.

    >>> classify_action("restart")
    'reactive'
    >>> classify_action("new_module")
    'proactive'
    >>> classify_action("maintenance")
    'neutral'
    >>> classify_action("something_new")
    'neutral'
    """
    if action in PROACTIVE_ACTIONS:
        return "proactive"
    if action in REACTIVE_ACTIONS:
        return "reactive"
    return "neutral"


def classify_visit(actions: list[str]) -> str:
    """Classify a visit by its dominant action type.

    Uses weighted voting: each proactive action counts as 2, each
    reactive action counts as 1.  The side with more weight wins.
    A tie (or all-neutral visit) is classified as 'mixed'.

    Returns one of: 'proactive', 'reactive', 'mixed'.

    >>> classify_visit(["restart"])
    'reactive'
    >>> classify_visit(["new_module"])
    'proactive'
    >>> classify_visit(["restart", "new_module"])
    'proactive'
    >>> classify_visit(["restart", "push_repair", "new_content"])
    'reactive'
    >>> classify_visit([])
    'mixed'
    >>> classify_visit(["maintenance"])
    'mixed'
    """
    if not actions:
        return "mixed"

    proactive_score = sum(
        PROACTIVE_WEIGHT for a in actions if classify_action(a) == "proactive"
    )
    reactive_score = sum(
        REACTIVE_WEIGHT for a in actions if classify_action(a) == "reactive"
    )

    if proactive_score > reactive_score:
        return "proactive"
    if reactive_score > proactive_score:
        return "reactive"
    return "mixed"


def classify_visits(visits: list[dict[str, Any]]) -> list[str]:
    """Classify a list of visits.  Each visit must have an 'actions' key.

    Returns a list of classification strings in the same order.

    >>> classify_visits([
    ...     {"actions": ["restart"]},
    ...     {"actions": ["new_module"]},
    ...     {"actions": []},
    ... ])
    ['reactive', 'proactive', 'mixed']
    """
    return [classify_visit(v.get("actions", [])) for v in visits]


# ---------------------------------------------------------------------------
# Entropy scoring
# ---------------------------------------------------------------------------

def _fractions(classifications: list[str]) -> dict[str, float]:
    """Compute proactive / reactive / mixed fractions.

    >>> _fractions(["proactive", "reactive", "proactive", "mixed"])
    {'proactive_fraction': 0.5, 'reactive_fraction': 0.25, 'mixed_fraction': 0.25}
    >>> _fractions([])
    {'proactive_fraction': 0.0, 'reactive_fraction': 0.0, 'mixed_fraction': 0.0}
    """
    n = len(classifications)
    if n == 0:
        return {
            "proactive_fraction": 0.0,
            "reactive_fraction": 0.0,
            "mixed_fraction": 0.0,
        }
    p = sum(1 for c in classifications if c == "proactive")
    r = sum(1 for c in classifications if c == "reactive")
    m = sum(1 for c in classifications if c == "mixed")
    return {
        "proactive_fraction": round(p / n, 4),
        "reactive_fraction": round(r / n, 4),
        "mixed_fraction": round(m / n, 4),
    }


def entropy_score(
    visits: list[dict[str, Any]],
    window: int = 20,
) -> dict[str, float]:
    """Compute entropy fractions over the most recent *window* visits.

    If fewer than *window* visits are provided, uses all available visits.

    >>> entropy_score([{"actions": ["new_module"]}], window=20)
    {'proactive_fraction': 1.0, 'reactive_fraction': 0.0, 'mixed_fraction': 0.0, 'window_size': 1}
    """
    recent = visits[-window:] if len(visits) > window else visits
    cls = classify_visits(recent)
    result = _fractions(cls)
    result["window_size"] = len(recent)
    return result


# ---------------------------------------------------------------------------
# Trend detection
# ---------------------------------------------------------------------------

def _linear_slope(values: list[float]) -> float:
    """Compute the slope of a simple linear regression (y on x).

    x = [0, 1, 2, ..., n-1], y = values.
    Returns 0.0 for fewer than 2 data points.

    >>> _linear_slope([0.0, 0.5, 1.0])
    0.5
    >>> _linear_slope([1.0, 0.5, 0.0])
    -0.5
    >>> _linear_slope([0.5])
    0.0
    >>> _linear_slope([])
    0.0
    """
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def entropy_trend(
    visits: list[dict[str, Any]],
    window: int = 20,
    step: int = 5,
) -> dict[str, Any]:
    """Compute the entropy trend over visit history.

    Slides a window of size *window* across the visit list in steps of
    *step*, computing the proactive fraction at each position.  Then
    fits a line to the series and reports the slope.

    Returns a dict with:

    - ``proactive_series``: list of proactive fractions over time
    - ``trend_slope``: slope of linear fit (positive = improving)
    - ``trend_direction``: 'improving' | 'stable' | 'degrading'

    The threshold for 'stable' is |slope| < 0.005 per visit.

    >>> visits = [{"actions": ["restart"]} for _ in range(10)] + [
    ...     {"actions": ["new_module"]} for _ in range(10)]
    >>> t = entropy_trend(visits, window=5, step=5)
    >>> t["trend_direction"]
    'improving'
    """
    if len(visits) < window:
        frac = entropy_score(visits, window=window)
        return {
            "proactive_series": [frac["proactive_fraction"]],
            "trend_slope": 0.0,
            "trend_direction": "stable",
        }

    series: list[float] = []
    for start in range(0, len(visits) - window + 1, step):
        chunk = visits[start : start + window]
        cls = classify_visits(chunk)
        fr = _fractions(cls)
        series.append(fr["proactive_fraction"])

    if not series:
        return {
            "proactive_series": [],
            "trend_slope": 0.0,
            "trend_direction": "stable",
        }

    slope = _linear_slope(series)

    # Threshold: 0.005 per visit ≈ 0.1 change over 20 visits.
    if slope > 0.005:
        direction = "improving"
    elif slope < -0.005:
        direction = "degrading"
    else:
        direction = "stable"

    return {
        "proactive_series": [round(s, 4) for s in series],
        "trend_slope": round(slope, 6),
        "trend_direction": direction,
    }


# ---------------------------------------------------------------------------
# Health assessment
# ---------------------------------------------------------------------------

def assess_health(
    proactive_fraction: float,
    trend_direction: str,
    sample_size: int,
    window: int = 20,
) -> str:
    """Classify the system's caretaker health.

    ===============  ====================================================
    class            condition
    ===============  ====================================================
    winning          pf >= 0.6 AND trend is not 'degrading'
    treading_water   0.4 <= pf < 0.6 OR trend is 'stable' at any level
    losing           pf < 0.4 AND trend is 'degrading'
    unknown          sample_size < window
    ===============  ====================================================

    >>> assess_health(0.7, "improving", 20)
    'winning'
    >>> assess_health(0.65, "stable", 20)
    'treading_water'
    >>> assess_health(0.65, "degrading", 20)
    'treading_water'
    >>> assess_health(0.5, "stable", 20)
    'treading_water'
    >>> assess_health(0.3, "degrading", 20)
    'losing'
    >>> assess_health(0.3, "stable", 20)
    'treading_water'
    >>> assess_health(0.8, "improving", 5, window=20)
    'unknown'
    """
    if sample_size < window:
        return "unknown"

    if proactive_fraction >= 0.6 and trend_direction != "degrading":
        return "winning"

    if proactive_fraction < 0.4 and trend_direction == "degrading":
        return "losing"

    return "treading_water"


def entropy_class(proactive_fraction: float, reactive_fraction: float) -> str:
    """Classify the entropy level of the system.

    Low entropy means the caretaker is focused on productive work.
    High entropy means energy is scattered across firefighting.

    >>> entropy_class(0.8, 0.1)
    'low-entropy'
    >>> entropy_class(0.5, 0.3)
    'medium-entropy'
    >>> entropy_class(0.2, 0.7)
    'high-entropy'
    >>> entropy_class(0.4, 0.4)
    'medium-entropy'
    """
    if proactive_fraction >= 0.6 and reactive_fraction <= 0.3:
        return "low-entropy"
    if reactive_fraction >= 0.6 and proactive_fraction <= 0.3:
        return "high-entropy"
    return "medium-entropy"


# ---------------------------------------------------------------------------
# Composite report
# ---------------------------------------------------------------------------

def entropy_report(
    visits: list[dict[str, Any]],
    window: int = 20,
    step: int = 5,
) -> dict[str, Any]:
    """Full caretaker entropy report.

    Combines scoring, trend detection, health assessment, and entropy
    classification into a single result dict.

    Parameters
    ----------
    visits : list of dicts, each with an 'actions' key (list of action strings)
    window : rolling window size for scoring (default 20)
    step   : step size for trend sliding window (default 5)

    Returns
    -------
    dict with keys:
        proactive_fraction, reactive_fraction, mixed_fraction,
        window_size, trend_direction, trend_slope, proactive_series,
        health, entropy_class

    >>> visits = [{"actions": ["new_module"]} for _ in range(25)]
    >>> r = entropy_report(visits, window=20)
    >>> r["health"]
    'winning'
    >>> r["proactive_fraction"]
    1.0
    >>> r["entropy_class"]
    'low-entropy'

    >>> visits2 = [{"actions": ["restart"]} for _ in range(25)]
    >>> r2 = entropy_report(visits2, window=20)
    >>> r2["health"]
    'losing'
    >>> r2["proactive_fraction"]
    0.0
    """
    score = entropy_score(visits, window=window)
    trend = entropy_trend(visits, window=window, step=step)

    pf = score["proactive_fraction"]
    rf = score["reactive_fraction"]

    health = assess_health(pf, trend["trend_direction"], score["window_size"], window)
    ec = entropy_class(pf, rf)

    return {
        "proactive_fraction": pf,
        "reactive_fraction": rf,
        "mixed_fraction": score["mixed_fraction"],
        "window_size": score["window_size"],
        "trend_direction": trend["trend_direction"],
        "trend_slope": trend["trend_slope"],
        "proactive_series": trend["proactive_series"],
        "health": health,
        "entropy_class": ec,
    }


# ---------------------------------------------------------------------------
# Action parser — extract actions from visit note text
# ---------------------------------------------------------------------------

_ACTION_KEYWORDS: dict[str, list[str]] = {
    "restart": [
        "restart", "restarted", "revival", "resurrect", "resurrection",
        "recovered process", "process recovery", "brought back",
        "killed and restarted", "respawned",
    ],
    "push_repair": [
        "rebase", "force-push", "force push", "divergence", "merge conflict",
        "push rejection", "push failure", "push repair", "rebased onto",
        "resolved divergence", "merge fix",
    ],
    "backlog_drain": [
        "catch-up", "backlog", "pending commits", "uncommitted files",
        "draining backlog", "committing accumulated", "catch-up commit",
        "pending changes",
    ],
    "lock_cleanup": [
        "stale lock", "lock cleanup", "PID file", "orphan lock",
        "removed lock", "cleaned lock",
    ],
    "ssh_rescue": [
        "ssh key", "ssh rescue", "known_hosts", "deploy key",
        "ssh permission", "key restoration", "key mismatch",
    ],
    "new_content": [
        "new note", "wrote a note", "added note", "original analysis",
        "new content", "proactive contribution", "reflection",
    ],
    "new_module": [
        "new module", "added module", "module with tests",
        "created module", "new python module", "tests for",
    ],
    "tooling": [
        "new tool", "monitoring script", "diagnostic", "CLI tool",
        "improved tooling", "tooling improvement", "new script",
    ],
    "analysis": [
        "analysis", "postmortem", "metrics review", "pattern identification",
        "trend analysis", "reviewed metrics", "examined history",
    ],
    "maintenance": [
        "status check", "verified running", "routine check",
        "housekeeping", "no issues found", "all clear",
    ],
}


def parse_actions_from_text(text: str) -> list[str]:
    """Extract action labels from a visit note's text.

    Scans the text for keyword matches and returns deduplicated action
    labels.  Useful for mining historical visit notes that don't have
    structured action fields.

    >>> parse_actions_from_text("restarted both processes and wrote a new note about entropy")
    ['restart', 'new_content']
    >>> parse_actions_from_text("routine status check, all clear")
    ['maintenance']
    >>> parse_actions_from_text("")
    []
    """
    text_lower = text.lower()
    found: list[str] = []
    for action, keywords in _ACTION_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                if action not in found:
                    found.append(action)
                break
    return found


# ---------------------------------------------------------------------------
# Batch analysis — classify a full visit history
# ---------------------------------------------------------------------------

def classify_history(
    visits: list[dict[str, Any]],
    text_key: str = "text",
) -> list[dict[str, Any]]:
    """Classify every visit in a history list.

    Each visit dict should have either an 'actions' key (pre-classified)
    or a *text_key* containing the visit note text from which actions
    will be extracted.

    Returns a new list of dicts, each augmented with 'actions' and
    'classification' keys.

    >>> history = [
    ...     {"id": 1, "text": "restarted both processes"},
    ...     {"id": 2, "actions": ["new_module"]},
    ... ]
    >>> result = classify_history(history)
    >>> result[0]["classification"]
    'reactive'
    >>> result[1]["classification"]
    'proactive'
    """
    enriched: list[dict[str, Any]] = []
    for v in visits:
        entry = dict(v)
        if "actions" not in entry or not entry["actions"]:
            text = entry.get(text_key, "")
            entry["actions"] = parse_actions_from_text(text)
        entry["classification"] = classify_visit(entry["actions"])
        enriched.append(entry)
    return enriched
