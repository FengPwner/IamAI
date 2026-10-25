"""commit_session_segmenter — partition a commit stream into sessions.

A *session* is a maximal run of commits where no two consecutive commits
are separated by more than ``gap_threshold`` seconds.  This is the
simplest useful segmentation of a commit history and a prerequisite for
per-session analysis (cadence within a session, focus within a session,
recovery after a session break).

This module fills the gap between:

- ``commit_gap_analyzer``, which classifies *individual* gaps but does
  not group commits into sessions;
- ``commit_phase_detector``, which identifies lifecycle *phases* (boot,
  growth, steady, stall, recovery, decay) via sliding windows;
- ``session_summary``, which summarises an *already-identified* session.

The segmenter answers: *where does one session end and the next begin,
and what does each session look like?*

Usage::

    from iamai.commit_session_segmenter import segment_sessions, SessionSummary

    timestamps = load_commit_timestamps()  # list of ISO-8601 strings
    summary = segment_sessions(timestamps, gap_threshold=1800)
    print(summary.session_count)      # 7
    print(summary.longest_session)    # SessionReport(...)
    print(summary.total_active_time)  # 14400.0
    print(summary.timeline_text)      # ASCII timeline

All timestamps are ISO-8601 strings.  No file I/O is performed.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

__all__ = [
    "SessionReport",
    "SessionSummary",
    "segment_sessions",
    "session_timeline_text",
    "DEFAULT_GAP_THRESHOLD",
]

# Default gap threshold: 1800 seconds (30 minutes).
# The batch committer runs every 600s; a gap of 3× that almost certainly
# means the process was stopped and restarted.
DEFAULT_GAP_THRESHOLD = 1800


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionReport:
    """One contiguous writing session."""

    index: int
    start: str                 # ISO-8601 first commit
    end: str                   # ISO-8601 last commit
    commit_count: int          # number of commits in session
    duration_seconds: float    # end − start (0 for single-commit sessions)
    gaps: List[float]          # inter-commit gaps within session (seconds)
    mean_gap: float            # mean of internal gaps
    median_gap: float          # median of internal gaps
    max_gap: float             # largest internal gap

    @property
    def single_commit(self) -> bool:
        """True if session consists of exactly one commit."""
        return self.commit_count == 1

    @property
    def throughput(self) -> float:
        """Commits per hour.  Returns 0.0 for single-commit sessions."""
        if self.duration_seconds <= 0:
            return 0.0
        return (self.commit_count / self.duration_seconds) * 3600


@dataclass(frozen=True)
class SessionSummary:
    """Aggregate report over all sessions."""

    sessions: List[SessionReport]
    gap_threshold: float
    total_commits: int
    total_active_time: float   # sum of all session durations (seconds)
    total_wall_time: float     # first commit → last commit (seconds)

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    @property
    def longest_session(self) -> Optional[SessionReport]:
        if not self.sessions:
            return None
        return max(self.sessions, key=lambda s: s.duration_seconds)

    @property
    def shortest_session(self) -> Optional[SessionReport]:
        if not self.sessions:
            return None
        return min(
            self.sessions,
            key=lambda s: s.duration_seconds if not s.single_commit else float("inf"),
        )

    @property
    def single_commit_sessions(self) -> int:
        return sum(1 for s in self.sessions if s.single_commit)

    @property
    def mean_session_length(self) -> float:
        if not self.sessions:
            return 0.0
        return statistics.mean(s.commit_count for s in self.sessions)

    @property
    def mean_session_duration(self) -> float:
        if not self.sessions:
            return 0.0
        return statistics.mean(s.duration_seconds for s in self.sessions)

    @property
    def break_durations(self) -> List[float]:
        """Gaps between consecutive sessions (seconds)."""
        if len(self.sessions) < 2:
            return []
        result = []
        for i in range(1, len(self.sessions)):
            prev_end = _parse_iso(self.sessions[i - 1].end)
            curr_start = _parse_iso(self.sessions[i].start)
            result.append((curr_start - prev_end).total_seconds())
        return result

    @property
    def mean_break_duration(self) -> float:
        breaks = self.break_durations
        if not breaks:
            return 0.0
        return statistics.mean(breaks)

    @property
    def active_ratio(self) -> float:
        """Fraction of wall time spent in active sessions."""
        if self.total_wall_time <= 0:
            return 0.0
        return min(self.total_active_time / self.total_wall_time, 1.0)

    @property
    def timeline_text(self) -> str:
        return session_timeline_text(self.sessions, self.gap_threshold)


# ---------------------------------------------------------------------------
# core algorithm
# ---------------------------------------------------------------------------

def segment_sessions(
    timestamps: List[str],
    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
) -> SessionSummary:
    """Partition *timestamps* into sessions.

    Parameters
    ----------
    timestamps : list of ISO-8601 strings
        Must be sorted in chronological order.  Duplicates are kept.
    gap_threshold : float
        Seconds.  Any inter-commit gap strictly greater than this value
        starts a new session.  Default 1800 (30 min).

    Returns
    -------
    SessionSummary
        Aggregate report with per-session detail.

    Raises
    ------
    ValueError
        If *timestamps* is empty.
    """
    if not timestamps:
        raise ValueError("timestamps must not be empty")

    dts = [_parse_iso(t) for t in timestamps]

    # Build session boundaries
    sessions: List[SessionReport] = []
    session_start = 0

    for i in range(1, len(dts)):
        gap = (dts[i] - dts[i - 1]).total_seconds()
        if gap > gap_threshold:
            sessions.append(_build_session(dts, timestamps, session_start, i - 1, len(sessions)))
            session_start = i

    # Last session
    sessions.append(_build_session(dts, timestamps, session_start, len(dts) - 1, len(sessions)))

    total_active = sum(s.duration_seconds for s in sessions)
    wall_time = (dts[-1] - dts[0]).total_seconds() if len(dts) > 1 else 0.0

    return SessionSummary(
        sessions=sessions,
        gap_threshold=gap_threshold,
        total_commits=len(dts),
        total_active_time=total_active,
        total_wall_time=wall_time,
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _build_session(
    dts: list, timestamps: list, start: int, end: int, index: int
) -> SessionReport:
    count = end - start + 1
    gaps: List[float] = []
    for i in range(start + 1, end + 1):
        gaps.append((dts[i] - dts[i - 1]).total_seconds())

    duration = (dts[end] - dts[start]).total_seconds()
    return SessionReport(
        index=index,
        start=timestamps[start],
        end=timestamps[end],
        commit_count=count,
        duration_seconds=duration,
        gaps=gaps,
        mean_gap=statistics.mean(gaps) if gaps else 0.0,
        median_gap=statistics.median(gaps) if gaps else 0.0,
        max_gap=max(gaps) if gaps else 0.0,
    )


def session_timeline_text(
    sessions: List[SessionReport],
    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
) -> str:
    """Produce an ASCII timeline of sessions.

    Each session is rendered as a block ``[====]`` whose width is
    proportional to its duration.  Breaks between sessions are shown
    as ``~~~``.

    Example::

        #0 [====] (12 commits, 7200s)
             ~~~ break 1800s ~~~
        #1 [==========] (24 commits, 14400s)
             ~~~ break 3600s ~~~
        #2 [==] (5 commits, 3600s)
    """
    if not sessions:
        return "(no sessions)"

    max_dur = max(s.duration_seconds for s in sessions) or 1.0
    max_width = 40
    lines: List[str] = []

    for i, s in enumerate(sessions):
        width = max(1, int((s.duration_seconds / max_dur) * max_width))
        bar = "=" * width
        lines.append(
            f"#{s.index} [{bar}] ({s.commit_count} commits, {int(s.duration_seconds)}s)"
        )
        if i < len(sessions) - 1:
            prev_end = _parse_iso(s.end)
            next_start = _parse_iso(sessions[i + 1].start)
            brk = (next_start - prev_end).total_seconds()
            lines.append(f"     ~~~ break {int(brk)}s ~~~")

    return "\n".join(lines)
