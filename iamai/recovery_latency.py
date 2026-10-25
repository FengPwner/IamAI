"""recovery_latency — measure stall-to-recovery duration.

When the automated writing system stalls (writer stops producing strokes),
the time from stall onset to recovery matters.  This module answers:

    "How long has the system been down, and how fast did we recover?"

It reads the strokes.jsonl log to find the last stroke timestamp, then
compares it against the current time (or a given reference time) to
compute recovery latency.

Key concepts
~~~~~~~~~~~~

- **stall onset**: timestamp of the last stroke before a gap exceeding
  ``cadence * stall_multiplier`` (default: 10x the normal cadence).
- **recovery time**: the timestamp of the first stroke *after* the gap.
- **recovery latency**: ``recovery_time - stall_onset`` in seconds.

If the system is still stalled (no recovery stroke yet), recovery latency
is measured as ``now - stall_onset`` and the ``recovered`` flag is False.

Usage::

    from iamai.recovery_latency import measure_recovery

    result = measure_recovery(repo, cadence_seconds=15)
    print(result["latency_seconds"])  # 1423.0
    print(result["recovered"])        # True or False
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime."""
    # Handle various ISO formats
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _load_strokes(strokes_path: Path) -> list[dict[str, Any]]:
    """Load stroke entries from the JSONL file."""
    if not strokes_path.exists():
        return []
    strokes = []
    with open(strokes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    strokes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return strokes


def find_stall_gaps(
    strokes: list[dict[str, Any]],
    cadence_seconds: float = 15.0,
    stall_multiplier: float = 10.0,
) -> list[dict[str, Any]]:
    """Find all gaps in stroke production that exceed the stall threshold.

    Returns a list of gap records, each containing:
    - ``before_seq``: seq number of the last stroke before the gap
    - ``after_seq``: seq number of the first stroke after the gap (or None)
    - ``before_ts``: timestamp of the last stroke before the gap
    - ``after_ts``: timestamp of the first stroke after the gap (or None)
    - ``gap_seconds``: duration of the gap in seconds
    - ``recovered``: True if a stroke appeared after the gap

    Parameters
    ----------
    strokes : list of stroke dicts (must have ``at`` and ``seq`` keys)
    cadence_seconds : expected interval between strokes
    stall_multiplier : gap must exceed ``cadence * stall_multiplier`` to
                       count as a stall
    """
    threshold = cadence_seconds * stall_multiplier
    gaps: list[dict[str, Any]] = []

    if len(strokes) < 2:
        return gaps

    for i in range(len(strokes) - 1):
        try:
            ts_before = _parse_iso(strokes[i]["at"])
            ts_after = _parse_iso(strokes[i + 1]["at"])
        except (KeyError, ValueError):
            continue

        gap = (ts_after - ts_before).total_seconds()
        if gap > threshold:
            gaps.append({
                "before_seq": strokes[i].get("seq"),
                "after_seq": strokes[i + 1].get("seq"),
                "before_ts": strokes[i]["at"],
                "after_ts": strokes[i + 1]["at"],
                "gap_seconds": gap,
                "recovered": True,
            })

    return gaps


def measure_recovery(
    repo: Path,
    cadence_seconds: float = 15.0,
    stall_multiplier: float = 10.0,
    now: datetime | None = None,
    strokes_path: Path | None = None,
) -> dict[str, Any]:
    """Measure the most recent stall and recovery status.

    Returns a dict with:
    - ``stalled``: True if a stall was detected at any point
    - ``recovered``: True if the most recent stall has been recovered
    - ``latency_seconds``: seconds from stall onset to recovery (or to now)
    - ``stall_onset``: ISO timestamp of the last stroke before the stall
    - ``recovery_time``: ISO timestamp of recovery (or None if still stalled)
    - ``total_stalls``: total number of stall events in history
    - ``recovered_stalls``: number of recovered stall events
    - ``longest_gap_seconds``: longest stall gap ever recorded

    Parameters
    ----------
    repo : Path to the repository root
    cadence_seconds : expected interval between strokes
    stall_multiplier : gap must exceed ``cadence * stall_multiplier`` to
                       count as a stall
    now : reference time (defaults to current UTC time)
    strokes_path : override path to strokes.jsonl (for testing)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if strokes_path is None:
        strokes_path = repo / "data" / "strokes.jsonl"

    strokes = _load_strokes(strokes_path)
    gaps = find_stall_gaps(strokes, cadence_seconds, stall_multiplier)

    result: dict[str, Any] = {
        "stalled": False,
        "recovered": False,
        "latency_seconds": 0.0,
        "stall_onset": None,
        "recovery_time": None,
        "total_stalls": len(gaps),
        "recovered_stalls": sum(1 for g in gaps if g["recovered"]),
        "longest_gap_seconds": 0.0,
    }

    if gaps:
        result["longest_gap_seconds"] = max(g["gap_seconds"] for g in gaps)

    if not strokes:
        return result

    # Check if currently stalled: is the last stroke too old?
    last_stroke = strokes[-1]
    try:
        last_ts = _parse_iso(last_stroke["at"])
    except (KeyError, ValueError):
        return result

    age = (now - last_ts).total_seconds()
    threshold = cadence_seconds * stall_multiplier

    if age > threshold:
        # Currently stalled
        result["stalled"] = True
        result["recovered"] = False
        result["stall_onset"] = last_stroke["at"]
        result["latency_seconds"] = age
        result["total_stalls"] = len(gaps) + 1  # include current
    elif gaps:
        # Not currently stalled, but had stalls in the past
        last_gap = gaps[-1]
        result["stalled"] = True
        result["recovered"] = True
        result["stall_onset"] = last_gap["before_ts"]
        result["recovery_time"] = last_gap["after_ts"]
        result["latency_seconds"] = last_gap["gap_seconds"]

    return result


def recovery_report(
    repo: Path,
    cadence_seconds: float = 15.0,
    stall_multiplier: float = 10.0,
    now: datetime | None = None,
) -> str:
    """Human-readable recovery latency report."""
    result = measure_recovery(repo, cadence_seconds, stall_multiplier, now)

    if not result["stalled"]:
        return "no stalls detected — system has been healthy"

    lines = []
    lines.append(f"total stall events: {result['total_stalls']}")
    lines.append(f"recovered: {result['recovered_stalls']}")
    lines.append(f"longest gap: {result['longest_gap_seconds']:.0f}s")

    if result["recovered"]:
        lines.append(
            f"last stall: {result['stall_onset']} -> {result['recovery_time']} "
            f"({result['latency_seconds']:.0f}s latency)"
        )
    else:
        lines.append(
            f"CURRENTLY STALLED since {result['stall_onset']} "
            f"({result['latency_seconds']:.0f}s and counting)"
        )

    return "\n".join(lines)
