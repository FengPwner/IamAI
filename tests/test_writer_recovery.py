"""Tests for iamai.writer_recovery — post-restart recovery classification.

A stalled writer is a fire; recovery quality is how well the fire
department did. These tests verify that the classification logic
correctly distinguishes full, partial, fragile, and failed recoveries
across a range of realistic and edge-case scenarios.
"""

import pytest

from iamai.writer_recovery import (
    recovery_quality,
    _median,
    _compute_ratio,
    _FULL_THRESHOLD,
    _PARTIAL_THRESHOLD,
)


# --- Helper tests ---


class TestMedian:
    def test_empty(self):
        assert _median([]) == 0.0

    def test_single(self):
        assert _median([7.0]) == 7.0

    def test_odd(self):
        assert _median([3.0, 1.0, 5.0]) == 3.0

    def test_even(self):
        assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5

    def test_unsorted_input(self):
        assert _median([5.0, 1.0, 3.0]) == 3.0

    def test_duplicates(self):
        assert _median([2.0, 2.0, 2.0]) == 2.0


class TestComputeRatio:
    def test_exact_match(self):
        # gaps of 15s with expected 15s → ratio = 1.0
        assert _compute_ratio(15, [15, 15, 15]) == pytest.approx(1.0)

    def test_faster_than_expected(self):
        # gaps of 10s with expected 15s → ratio = 1.5
        assert _compute_ratio(15, [10, 10, 10]) == pytest.approx(1.5)

    def test_slower_than_expected(self):
        # gaps of 30s with expected 15s → ratio = 0.5
        assert _compute_ratio(15, [30, 30, 30]) == pytest.approx(0.5)

    def test_empty_gaps(self):
        assert _compute_ratio(15, []) == 0.0

    def test_zero_expected(self):
        assert _compute_ratio(0, [15, 15]) == 0.0

    def test_zero_gap(self):
        # zero median gap → inf
        result = _compute_ratio(15, [0, 0, 0])
        assert result == float("inf")


# --- Quality classification tests ---


class TestRecoveryQuality:
    """Core classification tests for recovery_quality."""

    # --- Failed ---

    def test_failed_no_strokes(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[],
        )
        assert result["quality"] == "failed"
        assert result["ratio"] == 0.0
        assert result["stroke_count"] == 0
        assert "no strokes" in result["advice"].lower()

    # --- Full ---

    def test_full_exact_cadence(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[15, 16, 14, 15, 15],
        )
        assert result["quality"] == "full"
        assert result["ratio"] >= _FULL_THRESHOLD

    def test_full_faster_than_cadence(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[10, 12, 11, 10, 13],
        )
        assert result["quality"] == "full"
        assert result["ratio"] > 1.0

    def test_full_at_threshold_boundary(self):
        # ratio exactly at _FULL_THRESHOLD (0.80)
        # expected=15, median gap = 15/0.80 = 18.75
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[18.75, 18.75, 18.75],
        )
        assert result["quality"] == "full"
        assert result["ratio"] == pytest.approx(_FULL_THRESHOLD)

    # --- Partial ---

    def test_partial_degraded_cadence(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[25, 28, 30, 26, 27],
        )
        assert result["quality"] == "partial"
        assert result["ratio"] < _FULL_THRESHOLD
        assert result["ratio"] >= _PARTIAL_THRESHOLD

    def test_partial_at_lower_boundary(self):
        # ratio exactly at _PARTIAL_THRESHOLD (0.40)
        # expected=15, median gap = 15/0.40 = 37.5
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[37.5, 37.5, 37.5],
        )
        assert result["quality"] == "partial"
        assert result["ratio"] == pytest.approx(_PARTIAL_THRESHOLD)

    # --- Fragile ---

    def test_fragile_stalled_again(self):
        """Even with good gaps, stalled_again=True → fragile."""
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[15, 16, 14],
            stalled_again=True,
        )
        assert result["quality"] == "fragile"
        assert "stalled again" in result["advice"].lower()

    def test_fragile_very_slow(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[60, 90, 120, 80, 70],
        )
        assert result["quality"] == "fragile"
        assert result["ratio"] < _PARTIAL_THRESHOLD

    # --- Observation window ---

    def test_observation_window_preserved(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[15, 16],
            observation_window_seconds=600,
        )
        assert result["observation_window"] == 600

    def test_default_observation_window(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[15, 16],
        )
        assert result["observation_window"] == 300

    # --- Stroke count ---

    def test_stroke_count_matches_gaps(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[15, 16, 14, 15],
        )
        assert result["stroke_count"] == 4

    # --- Median gap ---

    def test_median_gap_calculated(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[10, 20, 15],
        )
        assert result["median_gap"] == 15.0

    def test_median_gap_even_count(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[10, 20],
        )
        assert result["median_gap"] == 15.0

    # --- Advice content ---

    def test_full_advice_nominal(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[15, 16, 14],
        )
        assert "nominal" in result["advice"].lower()

    def test_partial_advice_monitor(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[25, 28, 30],
        )
        assert "monitor" in result["advice"].lower()

    def test_failed_advice_urgent(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[],
        )
        assert "immediately" in result["advice"].lower()

    # --- Robustness ---

    def test_single_gap(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[15],
        )
        assert result["quality"] == "full"
        assert result["stroke_count"] == 1

    def test_large_gap_list(self):
        gaps = [15 + (i % 3) for i in range(100)]
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=gaps,
        )
        assert result["quality"] == "full"
        assert result["stroke_count"] == 100

    def test_mixed_integer_float_gaps(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[15, 16.5, 14, 15.2],
        )
        assert result["quality"] == "full"

    def test_all_same_gap(self):
        result = recovery_quality(
            expected_cadence_seconds=15,
            post_restart_gaps=[15, 15, 15, 15, 15],
        )
        assert result["ratio"] == pytest.approx(1.0)

    def test_ratio_bounded_fields(self):
        """All numeric fields should be finite numbers (not NaN)."""
        import math
        for gaps in [[], [1], [15, 16], [100, 200, 300]]:
            result = recovery_quality(
                expected_cadence_seconds=15,
                post_restart_gaps=gaps,
            )
            assert math.isfinite(result["ratio"])
            assert math.isfinite(result["median_gap"])
