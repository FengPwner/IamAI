"""Incarnation — track process lifecycle lineages.

The writer and batch committer are periodically killed by the container
runtime and restarted by ``run_both.sh``.  Each restart spawns a new
process with a new PID — an **incarnation** — that inherits the previous
session's state (stroke sequence, git HEAD, pending files).

``uptime_tracker`` answers "how long has the *current* session been
running".  ``restart_audit`` classifies *gap types* in stroke history.
Neither answers the broader question:

    *How many times have these processes been recycled, and how long
    does each incarnation typically survive?*

This module reads the ``data/restart_warmup.jsonl`` log (and optionally
the writer log at ``/tmp/iamai-<id>.log``) and builds a lineage: a
chronological list of incarnations with their lifespan, first stroke,
and restart cause.

Three public functions:

- ``incarnation_history(writer_id)`` — parse the warmup log and return a
  list of ``Incarnation`` dicts, each with keys ``pid``, ``start``,
  ``end``, ``duration_seconds``, ``first_stroke``.
- ``incarnation_stats(history)`` — summary statistics: total incarnations,
  mean/median/min/max duration, shortest survivor.
- ``current_incarnation(writer_id)`` — info about the *currently running*
  process, including how long it has been alive (reads PID file + /proc).

Verdict thresholds (for ``incarnation_verdict``)::

    mean_duration ≥ 3600 s  →  stable     (hour+ sessions)
    mean_duration ≥ 600  s  →  churny     (10-min recycling)
    otherwise               →  flaky      (<10-min sessions)

Edge cases:

- Empty or missing warmup log → returns empty history, verdict ``unknown``.
- Single incarnation with no end → duration is ``None`` (still running).
- Corrupted JSONL lines → silently skipped.

Usage::

    from iamai.incarnation import incarnation_history, incarnation_stats

    history = incarnation_history("qwen")
    stats = incarnation_stats(history)
    print(stats["verdict"])   # "churny"
    print(stats["mean"])      # 1800.0
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

_WARMUP_FILE = "data/restart_warmup.jsonl"

# Verdict thresholds (seconds)
_STABLE_THRESHOLD = 3600
_CHURNY_THRESHOLD = 600


def _repo_root() -> Path:
    """Best-effort repo root: walk up from this file."""
    here = Path(__file__).resolve().parent
    for parent in [here] + list(here.parents):
        if (parent / ".git").is_dir():
            return parent
    return Path.cwd()


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, tolerating Z and +00:00 variants."""
    if not ts_str:
        return None
    s = ts_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _read_warmup_log(path: Path) -> List[Dict[str, Any]]:
    """Read and parse the warmup JSONL, skipping bad lines."""
    events: List[Dict[str, Any]] = []
    if not path.exists():
        return events
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return events
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _pid_file(writer_id: str, kind: str) -> Path:
    return Path(f"/tmp/iamai-{kind}-{writer_id}.pid")


def _read_pid(path: Path) -> Optional[int]:
    """Read a PID from a file."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        return int(text) if text.isdigit() else None
    except (OSError, ValueError):
        return None


def _proc_start_seconds(pid: int) -> Optional[float]:
    """Get process start time as epoch seconds from /proc (Linux only)."""
    try:
        st = os.stat(f"/proc/{pid}")
        return st.st_mtime
    except (OSError, FileNotFoundError):
        return None


# ---------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------


def incarnation_history(
    writer_id: str = "qwen",
    warmup_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Parse the warmup log and return a list of incarnation records.

    Each record has:
    - pid (int)
    - start (datetime or None)
    - end (datetime or None — None if no next incarnation)
    - duration_seconds (float or None)
    - first_stroke (int or None)
    """
    if warmup_path:
        path = Path(warmup_path)
    else:
        path = _repo_root() / _WARMUP_FILE

    events = _read_warmup_log(path)
    if not events:
        return []

    # Build incarnation records: each "restart" event starts one.
    incarnations: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for ev in events:
        event_type = ev.get("event", "")
        pid = ev.get("pid")
        ts = _parse_ts(ev.get("ts", ""))

        if event_type == "restart":
            # Close previous incarnation
            if current is not None:
                current["end"] = ts
                if current["start"] and ts:
                    current["duration_seconds"] = (ts - current["start"]).total_seconds()
                incarnations.append(current)
            # Start new incarnation
            current = {
                "pid": pid,
                "start": ts,
                "end": None,
                "duration_seconds": None,
                "first_stroke": None,
            }

        elif event_type == "first_stroke" and current is not None:
            if ev.get("pid") == current["pid"]:
                current["first_stroke"] = ev.get("stroke_seq")

    # The last incarnation has no end — it may still be running
    if current is not None:
        incarnations.append(current)

    return incarnations


def incarnation_stats(
    history: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute summary statistics from an incarnation history.

    Returns a dict with:
    - count (int)
    - mean (float or None)
    - median (float or None)
    - min (float or None)
    - max (float or None)
    - shortest_pid (int or None)
    - verdict (str): stable / churny / flaky / unknown
    """
    if not history:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
            "shortest_pid": None,
            "verdict": "unknown",
        }

    durations = [
        h["duration_seconds"]
        for h in history
        if h.get("duration_seconds") is not None
    ]

    if not durations:
        return {
            "count": len(history),
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
            "shortest_pid": history[0].get("pid") if history else None,
            "verdict": "unknown",
        }

    sorted_d = sorted(durations)
    n = len(sorted_d)
    mean = sum(sorted_d) / n
    if n % 2 == 0:
        median = (sorted_d[n // 2 - 1] + sorted_d[n // 2]) / 2
    else:
        median = sorted_d[n // 2]

    # Find shortest incarnation
    shortest = min(history, key=lambda h: h["duration_seconds"]
                   if h.get("duration_seconds") is not None else float("inf"))

    return {
        "count": len(history),
        "mean": round(mean, 1),
        "median": round(median, 1),
        "min": round(min(sorted_d), 1),
        "max": round(max(sorted_d), 1),
        "shortest_pid": shortest.get("pid"),
        "verdict": incarnation_verdict(mean),
    }


def incarnation_verdict(mean_duration: Optional[float]) -> str:
    """Map mean duration to a verdict string."""
    if mean_duration is None:
        return "unknown"
    if mean_duration >= _STABLE_THRESHOLD:
        return "stable"
    if mean_duration >= _CHURNY_THRESHOLD:
        return "churny"
    return "flaky"


def current_incarnation(
    writer_id: str = "qwen",
) -> Dict[str, Any]:
    """Info about the currently running writer process.

    Returns a dict with:
    - pid (int or None)
    - alive (bool)
    - uptime_seconds (float or None)
    - warmup (float) — seconds since PID file was modified
    """
    pf = _pid_file(writer_id, "writer")
    pid = _read_pid(pf)

    alive = False
    uptime: Optional[float] = None
    warmup: Optional[float] = None

    if pid is not None:
        try:
            os.kill(pid, 0)
            alive = True
        except OSError:
            alive = False

        if alive:
            proc_start = _proc_start_seconds(pid)
            if proc_start is not None:
                uptime = time.time() - proc_start

        # Warmup: how long since the PID file was last touched
        try:
            warmup = time.time() - pf.stat().st_mtime
        except OSError:
            pass

    return {
        "pid": pid,
        "alive": alive,
        "uptime_seconds": round(uptime, 1) if uptime is not None else None,
        "warmup_seconds": round(warmup, 1) if warmup is not None else None,
    }


def incarnation_summary(writer_id: str = "qwen") -> str:
    """One-liner for caretaker reports."""
    history = incarnation_history(writer_id)
    stats = incarnation_stats(history)
    cur = current_incarnation(writer_id)

    if not history:
        return f"no incarnation history for '{writer_id}'"

    count = stats["count"]
    verdict = stats["verdict"]
    mean_str = f"{stats['mean']:.0f}s" if stats["mean"] is not None else "?"
    cur_str = "alive" if cur["alive"] else "dead"
    cur_pid = cur["pid"] or "?"
    cur_up = f"{cur['uptime_seconds']:.0f}s" if cur.get("uptime_seconds") else "?"

    return (
        f"{count} incarnation(s), mean {mean_str}, "
        f"verdict: {verdict} | current: pid {cur_pid} {cur_str} ({cur_up})"
    )
