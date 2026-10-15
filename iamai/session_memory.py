"""Session memory — reconstruct session boundaries and summaries from stroke logs.

The writer runs in bursts separated by silence. A *session* is a contiguous
run of strokes where no inter-stroke gap exceeds ``max_gap_seconds`` (default
30 minutes). When the gap is wider, a new session begins.

This module answers three questions:

1. **How many sessions have there been, and when?**
2. **What happened in each session?** (stroke count, kinds, duration, files)
3. **What should the next session know?** (a brief summarising recent work)

Usage::

    from iamai.session_memory import (
        detect_sessions,
        session_summary,
        session_brief,
    )

    sessions = detect_sessions(max_gap_seconds=1800)
    for s in sessions[-3:]:
        print(f"session {s['id']}: {s['stroke_count']} strokes, "
              f"{s['duration_seconds']}s, kinds={s['kind_breakdown']}")

    brief = session_brief(last_n=5)
    print(brief)
    # "5 sessions: 127 strokes over 4h12m, top kinds: thought(45) note(32) ..."

Design notes:

- Sessions are detected purely from timestamps; no external state needed.
- The brief is deterministic: same inputs always produce the same output.
- Large repos with tens of thousands of strokes still parse in <1s because
  we only read timestamps and kinds, not full text bodies.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_DEFAULT_STROKES_PATH = Path("data/strokes.jsonl")

# Gaps longer than this (seconds) start a new session.
DEFAULT_SESSION_GAP = 1800  # 30 minutes


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp to a timezone-aware UTC datetime."""
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_strokes_light(path: Path) -> List[Dict[str, Any]]:
    """Load only the fields we need from strokes.jsonl.

    We skip ``text`` to keep memory low on large logs.
    """
    if not path.exists():
        return []

    strokes: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            at = obj.get("at")
            if not at:
                continue
            strokes.append({
                "seq": obj.get("seq", 0),
                "at": _parse_ts(at),
                "kind": obj.get("kind", "unknown"),
                "path": obj.get("path", ""),
            })
    return strokes


def detect_sessions(
    strokes_path: Optional[Path] = None,
    max_gap_seconds: int = DEFAULT_SESSION_GAP,
) -> List[Dict[str, Any]]:
    """Detect sessions from stroke timestamps.

    Returns a list of session dicts, each containing::

        {
            "id": 1-based session index,
            "start": datetime,
            "end": datetime,
            "duration_seconds": float,
            "stroke_count": int,
            "kind_breakdown": {"thought": 12, "note": 5, ...},
            "files_touched": ["notes/history.md", ...],
            "first_seq": int,
            "last_seq": int,
        }
    """
    path = strokes_path or _DEFAULT_STROKES_PATH
    strokes = _load_strokes_light(path)
    if not strokes:
        return []

    sessions: List[Dict[str, Any]] = []
    current_strokes: List[Dict[str, Any]] = [strokes[0]]

    for i in range(1, len(strokes)):
        gap = (strokes[i]["at"] - strokes[i - 1]["at"]).total_seconds()
        if gap > max_gap_seconds:
            sessions.append(_build_session(len(sessions) + 1, current_strokes))
            current_strokes = [strokes[i]]
        else:
            current_strokes.append(strokes[i])

    # Last session
    sessions.append(_build_session(len(sessions) + 1, current_strokes))
    return sessions


def _build_session(session_id: int, strokes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a summary dict for one session."""
    start = strokes[0]["at"]
    end = strokes[-1]["at"]
    duration = (end - start).total_seconds()

    kind_counts: Counter = Counter(s["kind"] for s in strokes)
    files = sorted({s["path"] for s in strokes if s["path"]})

    return {
        "id": session_id,
        "start": start,
        "end": end,
        "duration_seconds": duration,
        "stroke_count": len(strokes),
        "kind_breakdown": dict(kind_counts.most_common()),
        "files_touched": files,
        "first_seq": strokes[0]["seq"],
        "last_seq": strokes[-1]["seq"],
    }


def session_summary(
    strokes_path: Optional[Path] = None,
    max_gap_seconds: int = DEFAULT_SESSION_GAP,
) -> Dict[str, Any]:
    """Return aggregate statistics across all detected sessions.

    Returns::

        {
            "total_sessions": int,
            "total_strokes": int,
            "total_duration_seconds": float,
            "avg_strokes_per_session": float,
            "avg_duration_seconds": float,
            "longest_session_id": int,
            "longest_session_strokes": int,
            "kind_totals": {"thought": 120, "note": 95, ...},
        }
    """
    sessions = detect_sessions(strokes_path, max_gap_seconds)
    if not sessions:
        return {
            "total_sessions": 0,
            "total_strokes": 0,
            "total_duration_seconds": 0.0,
            "avg_strokes_per_session": 0.0,
            "avg_duration_seconds": 0.0,
            "longest_session_id": 0,
            "longest_session_strokes": 0,
            "kind_totals": {},
        }

    total_strokes = sum(s["stroke_count"] for s in sessions)
    total_duration = sum(s["duration_seconds"] for s in sessions)
    longest = max(sessions, key=lambda s: s["stroke_count"])

    kind_totals: Counter = Counter()
    for s in sessions:
        kind_totals.update(s["kind_breakdown"])

    return {
        "total_sessions": len(sessions),
        "total_strokes": total_strokes,
        "total_duration_seconds": total_duration,
        "avg_strokes_per_session": total_strokes / len(sessions),
        "avg_duration_seconds": total_duration / len(sessions),
        "longest_session_id": longest["id"],
        "longest_session_strokes": longest["stroke_count"],
        "kind_totals": dict(kind_totals.most_common()),
    }


def session_brief(
    strokes_path: Optional[Path] = None,
    max_gap_seconds: int = DEFAULT_SESSION_GAP,
    last_n: int = 5,
) -> str:
    """Generate a human-readable brief of the most recent sessions.

    Example output::

        session 14: 42 strokes, 10m30s, thought(15) note(10) snippet(9) devlog(8)
        session 15: 38 strokes, 9m15s, note(12) thought(10) metrics(8) snippet(8)
        ---
        5 sessions: 187 strokes over 48m15s, top kinds: thought(52) note(45) ...
    """
    sessions = detect_sessions(strokes_path, max_gap_seconds)
    if not sessions:
        return "no sessions detected"

    recent = sessions[-last_n:]
    lines: List[str] = []

    for s in recent:
        dur = _format_duration(s["duration_seconds"])
        kinds = " ".join(f"{k}({v})" for k, v in sorted(
            s["kind_breakdown"].items(), key=lambda x: -x[1]
        ))
        lines.append(
            f"session {s['id']}: {s['stroke_count']} strokes, "
            f"{dur}, {kinds}"
        )

    # Summary line
    total_strokes = sum(s["stroke_count"] for s in recent)
    total_dur = sum(s["duration_seconds"] for s in recent)

    all_kinds: Counter = Counter()
    for s in recent:
        all_kinds.update(s["kind_breakdown"])
    top = all_kinds.most_common(4)
    top_str = " ".join(f"{k}({v})" for k, v in top)

    lines.append("---")
    lines.append(
        f"{len(recent)} sessions: {total_strokes} strokes over "
        f"{_format_duration(total_dur)}, top kinds: {top_str}"
    )

    return "\n".join(lines)


def _format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s" if secs else f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h{mins:02d}m"


def session_pace(
    strokes_path: Optional[Path] = None,
    max_gap_seconds: int = DEFAULT_SESSION_GAP,
    expected_cadence: float = 15.0,
) -> Dict[str, Any]:
    """Compute per-session cadence adherence.

    For each session, calculates the actual mean gap between strokes
    and compares it to the expected cadence.

    Returns::

        {
            "sessions": [
                {
                    "id": int,
                    "mean_gap": float,
                    "cadence_ratio": float,  # mean_gap / expected_cadence
                    "on_target": bool,       # 0.5 <= ratio <= 2.0
                },
                ...
            ],
            "overall_mean_gap": float,
            "sessions_on_target_pct": float,
        }
    """
    path = strokes_path or _DEFAULT_STROKES_PATH
    strokes = _load_strokes_light(path)
    if not strokes:
        return {"sessions": [], "overall_mean_gap": 0.0, "sessions_on_target_pct": 0.0}

    sessions = detect_sessions(strokes_path, max_gap_seconds)
    results: List[Dict[str, Any]] = []

    # Build per-session mean gaps from the raw stroke list
    session_boundaries = []
    current_start = 0
    for i in range(1, len(strokes)):
        gap = (strokes[i]["at"] - strokes[i - 1]["at"]).total_seconds()
        if gap > max_gap_seconds:
            session_boundaries.append((current_start, i - 1))
            current_start = i
    session_boundaries.append((current_start, len(strokes) - 1))

    all_gaps: List[float] = []
    for idx, (start, end) in enumerate(session_boundaries):
        session_strokes = strokes[start:end + 1]
        if len(session_strokes) < 2:
            results.append({
                "id": idx + 1,
                "mean_gap": 0.0,
                "cadence_ratio": 0.0,
                "on_target": False,
            })
            continue

        gaps = [
            (session_strokes[j]["at"] - session_strokes[j - 1]["at"]).total_seconds()
            for j in range(1, len(session_strokes))
        ]
        mean_gap = sum(gaps) / len(gaps)
        all_gaps.extend(gaps)
        ratio = mean_gap / expected_cadence if expected_cadence > 0 else 0.0

        results.append({
            "id": idx + 1,
            "mean_gap": round(mean_gap, 1),
            "cadence_ratio": round(ratio, 2),
            "on_target": 0.5 <= ratio <= 2.0,
        })

    overall = sum(all_gaps) / len(all_gaps) if all_gaps else 0.0
    on_target_count = sum(1 for r in results if r["on_target"])
    pct = (on_target_count / len(results) * 100) if results else 0.0

    return {
        "sessions": results,
        "overall_mean_gap": round(overall, 1),
        "sessions_on_target_pct": round(pct, 1),
    }
