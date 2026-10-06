"""Rolling stroke rate computation for the IamAI repository.

Caretakers already have ``stall_classifier`` (is the writer dead?) and
``commit_health`` (overall health score). What's missing: *how fast is
the writer actually producing?* A writer can be alive but sluggish —
producing one stroke per minute instead of four — and no existing
module catches that.

This module reads ``data/strokes.jsonl`` and computes:

- **Total rate** over a configurable time window
- **Per-kind breakdown** (thought, snippet, note, devlog, garden, metrics)
- **Trend detection** — is the writer accelerating, steady, or declining?

The key insight: rate is only meaningful relative to the writer's
cadence. Four strokes per minute sounds fast until you learn the
cadence is one every fifteen seconds (four per minute expected).

Usage::

    from iamai.stroke_rate import stroke_rate, rate_summary

    info = stroke_rate(window_hours=1.0)
    print(info["total_rate_per_hour"])   # e.g. 240.0
    print(info["by_kind"])               # {"thought": 60, "snippet": 60, ...}
    print(info["trend"])                 # "steady"

    summary = rate_summary(window_hours=1.0)
    print(summary)  # "240 strokes/hr over last 1h, trend: steady"
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter


_DEFAULT_STROKES_PATH = Path("data/strokes.jsonl")


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a timezone-aware datetime.

    Handles both ``+00:00`` and ``Z`` suffixes, plus bare datetimes
    (assumed UTC).

    Args:
        ts: ISO 8601 timestamp string

    Returns:
        timezone-aware datetime in UTC
    """
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_strokes(path: Path) -> list[dict]:
    """Load strokes from a JSONL file.

    Each line is a JSON object with at least ``seq``, ``at``, and
    optionally ``kind`` and ``text``.

    Args:
        path: path to the strokes JSONL file

    Returns:
        List of stroke dicts, each with a parsed ``_dt`` key added

    Raises:
        FileNotFoundError: if the file doesn't exist
    """
    strokes = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                obj["_dt"] = _parse_timestamp(obj["at"])
                strokes.append(obj)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return strokes


def _strokes_in_window(
    strokes: list[dict],
    now: datetime,
    window_hours: float,
) -> list[dict]:
    """Filter strokes to those within the time window.

    Args:
        strokes: list of stroke dicts with ``_dt`` keys
        now: current time (timezone-aware)
        window_hours: how many hours back to include

    Returns:
        Filtered list of strokes within the window
    """
    cutoff = now.replace(
        hour=now.hour, minute=now.minute,
        second=now.second, microsecond=now.microsecond,
    )
    # Use timedelta for proper subtraction
    from datetime import timedelta
    cutoff = now - timedelta(hours=window_hours)
    return [s for s in strokes if s["_dt"] >= cutoff]


def stroke_rate(
    window_hours: float = 1.0,
    strokes_path: Path | str | None = None,
    now: datetime | None = None,
) -> dict:
    """Compute stroke rate over a time window.

    Args:
        window_hours: how many hours back to look (default 1.0)
        strokes_path: path to strokes JSONL file (default: data/strokes.jsonl)
        now: current time override for testing (default: utcnow)

    Returns:
        Dict with keys:
        - total: int, number of strokes in the window
        - total_rate_per_hour: float, extrapolated hourly rate
        - by_kind: dict[str, int], stroke count per kind
        - rate_per_kind: dict[str, float], hourly rate per kind
        - trend: str ("accelerating" | "steady" | "declining" | "unknown")
        - window_hours: float, the window used
        - oldest_stroke_dt: datetime or None
        - newest_stroke_dt: datetime or None
    """
    path = Path(strokes_path) if strokes_path else _DEFAULT_STROKES_PATH
    if now is None:
        now = datetime.now(timezone.utc)

    all_strokes = _load_strokes(path)
    windowed = _strokes_in_window(all_strokes, now, window_hours)

    if not windowed:
        return {
            "total": 0,
            "total_rate_per_hour": 0.0,
            "by_kind": {},
            "rate_per_kind": {},
            "trend": "unknown",
            "window_hours": window_hours,
            "oldest_stroke_dt": None,
            "newest_stroke_dt": None,
        }

    total = len(windowed)
    rate = total / window_hours if window_hours > 0 else 0.0

    # Per-kind breakdown
    kind_counts: Counter = Counter()
    for s in windowed:
        kind = s.get("kind", "unknown")
        kind_counts[kind] += 1

    by_kind = dict(kind_counts)
    rate_per_kind = {
        k: v / window_hours if window_hours > 0 else 0.0
        for k, v in by_kind.items()
    }

    # Trend detection: compare first half vs second half of window
    trend = _detect_trend(windowed, window_hours, now)

    return {
        "total": total,
        "total_rate_per_hour": round(rate, 1),
        "by_kind": by_kind,
        "rate_per_kind": {k: round(v, 1) for k, v in rate_per_kind.items()},
        "trend": trend,
        "window_hours": window_hours,
        "oldest_stroke_dt": windowed[0]["_dt"],
        "newest_stroke_dt": windowed[-1]["_dt"],
    }


def _detect_trend(
    windowed: list[dict],
    window_hours: float,
    now: datetime,
) -> str:
    """Detect whether the writing rate is accelerating, steady, or declining.

    Splits the window in half and compares stroke counts. A >20%
    difference triggers a trend label; otherwise it's steady.

    Args:
        windowed: strokes within the window (sorted by time)
        window_hours: window size in hours
        now: current time

    Returns:
        "accelerating", "steady", "declining", or "unknown"
    """
    if len(windowed) < 2:
        return "unknown"

    from datetime import timedelta
    midpoint = now - timedelta(hours=window_hours / 2)

    first_half = sum(1 for s in windowed if s["_dt"] < midpoint)
    second_half = sum(1 for s in windowed if s["_dt"] >= midpoint)

    if first_half == 0 and second_half == 0:
        return "unknown"
    if first_half == 0:
        return "accelerating"
    if second_half == 0:
        return "declining"

    ratio = second_half / first_half
    if ratio > 1.2:
        return "accelerating"
    if ratio < 0.8:
        return "declining"
    return "steady"


def rate_summary(
    window_hours: float = 1.0,
    strokes_path: Path | str | None = None,
) -> str:
    """One-line human-readable rate summary.

    Args:
        window_hours: how many hours back to look
        strokes_path: optional path override

    Returns:
        Summary like "240 strokes/hr over last 1h, trend: steady"
    """
    info = stroke_rate(window_hours=window_hours, strokes_path=strokes_path)

    rate = info["total_rate_per_hour"]
    trend = info["trend"]
    total = info["total"]

    # Format window nicely
    if window_hours == int(window_hours):
        window_str = f"{int(window_hours)}h"
    else:
        window_str = f"{window_hours}h"

    parts = [f"{rate:.0f} strokes/hr over last {window_str}"]
    parts.append(f"{total} total")

    if info["by_kind"]:
        top_kinds = sorted(info["by_kind"].items(), key=lambda x: -x[1])[:3]
        kind_str = ", ".join(f"{k}:{v}" for k, v in top_kinds)
        parts.append(f"top: {kind_str}")

    parts.append(f"trend: {trend}")

    return ", ".join(parts)


def compare_windows(
    short_hours: float = 1.0,
    long_hours: float = 6.0,
    strokes_path: Path | str | None = None,
) -> dict:
    """Compare short-term vs long-term stroke rates.

    Useful for detecting whether the current pace is above or below
    the recent average. A caretaker can use this to decide if a
    "healthy" commit_health score is because things are genuinely
    fine, or because the window is too short to see the problem.

    Args:
        short_hours: short window in hours (default 1.0)
        long_hours: long window in hours (default 6.0)
        strokes_path: optional path override

    Returns:
        Dict with keys:
        - short_rate: float, strokes/hr over short window
        - long_rate: float, strokes/hr over long window
        - ratio: float, short_rate / long_rate (>1 = above average)
        - verdict: str ("above_average" | "normal" | "below_average" | "unknown")
    """
    short_info = stroke_rate(window_hours=short_hours, strokes_path=strokes_path)
    long_info = stroke_rate(window_hours=long_hours, strokes_path=strokes_path)

    short_rate = short_info["total_rate_per_hour"]
    long_rate = long_info["total_rate_per_hour"]

    if long_rate == 0:
        return {
            "short_rate": short_rate,
            "long_rate": long_rate,
            "ratio": 0.0,
            "verdict": "unknown",
        }

    ratio = short_rate / long_rate

    if ratio > 1.2:
        verdict = "above_average"
    elif ratio < 0.8:
        verdict = "below_average"
    else:
        verdict = "normal"

    return {
        "short_rate": round(short_rate, 1),
        "long_rate": round(long_rate, 1),
        "ratio": round(ratio, 2),
        "verdict": verdict,
    }
