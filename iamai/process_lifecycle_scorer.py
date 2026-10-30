"""process_lifecycle_scorer — score autonomous process stability over time.

When a caretaker visits a long-running autonomous writer, the most
important question is not "is it alive right now?" but "has it been
stable since the last visit?".  A process that was reclaimed three
times overnight and restarted each time looks healthy at the moment
of observation but has been silently losing strokes for hours.

This module answers: **how stable has this process been?**

It takes a list of lifecycle events (start, stop, crash) and computes:

- **stability_score**: 0.0 (constant churn) to 1.0 (never interrupted)
- **reclamation_count**: how many times the process was killed externally
- **mean_uptime**: average seconds between start and next stop
- **churn_rate**: reclaims per hour over the observation window
- **verdict**: healthy / degraded / critical

Verdict thresholds:

==========  =========================================================
verdict     meaning
==========  =========================================================
healthy     0 reclaims, or uptime > 6 hours since last reclaim
degraded    1–2 reclaims in the window, or uptime 1–6 hours
critical    3+ reclaims, or uptime < 1 hour, or no uptime data
==========  =========================================================

Usage::

    from iamai.process_lifecycle_scorer import score_lifecycle

    events = [
        {"kind": "start", "at": "2026-10-24T01:00:00+08:00"},
        {"kind": "stop",  "at": "2026-10-24T04:00:00+08:00"},
        {"kind": "start", "at": "2026-10-24T04:01:00+08:00"},
    ]

    result = score_lifecycle(events)
    print(result["stability_score"])  # ~0.5
    print(result["verdict"])          # "degraded"
    print(result["reclamation_count"])  # 1
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


# Thresholds for verdict classification
_CRITICAL_RECLAIMS = 3
_DEGRADED_RECLAIMS = 1
_CRITICAL_UPTIME_HOURS = 1.0
_DEGRADED_UPTIME_HOURS = 6.0
_HEALTHY_UPTIME_HOURS = 6.0


def _parse_ts(ts: str | datetime) -> datetime:
    """Parse a timestamp string or return datetime as-is."""
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(ts)


def _ensure_tz(dt: datetime) -> datetime:
    """Attach UTC if the datetime is naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _extract_uptimes(events: list[dict[str, Any]]) -> list[float]:
    """Pair start->stop events and return uptime durations in seconds.

    Events are sorted chronologically.  Each 'start' is paired with
    the next 'stop' (if any).  Consecutive starts without an intervening
    stop are treated as overlapping and only the earliest counts.
    Consecutive stops without a preceding start are ignored.
    """
    if not events:
        return []

    sorted_events = sorted(events, key=lambda e: _parse_ts(e["at"]))
    uptimes: list[float] = []
    pending_start: datetime | None = None

    for ev in sorted_events:
        kind = ev["kind"]
        ts = _ensure_tz(_parse_ts(ev["at"]))
        if kind == "start":
            if pending_start is None:
                pending_start = ts
        elif kind in ("stop", "crash", "exit"):
            if pending_start is not None:
                uptimes.append((ts - pending_start).total_seconds())
                pending_start = None

    return uptimes


def _count_reclamations(events: list[dict[str, Any]]) -> int:
    """Count external reclamation events (kind='stop' or 'crash').

    Consecutive stops without an intervening start count as one
    reclamation (they represent a single shutdown event).
    """
    if not events:
        return 0

    sorted_events = sorted(events, key=lambda e: _parse_ts(e["at"]))
    count = 0
    saw_start = False

    for ev in sorted_events:
        kind = ev["kind"]
        if kind == "start":
            saw_start = True
        elif kind in ("stop", "crash", "exit") and saw_start:
            count += 1
            saw_start = False

    return count


def _observation_window_seconds(events: list[dict[str, Any]]) -> float:
    """Total span from first to last event, in seconds."""
    if len(events) < 2:
        return 0.0
    sorted_events = sorted(events, key=lambda e: _parse_ts(e["at"]))
    first = _ensure_tz(_parse_ts(sorted_events[0]["at"]))
    last = _ensure_tz(_parse_ts(sorted_events[-1]["at"]))
    return max((last - first).total_seconds(), 1.0)


def _stability_score(
    reclamation_count: int,
    uptimes: list[float],
    window_seconds: float,
) -> float:
    """Compute stability score from 0.0 (constant churn) to 1.0 (stable).

    Score is the product of:
    - uptime ratio: total uptime / observation window
    - reclaim penalty: exp(-0.5 * reclamation_count)
    """
    if not uptimes or window_seconds <= 0:
        return 0.0

    total_uptime = sum(uptimes)
    uptime_ratio = min(total_uptime / window_seconds, 1.0)
    reclaim_penalty = math.exp(-0.5 * reclamation_count)
    return round(uptime_ratio * reclaim_penalty, 4)


def _current_uptime_seconds(
    events: list[dict[str, Any]],
    now: datetime | None = None,
) -> float | None:
    """Seconds since the last 'start' event, or None if no start exists."""
    if not events:
        return None

    sorted_events = sorted(events, key=lambda e: _parse_ts(e["at"]))
    last_event = sorted_events[-1]

    if last_event["kind"] != "start":
        return None

    start_ts = _ensure_tz(_parse_ts(last_event["at"]))
    ref = _ensure_tz(now) if now else _ensure_tz(datetime.now(timezone.utc))
    return max((ref - start_ts).total_seconds(), 0.0)


def _verdict(
    reclamation_count: int,
    current_uptime: float | None,
    stability_score: float,
) -> str:
    """Classify the process lifecycle into healthy / degraded / critical."""
    if current_uptime is None:
        return "critical"

    uptime_hours = current_uptime / 3600.0

    if reclamation_count >= _CRITICAL_RECLAIMS:
        return "critical"
    if uptime_hours < _CRITICAL_UPTIME_HOURS:
        return "critical"
    if reclamation_count >= _DEGRADED_RECLAIMS:
        return "degraded"
    if uptime_hours < _HEALTHY_UPTIME_HOURS:
        return "degraded"
    return "healthy"


def score_lifecycle(
    events: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Score the lifecycle stability of an autonomous process.

    Parameters
    ----------
    events : list of dicts
        Each dict must have ``kind`` (start/stop/crash/exit) and ``at``
        (ISO timestamp string or datetime).
    now : datetime, optional
        Reference time for current uptime calculation.  Defaults to
        ``datetime.now(timezone.utc)``.

    Returns
    -------
    dict with keys:
        stability_score : float (0.0-1.0)
        verdict : str (healthy / degraded / critical)
        reclamation_count : int
        mean_uptime : float (seconds)
        churn_rate : float (reclaims per hour)
        current_uptime : float | None (seconds since last start)
        uptimes : list[float] (individual uptime durations in seconds)
    """
    uptimes = _extract_uptimes(events)
    reclamation_count = _count_reclamations(events)
    window = _observation_window_seconds(events)
    score = _stability_score(reclamation_count, uptimes, window)
    current = _current_uptime_seconds(events, now)
    mean_uptime = sum(uptimes) / len(uptimes) if uptimes else 0.0
    window_hours = window / 3600.0
    churn_rate = reclamation_count / window_hours if window_hours > 0 else 0.0

    return {
        "stability_score": score,
        "verdict": _verdict(reclamation_count, current, score),
        "reclamation_count": reclamation_count,
        "mean_uptime": round(mean_uptime, 2),
        "churn_rate": round(churn_rate, 4),
        "current_uptime": round(current, 2) if current is not None else None,
        "uptimes": [round(u, 2) for u in uptimes],
    }
