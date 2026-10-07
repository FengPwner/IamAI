"""Stroke freshness monitor — how recent is the latest stroke?

``stroke_rate`` tells you throughput; ``stall_classifier`` tells you if
the writer is dead.  Neither answers the simplest question a caretaker
asks on arrival: *how stale is the repo right now?*

This module reads ``data/strokes.jsonl`` (last line only — it seeks from
the end) and classifies freshness into four tiers:

===========  ===============================================
verdict      meaning
===========  ===============================================
``fresh``    last stroke < 2× the writer's cadence
``warm``     last stroke < 5× cadence — alive but slow
``stale``    last stroke < 20× cadence — probably stalled
``dead``     last stroke ≥ 20× cadence — writer is gone
===========  ===============================================

The cadence is configurable (default 15 s).  A helper ``freshness_report``
returns a one-line human-readable string suitable for caretaker logs.

Usage::

    from iamai.stroke_freshness import freshness, freshness_report

    info = freshness(repo, cadence_seconds=15)
    print(info["verdict"])      # "fresh"
    print(info["age_seconds"])  # 12.4

    print(freshness_report(repo))
    # "fresh — last stroke 12s ago (cadence 15s)"
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


_TIERS = [
    ("fresh", 2),
    ("warm", 5),
    ("stale", 20),
]
_FALLBACK = "dead"


def _last_stroke_time(strokes_path: Path) -> datetime | None:
    """Read the timestamp of the last line in strokes.jsonl.

    Seeks from the end for efficiency — the file can be thousands of lines
    long but we only need the final entry.
    """
    if not strokes_path.exists():
        return None
    with open(strokes_path, "rb") as f:
        # Seek to end, then scan backwards for the last newline
        f.seek(0, 2)
        size = f.tell()
        if size == 0:
            return None
        # Read last 1024 bytes — enough for one JSONL line
        read_size = min(size, 1024)
        f.seek(-read_size, 2)
        chunk = f.read().decode("utf-8", errors="replace")
    lines = [l for l in chunk.strip().split("\n") if l.strip()]
    if not lines:
        return None
    try:
        entry = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    ts_str = entry.get("at")
    if ts_str is None:
        return None
    return datetime.fromisoformat(ts_str)


def _classify(age_seconds: float, cadence_seconds: float) -> str:
    """Map an age to a freshness verdict."""
    for verdict, multiplier in _TIERS:
        if age_seconds < multiplier * cadence_seconds:
            return verdict
    return _FALLBACK


def freshness(
    repo: Path,
    cadence_seconds: float = 15.0,
    now: datetime | None = None,
) -> dict:
    """Return a freshness snapshot for the repo.

    Parameters
    ----------
    repo:
        Repository root (must contain ``data/strokes.jsonl``).
    cadence_seconds:
        Expected interval between strokes (default 15 s).
    now:
        Override "now" for testing; defaults to ``datetime.now(timezone.utc)``.

    Returns
    -------
    dict with keys: ``verdict``, ``age_seconds``, ``cadence_seconds``,
    ``last_stroke_at`` (ISO string or ``None``), ``strokes_path``.
    """
    strokes_path = repo / "data" / "strokes.jsonl"
    last_ts = _last_stroke_time(strokes_path)
    if now is None:
        now = datetime.now(timezone.utc)

    if last_ts is None:
        return {
            "verdict": _FALLBACK,
            "age_seconds": float("inf"),
            "cadence_seconds": cadence_seconds,
            "last_stroke_at": None,
            "strokes_path": str(strokes_path),
        }

    age = (now - last_ts).total_seconds()
    return {
        "verdict": _classify(age, cadence_seconds),
        "age_seconds": round(age, 1),
        "cadence_seconds": cadence_seconds,
        "last_stroke_at": last_ts.isoformat(),
        "strokes_path": str(strokes_path),
    }


def freshness_report(
    repo: Path,
    cadence_seconds: float = 15.0,
    now: datetime | None = None,
) -> str:
    """One-line human-readable freshness summary.

    Example: ``"fresh — last stroke 12s ago (cadence 15s)"``
    """
    info = freshness(repo, cadence_seconds=cadence_seconds, now=now)
    if info["last_stroke_at"] is None:
        return "dead — no strokes found in data/strokes.jsonl"
    age = info["age_seconds"]
    if age < 60:
        age_str = f"{age:.0f}s"
    elif age < 3600:
        age_str = f"{age / 60:.1f}m"
    else:
        age_str = f"{age / 3600:.1f}h"
    return (
        f"{info['verdict']} — last stroke {age_str} ago "
        f"(cadence {cadence_seconds:.0f}s)"
    )
