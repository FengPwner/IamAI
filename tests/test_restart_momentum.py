"""Tests for iamai.restart_momentum."""

import pytest

from iamai.restart_momentum import momentum_score


# ---------------------------------------------------------------------------
# Basic scoring
# ---------------------------------------------------------------------------


class TestMomentumScore:
    def test_empty_returns_no_data(self):
        result = momentum_score([], target_minutes=30)
        assert result["verdict"] == "no_data"
        assert result["score"] == 0.0
        assert result["session_count"] == 0

    def test_all_long_sessions_healthy(self):
        durations = [60, 90, 120, 45]
        result = momentum_score(durations, target_minutes=30)
        assert result["verdict"] == "healthy"
        assert result["score"] > 0.5
        assert result["crash_count"] == 0

    def test_all_crashes_negative(self):
        durations = [1, 2, 1, 2.5]
        result = momentum_score(durations, target_minutes=30)
        assert result["verdict"] == "crash_loop"
        assert result["score"] < 0.0
        assert result["crash_count"] == 4

    def test_mixed_sessions_weak(self):
        durations = [60, 5, 90, 2]
        result = momentum_score(durations, target_minutes=30)
        # Some long, some short — score should be moderate
        assert -1.0 <= result["score"] <= 1.0
        assert result["session_count"] == 4

    def test_score_clamped_to_range(self):
        # Extreme values shouldn't produce out-of-range scores
        durations = [1000, 1000, 1000]
        result = momentum_score(durations, target_minutes=30)
        assert -1.0 <= result["score"] <= 1.0

        durations = [0.1, 0.1, 0.1]
        result = momentum_score(durations, target_minutes=30)
        assert -1.0 <= result["score"] <= 1.0


# ---------------------------------------------------------------------------
# Crash penalty
# ---------------------------------------------------------------------------


class TestCrashPenalty:
    def test_short_sessions_counted_as_crashes(self):
        # 10% of 30 = 3 minutes threshold
        durations = [60, 2, 90, 1]
        result = momentum_score(durations, target_minutes=30)
        assert result["crash_count"] == 2

    def test_boundary_not_crash(self):
        # Exactly at threshold shouldn't crash-count
        durations = [3.0]  # exactly 10% of 30
        result = momentum_score(durations, target_minutes=30)
        assert result["crash_count"] == 0

    def test_crash_penalty_amplifies_negative(self):
        # One crash session should pull score significantly negative
        one_crash = [2.0]
        one_long = [60.0]
        crash_result = momentum_score(one_crash, target_minutes=30)
        long_result = momentum_score(one_long, target_minutes=30)
        assert crash_result["score"] < long_result["score"]


# ---------------------------------------------------------------------------
# Trend detection
# ---------------------------------------------------------------------------


class TestTrend:
    def test_improving_trend(self):
        # First half: crashes, second half: long sessions
        durations = [1, 2, 1, 2, 60, 90, 120, 60]
        result = momentum_score(durations, target_minutes=30)
        assert result["trend"] == "improving"

    def test_declining_trend(self):
        # First half: long sessions, second half: crashes
        durations = [60, 90, 120, 60, 1, 2, 1, 2]
        result = momentum_score(durations, target_minutes=30)
        assert result["trend"] == "declining"

    def test_stable_trend(self):
        # All similar durations
        durations = [45, 50, 55, 48, 52, 50, 47, 53]
        result = momentum_score(durations, target_minutes=30)
        assert result["trend"] == "stable"

    def test_insufficient_data_trend(self):
        durations = [30, 60]
        result = momentum_score(durations, target_minutes=30)
        assert result["trend"] == "insufficient_data"


# ---------------------------------------------------------------------------
# Custom target
# ---------------------------------------------------------------------------


class TestCustomTarget:
    def test_short_target_makes_sessions_healthy(self):
        # 5-minute target: 10-minute sessions should be healthy
        durations = [10, 12, 8, 15]
        result = momentum_score(durations, target_minutes=5)
        assert result["verdict"] == "healthy"

    def test_long_target_makes_sessions_crash(self):
        # 120-minute target: 10-minute sessions should be crashes
        durations = [10, 12, 8, 15]
        result = momentum_score(durations, target_minutes=120)
        assert result["verdict"] == "crash_loop"

    def test_mean_duration_computed(self):
        durations = [10, 20, 30]
        result = momentum_score(durations, target_minutes=20)
        assert result["mean_duration"] == 20.0
