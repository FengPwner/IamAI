"""Process continuity — how reliably does the writer stay alive between visits?

A visit is *continuous* if the writer process was already running and
actively producing strokes when the caretaker arrived.  A visit is a
*break* if the writer had to be restarted, or was stalled (silent past
2× its cadence).

The **continuity score** over a window of visits is::

    score = continuous_visits / total_visits

Interpretation::

    1.0        unbroken — writer has been alive every visit
    0.8–1.0    strong — rare disruptions
    0.5–0.8    fragile — writer dies roughly as often as it survives
    0.2–0.5    brittle — most visits require intervention
    0.0–0.2    broken — writer rarely survives between visits

The module also provides:

- **current_streak**: consecutive continuous visits ending at the most
  recent visit (0 if the latest visit is a break)
- **longest_streak**: longest run of consecutive continuous visits in
  the window
- **break_density**: number of breaks per 10 visits (extrapolated)
- **continuity_trend**: comparing two consecutive windows — "improving",
  "flat", or "degrading"

Usage::

    from iamai.process_continuity import analyse

    visits = [
        {"alive": True,  "stalled": False, "ts": "..."},
        {"alive": False, "stalled": False, "ts": "..."},  # dead
        {"alive": True,  "stalled": True,  "ts": "..."},  # stalled = break
        {"alive": True,  "stalled": False, "ts": "..."},
    ]

    report = analyse(visits, window=20)
    print(report["score"])            # 0.0–1.0
    print(report["band"])             # "unbroken" | "strong" | ...
    print(report["current_streak"])   # int
    print(report["longest_streak"])   # int
    print(report["break_density"])    # float (breaks per 10 visits)
    print(report["trend"])            # "improving" | "flat" | "degrading"
"""

from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_BANDS = [
    (1.0, "unbroken"),
    (0.8, "strong"),
    (0.5, "fragile"),
    (0.2, "brittle"),
    (0.0, "broken"),
]


def _is_continuous(v: Dict[str, Any]) -> bool:
    """A visit is continuous if the writer was alive *and* not stalled."""
    return bool(v.get("alive", False)) and not bool(v.get("stalled", False))


def _band(score: float) -> str:
    for threshold, label in _BANDS:
        if score >= threshold:
            return label
    return "broken"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def continuity_score(visits: List[Dict[str, Any]], window: int = 20) -> float:
    """Fraction of visits in the window that were continuous.

    Returns 0.0 for an empty list.
    """
    if not visits:
        return 0.0
    tail = visits[-window:]
    continuous = sum(1 for v in tail if _is_continuous(v))
    return continuous / len(tail)


def current_streak(visits: List[Dict[str, Any]]) -> int:
    """Count of consecutive continuous visits ending at the most recent.

    Returns 0 if the latest visit is a break or the list is empty.
    """
    streak = 0
    for v in reversed(visits):
        if _is_continuous(v):
            streak += 1
        else:
            break
    return streak


def longest_streak(visits: List[Dict[str, Any]], window: int = 20) -> int:
    """Longest run of consecutive continuous visits in the window."""
    tail = visits[-window:]
    best = 0
    run = 0
    for v in tail:
        if _is_continuous(v):
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def break_density(visits: List[Dict[str, Any]], window: int = 20) -> float:
    """Number of breaks per 10 visits (extrapolated from the window).

    Returns 0.0 for an empty list.
    """
    if not visits:
        return 0.0
    tail = visits[-window:]
    breaks = sum(1 for v in tail if not _is_continuous(v))
    return (breaks / len(tail)) * 10


def continuity_trend(
    visits: List[Dict[str, Any]], window: int = 20
) -> str:
    """Compare two consecutive half-windows to detect trend direction.

    Splits the window into two halves and compares the continuity score
    of each.  Returns "improving", "flat", or "degrading".

    With fewer than 2 visits, returns "flat".
    """
    tail = visits[-window:]
    if len(tail) < 2:
        return "flat"
    mid = len(tail) // 2
    first_half = tail[:mid]
    second_half = tail[mid:]
    s1 = continuity_score(first_half, window=len(first_half))
    s2 = continuity_score(second_half, window=len(second_half))
    delta = s2 - s1
    if delta > 0.05:
        return "improving"
    elif delta < -0.05:
        return "degrading"
    return "flat"


def analyse(
    visits: List[Dict[str, Any]], window: int = 20
) -> Dict[str, Any]:
    """Composite continuity report for the given visits.

    Returns a dict with keys: score, band, current_streak,
    longest_streak, break_density, trend, window, total_in_window.
    """
    tail = visits[-window:]
    score = continuity_score(tail, window=window)
    return {
        "score": round(score, 4),
        "band": _band(score),
        "current_streak": current_streak(tail),
        "longest_streak": longest_streak(tail, window=window),
        "break_density": round(break_density(tail, window=window), 2),
        "trend": continuity_trend(tail, window=window),
        "window": window,
        "total_in_window": len(tail),
    }
