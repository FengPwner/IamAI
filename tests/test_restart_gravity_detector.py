#!/usr/bin/env python3
"""tests for scripts/restart_gravity_detector.py — restart gravity detector."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from restart_gravity_detector import (
    is_restart_commit,
    compute_intervals,
    linear_regression,
    compute_decay_ratio,
    score_interval_trend,
    score_interval_stability,
    score_restart_density,
    score_decay_compounding,
    format_bar,
    format_report,
    parse_timestamp,
)
from datetime import datetime, timezone, timedelta


# ── timestamp parsing ────────────────────────────────────────────────


class TestParseTimestamp:
    def test_standard_format(self):
        ts = parse_timestamp("2026-10-24 14:00:00 +0800")
        assert ts is not None
        assert ts.year == 2026
        assert ts.month == 10
        assert ts.day == 24

    def test_without_timezone(self):
        ts = parse_timestamp("2026-10-24 14:00:00")
        assert ts is not None
        assert ts.hour == 14

    def test_invalid_format(self):
        ts = parse_timestamp("not a date")
        assert ts is None

    def test_empty_string(self):
        ts = parse_timestamp("")
        assert ts is None


# ── restart commit detection ─────────────────────────────────────────


class TestIsRestartCommit:
    def test_process_restart(self):
        assert is_restart_commit("process restart after stall") is True

    def test_restart_after(self):
        assert is_restart_commit("restart after resource exhaustion") is True

    def test_caretaker_restart(self):
        assert is_restart_commit("caretaker visit 342: restart writer + flush") is True

    def test_writer_restart(self):
        assert is_restart_commit("writer restart: pid 1234 up") is True

    def test_catch_up_restart(self):
        assert is_restart_commit("catch-up: restart stalled writer") is True

    def test_recovery_restart(self):
        assert is_restart_commit("recovery: restart after crash") is True

    def test_regular_stroke(self):
        assert is_restart_commit("writer stroke (auto-sync)") is False

    def test_regular_caretaker(self):
        assert is_restart_commit("caretaker visit 340: add feature.py") is False

    def test_update_docs(self):
        assert is_restart_commit("update documentation for module X") is False

    def test_case_insensitive(self):
        assert is_restart_commit("PROCESS RESTART after stall") is True

    def test_flush_as_restart(self):
        assert is_restart_commit("caretaker visit 342: add session_detector.py + flush 9 pending") is True


# ── interval computation ─────────────────────────────────────────────


def _make_event(minutes_offset: int, sha: str = "abc12345") -> dict:
    """helper to create an event dict with a specific timestamp offset."""
    base = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    return {
        "sha": sha,
        "timestamp": base + timedelta(minutes=minutes_offset),
        "message": "restart event",
    }


class TestComputeIntervals:
    def test_single_event(self):
        events = [_make_event(0)]
        assert compute_intervals(events) == []

    def test_empty(self):
        assert compute_intervals([]) == []

    def test_two_events(self):
        events = [_make_event(0), _make_event(60)]
        intervals = compute_intervals(events)
        assert len(intervals) == 1
        assert intervals[0] == 3600.0  # 60 minutes = 3600 seconds

    def test_multiple_events(self):
        events = [_make_event(0), _make_event(30), _make_event(90)]
        intervals = compute_intervals(events)
        assert len(intervals) == 2
        assert intervals[0] == 1800.0  # 30 min
        assert intervals[1] == 3600.0  # 60 min

    def test_same_timestamp(self):
        events = [_make_event(0), _make_event(0)]
        intervals = compute_intervals(events)
        assert len(intervals) == 0  # zero delta filtered out

    def test_chronological_order(self):
        events = [_make_event(0), _make_event(10), _make_event(15), _make_event(30)]
        intervals = compute_intervals(events)
        assert len(intervals) == 3
        assert intervals == [600.0, 300.0, 900.0]


# ── linear regression ────────────────────────────────────────────────


class TestLinearRegression:
    def test_empty(self):
        slope, r2 = linear_regression([])
        assert slope == 0.0
        assert r2 == 0.0

    def test_single_value(self):
        slope, r2 = linear_regression([5.0])
        assert slope == 0.0
        assert r2 == 0.0

    def test_constant_values(self):
        slope, r2 = linear_regression([100.0, 100.0, 100.0, 100.0])
        assert abs(slope) < 0.001

    def test_positive_trend(self):
        # intervals growing: 100, 200, 300, 400
        slope, r2 = linear_regression([100.0, 200.0, 300.0, 400.0])
        assert slope > 0
        assert r2 > 0.9  # strong linear fit

    def test_negative_trend(self):
        # intervals shrinking: 400, 300, 200, 100
        slope, r2 = linear_regression([400.0, 300.0, 200.0, 100.0])
        assert slope < 0
        assert r2 > 0.9  # strong linear fit

    def test_noisy_data(self):
        # noisy but roughly flat
        slope, r2 = linear_regression([100.0, 80.0, 120.0, 90.0, 110.0])
        assert r2 < 0.5  # weak fit

    def test_two_points(self):
        slope, r2 = linear_regression([100.0, 200.0])
        assert abs(slope - 100.0) < 0.001
        assert abs(r2 - 1.0) < 0.001


# ── decay ratio ──────────────────────────────────────────────────────


class TestComputeDecayRatio:
    def test_insufficient_data(self):
        assert compute_decay_ratio([], window=5) == 1.0
        assert compute_decay_ratio([100.0], window=5) == 1.0

    def test_stable_intervals(self):
        intervals = [100.0] * 20
        ratio = compute_decay_ratio(intervals, window=5)
        assert abs(ratio - 1.0) < 0.01

    def test_shrinking_intervals(self):
        # historic: 200 each, recent: 100 each → ratio = 0.5
        intervals = [200.0] * 10 + [100.0] * 5
        ratio = compute_decay_ratio(intervals, window=5)
        assert abs(ratio - 0.5) < 0.01

    def test_growing_intervals(self):
        # historic: 100 each, recent: 200 each → ratio = 2.0
        intervals = [100.0] * 10 + [200.0] * 5
        ratio = compute_decay_ratio(intervals, window=5)
        assert abs(ratio - 2.0) < 0.01

    def test_moderate_decay(self):
        intervals = [300.0, 280.0, 260.0, 250.0, 240.0, 230.0,
                     200.0, 180.0, 160.0, 140.0]
        ratio = compute_decay_ratio(intervals, window=3)
        assert ratio < 1.0

    def test_window_equals_historic(self):
        # only enough data for window + 1
        intervals = [200.0] + [100.0] * 5
        ratio = compute_decay_ratio(intervals, window=5)
        assert abs(ratio - 0.5) < 0.01


# ── scoring functions ────────────────────────────────────────────────


class TestScoreIntervalTrend:
    def test_empty(self):
        assert score_interval_trend([]) == 0

    def test_two_points(self):
        assert score_interval_trend([100.0, 200.0]) == 0  # < 3 points

    def test_growing_intervals(self):
        # strongly positive trend → low score (good)
        intervals = [1000.0, 2000.0, 3000.0, 4000.0, 5000.0]
        score = score_interval_trend(intervals)
        assert score <= 10

    def test_shrinking_intervals(self):
        # strongly negative trend → high score (bad)
        intervals = [5000.0, 4000.0, 3000.0, 2000.0, 1000.0]
        score = score_interval_trend(intervals)
        assert score >= 14

    def test_stable_intervals(self):
        intervals = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0]
        score = score_interval_trend(intervals)
        assert score < 5


class TestScoreIntervalStability:
    def test_empty(self):
        assert score_interval_stability([]) == 0

    def test_perfectly_stable(self):
        intervals = [1000.0] * 10
        assert score_interval_stability(intervals) == 0

    def test_highly_variable(self):
        # very high coefficient of variation
        intervals = [100.0, 5000.0, 50.0, 8000.0, 200.0]
        score = score_interval_stability(intervals)
        assert score > 10

    def test_moderate_variance(self):
        intervals = [900.0, 1000.0, 1100.0, 950.0, 1050.0]
        score = score_interval_stability(intervals)
        assert 0 < score < 10


class TestScoreRestartDensity:
    def test_zero_commits(self):
        assert score_restart_density(".", 0, 0) == 0

    def test_low_density(self):
        # 2 restarts in 500 commits = 0.4%
        assert score_restart_density(".", 2, 500) == 0

    def test_high_density(self):
        # 50 restarts in 100 commits = 50%
        score = score_restart_density(".", 50, 100)
        assert score == 25

    def test_moderate_density(self):
        # 15 restarts in 100 commits = 15%
        score = score_restart_density(".", 15, 100)
        assert 5 < score < 20

    def test_threshold_boundary(self):
        # exactly 5% → should be 0
        assert score_restart_density(".", 5, 100) == 0
        # exactly 30% → should be 25
        assert score_restart_density(".", 30, 100) == 25


class TestScoreDecayCompounding:
    def test_stable(self):
        intervals = [1000.0] * 20
        assert score_decay_compounding(intervals) == 0

    def test_severe_decay(self):
        # recent intervals are much shorter
        intervals = [1000.0] * 10 + [200.0] * 5
        score = score_decay_compounding(intervals)
        assert score > 15

    def test_improving(self):
        # recent intervals are longer
        intervals = [500.0] * 10 + [1000.0] * 5
        assert score_decay_compounding(intervals) == 0

    def test_moderate_decay(self):
        intervals = [1000.0] * 10 + [700.0] * 5
        score = score_decay_compounding(intervals)
        assert 0 < score <= 15


# ── formatting ───────────────────────────────────────────────────────


class TestFormatBar:
    def test_zero(self):
        bar = format_bar(0)
        assert "░" * 20 in bar
        assert "0/25" in bar

    def test_max(self):
        bar = format_bar(25)
        assert "█" * 20 in bar
        assert "25/25" in bar

    def test_half(self):
        bar = format_bar(12)
        assert "█" in bar
        assert "░" in bar

    def test_overflow(self):
        bar = format_bar(30)
        assert "█" * 20 in bar


class TestFormatReport:
    def test_error(self):
        result = {"error": "something broke"}
        report = format_report(result)
        assert "ERROR" in report
        assert "something broke" in report

    def test_stable_orbit(self):
        result = {
            "grade": "STABLE_ORBIT",
            "total_score": 10,
            "metrics": {
                "interval_trend": 2,
                "interval_stability": 3,
                "restart_density": 2,
                "decay_compounding": 3,
            },
            "restart_count": 5,
            "interval_count": 4,
            "mean_interval_seconds": 7200.0,
            "median_interval_seconds": 7000.0,
            "trend_slope": 100.0,
            "trend_r_squared": 0.5,
            "decay_ratio": 1.05,
            "recent_events": [
                {"sha": "abc12345", "timestamp": "2026-10-24T12:00:00",
                 "message": "restart event"},
            ],
        }
        report = format_report(result)
        assert "STABLE_ORBIT" in report
        assert "10/100" in report
        assert "abc12345" in report

    def test_terminal_descent(self):
        result = {
            "grade": "TERMINAL_DESCENT",
            "total_score": 85,
            "metrics": {
                "interval_trend": 23,
                "interval_stability": 20,
                "restart_density": 22,
                "decay_compounding": 20,
            },
            "restart_count": 50,
            "interval_count": 49,
            "mean_interval_seconds": 600.0,
            "median_interval_seconds": 400.0,
            "trend_slope": -500.0,
            "trend_r_squared": 0.85,
            "decay_ratio": 0.4,
            "recent_events": [],
        }
        report = format_report(result)
        assert "TERMINAL_DESCENT" in report
        assert "shrinking" in report
