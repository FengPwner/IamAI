"""Tests for iamai.rescue_ratio — rescue visit health analysis."""

import pytest

from iamai.rescue_ratio import (
    RescueAnalyser,
    consecutive_rescues,
    mean_time_between_rescues,
    rescue_ratio,
    severity,
    trend,
)


# ---------------------------------------------------------------------------
# rescue_ratio
# ---------------------------------------------------------------------------


class TestRescueRatio:
    def test_empty_list(self):
        assert rescue_ratio([]) == 0.0

    def test_all_healthy(self):
        visits = [{"kind": "healthy"}] * 10
        assert rescue_ratio(visits) == 0.0

    def test_all_rescue(self):
        visits = [{"kind": "rescue"}] * 10
        assert rescue_ratio(visits) == 1.0

    def test_half_and_half(self):
        visits = [{"kind": "rescue"}] * 5 + [{"kind": "healthy"}] * 5
        assert rescue_ratio(visits) == 0.5

    def test_window_limits_scope(self):
        # 20 visits: 10 rescue + 10 healthy, but window=5 only sees last 5
        visits = [{"kind": "rescue"}] * 10 + [{"kind": "healthy"}] * 10
        assert rescue_ratio(visits, window=5) == 0.0

    def test_window_larger_than_list(self):
        visits = [{"kind": "rescue"}, {"kind": "healthy"}]
        assert rescue_ratio(visits, window=100) == 0.5

    def test_single_rescue(self):
        assert rescue_ratio([{"kind": "rescue"}]) == 1.0

    def test_single_healthy(self):
        assert rescue_ratio([{"kind": "healthy"}]) == 0.0

    def test_missing_kind_treated_as_not_rescue(self):
        visits = [{}] * 5
        assert rescue_ratio(visits) == 0.0


# ---------------------------------------------------------------------------
# severity
# ---------------------------------------------------------------------------


class TestSeverity:
    def test_stable(self):
        assert severity(0.0) == "stable"

    def test_healthy_low(self):
        assert severity(0.01) == "healthy"

    def test_healthy_high(self):
        assert severity(0.19) == "healthy"

    def test_stressed(self):
        assert severity(0.2) == "stressed"
        assert severity(0.49) == "stressed"

    def test_distressed(self):
        assert severity(0.5) == "distressed"
        assert severity(0.79) == "distressed"

    def test_critical(self):
        assert severity(0.8) == "critical"
        assert severity(1.0) == "critical"

    def test_above_one_returns_critical(self):
        assert severity(1.5) == "critical"

    def test_negative_ratio(self):
        # negative shouldn't crash — falls through to stable
        assert severity(-0.1) == "stable"


# ---------------------------------------------------------------------------
# consecutive_rescues
# ---------------------------------------------------------------------------


class TestConsecutiveRescues:
    def test_empty(self):
        assert consecutive_rescues([]) == 0

    def test_last_healthy(self):
        visits = [{"kind": "rescue"}] * 5 + [{"kind": "healthy"}]
        assert consecutive_rescues(visits) == 0

    def test_all_rescue(self):
        visits = [{"kind": "rescue"}] * 7
        assert consecutive_rescues(visits) == 7

    def test_tail_streak(self):
        visits = (
            [{"kind": "rescue"}] * 3
            + [{"kind": "healthy"}]
            + [{"kind": "rescue"}] * 4
        )
        assert consecutive_rescues(visits) == 4

    def test_single_rescue_at_end(self):
        visits = [{"kind": "healthy"}] * 10 + [{"kind": "rescue"}]
        assert consecutive_rescues(visits) == 1

    def test_no_kind_key(self):
        visits = [{}] * 5
        assert consecutive_rescues(visits) == 0


# ---------------------------------------------------------------------------
# mean_time_between_rescues
# ---------------------------------------------------------------------------


class TestMeanTimeBetweenRescues:
    def test_fewer_than_two_rescues(self):
        visits = [{"kind": "rescue", "ts": "2026-10-20T10:00:00+08:00"}]
        assert mean_time_between_rescues(visits) is None

    def test_no_rescues(self):
        visits = [{"kind": "healthy", "ts": "2026-10-20T10:00:00+08:00"}]
        assert mean_time_between_rescues(visits) is None

    def test_empty(self):
        assert mean_time_between_rescues([]) is None

    def test_two_rescues_one_hour_apart(self):
        visits = [
            {"kind": "rescue", "ts": "2026-10-20T10:00:00+08:00"},
            {"kind": "healthy", "ts": "2026-10-20T10:30:00+08:00"},
            {"kind": "rescue", "ts": "2026-10-20T11:00:00+08:00"},
        ]
        mtbr = mean_time_between_rescues(visits)
        assert mtbr is not None
        assert abs(mtbr - 3600.0) < 1.0

    def test_three_rescues_equal_spacing(self):
        visits = [
            {"kind": "rescue", "ts": "2026-10-20T10:00:00+08:00"},
            {"kind": "rescue", "ts": "2026-10-20T11:00:00+08:00"},
            {"kind": "rescue", "ts": "2026-10-20T12:00:00+08:00"},
        ]
        mtbr = mean_time_between_rescues(visits)
        assert mtbr is not None
        assert abs(mtbr - 3600.0) < 1.0

    def test_ignores_healthy_visits(self):
        visits = [
            {"kind": "rescue", "ts": "2026-10-20T10:00:00+00:00"},
            {"kind": "healthy", "ts": "2026-10-20T10:15:00+00:00"},
            {"kind": "healthy", "ts": "2026-10-20T10:30:00+00:00"},
            {"kind": "rescue", "ts": "2026-10-20T10:45:00+00:00"},
        ]
        mtbr = mean_time_between_rescues(visits)
        assert mtbr is not None
        assert abs(mtbr - 2700.0) < 1.0  # 45 minutes

    def test_z_suffix_timestamps(self):
        visits = [
            {"kind": "rescue", "ts": "2026-10-20T02:00:00Z"},
            {"kind": "rescue", "ts": "2026-10-20T04:00:00Z"},
        ]
        mtbr = mean_time_between_rescues(visits)
        assert mtbr is not None
        assert abs(mtbr - 7200.0) < 1.0


# ---------------------------------------------------------------------------
# trend
# ---------------------------------------------------------------------------


class TestTrend:
    def test_not_enough_data(self):
        visits = [{"kind": "rescue"}] * 5
        assert trend(visits, window=10) == "flat"

    def test_improving(self):
        # previous window: all rescue; recent window: all healthy
        visits = [{"kind": "rescue"}] * 10 + [{"kind": "healthy"}] * 10
        assert trend(visits, window=10) == "improving"

    def test_worsening(self):
        visits = [{"kind": "healthy"}] * 10 + [{"kind": "rescue"}] * 10
        assert trend(visits, window=10) == "worsening"

    def test_flat(self):
        visits = (
            [{"kind": "rescue"}] * 5 + [{"kind": "healthy"}] * 5
        ) * 2
        assert trend(visits, window=10) == "flat"

    def test_exact_boundary(self):
        visits = [{"kind": "rescue"}] * 10 + [{"kind": "healthy"}] * 10
        assert trend(visits, window=10) == "improving"


# ---------------------------------------------------------------------------
# RescueAnalyser (composite)
# ---------------------------------------------------------------------------


class TestRescueAnalyser:
    def test_empty_visits(self):
        analyser = RescueAnalyser(window=10)
        report = analyser.analyse([])
        assert report["ratio"] == 0.0
        assert report["severity"] == "stable"
        assert report["consecutive_rescues"] == 0
        assert report["trend"] == "flat"
        assert report["mean_time_between_rescues"] is None
        assert report["total_visits"] == 0

    def test_full_report(self):
        visits = (
            [{"kind": "healthy", "ts": "2026-10-19T01:00:00+08:00"}] * 10
            + [{"kind": "rescue", "ts": "2026-10-20T01:00:00+08:00"}] * 10
        )
        analyser = RescueAnalyser(window=10)
        report = analyser.analyse(visits)

        assert report["ratio"] == 1.0
        assert report["severity"] == "critical"
        assert report["consecutive_rescues"] == 10
        assert report["trend"] == "worsening"
        assert report["total_visits"] == 20
        assert report["window"] == 10
        # mtbr: 10 rescues at identical timestamps → gaps are 0
        assert report["mean_time_between_rescues"] is not None

    def test_mixed_scenario(self):
        visits = [
            {"kind": "rescue", "ts": "2026-10-15T10:00:00+08:00"},
            {"kind": "rescue", "ts": "2026-10-16T10:00:00+08:00"},
            {"kind": "healthy", "ts": "2026-10-17T10:00:00+08:00"},
            {"kind": "healthy", "ts": "2026-10-18T10:00:00+08:00"},
            {"kind": "rescue", "ts": "2026-10-19T10:00:00+08:00"},
        ]
        analyser = RescueAnalyser(window=5)
        report = analyser.analyse(visits)

        assert report["ratio"] == 0.6
        assert report["severity"] == "distressed"
        assert report["consecutive_rescues"] == 1
        assert report["total_visits"] == 5
        # trend needs 2*window=10 visits, only 5 → flat
        assert report["trend"] == "flat"

    def test_window_parameter_passed(self):
        analyser = RescueAnalyser(window=3)
        visits = [
            {"kind": "healthy"},
            {"kind": "rescue"},
            {"kind": "rescue"},
            {"kind": "rescue"},
        ]
        report = analyser.analyse(visits)
        # window=3 → last 3 are all rescue
        assert report["ratio"] == 1.0
        assert report["window"] == 3
