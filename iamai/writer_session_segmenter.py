"""writer_session_segmenter — split stroke history into writing sessions.

A *session* is a maximal run of consecutive strokes where no two adjacent
strokes are separated by more than ``gap_threshold`` seconds.  The segmenter
reads timestamped stroke data (the append-only ``data/strokes.jsonl`` log)
and produces per-session summaries plus aggregate statistics.

Why it matters
--------------

The writer runs in bursts.  Knowing the shape of those bursts — how long
they last, how dense they are, what kinds of strokes dominate — helps the
caretaker distinguish healthy cadence from pathological patterns like
micro-sessions (one stroke then crash) or marathon sessions (writer stuck
in a loop, never yielding).

Session metrics
~~~~~~~~~~~~~~~

Each session dict contains:

==================  ======================================================
key                 meaning
==================  ======================================================
session_id          1-based index in chronological order
start               ISO-8601 timestamp of the first stroke
end                 ISO-8601 timestamp of the last stroke
duration_seconds    wall-clock seconds from first to last stroke
stroke_count        number of strokes in this session
stroke_rate         strokes per minute (0 for single-stroke sessions)
kinds               dict of {kind: count} within this session
first_text          preview of the first stroke's text (up to 80 chars)
==================  ======================================================

Aggregate summary
~~~~~~~~~~~~~~~~~

``session_summary()`` returns:

=====================  =================================================
key                    meaning
=====================  =================================================
total_sessions         number of sessions found
total_strokes          sum of all stroke counts
avg_session_length     mean stroke count per session
avg_duration_minutes   mean session duration in minutes
avg_rate_per_min       mean stroke rate across sessions
longest_session        dict of the session with the most strokes
shortest_session       dict of the session with the fewest strokes
micro_sessions         count of sessions with exactly 1 stroke
marathon_sessions      count of sessions longer than 1 hour
gap_threshold_used     the threshold (seconds) that was applied
=====================  =================================================

Usage::

    from iamai.writer_session_segmenter import segment, session_summary

    strokes = [
        {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "hello"},
        {"at": "2026-10-27T10:00:15+00:00", "kind": "note",    "text": "world"},
        {"at": "2026-10-27T10:15:00+00:00", "kind": "thought", "text": "new session"},
    ]
    sessions = segment(strokes, gap_threshold=300)
    assert len(sessions) == 2

    summary = session_summary(strokes)
    print(summary["total_sessions"])   # 2
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# timestamp parsing
# ---------------------------------------------------------------------------


def _parse_ts(raw: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# core segmentation
# ---------------------------------------------------------------------------


def segment(
    strokes: Sequence[Dict[str, Any]],
    gap_threshold: int = 300,
) -> List[Dict[str, Any]]:
    """Split *strokes* into sessions.

    Parameters
    ----------
    strokes:
        Ordered sequence of dicts.  Each must have ``"at"`` (ISO-8601
        timestamp).  Optional keys: ``"kind"``, ``"text"``, ``"seq"``.
    gap_threshold:
        Seconds.  Two consecutive strokes with a gap **strictly greater**
        than this value start a new session.

    Returns
    -------
    list of session dicts (see module docstring for schema).
    """
    if not strokes:
        return []

    # --- build time-sorted index ------------------------------------------
    indexed: list[tuple[int, datetime, dict]] = []
    for i, s in enumerate(strokes):
        ts = _parse_ts(s.get("at", ""))
        if ts is None:
            continue
        indexed.append((i, ts, s))

    if not indexed:
        return []

    indexed.sort(key=lambda t: t[1])

    # --- split into sessions ----------------------------------------------
    sessions: list[dict[str, Any]] = []
    current: list[tuple[int, datetime, dict]] = [indexed[0]]

    for item in indexed[1:]:
        _, ts, _ = item
        prev_ts = current[-1][1]
        gap = (ts - prev_ts).total_seconds()
        if gap > gap_threshold:
            sessions.append(_build_session(current, len(sessions) + 1))
            current = [item]
        else:
            current.append(item)

    # flush last session
    sessions.append(_build_session(current, len(sessions) + 1))

    return sessions


def _build_session(
    entries: list[tuple[int, datetime, dict]],
    session_id: int,
) -> Dict[str, Any]:
    """Construct a session summary dict from its member entries."""
    first_ts = entries[0][1]
    last_ts = entries[-1][1]
    duration = (last_ts - first_ts).total_seconds()
    count = len(entries)

    kinds: Counter = Counter()
    for _, _, s in entries:
        k = s.get("kind", "unknown")
        kinds[k] += 1

    rate = (count / (duration / 60.0)) if duration > 0 else 0.0

    first_text = str(entries[0][2].get("text", ""))
    preview = first_text[:80] if first_text else ""

    return {
        "session_id": session_id,
        "start": first_ts.isoformat(),
        "end": last_ts.isoformat(),
        "duration_seconds": round(duration, 1),
        "stroke_count": count,
        "stroke_rate": round(rate, 2),
        "kinds": dict(kinds),
        "first_text": preview,
    }


# ---------------------------------------------------------------------------
# aggregate summary
# ---------------------------------------------------------------------------


def session_summary(
    strokes: Sequence[Dict[str, Any]],
    gap_threshold: int = 300,
) -> Dict[str, Any]:
    """Compute aggregate statistics across all sessions.

    Returns a dict (see module docstring for keys).
    """
    sessions = segment(strokes, gap_threshold=gap_threshold)

    if not sessions:
        return {
            "total_sessions": 0,
            "total_strokes": 0,
            "avg_session_length": 0.0,
            "avg_duration_minutes": 0.0,
            "avg_rate_per_min": 0.0,
            "longest_session": None,
            "shortest_session": None,
            "micro_sessions": 0,
            "marathon_sessions": 0,
            "gap_threshold_used": gap_threshold,
        }

    counts = [s["stroke_count"] for s in sessions]
    durations_min = [s["duration_seconds"] / 60.0 for s in sessions]
    rates = [s["stroke_rate"] for s in sessions]

    longest = max(sessions, key=lambda s: s["stroke_count"])
    shortest = min(sessions, key=lambda s: s["stroke_count"])

    micro = sum(1 for c in counts if c == 1)
    marathon = sum(1 for d in durations_min if d > 60.0)

    n = len(sessions)
    return {
        "total_sessions": n,
        "total_strokes": sum(counts),
        "avg_session_length": round(sum(counts) / n, 2),
        "avg_duration_minutes": round(sum(durations_min) / n, 2),
        "avg_rate_per_min": round(sum(rates) / n, 2),
        "longest_session": longest,
        "shortest_session": shortest,
        "micro_sessions": micro,
        "marathon_sessions": marathon,
        "gap_threshold_used": gap_threshold,
    }


# ---------------------------------------------------------------------------
# convenience: load from jsonl
# ---------------------------------------------------------------------------


def load_strokes(path: str | Path = "data/strokes.jsonl") -> List[Dict[str, Any]]:
    """Read all strokes from a JSONL file.

    Each line must be a valid JSON object.  Malformed lines are skipped.
    """
    p = Path(path)
    if not p.exists():
        return []
    results: list[dict[str, Any]] = []
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return results
