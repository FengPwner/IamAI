"""session_boundary_detector — detect work sessions from commit timestamps.

A long-running automated writer produces commits in clusters: bursts
of activity separated by quiet periods.  This module identifies those
clusters as *sessions* and computes per-session statistics useful for
caretaker dashboards and health scoring.

The detection algorithm is straightforward:

1. Compute gaps between consecutive commits.
2. A gap exceeding ``session_gap_threshold`` marks a session boundary.
3. Each run of commits between boundaries is one session.

Usage::

    from iamai.session_boundary_detector import detect_sessions, SessionProfile

    timestamps = load_commit_timestamps()  # ISO-8601 strings
    profile = detect_sessions(timestamps)
    print(profile.session_count)       # 7
    print(profile.mean_session_length) # 12.4 commits
    print(profile.longest_session)     # 34 commits
    print(profile.rhythm)              # "clustered" / "steady" / "scattered"

All functions accept ISO-8601 timestamp strings — no file I/O in core
logic, making it trivially testable.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_SESSION_GAP = 1200.0          # seconds — 20 min gap = new session
DEFAULT_MIN_SESSION_SIZE = 2           # minimum commits to count as a session
DEFAULT_BATCH_INTERVAL = 600.0         # expected commit cadence


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------

@dataclass
class Session:
    """A single detected work session."""

    index: int                         # 0-based session number
    start_time: str                    # ISO-8601 timestamp of first commit
    end_time: str                      # ISO-8601 timestamp of last commit
    commit_count: int = 0
    duration_seconds: float = 0.0
    internal_gaps: List[float] = field(default_factory=list)

    @property
    def mean_gap(self) -> float:
        """Average gap between commits within this session."""
        if not self.internal_gaps:
            return 0.0
        return statistics.mean(self.internal_gaps)

    @property
    def is_burst(self) -> bool:
        """True if mean internal gap < half the batch interval."""
        if not self.internal_gaps:
            return False
        return self.mean_gap < 300.0

    @property
    def cadence_health(self) -> str:
        """How regular the within-session rhythm is.

        ===========  =====================================================
        verdict      meaning
        ===========  =====================================================
        tight        CV < 0.15 — clockwork within this session
        loose        CV < 0.40 — acceptable variation
        ragged       CV >= 0.40 — irregular rhythm
        ===========  =====================================================
        """
        if len(self.internal_gaps) < 2:
            return "unknown"
        m = statistics.mean(self.internal_gaps)
        if m <= 0:
            return "unknown"
        s = statistics.stdev(self.internal_gaps)
        cv = s / m
        if cv < 0.15:
            return "tight"
        if cv < 0.40:
            return "loose"
        return "ragged"


@dataclass
class SessionProfile:
    """Aggregate analysis of all detected sessions."""

    sessions: List[Session] = field(default_factory=list)
    total_commits: int = 0

    @property
    def session_count(self) -> int:
        """Number of detected sessions."""
        return len(self.sessions)

    @property
    def mean_session_length(self) -> float:
        """Average commits per session."""
        if not self.sessions:
            return 0.0
        return statistics.mean(s.commit_count for s in self.sessions)

    @property
    def median_session_length(self) -> float:
        """Median commits per session."""
        if not self.sessions:
            return 0.0
        return statistics.median(s.commit_count for s in self.sessions)

    @property
    def longest_session(self) -> int:
        """Maximum commits in a single session."""
        if not self.sessions:
            return 0
        return max(s.commit_count for s in self.sessions)

    @property
    def shortest_session(self) -> int:
        """Minimum commits in a single session."""
        if not self.sessions:
            return 0
        return min(s.commit_count for s in self.sessions)

    @property
    def burst_count(self) -> int:
        """Number of sessions classified as bursts."""
        return sum(1 for s in self.sessions if s.is_burst)

    @property
    def mean_session_duration(self) -> float:
        """Average session duration in seconds."""
        if not self.sessions:
            return 0.0
        return statistics.mean(s.duration_seconds for s in self.sessions)

    @property
    def total_active_time(self) -> float:
        """Sum of all session durations in seconds."""
        return sum(s.duration_seconds for s in self.sessions)

    @property
    def rhythm(self) -> str:
        """Overall work rhythm classification.

        ===========  =====================================================
        verdict      meaning
        ===========  =====================================================
        steady       1-2 sessions — continuous work with few breaks
        clustered    3-6 sessions — normal work/rest pattern
        scattered    7+ sessions — fragmented, possibly interrupted work
        ===========  =====================================================
        """
        n = self.session_count
        if n <= 2:
            return "steady"
        if n <= 6:
            return "clustered"
        return "scattered"

    @property
    def health_score(self) -> float:
        """Numeric health score in [0, 1].

        Combines rhythm appropriateness, session regularity, and
        burst fraction into a single metric.
        """
        if not self.sessions:
            return 0.0

        # rhythm score: clustered is ideal (1.0), steady is good (0.8),
        # scattered is concerning (0.4)
        rhythm_map = {"steady": 0.8, "clustered": 1.0, "scattered": 0.4}
        r_score = rhythm_map.get(self.rhythm, 0.5)

        # regularity: CV of session lengths — lower is better
        lengths = [s.commit_count for s in self.sessions]
        if len(lengths) >= 2:
            m = statistics.mean(lengths)
            s = statistics.stdev(lengths)
            cv = s / m if m > 0 else 1.0
            reg_score = max(0.0, 1.0 - cv)
        else:
            reg_score = 1.0

        # burst bonus: some bursts are fine, all bursts is concerning
        if self.session_count > 0:
            burst_ratio = self.burst_count / self.session_count
            burst_score = 1.0 - abs(burst_ratio - 0.3)  # ideal ~30% bursts
        else:
            burst_score = 0.5

        return max(0.0, min(1.0, (r_score * 0.4 + reg_score * 0.35 + burst_score * 0.25)))


# ---------------------------------------------------------------------------
# core functions
# ---------------------------------------------------------------------------

def _parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def detect_sessions(
    timestamps: Sequence[str],
    session_gap: float = DEFAULT_SESSION_GAP,
    min_session_size: int = DEFAULT_MIN_SESSION_SIZE,
) -> SessionProfile:
    """Detect work sessions from a sequence of commit timestamps.

    Parameters
    ----------
    timestamps : sequence of str
        ISO-8601 timestamps of commits, in chronological order.
    session_gap : float
        Seconds of inactivity that mark a new session (default 1200s).
    min_session_size : int
        Minimum commits for a group to qualify as a session (default 2).

    Returns
    -------
    SessionProfile
        Aggregate analysis with per-session details.
    """
    if len(timestamps) < 2:
        return SessionProfile(total_commits=len(timestamps))

    parsed = sorted(_parse_ts(ts) for ts in timestamps)
    total = len(parsed)

    # compute gaps and split into groups at boundaries
    groups: List[List[datetime]] = [[parsed[0]]]
    for i in range(1, len(parsed)):
        gap = (parsed[i] - parsed[i - 1]).total_seconds()
        if gap >= session_gap:
            groups.append([])
        groups[-1].append(parsed[i])

    # build sessions from groups meeting minimum size
    profile = SessionProfile(total_commits=total)
    session_idx = 0
    for group in groups:
        if len(group) < min_session_size:
            continue
        first = group[0]
        last = group[-1]
        duration = (last - first).total_seconds()
        internal_gaps = [
            (group[j + 1] - group[j]).total_seconds()
            for j in range(len(group) - 1)
        ]
        session = Session(
            index=session_idx,
            start_time=first.isoformat(),
            end_time=last.isoformat(),
            commit_count=len(group),
            duration_seconds=duration,
            internal_gaps=internal_gaps,
        )
        profile.sessions.append(session)
        session_idx += 1

    return profile


def session_summary_text(profile: SessionProfile) -> str:
    """Produce a human-readable one-liner for caretaker status output."""
    n = profile.session_count
    rhythm = profile.rhythm
    health = profile.health_score
    parts = [
        f"sessions: {n} ({rhythm}, health {health:.2f})",
        f"avg {profile.mean_session_length:.1f} commits/session",
    ]
    if profile.burst_count > 0:
        parts.append(f"{profile.burst_count} burst sessions")
    return ", ".join(parts)


def inter_session_gaps(profile: SessionProfile) -> List[float]:
    """Compute gaps in seconds between consecutive sessions.

    Returns
    -------
    list of float
        Seconds between the end of one session and the start of the next.
    """
    if len(profile.sessions) < 2:
        return []

    gaps = []
    for i in range(1, len(profile.sessions)):
        prev_end = _parse_ts(profile.sessions[i - 1].end_time)
        curr_start = _parse_ts(profile.sessions[i].start_time)
        gaps.append((curr_start - prev_end).total_seconds())
    return gaps
