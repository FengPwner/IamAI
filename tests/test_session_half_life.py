"""Tests for session_half_life module — writer session decay analysis."""

import math
import pytest
from tools.session_half_life import (
    parse_session_durations,
    fit_exponential_decay,
    classify_trend,
    estimate_half_life_minutes,
    summarize,
)


# ---------------------------------------------------------------------------
# parse_session_durations
# ---------------------------------------------------------------------------

class TestParseSessionDurations:
    def test_empty_history(self):
        assert parse_session_durations([]) == []

    def test_single_restart(self):
        history = [{"at": "2026-10-20T10:00:00+00:00", "kind": "restart"}]
        assert parse_session_durations(history) == []

    def test_two_restarts_30min(self):
        history = [
            {"at": "2026-10-20T10:00:00+00:00", "kind": "restart"},
            {"at": "2026-10-20T10:30:00+00:00", "kind": "restart"},
        ]
        durations = parse_session_durations(history)
        assert len(durations) == 1
        assert abs(durations[0] - 30.0) < 0.01

    def test_filters_non_restart_entries(self):
        history = [
            {"at": "2026-10-20T10:00:00+00:00", "kind": "restart"},
            {"at": "2026-10-20T10:15:00+00:00", "kind": "thought"},
            {"at": "2026-10-20T10:20:00+00:00", "kind": "restart"},
        ]
        durations = parse_session_durations(history)
        assert len(durations) == 1
        assert abs(durations[0] - 20.0) < 0.01

    def test_handles_unsorted_input(self):
        history = [
            {"at": "2026-10-20T10:20:00+00:00", "kind": "restart"},
            {"at": "2026-10-20T10:00:00+00:00", "kind": "restart"},
        ]
        durations = parse_session_durations(history)
        assert len(durations) == 1
        assert abs(durations[0] - 20.0) < 0.01

    def test_naive_timestamps_treated_as_utc(self):
        history = [
            {"at": "2026-10-20T10:00:00", "kind": "restart"},
            {"at": "2026-10-20T10:45:00", "kind": "restart"},
        ]
        durations = parse_session_durations(history)
        assert len(durations) == 1
        assert abs(durations[0] - 45.0) < 0.01


# ---------------------------------------------------------------------------
# fit_exponential_decay
# ---------------------------------------------------------------------------

class TestFitExponentialDecay:
    def test_empty_returns_zero(self):
        fit = fit_exponential_decay([])
        assert fit["a"] == 0.0
        assert fit["k"] == 0.0

    def test_single_value(self):
        fit = fit_exponential_decay([30.0])
        assert fit["a"] == 30.0
        assert fit["half_life_sessions"] == float("inf")

    def test_constant_sessions_no_decay(self):
        durations = [20.0, 20.0, 20.0, 20.0, 20.0]
        fit = fit_exponential_decay(durations)
        assert abs(fit["k"]) < 0.01
        assert fit["half_life_sessions"] == float("inf")

    def test_shrinking_sessions_negative_k(self):
        # Each session ~80% of previous: 50, 40, 32, 25.6, 20.5
        durations = [50.0, 40.0, 32.0, 25.6, 20.5]
        fit = fit_exponential_decay(durations)
        assert fit["k"] < -0.05
        assert fit["r_squared"] > 0.9
        assert fit["half_life_sessions"] < 10

    def test_growing_sessions_positive_k(self):
        durations = [10.0, 15.0, 22.0, 33.0, 50.0]
        fit = fit_exponential_decay(durations)
        assert fit["k"] > 0.05
        assert fit["half_life_sessions"] == float("inf")

    def test_r_squared_high_for_clean_data(self):
        durations = [60.0, 48.0, 38.4, 30.7, 24.6]
        fit = fit_exponential_decay(durations)
        assert fit["r_squared"] > 0.95


# ---------------------------------------------------------------------------
# classify_trend
# ---------------------------------------------------------------------------

class TestClassifyTrend:
    def test_shrinking(self):
        assert classify_trend(-0.1, 0.8) == "shrinking"

    def test_growing(self):
        assert classify_trend(0.1, 0.8) == "growing"

    def test_stable_tight_k(self):
        assert classify_trend(0.01, 0.8) == "stable"

    def test_stable_low_r_squared(self):
        # Even with large k, noisy data → stable
        assert classify_trend(-0.1, 0.1) == "stable"

    def test_boundary_k_negative(self):
        assert classify_trend(-0.02, 0.5) == "stable"

    def test_boundary_k_positive(self):
        assert classify_trend(0.02, 0.5) == "stable"


# ---------------------------------------------------------------------------
# estimate_half_life_minutes
# ---------------------------------------------------------------------------

class TestEstimateHalfLifeMinutes:
    def test_no_durations_returns_inf(self):
        fit = {"a": 0, "k": 0.0, "r_squared": 0.0}
        assert estimate_half_life_minutes([], fit) == float("inf")

    def test_growing_returns_inf(self):
        fit = {"a": 30.0, "k": 0.05, "r_squared": 0.8}
        assert estimate_half_life_minutes([30.0, 35.0], fit) == float("inf")

    def test_shrinking_finite(self):
        fit = {"a": 50.0, "k": -0.1, "r_squared": 0.9}
        durations = [50.0, 45.0, 40.0, 36.0, 32.0]
        hlm = estimate_half_life_minutes(durations, fit)
        assert 0 < hlm < 1000

    def test_faster_decay_shorter_half_life(self):
        fit_slow = {"a": 50.0, "k": -0.05, "r_squared": 0.9}
        fit_fast = {"a": 50.0, "k": -0.2, "r_squared": 0.9}
        durations = [50.0, 40.0, 30.0, 20.0]
        slow = estimate_half_life_minutes(durations, fit_slow)
        fast = estimate_half_life_minutes(durations, fit_fast)
        assert fast < slow


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

class TestSummarize:
    def test_constant_sessions(self):
        durations = [20.0, 20.0, 20.0, 20.0, 20.0]
        s = summarize(durations)
        assert s["session_count"] == 5
        assert s["mean_duration_min"] == 20.0
        assert s["trend"] == "stable"
        assert s["half_life_minutes"] == float("inf")

    def test_shrinking_sessions(self):
        durations = [60.0, 48.0, 38.4, 30.7, 24.6, 19.7, 15.7]
        s = summarize(durations)
        assert s["session_count"] == 7
        assert s["trend"] == "shrinking"
        assert s["decay_rate_k"] < 0
        assert s["half_life_minutes"] < float("inf")
        assert len(s["recent_5"]) == 5

    def test_recent_5_caps_at_5(self):
        durations = [10.0] * 10
        s = summarize(durations)
        assert len(s["recent_5"]) == 5

    def test_recent_5_with_3(self):
        durations = [10.0, 20.0, 30.0]
        s = summarize(durations)
        assert len(s["recent_5"]) == 3
