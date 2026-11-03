"""visit_diff — compare two caretaker visit snapshots.

Between one caretaker visit and the next, many things can happen:
strokes land, commits are made, processes die and restart, backlog
grows or shrinks.  The caretaker needs a quick, structured summary
of *what changed* — not a full log dump, but the deltas that matter.

This module takes two visit snapshots (dicts) and returns a
``VisitDelta`` describing the interval.

Snapshot schema (what the caretaker collects at each visit)::

    {
        "ts": "2026-11-03T16:00:00+08:00",   # ISO-8601 visit time
        "writer_running": True,              # bool
        "batch_running": True,               # bool
        "writer_pid": 12345,                 # int or None
        "batch_pid": 12346,                  # int or None
        "uncommitted_files": 0,              # int
        "unpushed_commits": 3,               # int
        "total_strokes": 6100,               # int (lines in strokes.jsonl)
        "last_commit_sha": "abc1234",        # str or None
        "stall_detected": False,             # bool
    }

Output (``VisitDelta``) fields::

    elapsed_seconds       wall-clock seconds between visits
    strokes_produced      new strokes (total_strokes delta)
    strokes_per_minute    average stroke rate in the interval
    commits_made          unpushed_commits delta (positive = grew)
    backlog_cleared       True if uncommitted went from >0 to 0
    writer_restarted      True if writer_pid changed or went down→up
    batch_restarted       True if batch_pid changed or went down→up
    writer_downtime       "was_down" | "was_up" | "unknown"
    stall_now             True if stall_detected flipped to True
    summary               one-line human-readable summary

Grades for ``writer_downtime``:

==============  =====================================================
value           meaning
==============  =====================================================
was_up          writer was running at both visits (no restart needed)
was_down        writer was NOT running at previous visit (restart happened)
unknown         previous snapshot missing or malformed
==============  =====================================================

Usage::

    from iamai.visit_diff import diff, VisitDelta

    prev = {"ts": "...", "writer_running": False, ...}
    curr = {"ts": "...", "writer_running": True,  ...}

    delta = diff(prev, curr)
    print(delta.summary)
    print(delta.strokes_produced)

Pure function — no I/O, no subprocess, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_ts(ts: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    if not ts:
        return None
    try:
        # handle +08:00 style offsets
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _safe_int(val, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_bool(val, default: bool = False) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return default


# ---------------------------------------------------------------------------
# VisitDelta
# ---------------------------------------------------------------------------


@dataclass
class VisitDelta:
    """Structured comparison between two caretaker visit snapshots."""

    elapsed_seconds: float = 0.0
    strokes_produced: int = 0
    strokes_per_minute: float = 0.0
    commits_made: int = 0
    backlog_cleared: bool = False
    writer_restarted: bool = False
    batch_restarted: bool = False
    writer_downtime: str = "unknown"
    stall_now: bool = False
    summary: str = ""

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "strokes_produced": self.strokes_produced,
            "strokes_per_minute": round(self.strokes_per_minute, 2),
            "commits_made": self.commits_made,
            "backlog_cleared": self.backlog_cleared,
            "writer_restarted": self.writer_restarted,
            "batch_restarted": self.batch_restarted,
            "writer_downtime": self.writer_downtime,
            "stall_now": self.stall_now,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# core diff
# ---------------------------------------------------------------------------


def diff(prev: dict, curr: dict) -> VisitDelta:
    """Compare two visit snapshots and return a VisitDelta.

    Parameters
    ----------
    prev : dict
        Snapshot from the previous visit.
    curr : dict
        Snapshot from the current visit.

    Returns
    -------
    VisitDelta
        Structured summary of what changed.
    """
    delta = VisitDelta()

    # -- elapsed time --
    t_prev = _parse_ts(prev.get("ts", ""))
    t_curr = _parse_ts(curr.get("ts", ""))
    if t_prev and t_curr and t_curr >= t_prev:
        delta.elapsed_seconds = (t_curr - t_prev).total_seconds()
    elif t_prev and t_curr:
        delta.elapsed_seconds = 0.0  # clock went backwards — treat as 0

    # -- strokes --
    s_prev = _safe_int(prev.get("total_strokes"))
    s_curr = _safe_int(curr.get("total_strokes"))
    delta.strokes_produced = max(0, s_curr - s_prev)
    if delta.elapsed_seconds > 0:
        delta.strokes_per_minute = (
            delta.strokes_produced / (delta.elapsed_seconds / 60.0)
        )

    # -- commits --
    c_prev = _safe_int(prev.get("unpushed_commits"))
    c_curr = _safe_int(curr.get("unpushed_commits"))
    delta.commits_made = c_curr - c_prev  # can be negative if pushes happened

    # -- backlog --
    u_prev = _safe_int(prev.get("uncommitted_files"))
    u_curr = _safe_int(curr.get("uncommitted_files"))
    delta.backlog_cleared = (u_prev > 0 and u_curr == 0)

    # -- writer restart detection --
    w_prev_running = _safe_bool(prev.get("writer_running"))
    w_curr_running = _safe_bool(curr.get("writer_running"))
    has_prev = "writer_running" in prev
    pid_prev = prev.get("writer_pid")
    pid_curr = curr.get("writer_pid")

    if not has_prev:
        delta.writer_downtime = "unknown"
    elif not w_prev_running and w_curr_running:
        delta.writer_restarted = True
        delta.writer_downtime = "was_down"
    elif w_prev_running and w_curr_running and pid_prev != pid_curr:
        delta.writer_restarted = True
        delta.writer_downtime = "was_up"  # pid changed while both "running"
    elif w_prev_running and w_curr_running:
        delta.writer_downtime = "was_up"
    elif w_prev_running and not w_curr_running:
        delta.writer_downtime = "was_up"
    elif not w_prev_running and not w_curr_running:
        delta.writer_downtime = "was_down"

    # -- batch restart detection --
    b_prev_running = _safe_bool(prev.get("batch_running"))
    b_curr_running = _safe_bool(curr.get("batch_running"))
    bpid_prev = prev.get("batch_pid")
    bpid_curr = curr.get("batch_pid")

    if not b_prev_running and b_curr_running:
        delta.batch_restarted = True
    elif b_prev_running and b_curr_running and bpid_prev != bpid_curr:
        delta.batch_restarted = True

    # -- stall --
    delta.stall_now = _safe_bool(curr.get("stall_detected"))

    # -- summary --
    parts = []
    if delta.elapsed_seconds > 0:
        mins = delta.elapsed_seconds / 60
        parts.append(f"{mins:.0f}min gap")
    if delta.strokes_produced > 0:
        parts.append(f"{delta.strokes_produced} new strokes")
    if delta.strokes_per_minute > 0:
        parts.append(f"{delta.strokes_per_minute:.1f}/min")
    if delta.writer_restarted:
        parts.append("writer restarted")
    if delta.batch_restarted:
        parts.append("batch restarted")
    if delta.backlog_cleared:
        parts.append("backlog cleared")
    if delta.stall_now:
        parts.append("STALL detected")
    delta.summary = ", ".join(parts) if parts else "no change"

    return delta


# ---------------------------------------------------------------------------
# convenience: batch diff
# ---------------------------------------------------------------------------


def diff_many(snapshots: list) -> list:
    """Compute diffs between consecutive snapshots.

    Parameters
    ----------
    snapshots : list[dict]
        Ordered list of visit snapshots (oldest first).

    Returns
    -------
    list[VisitDelta]
        One delta per consecutive pair.
    """
    if len(snapshots) < 2:
        return []
    return [diff(snapshots[i], snapshots[i + 1]) for i in range(len(snapshots) - 1)]
