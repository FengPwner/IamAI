"""Tests for stroke_recovery_time module."""

import pytest
from iamai.stroke_recovery_time import (
    classify_recovery,
    recovery_times,
    recovery_summary,
)


class TestClassifyRecovery:
    """Classification of recovery speed by gap duration."""

    def test_fast_under_60s(self):
        assert classify_recovery(0) == "fast"
        assert classify_recovery(30) == "fast"
        assert classify_recovery(59) == "fast"

    def test_normal_60_to_300(self):
        assert classify_recovery(60) == "normal"
        assert classify_recovery(120) == "normal"
        assert classify_recovery(299) == "normal"

    def test_slow_over_300(self):
        assert classify_recovery(300) == "slow"
        assert classify_recovery(600) == "slow"
        assert classify_recovery(3600) == "slow"

    def test_stalled_negative(self):
        assert classify_recovery(-1) == "stalled"
        assert classify_recovery(-100) == "stalled"

    def test_boundary_values(self):
        assert classify_recovery(59.9) == "fast"
        assert classify_recovery(60.0) == "normal"
        assert classify_recovery(299.9) == "normal"
        assert classify_recovery(300.0) == "slow"

    def test_fractional_seconds(self):
        assert classify_recovery(0.5) == "fast"
        assert classify_recovery(45.7) == "fast"
        assert classify_recovery(150.3) == "normal"


class TestRecoveryTimes:
    """Integration tests for recovery_times with real repo data."""

    def test_returns_list(self):
        result = recovery_times()
        assert isinstance(result, list)

    def test_entries_have_required_keys(self):
        result = recovery_times(max_commits=50)
        if not result:
            pytest.skip("no restart events in recent history")
        entry = result[0]
        required = {
            "restart_sha", "restart_at", "restart_subject",
            "first_stroke_at", "gap_seconds", "classification",
        }
        assert required.issubset(entry.keys())

    def test_gap_is_numeric(self):
        for entry in recovery_times(max_commits=50):
            assert isinstance(entry["gap_seconds"], (int, float))

    def test_classification_is_valid(self):
        valid = {"fast", "normal", "slow", "stalled"}
        for entry in recovery_times(max_commits=50):
            assert entry["classification"] in valid

    def test_sha_is_short(self):
        for entry in recovery_times(max_commits=50):
            assert len(entry["restart_sha"]) == 7


class TestRecoverySummary:
    """Summary string formatting."""

    def test_returns_string(self):
        result = recovery_summary()
        assert isinstance(result, str)

    def test_contains_restarts(self):
        result = recovery_summary()
        assert "restarts" in result or "no restart" in result

    def test_includes_median_when_data_exists(self):
        result = recovery_summary(max_commits=200)
        if "no restart" not in result:
            assert "median" in result
            assert "max" in result
