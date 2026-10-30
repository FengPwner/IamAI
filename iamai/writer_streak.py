"""Writer streak tracker: consecutive successful write cycles.

Existing modules track rate, freshness, gaps, and stalls — but none of them
capture *continuity*. A writer that alternates success/failure/success/failure
looks fine on average (50% success rate, cadence only half-broken) but is
clearly unhealthy. A streak counter makes this visible.

A streak is the count of consecutive successful ticks since the last failure.
It resets to zero on any failure. The longest streak is remembered as a
high-water mark.

This module is pure — no I/O, no file reads. Feed it a sequence of boolean
outcomes (True = successful tick, False = missed/failed tick) and it returns
streak statistics.

Usage::

    from iamai.writer_streak import streak_stats

    outcomes = [True, True, True, False, True, True, True, True, True]
    stats = streak_stats(outcomes)
    print(stats["current"])     # 5  (five consecutive successes at end)
    print(stats["longest"])     # 5
    print(stats["total_ticks"]) # 9
    print(stats["success_rate"])# 0.8889
    print(stats["resilience"])  # 0.625  (current/longest ratio; 1.0 = at peak)

Why resilience matters:
    A current streak of 50 sounds great — but if the longest was 500, the
    writer has been underperforming for a while. Resilience = current/longest
    gives a quick "are we back to normal?" reading.
"""

from __future__ import annotations

from typing import Sequence


def current_streak(outcomes: Sequence[bool]) -> int:
    """Count consecutive successes at the end of the sequence.

    Args:
        outcomes: chronological list of tick outcomes (True=success)

    Returns:
        Number of consecutive True values at the tail. 0 if empty or last is False.

    Examples:
        >>> current_streak([True, True, False, True, True, True])
        3
        >>> current_streak([False])
        0
        >>> current_streak([])
        0
    """
    count = 0
    for outcome in reversed(outcomes):
        if outcome:
            count += 1
        else:
            break
    return count


def longest_streak(outcomes: Sequence[bool]) -> int:
    """Find the longest run of consecutive successes.

    Args:
        outcomes: chronological list of tick outcomes

    Returns:
        Maximum consecutive True count. 0 if all False or empty.

    Examples:
        >>> longest_streak([True, True, False, True, True, True])
        3
        >>> longest_streak([True, True, True])
        3
        >>> longest_streak([False, False])
        0
    """
    best = 0
    run = 0
    for outcome in outcomes:
        if outcome:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def streak_stats(outcomes: Sequence[bool]) -> dict:
    """Compute streak statistics from a sequence of tick outcomes.

    Args:
        outcomes: chronological list of tick outcomes (True=success, False=failure)

    Returns:
        Dictionary with keys:
        - current: current streak length (consecutive successes at tail)
        - longest: longest streak ever recorded
        - total_ticks: total number of ticks observed
        - successes: total successful ticks
        - failures: total failed ticks
        - success_rate: fraction of successful ticks (0.0-1.0), 0.0 if empty
        - resilience: current/longest ratio (0.0-1.0), 1.0 if no failures ever
        - streaks: list of all streak lengths (each run of successes)

    Examples:
        >>> stats = streak_stats([True, True, False, True])
        >>> stats["current"]
        1
        >>> stats["longest"]
        2
        >>> stats["resilience"]
        0.5
    """
    total = len(outcomes)
    successes = sum(1 for o in outcomes if o)
    failures = total - successes

    cur = current_streak(outcomes)
    lng = longest_streak(outcomes)

    # Collect all streak lengths
    streaks = []
    run = 0
    for outcome in outcomes:
        if outcome:
            run += 1
        else:
            if run > 0:
                streaks.append(run)
            run = 0
    if run > 0:
        streaks.append(run)

    success_rate = successes / total if total > 0 else 0.0
    resilience = cur / lng if lng > 0 else (1.0 if total == 0 else 0.0)

    return {
        "current": cur,
        "longest": lng,
        "total_ticks": total,
        "successes": successes,
        "failures": failures,
        "success_rate": round(success_rate, 4),
        "resilience": round(resilience, 4),
        "streaks": streaks,
    }


def streak_verdict(stats: dict, healthy_threshold: int = 10) -> str:
    """Give a human-readable verdict based on streak stats.

    Args:
        stats: output from streak_stats()
        healthy_threshold: streak length considered "healthy"

    Returns:
        One of: "solid", "recovering", "fragile", "dead"

    Examples:
        >>> streak_verdict({"current": 50, "longest": 60, "failures": 2})
        'solid'
        >>> streak_verdict({"current": 3, "longest": 100, "failures": 10})
        'recovering'
        >>> streak_verdict({"current": 0, "longest": 0, "failures": 5})
        'dead'
    """
    cur = stats.get("current", 0)
    lng = stats.get("longest", 0)
    failures = stats.get("failures", 0)

    if cur == 0 and lng == 0:
        return "dead"
    if cur >= healthy_threshold and stats.get("resilience", 0) >= 0.8:
        return "solid"
    if cur > 0 and lng > 0 and stats.get("resilience", 0) < 0.3:
        return "recovering"
    if cur == 0 and failures > 0:
        return "fragile"
    return "solid" if cur >= healthy_threshold else "recovering"
