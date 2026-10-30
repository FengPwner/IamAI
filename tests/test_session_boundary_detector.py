"""Tests for iamai.session_boundary_detector — work session detection.

Covers: detect_sessions, Session properties, SessionProfile aggregates,
session_summary_text, inter_session_gaps, and edge cases.
"""

import pytest

from iamai.session_boundary_detector import (
    Session,
    SessionProfile,
    detect_sessions,
    inter_session_gaps,
    session_summary_text,
    DEFAULT_SESSION_GAP,
    DEFAULT_BATCH_INTERVAL,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_ts(base: str, offsets_seconds: list) -> list:
    """Generate ISO-8601 timestamps from a base + offsets."""
    from datetime import datetime, timedelta, timezone
    base_dt = datetime.fromisoformat(base).replace(tzinfo=timezone.utc)
    return [
        (base_dt + timedelta(seconds=s)).isoformat()
        for s in offsets_seconds
    ]


# ===========================================================================
# detect_sessions — basic detection
# ===========================================================================

class TestDetectSessions:
    """Tests for the detect_sessions function."""

    def test_empty_input(self):
        profile = detect_sessions([])
        assert profile.session_count == 0
        assert profile.total_commits == 0

    def test_single_timestamp(self):
        profile = detect_sessions(["2026-10-24T10:00:00+00:00"])
        assert profile.session_count == 0
        assert profile.total_commits == 1

    def test_two_close_timestamps_one_session(self):
        ts = _make_ts("2026-10-24T10:00:00", [0, 600])
        profile = detect_sessions(ts)
        assert profile.session_count == 1
        assert profile.sessions[0].commit_count == 2

    def test_two_far_timestamps_two_sessions(self):
        # 2000s gap > 1200s threshold → two sessions
        ts = _make_ts("2026-10-24T10:00:00", [0, 600, 2600, 3200])
        profile = detect_sessions(ts)
        assert profile.session_count == 2

    def test_clear_session_boundary(self):
        # session 1: commits at 0, 600, 1200
        # gap of 1800s (> 1200 threshold)
        # session 2: commits at 3000, 3600
        ts = _make_ts("2026-10-24T10:00:00", [0, 600, 1200, 3000, 3600])
        profile = detect_sessions(ts)
        assert profile.session_count == 2
        assert profile.sessions[0].commit_count == 3
        assert profile.sessions[1].commit_count == 2

    def test_multiple_sessions(self):
        offsets = [
            0, 600, 1200,       # session 1: 3 commits
            3000, 3600,          # session 2: 2 commits
            6000, 6600, 7200, 7800,  # session 3: 4 commits
        ]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert profile.session_count == 3

    def test_min_session_size_filter(self):
        # One commit isolated, then a pair
        offsets = [0, 2000, 2600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts, min_session_size=2)
        # First group has 1 commit (below min), second has 2
        assert profile.session_count == 1
        assert profile.sessions[0].commit_count == 2

    def test_custom_session_gap(self):
        offsets = [0, 300, 900, 1200]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        # With default 1200s gap: one session (max internal gap 600s)
        profile_default = detect_sessions(ts)
        assert profile_default.session_count == 1
        # With 500s gap: splits at the 600s internal gaps
        profile_custom = detect_sessions(ts, session_gap=500.0)
        assert profile_custom.session_count >= 2

    def test_sorted_even_if_input_unsorted(self):
        offsets = [1200, 0, 600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert profile.session_count == 1
        assert profile.sessions[0].commit_count == 3


# ===========================================================================
# Session properties
# ===========================================================================

class TestSessionProperties:
    """Tests for Session dataclass properties."""

    def test_mean_gap_empty(self):
        s = Session(index=0, start_time="", end_time="", internal_gaps=[])
        assert s.mean_gap == 0.0

    def test_mean_gap_with_values(self):
        s = Session(index=0, start_time="", end_time="",
                    internal_gaps=[100.0, 200.0, 300.0])
        assert s.mean_gap == 200.0

    def test_is_burst_true(self):
        s = Session(index=0, start_time="", end_time="",
                    internal_gaps=[100.0, 200.0, 150.0])
        assert s.is_burst is True

    def test_is_burst_false(self):
        s = Session(index=0, start_time="", end_time="",
                    internal_gaps=[600.0, 700.0, 650.0])
        assert s.is_burst is False

    def test_is_burst_empty_gaps(self):
        s = Session(index=0, start_time="", end_time="", internal_gaps=[])
        assert s.is_burst is False

    def test_cadence_health_tight(self):
        # Very low variance gaps
        s = Session(index=0, start_time="", end_time="",
                    internal_gaps=[600.0, 605.0, 598.0, 602.0])
        assert s.cadence_health == "tight"

    def test_cadence_health_loose(self):
        # Moderate variance
        s = Session(index=0, start_time="", end_time="",
                    internal_gaps=[400.0, 600.0, 800.0, 500.0])
        assert s.cadence_health == "loose"

    def test_cadence_health_ragged(self):
        # High variance
        s = Session(index=0, start_time="", end_time="",
                    internal_gaps=[100.0, 900.0, 50.0, 1500.0])
        assert s.cadence_health == "ragged"

    def test_cadence_health_unknown_insufficient(self):
        s = Session(index=0, start_time="", end_time="",
                    internal_gaps=[600.0])
        assert s.cadence_health == "unknown"


# ===========================================================================
# SessionProfile properties
# ===========================================================================

class TestSessionProfileProperties:
    """Tests for SessionProfile aggregate properties."""

    def test_empty_profile(self):
        p = SessionProfile()
        assert p.session_count == 0
        assert p.mean_session_length == 0.0
        assert p.longest_session == 0
        assert p.shortest_session == 0
        assert p.burst_count == 0
        assert p.total_active_time == 0.0

    def test_session_count(self):
        offsets = [0, 600, 2000, 2600, 4000, 4600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert profile.session_count == 3

    def test_mean_session_length(self):
        offsets = [0, 600, 1200, 3000, 3600, 6000, 6600, 7200]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        # 3 sessions: 3, 2, 3 commits → mean = 8/3 ≈ 2.67
        assert abs(profile.mean_session_length - 8 / 3) < 0.01

    def test_longest_session(self):
        offsets = [0, 600, 2000, 2600, 3200, 3800, 5000, 5600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        # session 1: 2, session 2: 4, session 3: 2
        assert profile.longest_session == 4

    def test_shortest_session(self):
        offsets = [0, 600, 2000, 2600, 3200, 3800, 5000, 5600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert profile.shortest_session == 2

    def test_burst_count(self):
        # session 1: burst (100s gaps), session 2: normal (600s gaps)
        offsets = [0, 100, 200, 2000, 2600, 3200]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert profile.burst_count == 1

    def test_mean_session_duration(self):
        offsets = [0, 600, 2000, 2600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        # session 1: duration 600s, session 2: duration 600s
        assert profile.mean_session_duration == 600.0

    def test_total_active_time(self):
        offsets = [0, 600, 2000, 2600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert profile.total_active_time == 1200.0


# ===========================================================================
# rhythm classification
# ===========================================================================

class TestRhythm:
    """Tests for SessionProfile.rhythm property."""

    def test_steady_one_session(self):
        offsets = [0, 600, 1200, 1800]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert profile.rhythm == "steady"

    def test_clustered_three_sessions(self):
        offsets = [0, 600, 2000, 2600, 4000, 4600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert profile.rhythm == "clustered"

    def test_scattered_many_sessions(self):
        offsets = [
            0, 600, 2000, 2600, 4000, 4600,
            6000, 6600, 8000, 8600, 10000, 10600,
            12000, 12600,
        ]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert profile.rhythm == "scattered"


# ===========================================================================
# health_score
# ===========================================================================

class TestHealthScore:
    """Tests for SessionProfile.health_score property."""

    def test_empty_profile_zero(self):
        p = SessionProfile()
        assert p.health_score == 0.0

    def test_clustered_profile_high_score(self):
        # 3 evenly-spaced sessions of equal size — ideal clustered
        offsets = [0, 600, 1200, 3000, 3600, 4200, 6000, 6600, 7200]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert profile.health_score > 0.5

    def test_score_bounded(self):
        offsets = [0, 600, 2000, 2600, 4000, 4600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert 0.0 <= profile.health_score <= 1.0

    def test_scattered_low_score(self):
        # Many tiny sessions with varied sizes
        offsets = []
        t = 0
        for size in [2, 4, 2, 3, 2, 5, 2]:
            for _ in range(size):
                offsets.append(t)
                t += 100  # burst-like within session
            t += 2000  # gap between sessions
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert profile.rhythm == "scattered"
        assert profile.health_score < 0.6


# ===========================================================================
# inter_session_gaps
# ===========================================================================

class TestInterSessionGaps:
    """Tests for the inter_session_gaps function."""

    def test_empty_profile(self):
        gaps = inter_session_gaps(SessionProfile())
        assert gaps == []

    def test_single_session(self):
        offsets = [0, 600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        gaps = inter_session_gaps(profile)
        assert gaps == []

    def test_two_sessions(self):
        offsets = [0, 600, 2000, 2600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        gaps = inter_session_gaps(profile)
        assert len(gaps) == 1
        # session 1 ends at 600s, session 2 starts at 2000s → gap = 1400s
        assert gaps[0] == 1400.0

    def test_three_sessions(self):
        offsets = [0, 600, 2000, 2600, 5000, 5600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        gaps = inter_session_gaps(profile)
        assert len(gaps) == 2
        assert gaps[0] == 1400.0  # 2000 - 600
        assert gaps[1] == 2400.0  # 5000 - 2600


# ===========================================================================
# session_summary_text
# ===========================================================================

class TestSessionSummaryText:
    """Tests for the session_summary_text function."""

    def test_empty_profile(self):
        text = session_summary_text(SessionProfile())
        assert "sessions: 0" in text

    def test_with_bursts(self):
        offsets = [0, 100, 2000, 2100, 4000, 4100]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        text = session_summary_text(profile)
        assert "burst" in text

    def test_contains_rhythm(self):
        offsets = [0, 600, 2000, 2600, 4000, 4600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        text = session_summary_text(profile)
        assert profile.rhythm in text


# ===========================================================================
# edge cases
# ===========================================================================

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_all_same_timestamp(self):
        ts = ["2026-10-24T10:00:00+00:00"] * 5
        profile = detect_sessions(ts)
        assert profile.session_count == 1
        assert profile.sessions[0].commit_count == 5
        assert profile.sessions[0].duration_seconds == 0.0

    def test_exactly_at_threshold(self):
        # gap exactly at 1200s threshold → splits (>= threshold)
        # need two commits on each side for min_session_size
        offsets = [0, 600, 1800, 2400]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        # 600s gap, then 1200s gap (>= 1200 → boundary), then 600s gap
        assert profile.session_count == 2

    def test_just_below_threshold(self):
        offsets = [0, 600, 1799]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert profile.session_count == 1

    def test_z_suffix_timestamps(self):
        ts = ["2026-10-24T10:00:00Z", "2026-10-24T10:10:00Z"]
        profile = detect_sessions(ts)
        assert profile.session_count == 1

    def test_no_timezone_timestamps(self):
        ts = ["2026-10-24T10:00:00", "2026-10-24T10:10:00"]
        profile = detect_sessions(ts)
        assert profile.session_count == 1

    def test_large_dataset(self):
        # 1000 commits at 600s intervals — should be one steady session
        offsets = list(range(0, 600_000, 600))
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts)
        assert profile.session_count == 1
        assert profile.sessions[0].commit_count == 1000

    def test_total_commits_includes_orphans(self):
        # orphan commit between sessions still counted in total
        offsets = [0, 600, 1500, 3000, 3600]
        ts = _make_ts("2026-10-24T10:00:00", offsets)
        profile = detect_sessions(ts, min_session_size=2)
        # 5 total commits even if some are orphaned
        assert profile.total_commits == 5
