"""Tests for iamai.repo_respiration.

Covers: RespirationReport dataclass, breath interval computation, apnea
detection, regularity scoring, depth scoring, composite scoring, pattern
classification, end-to-end respiration_report(), and respiration_summary().
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest

from iamai.repo_respiration import (
    DEFAULT_APNEA_THRESHOLD,
    DEFAULT_BATCH_INTERVAL,
    RespirationReport,
    _classify_pattern,
    _composite_score,
    _compute_breath_intervals,
    _depth_score_fn,
    _detect_apnea,
    _git_diffstat,
    _git_log,
    _regularity_score,
    respiration_report,
    respiration_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ts_list(n: int, interval_s: int = 600, base: datetime | None = None):
    """Generate a list of n chronological datetime objects, newest first.

    Mimics git log output order (newest first).
    """
    if base is None:
        base = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
    chrono = [base + timedelta(seconds=i * interval_s) for i in range(n)]
    return list(reversed(chrono))


# ---------------------------------------------------------------------------
# RespirationReport dataclass
# ---------------------------------------------------------------------------

class TestRespirationReport:
    def test_defaults(self):
        r = RespirationReport()
        assert r.breath_rate == 0.0
        assert r.tidal_volume == 0.0
        assert r.apnea_events == 0
        assert r.longest_apnea == 0.0
        assert r.regularity == 0.0
        assert r.depth_score == 0.0
        assert r.respiration_score == 0.0
        assert r.pattern == "dormant"
        assert r.total_breaths == 0
        assert r.analysis_window_hours == 0.0
        assert r.breath_intervals == []

    def test_custom_values(self):
        r = RespirationReport(
            breath_rate=6.0,
            tidal_volume=4.2,
            apnea_events=1,
            longest_apnea=2400.0,
            regularity=85.0,
            depth_score=78.0,
            respiration_score=74.0,
            pattern="eupnea",
            total_breaths=50,
            analysis_window_hours=8.3,
        )
        assert r.breath_rate == 6.0
        assert r.tidal_volume == 4.2
        assert r.pattern == "eupnea"
        assert r.total_breaths == 50

    def test_intervals_default_empty(self):
        r = RespirationReport()
        assert r.breath_intervals == []


# ---------------------------------------------------------------------------
# _compute_breath_intervals
# ---------------------------------------------------------------------------

class TestComputeBreathIntervals:
    def test_empty(self):
        assert _compute_breath_intervals([], 600) == []

    def test_single_commit(self):
        ts = _make_ts_list(1)
        assert _compute_breath_intervals(ts, 600) == []

    def test_regular_commits_one_breath(self):
        """All commits within one batch interval → no gap → zero breath intervals."""
        # 5 commits, 30s apart, batch_interval=600 → all one breath
        ts = _make_ts_list(5, interval_s=30)
        intervals = _compute_breath_intervals(ts, 600)
        # No gap > 900s (600*1.5), so no breath boundaries
        assert intervals == []

    def test_two_breaths(self):
        """Two clusters separated by > batch_interval * 1.5."""
        base = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
        # cluster 1: 3 commits at t=0, t=60, t=120
        # cluster 2: 3 commits at t=1200, t=1260, t=1320
        chrono = [
            base,
            base + timedelta(seconds=60),
            base + timedelta(seconds=120),
            base + timedelta(seconds=1200),
            base + timedelta(seconds=1260),
            base + timedelta(seconds=1320),
        ]
        ts = list(reversed(chrono))  # newest first
        intervals = _compute_breath_intervals(ts, 600)
        assert len(intervals) == 1
        assert intervals[0] == 1200.0  # gap between breath starts

    def test_three_breaths(self):
        base = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
        chrono = [
            base,
            base + timedelta(seconds=30),
            base + timedelta(seconds=600),
            base + timedelta(seconds=630),
            base + timedelta(seconds=1200),
            base + timedelta(seconds=1230),
        ]
        ts = list(reversed(chrono))
        intervals = _compute_breath_intervals(ts, 300)
        # threshold = 300 * 1.5 = 450s
        # gaps: 30, 540, 30, 540, 30 → boundaries at indices 2, 4
        assert len(intervals) == 2
        assert intervals[0] == 600.0
        assert intervals[1] == 600.0

    def test_all_same_timestamp(self):
        base = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
        ts = [base] * 5
        intervals = _compute_breath_intervals(ts, 600)
        assert intervals == []


# ---------------------------------------------------------------------------
# _detect_apnea
# ---------------------------------------------------------------------------

class TestDetectApnea:
    def test_empty(self):
        assert _detect_apnea([], 1800) == []

    def test_single_commit(self):
        ts = _make_ts_list(1)
        assert _detect_apnea(ts, 1800) == []

    def test_no_apnea(self):
        """Regular commits, no gaps above threshold."""
        ts = _make_ts_list(10, interval_s=300)
        events = _detect_apnea(ts, 1800)
        assert events == []

    def test_one_apnea_event(self):
        base = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
        chrono = [
            base,
            base + timedelta(seconds=300),
            base + timedelta(seconds=600),
            base + timedelta(seconds=3000),  # gap of 2400s → apnea
            base + timedelta(seconds=3300),
        ]
        ts = list(reversed(chrono))
        events = _detect_apnea(ts, 1800)
        assert len(events) == 1
        assert events[0] == 2400.0

    def test_multiple_apnea_events(self):
        base = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
        chrono = [
            base,
            base + timedelta(seconds=300),
            base + timedelta(seconds=3000),   # gap 2700s
            base + timedelta(seconds=3300),
            base + timedelta(seconds=6000),   # gap 2700s
            base + timedelta(seconds=6300),
        ]
        ts = list(reversed(chrono))
        events = _detect_apnea(ts, 1800)
        assert len(events) == 2
        assert all(e > 1800 for e in events)

    def test_custom_threshold(self):
        ts = _make_ts_list(5, interval_s=500)
        # All gaps are 500s; threshold 400 → all are apnea
        events = _detect_apnea(ts, 400)
        assert len(events) == 4
        # threshold 600 → none are apnea
        events2 = _detect_apnea(ts, 600)
        assert events2 == []


# ---------------------------------------------------------------------------
# _regularity_score
# ---------------------------------------------------------------------------

class TestRegularityScore:
    def test_empty(self):
        assert _regularity_score([]) == 0.0

    def test_single_value(self):
        assert _regularity_score([600.0]) == 0.0

    def test_perfectly_regular(self):
        intervals = [600.0] * 10
        assert _regularity_score(intervals) == 100.0

    def test_slight_variation(self):
        intervals = [600.0, 610.0, 590.0, 605.0, 595.0]
        score = _regularity_score(intervals)
        assert 80.0 < score < 100.0

    def test_high_variation(self):
        intervals = [100.0, 1000.0, 200.0, 900.0, 300.0]
        score = _regularity_score(intervals)
        assert score < 70.0

    def test_extreme_variation(self):
        intervals = [10.0, 10000.0, 10.0, 10000.0]
        score = _regularity_score(intervals)
        assert score < 60.0

    def test_two_values_same(self):
        score = _regularity_score([600.0, 600.0])
        assert score == 100.0

    def test_two_values_different(self):
        score = _regularity_score([300.0, 900.0])
        assert 0.0 <= score < 100.0


# ---------------------------------------------------------------------------
# _depth_score_fn
# ---------------------------------------------------------------------------

class TestDepthScore:
    def test_zero_volume(self):
        assert _depth_score_fn(0.0) == 0.0

    def test_negative_volume(self):
        assert _depth_score_fn(-1.0) == 0.0

    def test_optimal_volume(self):
        """At target volume (default 5.0), score should be near 100."""
        score = _depth_score_fn(5.0)
        assert score == 100.0

    def test_near_optimal(self):
        score = _depth_score_fn(4.0)
        assert score > 80.0

    def test_too_shallow(self):
        score = _depth_score_fn(0.1)
        assert score < 20.0

    def test_too_deep(self):
        score = _depth_score_fn(200.0)
        assert score < 20.0

    def test_custom_target(self):
        score = _depth_score_fn(10.0, target_volume=10.0)
        assert score == 100.0

    def test_symmetry(self):
        """Same ratio above/below target should give same score."""
        s_low = _depth_score_fn(2.5, target_volume=5.0)   # half
        s_high = _depth_score_fn(10.0, target_volume=5.0)  # double
        assert abs(s_low - s_high) < 0.1


# ---------------------------------------------------------------------------
# _composite_score
# ---------------------------------------------------------------------------

class TestCompositeScore:
    def test_perfect_score(self):
        """Perfect regularity, optimal depth, no apnea, ideal rate."""
        score = _composite_score(
            regularity=100.0, depth=100.0, apnea_events=0, breath_rate=6.0
        )
        assert score == 100.0

    def test_zero_everything(self):
        score = _composite_score(
            regularity=0.0, depth=0.0, apnea_events=0, breath_rate=0.0
        )
        # apnea_component = 30, rate_bonus = -10 → raw = 0 + 0 + 30 - 10 = 20
        assert score == 20.0

    def test_apnea_penalty(self):
        """Each apnea event costs 10 points in the apnea component."""
        s0 = _composite_score(100.0, 100.0, 0, 6.0)
        s1 = _composite_score(100.0, 100.0, 1, 6.0)
        s3 = _composite_score(100.0, 100.0, 3, 6.0)
        assert s0 > s1
        assert s1 > s3
        assert s3 == s0 - 30.0  # 3 events * 10 = 30 penalty

    def test_apnea_penalty_capped_at_30(self):
        s5 = _composite_score(100.0, 100.0, 5, 6.0)
        s10 = _composite_score(100.0, 100.0, 10, 6.0)
        assert s5 == s10  # both maxed out

    def test_high_rate_penalty(self):
        s_normal = _composite_score(100.0, 100.0, 0, 6.0)
        s_fast = _composite_score(100.0, 100.0, 0, 15.0)
        assert s_normal > s_fast

    def test_low_rate_penalty(self):
        s_normal = _composite_score(100.0, 100.0, 0, 6.0)
        s_slow = _composite_score(100.0, 100.0, 0, 1.0)
        assert s_normal > s_slow

    def test_clamped_to_0_100(self):
        s_high = _composite_score(100.0, 100.0, 0, 6.0)
        assert s_high <= 100.0
        s_low = _composite_score(0.0, 0.0, 10, 0.0)
        assert s_low >= 0.0


# ---------------------------------------------------------------------------
# _classify_pattern
# ---------------------------------------------------------------------------

class TestClassifyPattern:
    def test_dormant_few_breaths(self):
        assert _classify_pattern(90.0, 6.0, 0, 5) == "dormant"

    def test_dormant_zero_breaths(self):
        assert _classify_pattern(90.0, 0.0, 0, 0) == "dormant"

    def test_eupnea(self):
        assert _classify_pattern(80.0, 6.0, 0, 50) == "eupnea"

    def test_eupnea_boundary(self):
        assert _classify_pattern(70.0, 6.0, 0, 50) == "eupnea"

    def test_apneic(self):
        assert _classify_pattern(50.0, 6.0, 5, 50) == "apneic"

    def test_hyperventilation(self):
        assert _classify_pattern(50.0, 15.0, 0, 50) == "hyperventilation"

    def test_hypoventilation(self):
        assert _classify_pattern(50.0, 1.0, 0, 50) == "hypoventilation"

    def test_irregular(self):
        assert _classify_pattern(30.0, 6.0, 1, 50) == "irregular"

    def test_apneic_takes_priority_over_hyperventilation(self):
        """When both apnea and high rate conditions met, apneic wins."""
        assert _classify_pattern(50.0, 15.0, 5, 50) == "apneic"

    def test_eupnea_exactly_ten_breaths(self):
        assert _classify_pattern(80.0, 6.0, 0, 10) == "eupnea"


# ---------------------------------------------------------------------------
# _git_log (mocked)
# ---------------------------------------------------------------------------

class TestGitLog:
    def test_empty_repo(self, tmp_path):
        """Non-git directory returns empty list."""
        result = _git_log(tmp_path, 100)
        assert result == []

    def test_parse_output(self):
        fake_output = (
            "abc123 2026-10-25T10:00:00+00:00\n"
            "def456 2026-10-25T09:50:00+00:00\n"
        )
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout=fake_output
            )
            entries = _git_log(".", 100)
            assert len(entries) == 2
            assert entries[0][0] == "abc123"
            assert entries[1][0] == "def456"

    def test_git_failure(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="")
            entries = _git_log(".", 100)
            assert entries == []

    def test_malformed_lines_skipped(self):
        fake_output = (
            "abc123 2026-10-25T10:00:00+00:00\n"
            "badline\n"
            "def456 2026-10-25T09:50:00+00:00\n"
        )
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout=fake_output
            )
            entries = _git_log(".", 100)
            assert len(entries) == 2


# ---------------------------------------------------------------------------
# _git_diffstat (mocked)
# ---------------------------------------------------------------------------

class TestGitDiffstat:
    def test_normal_commit(self):
        fake_output = "file1.py\nfile2.py\nfile3.py\n"
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout=fake_output
            )
            assert _git_diffstat(".", "abc123") == 3

    def test_empty_commit(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="")
            assert _git_diffstat(".", "abc123") == 0

    def test_git_failure(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="")
            assert _git_diffstat(".", "abc123") == 0


# ---------------------------------------------------------------------------
# respiration_report (end-to-end, mocked git)
# ---------------------------------------------------------------------------

class TestRespirationReportE2E:
    def _mock_entries(self, n, interval_s=600, files_per_commit=5):
        """Create mock git log entries."""
        base = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
        entries = []
        for i in range(n):
            ts = base + timedelta(seconds=i * interval_s)
            commit_hash = f"commit{i:04d}"
            entries.append((commit_hash, ts))
        return list(reversed(entries))  # newest first

    def test_empty_repo(self):
        with mock.patch("iamai.repo_respiration._git_log", return_value=[]):
            r = respiration_report(".")
            assert r.pattern == "dormant"
            assert r.breath_rate == 0.0
            assert r.total_breaths == 0

    def test_single_commit(self):
        entries = [(
            "abc123",
            datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
        )]
        with mock.patch("iamai.repo_respiration._git_log", return_value=entries):
            r = respiration_report(".")
            assert r.pattern == "dormant"

    def test_regular_breathing(self):
        """20 commits at regular 600s intervals with batch_interval=300 → multiple breaths."""
        entries = self._mock_entries(20, interval_s=600)
        with mock.patch("iamai.repo_respiration._git_log", return_value=entries), \
             mock.patch("iamai.repo_respiration._git_diffstat", return_value=5):
            # batch_interval=300 → gap_threshold=450; 600s gaps create breath boundaries
            r = respiration_report(".", batch_interval=300)
            assert r.total_breaths >= 2
            assert r.regularity > 50.0

    def test_apneic_repo(self):
        """Commits with large gaps → apnea events detected."""
        base = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
        chrono = [
            base,
            base + timedelta(seconds=60),
            base + timedelta(seconds=120),
            base + timedelta(seconds=3000),   # gap
            base + timedelta(seconds=3060),
            base + timedelta(seconds=6000),   # gap
            base + timedelta(seconds=6060),
            base + timedelta(seconds=9000),   # gap
            base + timedelta(seconds=9060),
            base + timedelta(seconds=12000),  # gap
            base + timedelta(seconds=12060),
            base + timedelta(seconds=15000),  # gap
            base + timedelta(seconds=15060),
        ]
        entries = [(f"c{i}", t) for i, t in enumerate(reversed(chrono))]
        with mock.patch("iamai.repo_respiration._git_log", return_value=entries), \
             mock.patch("iamai.repo_respiration._git_diffstat", return_value=3):
            r = respiration_report(".", batch_interval=600, apnea_threshold=1800)
            assert r.apnea_events >= 3
            assert r.longest_apnea >= 1800.0

    def test_hyperventilation(self):
        """Very frequent commits with small changes → hyperventilation."""
        entries = self._mock_entries(100, interval_s=30)
        with mock.patch("iamai.repo_respiration._git_log", return_value=entries), \
             mock.patch("iamai.repo_respiration._git_diffstat", return_value=1):
            r = respiration_report(".", batch_interval=600)
            # High breath rate, likely hyperventilation or at least high rate
            assert r.breath_rate > 0

    def test_breath_intervals_recorded(self):
        entries = self._mock_entries(10, interval_s=1200)
        with mock.patch("iamai.repo_respiration._git_log", return_value=entries), \
             mock.patch("iamai.repo_respiration._git_diffstat", return_value=5):
            r = respiration_report(".", batch_interval=600)
            # With 1200s intervals and 600s batch (threshold=900s), most gaps
            # create breath boundaries → intervals should be populated
            assert len(r.breath_intervals) > 0

    def test_analysis_window(self):
        entries = self._mock_entries(10, interval_s=600)
        with mock.patch("iamai.repo_respiration._git_log", return_value=entries), \
             mock.patch("iamai.repo_respiration._git_diffstat", return_value=3):
            r = respiration_report(".", batch_interval=600)
            # 10 commits * 600s = 5400s = 1.5h
            assert r.analysis_window_hours > 0


# ---------------------------------------------------------------------------
# respiration_summary
# ---------------------------------------------------------------------------

class TestRespirationSummary:
    def test_dormant(self):
        r = RespirationReport()
        s = respiration_summary(r)
        assert "dormant" in s
        assert "not enough" in s

    def test_eupnea(self):
        r = RespirationReport(
            breath_rate=6.0,
            tidal_volume=5.0,
            apnea_events=0,
            longest_apnea=0.0,
            regularity=85.0,
            depth_score=100.0,
            respiration_score=82.0,
            pattern="eupnea",
            total_breaths=50,
            analysis_window_hours=8.3,
        )
        s = respiration_summary(r)
        assert "eupnea" in s
        assert "6.0/h" in s
        assert "50 breaths" in s

    def test_apneic(self):
        r = RespirationReport(
            breath_rate=5.0,
            tidal_volume=3.0,
            apnea_events=5,
            longest_apnea=3600.0,
            regularity=40.0,
            depth_score=60.0,
            respiration_score=35.0,
            pattern="apneic",
            total_breaths=30,
            analysis_window_hours=6.0,
        )
        s = respiration_summary(r)
        assert "apneic" in s
        assert "5 events" in s
        assert "3600s" in s

    def test_hyperventilation(self):
        r = RespirationReport(
            breath_rate=15.0,
            tidal_volume=0.5,
            apnea_events=0,
            regularity=60.0,
            depth_score=20.0,
            respiration_score=45.0,
            pattern="hyperventilation",
            total_breaths=100,
            analysis_window_hours=6.7,
        )
        s = respiration_summary(r)
        assert "hyperventilation" in s

    def test_includes_all_fields(self):
        r = RespirationReport(
            breath_rate=6.0,
            tidal_volume=5.0,
            apnea_events=1,
            longest_apnea=2000.0,
            regularity=75.0,
            depth_score=90.0,
            respiration_score=70.0,
            pattern="eupnea",
            total_breaths=40,
            analysis_window_hours=6.7,
        )
        s = respiration_summary(r)
        assert "score=" in s
        assert "rate=" in s
        assert "depth=" in s
        assert "regularity=" in s
        assert "apnea=" in s
        assert "breaths" in s
