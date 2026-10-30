"""Daily target pacing for the IamAI writer.

Caretakers already know *rate* (stroke_rate), *freshness* (stroke_freshness),
and *diversity* (content_diversity).  But none of those answer the question
that matters at 6 pm: **are we on track for today?**

This module reads ``data/strokes.jsonl`` and computes:

- **Strokes today** — how many strokes landed since midnight UTC
- **Remaining target** — daily target minus today's count
- **Required rate** — strokes/hour needed from *now* to hit the target
- **Pace verdict** — ``ahead``, ``on_track``, or ``behind``
- **Projected total** — if the writer keeps its current rate, where does
  it end up at midnight?

The key insight: a writer doing 200 strokes/hr sounds healthy, but if the
daily target is 5000 and it's already 8 pm with only 1200 done, "healthy
rate" is a comforting lie.  Pacing puts rate and time-to-deadline in the
same sentence.

Usage::

    from iamai.stroke_pacer import pace_report, pace_summary

    report = pace_report(daily_target=1000)
    print(report["strokes_today"])    # e.g. 742
    print(report["remaining"])        # e.g. 258
    print(report["required_rate"])    # e.g. 64.5  (strokes/hr)
    print(report["verdict"])          # "on_track"
    print(report["projected_total"])  # e.g. 1087

    summary = pace_summary(daily_target=1000)
    # "742/1000 strokes today, need 64.5/hr (have 240.0/hr), on_track"
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_STROKES_PATH = Path("data/strokes.jsonl")


def _load_strokes(path: Path) -> list[dict[str, Any]]:
    """Load strokes from the JSONL log, skipping malformed lines."""
    if not path.is_file():
        return []
    strokes: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return strokes


def _parse_ts(raw: str) -> datetime:
    """Parse an ISO timestamp into a timezone-aware UTC datetime."""
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _strokes_since(strokes: list[dict[str, Any]], cutoff: datetime) -> int:
    """Count strokes at or after *cutoff*."""
    count = 0
    for s in strokes:
        try:
            if _parse_ts(s["at"]) >= cutoff:
                count += 1
        except (KeyError, ValueError):
            continue
    return count


def _recent_rate(
    strokes: list[dict[str, Any]],
    window_hours: float = 1.0,
    now: datetime | None = None,
) -> float:
    """Strokes per hour over the last *window_hours*."""
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - __import__("datetime").timedelta(hours=window_hours)
    n = _strokes_since(strokes, cutoff)
    return n / window_hours if window_hours > 0 else 0.0


def _verdict(
    strokes_today: int,
    daily_target: int,
    hours_left: float,
    current_rate: float,
) -> str:
    """Classify the pace as ahead / on_track / behind.

    Logic:
    - If target is already met → ``ahead``
    - If hours_left <= 0 and target not met → ``behind``
    - Compute required rate; if current_rate >= required_rate * 0.8 → on_track
    - If current_rate >= required_rate * 1.2 → ahead (exceeding)
    - Otherwise → behind
    """
    if strokes_today >= daily_target:
        return "ahead"
    if hours_left <= 0:
        return "behind"
    remaining = daily_target - strokes_today
    required = remaining / hours_left
    if current_rate >= required * 1.2:
        return "ahead"
    if current_rate >= required * 0.8:
        return "on_track"
    return "behind"


def pace_report(
    daily_target: int = 1000,
    strokes_path: Path | str | None = None,
    now: datetime | None = None,
    rate_window_hours: float = 1.0,
) -> dict[str, Any]:
    """Compute the pacing report.

    Parameters
    ----------
    daily_target:
        Number of strokes the writer aims to produce per day.
    strokes_path:
        Path to ``strokes.jsonl``; defaults to ``data/strokes.jsonl``.
    now:
        Override "now" for testing; defaults to ``datetime.now(UTC)``.
    rate_window_hours:
        How many hours of recent history to use for the current rate.

    Returns
    -------
    dict with keys:
        strokes_today, daily_target, remaining, hours_left,
        current_rate, required_rate, verdict, projected_total.
    """
    path = Path(strokes_path) if strokes_path else _DEFAULT_STROKES_PATH
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    strokes = _load_strokes(path)

    # Midnight UTC today
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    strokes_today = _strokes_since(strokes, midnight)

    # Hours left until midnight
    seconds_since_midnight = (now - midnight).total_seconds()
    hours_left = max(0.0, (86400 - seconds_since_midnight) / 3600)

    remaining = max(0, daily_target - strokes_today)
    required_rate = remaining / hours_left if hours_left > 0 else float("inf")
    current_rate = _recent_rate(strokes, window_hours=rate_window_hours, now=now)

    # Projected total: if current rate holds for the rest of the day
    projected_total = strokes_today + int(current_rate * hours_left)

    v = _verdict(strokes_today, daily_target, hours_left, current_rate)

    return {
        "strokes_today": strokes_today,
        "daily_target": daily_target,
        "remaining": remaining,
        "hours_left": round(hours_left, 2),
        "current_rate": round(current_rate, 1),
        "required_rate": round(required_rate, 1),
        "verdict": v,
        "projected_total": projected_total,
    }


def pace_summary(
    daily_target: int = 1000,
    strokes_path: Path | str | None = None,
    now: datetime | None = None,
) -> str:
    """One-line human-readable pacing summary."""
    r = pace_report(
        daily_target=daily_target, strokes_path=strokes_path, now=now
    )
    target = r["daily_target"]
    done = r["strokes_today"]
    need = r["required_rate"]
    have = r["current_rate"]
    v = r["verdict"]
    return (
        f"{done}/{target} strokes today, "
        f"need {need}/hr (have {have}/hr), {v}"
    )
