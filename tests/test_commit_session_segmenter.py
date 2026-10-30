"""Tests for iamai.commit_session_segmenter — session segmentation.

Covers: segment_sessions, SessionReport properties, SessionSummary
properties, session_timeline_text, edge cases, boundary conditions.
"""

import math
import pytest
from datetime import datetime, timedelta, timezone

from iamai.commit_session_segmenter import (
    SessionReport,
    SessionSummary,
    segment_sessions,
    session_timeline_text,
    DEFAULT_GAP_THRESHOLD,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_BASE = "2026-10-22T12:00:00+00:00"


def _make_ts(offsets_seconds: list[int], base: str = _BASE) -> list[str]:
    """Generate ISO-8601 timestamps from a base + list of offsets."""
    base_dt = datetime.fromisoformat(base).replace(tzinfo=timezone.utc)
    return [
        (base_dt + timedelta(seconds=s)).isoformat()
        for s in offsets_seconds
    ]


def _steady_offsets(interval: int = 600, count: int = 20) -> list[int]:
    """Offsets for *count* commits at a fixed *interval*."""
    return [i * interval for i in range(count)]


def _two_sessions(
    session1_count: int = 10,
    session1_interval: int = 600,
    gap: int = 7200,
    session2_count: int = 10,
    session2_interval: int = 600,
) -> list[str]:
    """Two sessions separated by a large gap."""
    offsets = _steady_offsets(session1_interval, session1_count)
    base2 = offsets[-1] + gap
    offsets += [base2 + i * session2_interval for i in range(session2_count)]
    return _make_ts(offsets)


# ---------------------------------------------------------------------------
# basic segmentation
# ---------------------------------------------------------------------------

class TestSegmentSessionsBasic:
    """Core segmentation logic."""

    def test_single_session_no_gap(self):
        ts = _make_ts(_steady_offsets(600, 20))
        s = segment_sessions(ts)
        assert s.session_count == 1
        assert s.total_commits == 20

    def test_two_sessions_detected(self):
        ts = _two_sessions(gap=7200)
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.session_count == 2
        assert s.sessions[0].commit_count == 10
        assert s.sessions[1].commit_count == 10

    def test_three_sessions(self):
        offsets = _steady_offsets(600, 5)
        base2 = offsets[-1] + 3600
        offsets += [base2 + i * 600 for i in range(5)]
        base3 = offsets[-1] + 3600
        offsets += [base3 + i * 600 for i in range(5)]
        ts = _make_ts(offsets)
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.session_count == 3

    def test_custom_gap_threshold(self):
        ts = _two_sessions(gap=1200)
        # With threshold 1800, 1200s gap → one session
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.session_count == 1
        # With threshold 600, 1200s gap → two sessions
        s = segment_sessions(ts, gap_threshold=600)
        assert s.session_count == 2

    def test_exact_threshold_is_one_session(self):
        """Gap exactly equal to threshold does NOT start a new session."""
        offsets = [0, 600, 1200, 3000, 3600]
        ts = _make_ts(offsets)
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.session_count == 1


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Boundary and edge-case handling."""

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            segment_sessions([])

    def test_single_commit(self):
        ts = _make_ts([0])
        s = segment_sessions(ts)
        assert s.session_count == 1
        assert s.sessions[0].single_commit is True
        assert s.sessions[0].commit_count == 1
        assert s.sessions[0].duration_seconds == 0.0

    def test_two_commits_no_gap(self):
        ts = _make_ts([0, 600])
        s = segment_sessions(ts)
        assert s.session_count == 1
        assert s.sessions[0].commit_count == 2

    def test_two_commits_large_gap(self):
        ts = _make_ts([0, 7200])
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.session_count == 2
        assert all(sess.single_commit for sess in s.sessions)

    def test_duplicate_timestamps(self):
        ts = _make_ts([0, 0, 0, 600, 600, 7800, 7800])
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.session_count == 2
        assert s.sessions[0].commit_count == 5
        assert s.sessions[1].commit_count == 2

    def test_naive_timestamps_treated_as_utc(self):
        """Timestamps without timezone info are assumed UTC."""
        ts = ["2026-10-22T12:00:00", "2026-10-22T12:10:00"]
        s = segment_sessions(ts)
        assert s.session_count == 1
        assert s.sessions[0].duration_seconds == 600.0


# ---------------------------------------------------------------------------
# SessionReport properties
# ---------------------------------------------------------------------------

class TestSessionReport:
    """Properties and methods of individual SessionReport."""

    def test_duration(self):
        ts = _make_ts(_steady_offsets(600, 10))
        s = segment_sessions(ts)
        sess = s.sessions[0]
        assert sess.duration_seconds == 5400.0  # 9 gaps × 600s

    def test_throughput(self):
        ts = _make_ts(_steady_offsets(600, 10))
        s = segment_sessions(ts)
        sess = s.sessions[0]
        # 10 commits in 5400s = 6.667 commits/hour
        assert abs(sess.throughput - (10 / 5400 * 3600)) < 0.001

    def test_single_commit_throughput_zero(self):
        ts = _make_ts([0])
        s = segment_sessions(ts)
        assert s.sessions[0].throughput == 0.0

    def test_gap_statistics(self):
        offsets = [0, 600, 900, 1800]  # gaps: 600, 300, 900
        ts = _make_ts(offsets)
        s = segment_sessions(ts)
        sess = s.sessions[0]
        assert sess.gaps == [600.0, 300.0, 900.0]
        assert sess.mean_gap == 600.0
        assert sess.median_gap == 600.0
        assert sess.max_gap == 900.0

    def test_single_commit_gaps_empty(self):
        ts = _make_ts([0])
        s = segment_sessions(ts)
        sess = s.sessions[0]
        assert sess.gaps == []
        assert sess.mean_gap == 0.0
        assert sess.median_gap == 0.0
        assert sess.max_gap == 0.0

    def test_session_index(self):
        ts = _two_sessions(gap=7200)
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.sessions[0].index == 0
        assert s.sessions[1].index == 1


# ---------------------------------------------------------------------------
# SessionSummary properties
# ---------------------------------------------------------------------------

class TestSessionSummary:
    """Aggregate properties of SessionSummary."""

    def test_total_commits(self):
        ts = _two_sessions(session1_count=10, session2_count=15, gap=7200)
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.total_commits == 25

    def test_total_active_time(self):
        ts = _two_sessions(session1_count=10, session1_interval=600,
                           session2_count=10, session2_interval=600, gap=7200)
        s = segment_sessions(ts, gap_threshold=1800)
        # Each session: 9 gaps × 600s = 5400s, total = 10800s
        assert s.total_active_time == 10800.0

    def test_total_wall_time(self):
        ts = _two_sessions(session1_count=5, session1_interval=600,
                           session2_count=5, session2_interval=600, gap=7200)
        s = segment_sessions(ts, gap_threshold=1800)
        # First commit at 0, last at (4*600) + 7200 + (4*600) = 12000
        assert s.total_wall_time == 12000.0

    def test_active_ratio(self):
        ts = _two_sessions(session1_count=5, session1_interval=600,
                           session2_count=5, session2_interval=600, gap=7200)
        s = segment_sessions(ts, gap_threshold=1800)
        # active = 2 × 2400 = 4800; wall = 12000; ratio = 0.4
        assert abs(s.active_ratio - 0.4) < 0.001

    def test_active_ratio_single_session(self):
        ts = _make_ts(_steady_offsets(600, 10))
        s = segment_sessions(ts)
        assert s.active_ratio == 1.0

    def test_active_ratio_single_commit(self):
        ts = _make_ts([0])
        s = segment_sessions(ts)
        assert s.active_ratio == 0.0

    def test_longest_session(self):
        ts = _two_sessions(session1_count=5, session2_count=20, gap=7200)
        s = segment_sessions(ts, gap_threshold=1800)
        longest = s.longest_session
        assert longest is not None
        assert longest.commit_count == 20

    def test_shortest_session(self):
        """shortest_session skips single-commit sessions by design."""
        offsets = _steady_offsets(600, 20)   # session 0: 20 commits, 11400s
        base2 = offsets[-1] + 7200
        offsets += [base2 + i * 600 for i in range(5)]  # session 1: 5 commits, 2400s
        base3 = offsets[-1] + 7200
        offsets += [base3]  # session 2: single commit (skipped)
        ts = _make_ts(offsets)
        s = segment_sessions(ts, gap_threshold=1800)
        shortest = s.shortest_session
        assert shortest is not None
        assert shortest.index == 1  # 5-commit session is shortest multi-commit
        assert shortest.commit_count == 5

    def test_longest_empty(self):
        with pytest.raises(ValueError):
            segment_sessions([])

    def test_mean_session_length(self):
        ts = _two_sessions(session1_count=10, session2_count=20, gap=7200)
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.mean_session_length == 15.0

    def test_mean_session_duration(self):
        ts = _two_sessions(session1_count=6, session1_interval=600,
                           session2_count=6, session2_interval=600, gap=7200)
        s = segment_sessions(ts, gap_threshold=1800)
        # Each session: 5 × 600 = 3000s
        assert s.mean_session_duration == 3000.0

    def test_single_commit_sessions_count(self):
        offsets = [0, 7200, 14400]  # three single-commit sessions
        ts = _make_ts(offsets)
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.single_commit_sessions == 3

    def test_break_durations(self):
        offsets = _steady_offsets(600, 5)
        base2 = offsets[-1] + 3600
        offsets += [base2 + i * 600 for i in range(5)]
        base3 = offsets[-1] + 7200
        offsets += [base3 + i * 600 for i in range(5)]
        ts = _make_ts(offsets)
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.session_count == 3
        breaks = s.break_durations
        assert len(breaks) == 2
        assert breaks[0] == 3600.0
        assert breaks[1] == 7200.0

    def test_break_durations_single_session(self):
        ts = _make_ts(_steady_offsets(600, 10))
        s = segment_sessions(ts)
        assert s.break_durations == []

    def test_mean_break_duration(self):
        offsets = _steady_offsets(600, 5)
        base2 = offsets[-1] + 3600
        offsets += [base2 + i * 600 for i in range(5)]
        base3 = offsets[-1] + 7200
        offsets += [base3 + i * 600 for i in range(5)]
        ts = _make_ts(offsets)
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.mean_break_duration == 5400.0  # (3600 + 7200) / 2


# ---------------------------------------------------------------------------
# timeline text
# ---------------------------------------------------------------------------

class TestTimelineText:
    """ASCII timeline rendering."""

    def test_single_session_timeline(self):
        ts = _make_ts(_steady_offsets(600, 10))
        s = segment_sessions(ts)
        text = s.timeline_text
        assert "#0" in text
        assert "10 commits" in text
        assert "break" not in text

    def test_two_session_timeline(self):
        ts = _two_sessions(session1_count=10, session2_count=10, gap=7200)
        s = segment_sessions(ts, gap_threshold=1800)
        text = s.timeline_text
        assert "#0" in text
        assert "#1" in text
        assert "break" in text
        assert "7200s" in text

    def test_empty_sessions_text(self):
        text = session_timeline_text([])
        assert "no sessions" in text

    def test_timeline_proportional_width(self):
        offsets = _steady_offsets(600, 20)  # long session
        base2 = offsets[-1] + 7200
        offsets += [base2 + i * 600 for i in range(3)]  # short session
        ts = _make_ts(offsets)
        s = segment_sessions(ts, gap_threshold=1800)
        text = s.timeline_text
        # First session bar should be wider than second
        lines = text.strip().split("\n")
        bar0 = lines[0].count("=")
        bar1 = lines[2].count("=")
        assert bar0 > bar1


# ---------------------------------------------------------------------------
# realistic scenarios
# ---------------------------------------------------------------------------

class TestRealisticScenarios:
    """End-to-end tests mimicking real commit patterns."""

    def test_writer_with_overnight_stall(self):
        """Simulate a day session, overnight gap, morning recovery."""
        # Day session: 20 commits every 10 min
        offsets = _steady_offsets(600, 20)
        # Overnight gap: 10 hours = 36000s
        night_start = offsets[-1] + 36000
        offsets += [night_start + i * 600 for i in range(15)]
        ts = _make_ts(offsets)

        s = segment_sessions(ts, gap_threshold=1800)
        assert s.session_count == 2
        assert s.sessions[0].commit_count == 20
        assert s.sessions[1].commit_count == 15
        assert s.mean_break_duration == 36000.0
        assert s.active_ratio < 0.5  # most time is overnight gap

    def test_frequent_short_sessions(self):
        """Writer keeps getting reclaimed and restarted."""
        offsets = []
        for i in range(10):
            base = i * 3600  # sessions 1 hour apart
            offsets += [base + j * 600 for j in range(3)]
        ts = _make_ts(offsets)

        s = segment_sessions(ts, gap_threshold=1800)
        assert s.session_count == 10
        assert all(sess.commit_count == 3 for sess in s.sessions)
        assert s.single_commit_sessions == 0

    def test_mixed_single_and_multi(self):
        """Mix of single-commit and multi-commit sessions."""
        offsets = [0, 600, 1200, 8400, 15600, 16200, 16800]
        ts = _make_ts(offsets)
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.session_count == 3
        assert s.sessions[0].commit_count == 3  # 0, 600, 1200
        assert s.sessions[1].single_commit      # 8400
        assert s.sessions[2].commit_count == 3  # 15600, 16200, 16800

    def test_very_frequent_commits(self):
        """Commits every 15 seconds — stroke-level cadence."""
        offsets = [i * 15 for i in range(100)]
        ts = _make_ts(offsets)
        s = segment_sessions(ts)
        assert s.session_count == 1
        assert s.sessions[0].commit_count == 100
        assert abs(s.sessions[0].mean_gap - 15.0) < 0.001

    def test_jittery_cadence_stays_one_session(self):
        """Irregular but never exceeding threshold."""
        import random
        random.seed(42)
        offsets = [0]
        for _ in range(49):
            offsets.append(offsets[-1] + random.randint(300, 1500))
        ts = _make_ts(offsets)
        s = segment_sessions(ts, gap_threshold=1800)
        assert s.session_count == 1

    def test_summary_gap_threshold_preserved(self):
        ts = _make_ts(_steady_offsets(600, 10))
        s = segment_sessions(ts, gap_threshold=900)
        assert s.gap_threshold == 900


# ---------------------------------------------------------------------------
# default constant
# ---------------------------------------------------------------------------

class TestDefaults:
    """Verify default constant values."""

    def test_default_gap_threshold(self):
        assert DEFAULT_GAP_THRESHOLD == 1800

    def test_default_used_when_not_specified(self):
        ts = _two_sessions(gap=2000)
        s = segment_sessions(ts)  # uses default 1800
        assert s.session_count == 2
