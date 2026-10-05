"""Track recovery events for the writer/batch process lifecycle.

A recovery event is the sequence: dead → restart → push complete.
Recording each event's timestamps lets us compute how long recoveries
take, spot trends, and alert when recovery itself is stalling.

This is deliberately simple: a JSON-lines file with one event per line,
plus a summary function. No database, no ORM — just timestamps.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def record_event(
    filepath: str | Path,
    detected_at: str,
    restarted_at: str,
    pushed_at: str,
    uncommitted_files: int = 0,
    notes: str = "",
) -> dict[str, Any]:
    """Append a recovery event to the JSONL file.

    Args:
        filepath: path to the recovery log (JSONL)
        detected_at: ISO timestamp when dead processes were detected
        restarted_at: ISO timestamp when processes were restarted
        pushed_at: ISO timestamp when push to remote succeeded
        uncommitted_files: how many files were pending at detection
        notes: free-text annotation (e.g., "push rejected, rebase needed")

    Returns:
        The event dict that was written
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "detected_at": detected_at,
        "restarted_at": restarted_at,
        "pushed_at": pushed_at,
        "uncommitted_files": uncommitted_files,
        "notes": notes,
    }

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return event


def load_events(filepath: str | Path) -> list[dict[str, Any]]:
    """Load all recovery events from the JSONL file.

    Args:
        filepath: path to the recovery log

    Returns:
        List of event dicts, oldest first
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return []

    events = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def _duration_seconds(start_iso: str, end_iso: str) -> float:
    """Compute seconds between two ISO timestamps."""
    fmt_start = datetime.fromisoformat(start_iso)
    fmt_end = datetime.fromisoformat(end_iso)
    return (fmt_end - fmt_start).total_seconds()


def recovery_stats(filepath: str | Path) -> dict[str, Any]:
    """Compute summary statistics for recovery events.

    Returns a dict with:
        - count: number of recorded recoveries
        - avg_restart_seconds: mean time from detection to restart
        - avg_push_seconds: mean time from restart to push
        - avg_total_seconds: mean time from detection to push
        - max_total_seconds: worst-case total recovery time

    Returns zeros if no events recorded.
    """
    events = load_events(filepath)
    if not events:
        return {
            "count": 0,
            "avg_restart_seconds": 0.0,
            "avg_push_seconds": 0.0,
            "avg_total_seconds": 0.0,
            "max_total_seconds": 0.0,
        }

    restart_secs = []
    push_secs = []
    total_secs = []

    for ev in events:
        r = _duration_seconds(ev["detected_at"], ev["restarted_at"])
        p = _duration_seconds(ev["restarted_at"], ev["pushed_at"])
        t = _duration_seconds(ev["detected_at"], ev["pushed_at"])
        restart_secs.append(r)
        push_secs.append(p)
        total_secs.append(t)

    count = len(events)
    return {
        "count": count,
        "avg_restart_seconds": round(sum(restart_secs) / count, 1),
        "avg_push_seconds": round(sum(push_secs) / count, 1),
        "avg_total_seconds": round(sum(total_secs) / count, 1),
        "max_total_seconds": round(max(total_secs), 1),
    }
