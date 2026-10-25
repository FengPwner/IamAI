"""Stroke momentum — is the writer speeding up or slowing down?

``stroke_rate`` answers *how fast*; ``stroke_momentum`` answers
*which direction*.  A writer producing 240 strokes/hr sounds healthy,
but if it was doing 480/hr an hour ago, that "healthy" number masks
a deceleration that will become a stall by dinner.

This module splits a time window into a **recent** quarter and a
**baseline** three-quarter span, computes the per-hour rate in each,
and reports:

===========  ================================================
verdict      meaning
===========  ================================================
``surging``  recent rate > 1.5x baseline — burst in progress
``steady``   recent rate within 0.5x–1.5x baseline
``fading``   recent rate < 0.5x baseline — deceleration
``flat``     both rates below 1 stroke/hr — effectively idle
===========  ================================================

The key insight: momentum is the *derivative* of throughput.  Rate
tells you position; momentum tells you velocity.  A caretaker that
watches both catches trouble a full commit-cycle earlier than one
watching rate alone.

Usage::

    from iamai.stroke_momentum import momentum, momentum_summary

    info = momentum(window_hours=2.0)
    print(info["verdict"])         # "fading"
    print(info["recent_rate"])     # 120.0
    print(info["baseline_rate"])   # 360.0
    print(info["ratio"])           # 0.33

    summary = momentum_summary(window_hours=2.0)
    # "fading — 120.0/hr (recent) vs 360.0/hr (baseline), ratio 0.33"
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DEFAULT_STROKES_PATH = Path("data/strokes.jsonl")


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a timezone-aware datetime.

    Handles ``+00:00``, ``Z`` suffixes, and bare datetimes (assumed UTC).
    """
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_strokes(path: Path) -> list[dict]:
    """Load strokes from a JSONL file, adding a ``_dt`` key to each."""
    strokes: list[dict] = []
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


def _classify(recent_rate: float, baseline_rate: float) -> str:
    """Classify momentum based on the ratio of recent to baseline rate.

    Returns one of: ``surging``, ``steady``, ``fading``, ``flat``.
    """
    if baseline_rate < 1.0 and recent_rate < 1.0:
        return "flat"
    if baseline_rate < 1.0:
        # baseline idle but recent activity — treat as surge from zero
        return "surging"
    ratio = recent_rate / baseline_rate
    if ratio > 1.5:
        return "surging"
    if ratio < 0.5:
        return "fading"
    return "steady"


def momentum(
    repo: Path | None = None,
    window_hours: float = 2.0,
    now: datetime | None = None,
    strokes_path: Path | None = None,
) -> dict:
    """Compute stroke momentum over the given window.

    Args:
        repo: repository root (used to locate strokes file)
        window_hours: look-back window in hours (default 2)
        now: override for current time (default: utcnow)
        strokes_path: explicit path to strokes JSONL (overrides repo)

    Returns:
        dict with keys:
            - ``verdict``: one of surging / steady / fading / flat
            - ``recent_rate``: strokes/hr in the most recent quarter
            - ``baseline_rate``: strokes/hr in the older three quarters
            - ``ratio``: recent_rate / baseline_rate (0 if baseline is 0)
            - ``recent_count``: raw stroke count in recent quarter
            - ``baseline_count``: raw stroke count in baseline span
            - ``window_hours``: the window used
    """
    if strokes_path is None:
        base = Path(repo) if repo else Path(".")
        strokes_path = base / _DEFAULT_STROKES_PATH
    if now is None:
        now = datetime.now(timezone.utc)

    strokes = _load_strokes(strokes_path)
    cutoff = now - timedelta(hours=window_hours)
    quarter = timedelta(hours=window_hours / 4)
    recent_start = now - quarter

    in_window = [s for s in strokes if s["_dt"] >= cutoff]
    recent = [s for s in in_window if s["_dt"] >= recent_start]
    baseline = [s for s in in_window if s["_dt"] < recent_start]

    quarter_hours = window_hours / 4
    baseline_hours = window_hours - quarter_hours

    recent_rate = len(recent) / quarter_hours if quarter_hours > 0 else 0.0
    baseline_rate = len(baseline) / baseline_hours if baseline_hours > 0 else 0.0
    ratio = recent_rate / baseline_rate if baseline_rate > 0 else 0.0

    verdict = _classify(recent_rate, baseline_rate)

    return {
        "verdict": verdict,
        "recent_rate": round(recent_rate, 2),
        "baseline_rate": round(baseline_rate, 2),
        "ratio": round(ratio, 3),
        "recent_count": len(recent),
        "baseline_count": len(baseline),
        "window_hours": window_hours,
    }


def momentum_summary(
    repo: Path | None = None,
    window_hours: float = 2.0,
    now: datetime | None = None,
    strokes_path: Path | None = None,
) -> str:
    """One-liner momentum summary for caretaker logs.

    Example::

        "fading — 120.0/hr (recent) vs 360.0/hr (baseline), ratio 0.333"
    """
    info = momentum(repo=repo, window_hours=window_hours, now=now,
                    strokes_path=strokes_path)
    return (
        f"{info['verdict']} — {info['recent_rate']}/hr (recent) vs "
        f"{info['baseline_rate']}/hr (baseline), ratio {info['ratio']}"
    )
