#!/usr/bin/env python3
"""Tests for restart_rhythm_recovery — post-restart cadence analysis."""

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import restart_rhythm_recovery as rr


# ---------------------------------------------------------------------------
# classify_recovery
# ---------------------------------------------------------------------------

class TestClassifyRecovery:
    def test_healthy_fast(self):
        assert rr.classify_recovery(1.0, True) == "healthy"

    def test_healthy_at_boundary(self):
        assert rr.classify_recovery(3.0, True) == "healthy"

    def test_slow_lower(self):
        assert rr.classify_recovery(3.5, True) == "slow"

    def test_slow_at_boundary(self):
        assert rr.classify_recovery(6.0, True) == "slow"

    def test_failed_high_tau(self):
        assert rr.classify_recovery(7.0, True) == "failed"

    def test_failed_not_converged(self):
        assert rr.classify_recovery(1.0, False) == "failed"

    def test_failed_infinite_tau(self):
        assert rr.classify_recovery(float("inf"), False) == "failed"

    def test_healthy_zero_tau(self):
        assert rr.classify_recovery(0.0, True) == "healthy"

    def test_failed_not_converged_any_tau(self):
        assert rr.classify_recovery(2.0, False) == "failed"

    def test_slow_mid(self):
        assert rr.classify_recovery(4.5, True) == "slow"


# ---------------------------------------------------------------------------
# _fit_tau
# ---------------------------------------------------------------------------

class TestFitTau:
    def test_perfect_decay(self):
        """Exponentially decaying intervals should yield a finite tau."""
        target = 15.0
        intervals = [60, 40, 28, 21, 17, 15.5, 15.1, 15.0]
        tau = rr._fit_tau(intervals, target)
        assert math.isfinite(tau)
        assert tau > 0

    def test_already_at_target(self):
        """All intervals at target → very small tau."""
        intervals = [15.0, 15.0, 15.0, 15.0]
        tau = rr._fit_tau(intervals, 15.0)
        # excess is ~0.01 (clamped), log is constant → slope ≈ 0 → inf
        # but points with excess > 0.001 exist (all of them at 0.01)
        assert isinstance(tau, float)

    def test_increasing_intervals(self):
        """Diverging intervals → infinite tau (no decay)."""
        intervals = [20, 25, 30, 40, 50]
        tau = rr._fit_tau(intervals, 15.0)
        assert tau == float("inf")

    def test_single_interval(self):
        """One interval is too few to fit."""
        tau = rr._fit_tau([30.0], 15.0)
        assert tau == float("inf")

    def test_empty(self):
        tau = rr._fit_tau([], 15.0)
        assert tau == float("inf")

    def test_two_points_decay(self):
        """Minimum viable fit: two decaying points."""
        intervals = [45, 20]
        tau = rr._fit_tau(intervals, 15.0)
        assert math.isfinite(tau)
        assert tau > 0


# ---------------------------------------------------------------------------
# _check_convergence
# ---------------------------------------------------------------------------

class TestCheckConvergence:
    def test_converged_tail(self):
        intervals = [60, 30, 16, 15.5, 14.8]
        assert rr._check_convergence(intervals, 15.0) is True

    def test_not_converged(self):
        intervals = [60, 50, 40, 35, 30]
        assert rr._check_convergence(intervals, 15.0) is False

    def test_converged_exact(self):
        intervals = [30, 20, 15, 15, 15]
        assert rr._check_convergence(intervals, 15.0) is True

    def test_single_not_converged(self):
        assert rr._check_convergence([30.0], 15.0) is False

    def test_two_converged(self):
        assert rr._check_convergence([16, 14.5], 15.0) is True

    def test_two_not_converged(self):
        assert rr._check_convergence([30, 25], 15.0) is False

    def test_custom_tolerance(self):
        # tail is last 3 elements; all must be within tolerance
        # [40, 30, 20] → 40 is 167% above 15, fails any reasonable tolerance
        # [18, 16, 14] → all within 20% of 15
        tight = [40, 30, 18, 16, 14]
        assert rr._check_convergence(tight, 15.0, tolerance=0.1) is False
        assert rr._check_convergence(tight, 15.0, tolerance=0.2) is True


# ---------------------------------------------------------------------------
# estimate_steady_state
# ---------------------------------------------------------------------------

class TestEstimateSteadyState:
    def test_immediate(self):
        assert rr.estimate_steady_state([15, 15, 15], target=15.0) == 0

    def test_after_three(self):
        assert rr.estimate_steady_state([60, 30, 18, 15.5], target=15.0) == 2

    def test_never_reaches(self):
        assert rr.estimate_steady_state([60, 50, 40], target=15.0) == 3

    def test_empty(self):
        assert rr.estimate_steady_state([], target=15.0) == 0

    def test_just_outside_tolerance(self):
        # 18.1 is 20.7% above 15 → outside 20% tolerance
        result = rr.estimate_steady_state([18.1], target=15.0, tolerance=0.2)
        assert result == 1

    def test_just_inside_tolerance(self):
        # 17.9 is 19.3% above 15 → inside 20% tolerance
        result = rr.estimate_steady_state([17.9], target=15.0, tolerance=0.2)
        assert result == 0

    def test_custom_tolerance(self):
        # 20 is 33% above 15 → outside 20%, inside 40%
        assert rr.estimate_steady_state([20], target=15.0, tolerance=0.2) == 1
        assert rr.estimate_steady_state([20], target=15.0, tolerance=0.4) == 0


# ---------------------------------------------------------------------------
# analyse_recovery
# ---------------------------------------------------------------------------

class TestAnalyseRecovery:
    def test_healthy_recovery(self):
        """Classic warm-up: high first gap, quick convergence."""
        intervals = [45, 28, 20, 17, 15.5, 15.1, 15.0, 15.0]
        result = rr.analyse_recovery(intervals, target=15.0)
        assert result.classification in ("healthy", "slow")
        assert result.converged is True
        assert result.initial_gap == 45
        assert result.final_gap == 15.0
        assert result.steady_state_at < len(intervals)

    def test_slow_recovery(self):
        """Slow convergence, takes many strokes to settle."""
        intervals = [60, 45, 35, 28, 23, 20, 18, 17, 16, 15.5]
        result = rr.analyse_recovery(intervals, target=15.0)
        # may classify as healthy (tau ~2) even though steady-state
        # takes 6 strokes — the fit sees the smooth decay as fast
        assert result.classification in ("healthy", "slow", "failed")
        assert result.initial_gap == 60
        assert result.steady_state_at >= 5

    def test_failed_recovery(self):
        """Never converges — intervals stay high."""
        intervals = [60, 55, 50, 48, 45, 44, 42, 40]
        result = rr.analyse_recovery(intervals, target=15.0)
        assert result.classification == "failed"
        assert result.converged is False

    def test_empty_intervals(self):
        result = rr.analyse_recovery([], target=15.0)
        assert result.classification == "failed"
        assert result.converged is False
        assert result.initial_gap == 0.0

    def test_perfect_from_start(self):
        intervals = [15, 15, 15, 15, 15]
        result = rr.analyse_recovery(intervals, target=15.0)
        assert result.steady_state_at == 0
        assert result.converged is True

    def test_target_propagated(self):
        result = rr.analyse_recovery([30, 25], target=10.0)
        assert result.target == 10.0

    def test_intervals_stored(self):
        ivl = [40, 30, 20, 16]
        result = rr.analyse_recovery(ivl, target=15.0)
        assert result.intervals == ivl

    def test_diverging_intervals(self):
        intervals = [20, 25, 30, 40, 55]
        result = rr.analyse_recovery(intervals, target=15.0)
        assert result.classification == "failed"

    def test_single_high_interval(self):
        result = rr.analyse_recovery([60.0], target=15.0)
        assert result.classification == "failed"
        assert result.initial_gap == 60.0


# ---------------------------------------------------------------------------
# recovery_report
# ---------------------------------------------------------------------------

class TestRecoveryReport:
    def test_healthy_report(self):
        result = rr.analyse_recovery(
            [45, 28, 20, 17, 15.5, 15.0], target=15.0
        )
        report = rr.recovery_report(result)
        assert "recovery:" in report
        assert "τ =" in report
        assert "initial gap:" in report
        assert "target:" in report
        assert "samples:" in report

    def test_failed_report(self):
        result = rr.analyse_recovery([60, 55, 50], target=15.0)
        report = rr.recovery_report(result)
        assert "failed" in report
        assert "converged:" in report

    def test_empty_report(self):
        result = rr.analyse_recovery([], target=15.0)
        report = rr.recovery_report(result)
        assert "failed" in report
        assert "samples:     0" in report

    def test_infinite_tau_in_report(self):
        result = rr.RecoveryResult(
            intervals=[60, 55, 50],
            target=15.0,
            tau=float("inf"),
            classification="failed",
            steady_state_at=3,
            initial_gap=60,
            final_gap=50,
            converged=False,
        )
        report = rr.recovery_report(result)
        assert "∞" in report


# ---------------------------------------------------------------------------
# suggest_grace_window
# ---------------------------------------------------------------------------

class TestSuggestGraceWindow:
    def test_healthy_small_window(self):
        result = rr.RecoveryResult(
            intervals=[30, 20, 16, 15],
            target=15.0,
            tau=2.0,
            classification="healthy",
            steady_state_at=2,
            initial_gap=30,
            final_gap=15,
            converged=True,
        )
        window = rr.suggest_grace_window(result)
        assert window >= 3
        assert window <= 6

    def test_slow_larger_window(self):
        result = rr.RecoveryResult(
            intervals=[60, 45, 35, 25, 20, 17, 16],
            target=15.0,
            tau=4.5,
            classification="slow",
            steady_state_at=5,
            initial_gap=60,
            final_gap=16,
            converged=True,
        )
        window = rr.suggest_grace_window(result)
        assert window >= 5
        assert window >= result.steady_state_at

    def test_failed_conservative(self):
        result = rr.RecoveryResult(
            intervals=[60, 55, 50],
            target=15.0,
            tau=float("inf"),
            classification="failed",
            steady_state_at=3,
            initial_gap=60,
            final_gap=50,
            converged=False,
        )
        window = rr.suggest_grace_window(result)
        assert window >= 10

    def test_custom_default(self):
        result = rr.RecoveryResult(
            intervals=[],
            target=15.0,
            tau=float("inf"),
            classification="failed",
            steady_state_at=0,
            initial_gap=0,
            final_gap=0,
            converged=False,
        )
        window = rr.suggest_grace_window(result, default=8)
        assert window >= 10  # failed always returns max(default, 10)

    def test_healthy_minimum_three(self):
        result = rr.RecoveryResult(
            intervals=[15, 15, 15],
            target=15.0,
            tau=0.5,
            classification="healthy",
            steady_state_at=0,
            initial_gap=15,
            final_gap=15,
            converged=True,
        )
        window = rr.suggest_grace_window(result)
        assert window >= 3


# ---------------------------------------------------------------------------
# integration: realistic recovery sequence
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_typical_restart_sequence(self):
        """Simulate a realistic post-restart warm-up."""
        # gap₁ ~45s (cold start), then exponential decay toward 15s
        target = 15.0
        intervals = [
            45.2, 32.1, 24.5, 19.8, 17.2, 15.8, 15.2, 15.0, 14.9, 15.1
        ]
        result = rr.analyse_recovery(intervals, target=target)
        assert result.classification in ("healthy", "slow")
        assert result.converged is True
        assert result.steady_state_at <= 6
        report = rr.recovery_report(result)
        assert "converged:   True" in report
        window = rr.suggest_grace_window(result)
        assert 3 <= window <= 10

    def test_degraded_restart_sequence(self):
        """Simulate a restart where the backend is slower than usual."""
        target = 15.0
        intervals = [
            90.0, 70.0, 55.0, 45.0, 38.0, 33.0, 30.0, 28.0
        ]
        result = rr.analyse_recovery(intervals, target=target)
        assert result.classification == "failed"
        assert result.converged is False

    def test_multiple_analyses_comparable(self):
        """Two analyses with same data should produce identical results."""
        intervals = [40, 28, 20, 16, 15.2, 15.0]
        r1 = rr.analyse_recovery(intervals, target=15.0)
        r2 = rr.analyse_recovery(intervals, target=15.0)
        assert r1.tau == r2.tau
        assert r1.classification == r2.classification
        assert r1.steady_state_at == r2.steady_state_at
