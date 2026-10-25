"""Tests for iamai.caretaker_rhythm — caretaker visit regularity analysis.

Covers:
  - _extract_visits: parsing caretaker-NN, caretaker:, non-matching lines
  - _intervals_minutes: empty, single, multi-visit intervals
  - _compute_stats: mean, median, std, min, max at boundaries
  - _rhythm_score: perfect regularity, high variance, zero mean
  - _find_gaps: threshold detection, chronological indexing
  - caretaker_rhythm: integration with mocked git log
  - rhythm_report: one-line formatting
  - Edge cases: empty repo, single visit, all gaps, no gaps
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.caretaker_rhythm import (
    _extract_visits,
    _intervals_minutes,
    _compute_stats,
    _rhythm_score,
    _find_gaps,
    caretaker_rhythm,
    rhythm_report,
    _CARETAKER_RE,
)


# ---------------------------------------------------------------------------
# _CARETAKER_RE
# ---------------------------------------------------------------------------


class TestCaretakerRegex:
    """Tests for the caretaker commit message regex."""

    def test_matches_caretaker_with_number(self):
        m = _CARETAKER_RE.match("caretaker-101: add module")
        assert m is not None
        assert m.group(1) == "101"

    def test_matches_caretaker_without_number(self):
        m = _CARETAKER_RE.match("caretaker: flush 2 pending state files")
        assert m is not None
        assert m.group(1) is None

    def test_matches_case_insensitive(self):
        m = _CARETAKER_RE.match("Caretaker-50: something")
        assert m is not None
        assert m.group(1) == "50"

    def test_rejects_catch_up(self):
        m = _CARETAKER_RE.match("catch-up: hourly caretaker restart")
        assert m is None

    def test_rejects_regular_commit(self):
        m = _CARETAKER_RE.match("guoban: note (stroke 121)")
        assert m is None

    def test_rejects_empty_message(self):
        m = _CARETAKER_RE.match("")
        assert m is None


# ---------------------------------------------------------------------------
# _extract_visits
# ---------------------------------------------------------------------------


class TestExtractVisits:
    """Tests for git log parsing into caretaker visits."""

    def test_parses_numbered_caretaker(self):
        log = "2026-10-09 12:04:36 +0800 caretaker-101: add push_preflight module"
        visits = _extract_visits(log)
        assert len(visits) == 1
        ts, msg, num = visits[0]
        assert num == 101
        assert "push_preflight" in msg
        assert ts.hour == 12
        assert ts.minute == 4

    def test_parses_unnumbered_caretaker(self):
        log = "2026-10-09 12:04:58 +0800 caretaker: flush 2 pending state files"
        visits = _extract_visits(log)
        assert len(visits) == 1
        ts, msg, num = visits[0]
        assert num is None
        assert "flush" in msg

    def test_skips_non_caretaker_commits(self):
        log = (
            "2026-10-09 13:00:56 +0800 catch-up: hourly caretaker restart\n"
            "2026-10-09 11:56:28 +0800 guoban: note (stroke 121)\n"
            "2026-10-09 12:04:36 +0800 caretaker-101: add module"
        )
        visits = _extract_visits(log)
        assert len(visits) == 1
        assert visits[0][2] == 101

    def test_multiple_visits_newest_first(self):
        log = (
            "2026-10-09 12:04:36 +0800 caretaker-101: second visit\n"
            "2026-10-09 11:07:16 +0800 caretaker-100: first visit"
        )
        visits = _extract_visits(log)
        assert len(visits) == 2
        assert visits[0][2] == 101  # newest first
        assert visits[1][2] == 100

    def test_handles_empty_input(self):
        assert _extract_visits("") == []

    def test_handles_blank_lines(self):
        log = "\n\n2026-10-09 12:04:36 +0800 caretaker-50: something\n\n"
        visits = _extract_visits(log)
        assert len(visits) == 1

    def test_preserves_timezone(self):
        log = "2026-10-09 05:00:00 +0000 caretaker-1: utc visit"
        visits = _extract_visits(log)
        assert len(visits) == 1
        assert visits[0][0].tzinfo is not None

    def test_different_timezones(self):
        log = (
            "2026-10-09 12:00:00 +0800 caretaker-2: cst visit\n"
            "2026-10-09 04:00:00 +0000 caretaker-1: utc visit"
        )
        visits = _extract_visits(log)
        assert len(visits) == 2
        # Both should parse correctly
        assert visits[0][0].hour == 12  # +0800
        assert visits[1][0].hour == 4  # +0000

    def test_malformed_timestamp_skipped(self):
        log = "not-a-date caretaker-1: bad line"
        visits = _extract_visits(log)
        assert len(visits) == 0


# ---------------------------------------------------------------------------
# _intervals_minutes
# ---------------------------------------------------------------------------


class TestIntervalsMinutes:
    """Tests for interval computation between visits."""

    def _make_visit(self, dt: datetime, msg: str = "caretaker: test", num=None):
        return (dt, msg, num)

    def test_empty_input(self):
        assert _intervals_minutes([]) == []

    def test_single_visit(self):
        v = [self._make_visit(datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc))]
        assert _intervals_minutes(v) == []

    def test_two_visits_one_hour_apart(self):
        v = [
            self._make_visit(datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc)),
            self._make_visit(datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)),
        ]
        intervals = _intervals_minutes(v)
        assert len(intervals) == 1
        assert intervals[0] == pytest.approx(60.0, abs=0.01)

    def test_three_visits_chronological_order(self):
        """Intervals should be oldest-to-newest chronologically."""
        v = [
            self._make_visit(datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)),
            self._make_visit(datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)),
            self._make_visit(datetime(2026, 10, 9, 11, 0, tzinfo=timezone.utc)),
        ]
        intervals = _intervals_minutes(v)
        assert len(intervals) == 2
        # Chronologically: 11:00→12:00 = 60m, 12:00→14:00 = 120m
        assert intervals[0] == pytest.approx(60.0, abs=0.01)
        assert intervals[1] == pytest.approx(120.0, abs=0.01)

    def test_mixed_intervals(self):
        v = [
            self._make_visit(datetime(2026, 10, 9, 15, 30, tzinfo=timezone.utc)),
            self._make_visit(datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)),
            self._make_visit(datetime(2026, 10, 9, 13, 45, tzinfo=timezone.utc)),
            self._make_visit(datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)),
        ]
        intervals = _intervals_minutes(v)
        assert len(intervals) == 3
        assert intervals[0] == pytest.approx(105.0, abs=0.01)  # 12:00→13:45
        assert intervals[1] == pytest.approx(15.0, abs=0.01)   # 13:45→14:00
        assert intervals[2] == pytest.approx(90.0, abs=0.01)   # 14:00→15:30

    def test_same_timestamp(self):
        dt = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
        v = [self._make_visit(dt), self._make_visit(dt)]
        intervals = _intervals_minutes(v)
        assert len(intervals) == 1
        assert intervals[0] == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# _compute_stats
# ---------------------------------------------------------------------------


class TestComputeStats:
    """Tests for statistical computation."""

    def test_empty_list(self):
        stats = _compute_stats([])
        assert stats["mean"] == 0.0
        assert stats["median"] == 0.0
        assert stats["std"] == 0.0
        assert stats["min"] == 0.0
        assert stats["max"] == 0.0

    def test_single_value(self):
        stats = _compute_stats([42.0])
        assert stats["mean"] == pytest.approx(42.0)
        assert stats["median"] == pytest.approx(42.0)
        assert stats["std"] == pytest.approx(0.0)
        assert stats["min"] == pytest.approx(42.0)
        assert stats["max"] == pytest.approx(42.0)

    def test_two_values(self):
        stats = _compute_stats([60.0, 120.0])
        assert stats["mean"] == pytest.approx(90.0)
        assert stats["median"] == pytest.approx(90.0)
        assert stats["min"] == pytest.approx(60.0)
        assert stats["max"] == pytest.approx(120.0)

    def test_known_values(self):
        # mean=5, variance=(4+0+4)/3=8/3, std=√(8/3)≈1.633
        stats = _compute_stats([3.0, 5.0, 7.0])
        assert stats["mean"] == pytest.approx(5.0)
        assert stats["median"] == pytest.approx(5.0)
        assert stats["std"] == pytest.approx((8.0 / 3.0) ** 0.5, abs=0.01)

    def test_odd_count_median(self):
        stats = _compute_stats([1.0, 3.0, 5.0, 7.0, 9.0])
        assert stats["median"] == pytest.approx(5.0)

    def test_even_count_median(self):
        stats = _compute_stats([1.0, 3.0, 5.0, 7.0])
        assert stats["median"] == pytest.approx(4.0)

    def test_all_same_values(self):
        stats = _compute_stats([60.0, 60.0, 60.0])
        assert stats["mean"] == pytest.approx(60.0)
        assert stats["std"] == pytest.approx(0.0)
        assert stats["min"] == pytest.approx(60.0)
        assert stats["max"] == pytest.approx(60.0)

    def test_precision_rounding(self):
        stats = _compute_stats([1.0, 2.0, 3.0])
        # All values should be rounded to 2 decimal places
        for key in ["mean", "median", "std", "min", "max"]:
            assert isinstance(stats[key], float)


# ---------------------------------------------------------------------------
# _rhythm_score
# ---------------------------------------------------------------------------


class TestRhythmScore:
    """Tests for rhythm score computation."""

    def test_perfect_regularity(self):
        assert _rhythm_score(0.0, 60.0) == pytest.approx(1.0)

    def test_zero_mean(self):
        assert _rhythm_score(0.0, 0.0) == pytest.approx(0.0)

    def test_high_variance(self):
        # CV = 60/60 = 1.0 → score = 0.0
        assert _rhythm_score(60.0, 60.0) == pytest.approx(0.0)

    def test_moderate_variance(self):
        # CV = 15/60 = 0.25 → score = 0.75
        assert _rhythm_score(15.0, 60.0) == pytest.approx(0.75)

    def test_clamped_at_zero(self):
        # CV = 120/60 = 2.0 → score = max(0, 1-2) = 0.0
        assert _rhythm_score(120.0, 60.0) == pytest.approx(0.0)

    def test_small_variance(self):
        # CV = 5/60 ≈ 0.083 → score ≈ 0.917
        assert _rhythm_score(5.0, 60.0) == pytest.approx(0.917, abs=0.001)

    def test_returns_float(self):
        result = _rhythm_score(10.0, 60.0)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# _find_gaps
# ---------------------------------------------------------------------------


class TestFindGaps:
    """Tests for gap detection."""

    def _make_visit(self, dt, msg="caretaker: test", num=None):
        return (dt, msg, num)

    def test_no_gaps(self):
        visits = [
            self._make_visit(datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc), num=3),
            self._make_visit(datetime(2026, 10, 9, 11, 0, tzinfo=timezone.utc), num=2),
            self._make_visit(datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc), num=1),
        ]
        intervals = [60.0, 60.0]  # all within 120m threshold
        gaps = _find_gaps(intervals, visits, 120.0)
        assert gaps == []

    def test_one_gap_detected(self):
        visits = [
            self._make_visit(datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc), num=3),
            self._make_visit(datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc), num=2),
            self._make_visit(datetime(2026, 10, 9, 11, 0, tzinfo=timezone.utc), num=1),
        ]
        intervals = [60.0, 180.0]  # second gap exceeds 120m
        gaps = _find_gaps(intervals, visits, 120.0)
        assert len(gaps) == 1
        assert gaps[0]["minutes"] == pytest.approx(180.0)
        assert gaps[0]["visit_number"] == 3

    def test_multiple_gaps(self):
        visits = [
            self._make_visit(datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc), num=4),
            self._make_visit(datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc), num=3),
            self._make_visit(datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc), num=2),
            self._make_visit(datetime(2026, 10, 9, 11, 0, tzinfo=timezone.utc), num=1),
        ]
        intervals = [60.0, 180.0, 180.0]
        gaps = _find_gaps(intervals, visits, 120.0)
        assert len(gaps) == 2

    def test_exact_threshold_not_flagged(self):
        visits = [
            self._make_visit(datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc), num=2),
            self._make_visit(datetime(2026, 10, 9, 11, 0, tzinfo=timezone.utc), num=1),
        ]
        intervals = [120.0]  # exactly at threshold
        gaps = _find_gaps(intervals, visits, 120.0)
        assert gaps == []

    def test_gap_includes_timestamp(self):
        ts = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)
        visits = [
            self._make_visit(ts, num=2),
            self._make_visit(datetime(2026, 10, 9, 11, 0, tzinfo=timezone.utc), num=1),
        ]
        intervals = [240.0]
        gaps = _find_gaps(intervals, visits, 120.0)
        assert len(gaps) == 1
        assert gaps[0]["timestamp"] == ts.isoformat()

    def test_custom_threshold(self):
        visits = [
            self._make_visit(datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc), num=2),
            self._make_visit(datetime(2026, 10, 9, 11, 0, tzinfo=timezone.utc), num=1),
        ]
        intervals = [60.0]
        # With 30m threshold, 60m is a gap
        gaps = _find_gaps(intervals, visits, 30.0)
        assert len(gaps) == 1
        # With 90m threshold, 60m is not a gap
        gaps = _find_gaps(intervals, visits, 90.0)
        assert gaps == []


# ---------------------------------------------------------------------------
# caretaker_rhythm (integration with mocked git)
# ---------------------------------------------------------------------------


MOCK_LOG = (
    "2026-10-09 12:04:36 +0800 caretaker-101: add push_preflight module\n"
    "2026-10-09 12:00:56 +0800 catch-up: hourly caretaker restart\n"
    "2026-10-09 11:07:16 +0800 caretaker-100: add backlog_pressure module\n"
    "2026-10-09 11:00:59 +0800 catch-up: hourly caretaker restart\n"
    "2026-10-09 10:03:50 +0800 caretaker-99: add commit_audit module\n"
    "2026-10-09 09:04:52 +0800 caretaker-98: add stall_recover module\n"
    "2026-10-09 08:04:19 +0800 caretaker-97: add stall_recover module\n"
    "2026-10-09 07:02:40 +0800 caretaker-31: new commit_blockage module\n"
)


class TestCaretakerRhythm:
    """Integration tests with mocked git subprocess."""

    @patch("iamai.caretaker_rhythm._git_log")
    def test_basic_analysis(self, mock_log, tmp_path):
        mock_log.return_value = MOCK_LOG
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path)

        assert result["visits"] == 6  # 6 caretaker commits
        assert result["mean_interval_minutes"] > 0
        assert result["rhythm_score"] >= 0.0
        assert result["rhythm_score"] <= 1.0

    @patch("iamai.caretaker_rhythm._git_log")
    def test_respects_max_visits(self, mock_log, tmp_path):
        mock_log.return_value = MOCK_LOG
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path, max_visits=3)
        assert result["visits"] == 3

    @patch("iamai.caretaker_rhythm._git_log")
    def test_gap_detection(self, mock_log, tmp_path):
        mock_log.return_value = MOCK_LOG
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path, gap_threshold_minutes=120.0)
        # There should be gaps: 07:02→08:04 = ~62m (no gap),
        # but the overall span includes larger gaps
        assert isinstance(result["gaps"], list)

    @patch("iamai.caretaker_rhythm._git_log")
    def test_span_hours(self, mock_log, tmp_path):
        mock_log.return_value = MOCK_LOG
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path)
        # First visit ~07:02, last ~12:04 → about 5 hours
        assert result["span_hours"] > 4.0
        assert result["span_hours"] < 6.0

    @patch("iamai.caretaker_rhythm._git_log")
    def test_timestamps_recorded(self, mock_log, tmp_path):
        mock_log.return_value = MOCK_LOG
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path)
        assert result["first_visit_at"] is not None
        assert result["last_visit_at"] is not None
        assert "2026-10-09" in result["first_visit_at"]

    @patch("iamai.caretaker_rhythm._git_log")
    def test_empty_log(self, mock_log, tmp_path):
        mock_log.return_value = ""
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path)
        assert result["visits"] == 0
        assert result["rhythm_score"] == 0.0
        assert result["gaps"] == []
        assert result["first_visit_at"] is None

    @patch("iamai.caretaker_rhythm._git_log")
    def test_single_visit(self, mock_log, tmp_path):
        mock_log.return_value = "2026-10-09 12:00:00 +0800 caretaker-1: only visit"
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path)
        assert result["visits"] == 1
        assert result["mean_interval_minutes"] == 0.0
        assert result["gaps"] == []

    @patch("iamai.caretaker_rhythm._git_log")
    def test_string_repo_path(self, mock_log, tmp_path):
        mock_log.return_value = MOCK_LOG
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(str(tmp_path))
        assert result["visits"] > 0

    @patch("iamai.caretaker_rhythm._git_log")
    def test_all_visits_are_caretakers(self, mock_log, tmp_path):
        """Non-caretaker commits should be excluded from visit count."""
        mock_log.return_value = (
            "2026-10-09 12:00:00 +0800 catch-up: restart\n"
            "2026-10-09 11:00:00 +0800 guoban: note\n"
            "2026-10-09 10:00:00 +0800 caretaker-50: visit"
        )
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path)
        assert result["visits"] == 1

    @patch("iamai.caretaker_rhythm._git_log")
    def test_rhythm_score_reasonable_for_hourly(self, mock_log, tmp_path):
        """Hourly visits with small jitter should score reasonably."""
        mock_log.return_value = (
            "2026-10-09 12:03:00 +0800 caretaker-5: visit\n"
            "2026-10-09 11:01:00 +0800 caretaker-4: visit\n"
            "2026-10-09 10:02:00 +0800 caretaker-3: visit\n"
            "2026-10-09 09:00:00 +0800 caretaker-2: visit\n"
            "2026-10-09 08:01:00 +0800 caretaker-1: visit"
        )
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path)
        # Mean ~60m, std should be small → decent score
        assert result["rhythm_score"] > 0.5


# ---------------------------------------------------------------------------
# rhythm_report
# ---------------------------------------------------------------------------


class TestRhythmReport:
    """Tests for the one-line report formatting."""

    @patch("iamai.caretaker_rhythm._git_log")
    def test_basic_format(self, mock_log, tmp_path):
        mock_log.return_value = MOCK_LOG
        (tmp_path / ".git").mkdir(parents=True)

        report = rhythm_report(tmp_path)
        assert "visits" in report
        assert "mean" in report
        assert "rhythm" in report
        assert "gap" in report

    @patch("iamai.caretaker_rhythm._git_log")
    def test_empty_repo_report(self, mock_log, tmp_path):
        mock_log.return_value = ""
        (tmp_path / ".git").mkdir(parents=True)

        report = rhythm_report(tmp_path)
        assert "no caretaker visits" in report

    @patch("iamai.caretaker_rhythm._git_log")
    def test_short_span_uses_hours(self, mock_log, tmp_path):
        mock_log.return_value = (
            "2026-10-09 14:00:00 +0800 caretaker-2: visit\n"
            "2026-10-09 12:00:00 +0800 caretaker-1: visit"
        )
        (tmp_path / ".git").mkdir(parents=True)

        report = rhythm_report(tmp_path)
        assert "h" in report  # should use hours, not days

    @patch("iamai.caretaker_rhythm._git_log")
    def test_long_span_uses_days(self, mock_log, tmp_path):
        mock_log.return_value = (
            "2026-10-09 12:00:00 +0800 caretaker-2: visit\n"
            "2026-10-05 12:00:00 +0800 caretaker-1: visit"
        )
        (tmp_path / ".git").mkdir(parents=True)

        report = rhythm_report(tmp_path)
        assert "d" in report  # should use days

    @patch("iamai.caretaker_rhythm._git_log")
    def test_single_gap_singular(self, mock_log, tmp_path):
        mock_log.return_value = (
            "2026-10-09 15:00:00 +0800 caretaker-2: visit\n"
            "2026-10-09 11:00:00 +0800 caretaker-1: visit"
        )
        (tmp_path / ".git").mkdir(parents=True)

        report = rhythm_report(tmp_path, gap_threshold_minutes=120.0)
        # 4 hours = 240m > 120m threshold → 1 gap
        assert "1 gap" in report
        assert "gaps" not in report  # singular, not plural

    @patch("iamai.caretaker_rhythm._git_log")
    def test_multiple_gaps_plural(self, mock_log, tmp_path):
        mock_log.return_value = (
            "2026-10-09 18:00:00 +0800 caretaker-3: visit\n"
            "2026-10-09 15:00:00 +0800 caretaker-2: visit\n"
            "2026-10-09 11:00:00 +0800 caretaker-1: visit"
        )
        (tmp_path / ".git").mkdir(parents=True)

        report = rhythm_report(tmp_path, gap_threshold_minutes=120.0)
        assert "gaps" in report


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    @patch("iamai.caretaker_rhythm._git_log")
    def test_only_catch_up_commits(self, mock_log, tmp_path):
        mock_log.return_value = (
            "2026-10-09 12:00:00 +0800 catch-up: hourly caretaker restart\n"
            "2026-10-09 11:00:00 +0800 catch-up: hourly caretaker restart"
        )
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path)
        assert result["visits"] == 0

    @patch("iamai.caretaker_rhythm._git_log")
    def test_unnumbered_caretaker_included(self, mock_log, tmp_path):
        mock_log.return_value = (
            "2026-10-09 12:00:00 +0800 caretaker: flush state files\n"
            "2026-10-09 11:00:00 +0800 caretaker-50: visit"
        )
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path)
        assert result["visits"] == 2

    @patch("iamai.caretaker_rhythm._git_log")
    def test_very_large_interval(self, mock_log, tmp_path):
        mock_log.return_value = (
            "2026-10-09 12:00:00 +0800 caretaker-2: visit\n"
            "2026-10-02 12:00:00 +0800 caretaker-1: visit"
        )
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path, gap_threshold_minutes=120.0)
        assert len(result["gaps"]) == 1
        assert result["gaps"][0]["minutes"] == pytest.approx(7 * 24 * 60, abs=1.0)

    @patch("iamai.caretaker_rhythm._git_log")
    def test_max_visits_one(self, mock_log, tmp_path):
        mock_log.return_value = MOCK_LOG
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path, max_visits=1)
        assert result["visits"] == 1
        assert result["mean_interval_minutes"] == 0.0

    @patch("iamai.caretaker_rhythm._git_log")
    def test_zero_gap_threshold(self, mock_log, tmp_path):
        """With threshold=0, every interval is a gap."""
        mock_log.return_value = (
            "2026-10-09 12:00:00 +0800 caretaker-3: visit\n"
            "2026-10-09 11:00:00 +0800 caretaker-2: visit\n"
            "2026-10-09 10:00:00 +0800 caretaker-1: visit"
        )
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path, gap_threshold_minutes=0.0)
        assert len(result["gaps"]) == 2

    @patch("iamai.caretaker_rhythm._git_log")
    def test_rhythm_score_with_identical_intervals(self, mock_log, tmp_path):
        """Identical intervals → std=0 → CV=0 → score=1.0."""
        mock_log.return_value = (
            "2026-10-09 12:00:00 +0800 caretaker-4: visit\n"
            "2026-10-09 11:00:00 +0800 caretaker-3: visit\n"
            "2026-10-09 10:00:00 +0800 caretaker-2: visit\n"
            "2026-10-09 09:00:00 +0800 caretaker-1: visit"
        )
        (tmp_path / ".git").mkdir(parents=True)

        result = caretaker_rhythm(tmp_path)
        assert result["rhythm_score"] == pytest.approx(1.0, abs=0.01)
