"""Tests for iamai.restart_resilience."""

from __future__ import annotations

import pytest

from iamai.restart_resilience import (
    resilience,
    resilience_report,
    score_continuity,
    score_gap,
    score_recovery_speed,
    score_stroke_loss,
)


# ---------------------------------------------------------------------------
# score_gap
# ---------------------------------------------------------------------------

class TestScoreGap:
    def test_zero_gap_is_perfect(self):
        assert score_gap(0) == 100.0

    def test_negative_gap_clamps_to_perfect(self):
        assert score_gap(-10) == 100.0

    def test_within_2x_cadence_is_perfect(self):
        assert score_gap(30, cadence=15) == 100.0

    def test_exactly_at_low_boundary(self):
        assert score_gap(30, cadence=15) == 100.0

    def test_midpoint(self):
        mid = (30 + 300) / 2  # 165
        s = score_gap(mid, cadence=15)
        assert 45 < s < 55

    def test_at_high_boundary(self):
        assert score_gap(300, cadence=15) == 0.0

    def test_beyond_high_boundary(self):
        assert score_gap(1000, cadence=15) == 0.0

    def test_custom_cadence(self):
        # cadence=60 → low=120, high=1200
        assert score_gap(120, cadence=60) == 100.0
        assert score_gap(1200, cadence=60) == 0.0

    def test_linear_decrease(self):
        scores = [score_gap(g, cadence=15) for g in [60, 120, 180, 240]]
        for a, b in zip(scores, scores[1:]):
            assert a > b  # monotonically decreasing


# ---------------------------------------------------------------------------
# score_stroke_loss
# ---------------------------------------------------------------------------

class TestScoreStrokeLoss:
    def test_zero_gap_is_perfect(self):
        assert score_stroke_loss(0, 0) == 100.0

    def test_all_expected_strokes_present(self):
        # gap=150s, cadence=15 → 10 expected, 10 actual
        assert score_stroke_loss(150, 10, cadence=15) == 100.0

    def test_more_than_expected(self):
        assert score_stroke_loss(150, 20, cadence=15) == 100.0

    def test_half_lost(self):
        # gap=150s → 10 expected, 5 actual → 50%
        s = score_stroke_loss(150, 5, cadence=15)
        assert s == 50.0

    def test_all_lost(self):
        s = score_stroke_loss(150, 0, cadence=15)
        assert s == 0.0

    def test_one_of_ten(self):
        s = score_stroke_loss(150, 1, cadence=15)
        assert s == 10.0

    def test_small_gap_one_expected(self):
        # gap=20s, cadence=15 → 1 expected, 0 actual → 0
        s = score_stroke_loss(20, 0, cadence=15)
        assert s == 0.0

    def test_small_gap_one_present(self):
        s = score_stroke_loss(20, 1, cadence=15)
        assert s == 100.0


# ---------------------------------------------------------------------------
# score_recovery_speed
# ---------------------------------------------------------------------------

class TestScoreRecoverySpeed:
    def test_instant_recovery(self):
        # first stroke at restart time → delay 0
        assert score_recovery_speed(1000, 1000, cadence=15) == 100.0

    def test_recovery_within_cadence(self):
        # delay = 10s < 15s cadence → 100
        assert score_recovery_speed(1000, 1010, cadence=15) == 100.0

    def test_recovery_at_cadence(self):
        assert score_recovery_speed(1000, 1015, cadence=15) == 100.0

    def test_recovery_midpoint(self):
        # delay = 5.5 * cadence = 82.5
        mid_ts = 1000 + (15 + 150) / 2  # midpoint
        s = score_recovery_speed(1000, mid_ts, cadence=15)
        assert 45 < s < 55

    def test_recovery_at_high_boundary(self):
        # delay = 10 * cadence = 150
        assert score_recovery_speed(1000, 1150, cadence=15) == 0.0

    def test_recovery_beyond_high(self):
        assert score_recovery_speed(1000, 2000, cadence=15) == 0.0

    def test_first_stroke_before_restart(self):
        # edge case: first_stroke_ts < restart_ts → clamped to 0 delay
        assert score_recovery_speed(1000, 990, cadence=15) == 100.0


# ---------------------------------------------------------------------------
# score_continuity
# ---------------------------------------------------------------------------

class TestScoreContinuity:
    def test_perfect_increment(self):
        assert score_continuity(100, 101) == 100.0

    def test_same_counter(self):
        assert score_continuity(100, 100) == 75.0

    def test_skip_one(self):
        # diff=2 → 50
        assert score_continuity(100, 102) == 50.0

    def test_skip_two(self):
        # diff=3 → 40
        assert score_continuity(100, 103) == 40.0

    def test_skip_many_clamps(self):
        # diff=10 → 50 - 80 = -30 → clamped to 0
        assert score_continuity(100, 110) == 0.0

    def test_counter_reset(self):
        # post < pre → 0
        assert score_continuity(100, 50) == 0.0

    def test_counter_zero_to_one(self):
        assert score_continuity(0, 1) == 100.0

    def test_large_skip(self):
        assert score_continuity(0, 100) == 0.0


# ---------------------------------------------------------------------------
# resilience (composite)
# ---------------------------------------------------------------------------

class TestResilience:
    def test_perfect_restart(self):
        """Everything ideal: tiny gap, counter +1, fast recovery."""
        r = resilience(
            last_stroke_ts=1000.0,
            first_stroke_ts=1020.0,  # 20s gap (within 2× cadence)
            restart_ts=1015.0,
            cadence=15,
            pre_counter=399,
            post_counter=400,
            actual_strokes_in_gap=1,
        )
        assert r["grade"] == "seamless"
        assert r["score"] >= 85

    def test_typical_restart(self):
        """Realistic: ~60s gap, counter OK, no strokes during gap."""
        r = resilience(
            last_stroke_ts=1000.0,
            first_stroke_ts=1060.0,
            restart_ts=1030.0,
            cadence=15,
            pre_counter=399,
            post_counter=400,
            actual_strokes_in_gap=0,
        )
        # gap=60s: score_gap should be ~89 (60 is between 30 and 300)
        # loss: 4 expected, 0 actual → 0
        # speed: delay=30s → ~78
        # continuity: +1 → 100
        assert r["grade"] in ("clean", "scarred")

    def test_disastrous_restart(self):
        """Long gap, counter reset, no strokes."""
        r = resilience(
            last_stroke_ts=1000.0,
            first_stroke_ts=1600.0,  # 600s gap
            restart_ts=1300.0,
            cadence=15,
            pre_counter=399,
            post_counter=200,  # counter reset!
            actual_strokes_in_gap=0,
        )
        assert r["grade"] == "lossy"
        assert r["score"] < 40
        assert r["dimensions"]["continuity"] == 0.0

    def test_gap_seconds_computed(self):
        r = resilience(
            last_stroke_ts=1000.0,
            first_stroke_ts=1050.0,
            restart_ts=1020.0,
        )
        assert r["gap_seconds"] == 50.0

    def test_expected_strokes_computed(self):
        r = resilience(
            last_stroke_ts=1000.0,
            first_stroke_ts=1300.0,
            restart_ts=1100.0,
            cadence=15,
        )
        # 300 / 15 = 20
        assert r["expected_strokes"] == 20

    def test_all_dimensions_present(self):
        r = resilience(
            last_stroke_ts=1000.0,
            first_stroke_ts=1050.0,
            restart_ts=1020.0,
        )
        dims = r["dimensions"]
        assert "gap" in dims
        assert "stroke_loss" in dims
        assert "recovery_speed" in dims
        assert "continuity" in dims


# ---------------------------------------------------------------------------
# resilience_report
# ---------------------------------------------------------------------------

class TestResilienceReport:
    def test_report_contains_grade(self):
        r = resilience(
            last_stroke_ts=1000.0,
            first_stroke_ts=1020.0,
            restart_ts=1015.0,
            pre_counter=99,
            post_counter=100,
        )
        report = resilience_report(r)
        assert r["grade"] in report

    def test_report_contains_score(self):
        r = resilience(
            last_stroke_ts=1000.0,
            first_stroke_ts=1050.0,
            restart_ts=1020.0,
        )
        report = resilience_report(r)
        assert str(r["score"]) in report

    def test_report_contains_gap_seconds(self):
        r = resilience(
            last_stroke_ts=1000.0,
            first_stroke_ts=1050.0,
            restart_ts=1020.0,
        )
        report = resilience_report(r)
        assert "50.0s" in report

    def test_report_is_single_line(self):
        r = resilience(
            last_stroke_ts=1000.0,
            first_stroke_ts=1100.0,
            restart_ts=1050.0,
        )
        report = resilience_report(r)
        assert "\n" not in report
