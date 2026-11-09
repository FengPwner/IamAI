"""tests for snippets/cadence_drift_compensator.py — visit 587.

covers:
  - DriftReport dataclass (is_drifting, drift_direction, repr)
  - recording (single, batch, window eviction, total_recorded)
  - analysis (nominal, mild, moderate, severe drift)
  - compensation factor (proportional correction, clamping)
  - adjusted_interval (with and without prior reports)
  - history and summary
  - edge cases (insufficient data, identical timestamps, negative intervals)
  - reset
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from snippets.cadence_drift_compensator import (
    CadenceDriftCompensator,
    DriftReport,
    _classify,
)


# ---------------------------------------------------------------------------
# DriftReport dataclass
# ---------------------------------------------------------------------------


class TestDriftReport:
    def test_is_drifting_nominal(self):
        r = DriftReport(
            target_interval=15.0, actual_interval=15.1,
            drift_pct=0.7, severity="nominal",
            compensation_factor=1.0, samples=10,
        )
        assert not r.is_drifting

    def test_is_drifting_mild(self):
        r = DriftReport(
            target_interval=15.0, actual_interval=16.0,
            drift_pct=6.7, severity="mild",
            compensation_factor=0.99, samples=10,
        )
        assert r.is_drifting

    def test_drift_direction_slow(self):
        r = DriftReport(
            target_interval=15.0, actual_interval=16.0,
            drift_pct=6.7, severity="mild",
            compensation_factor=0.99, samples=10,
        )
        assert r.drift_direction == "slow"

    def test_drift_direction_fast(self):
        r = DriftReport(
            target_interval=15.0, actual_interval=14.0,
            drift_pct=-6.7, severity="mild",
            compensation_factor=1.01, samples=10,
        )
        assert r.drift_direction == "fast"

    def test_drift_direction_stable(self):
        r = DriftReport(
            target_interval=15.0, actual_interval=15.05,
            drift_pct=0.3, severity="nominal",
            compensation_factor=1.0, samples=10,
        )
        assert r.drift_direction == "stable"

    def test_repr(self):
        r = DriftReport(
            target_interval=15.0, actual_interval=16.0,
            drift_pct=6.7, severity="mild",
            compensation_factor=0.993, samples=10,
        )
        s = repr(r)
        assert "target=15.0s" in s
        assert "actual=16.0s" in s
        assert "mild" in s

    def test_frozen(self):
        r = DriftReport(
            target_interval=15.0, actual_interval=15.0,
            drift_pct=0.0, severity="nominal",
            compensation_factor=1.0, samples=5,
        )
        with pytest.raises(AttributeError):
            r.severity = "severe"


# ---------------------------------------------------------------------------
# severity classification
# ---------------------------------------------------------------------------


class TestClassify:
    def test_nominal(self):
        assert _classify(3.0) == "nominal"
        assert _classify(-3.0) == "nominal"
        assert _classify(5.0) == "nominal"

    def test_mild(self):
        assert _classify(6.0) == "mild"
        assert _classify(15.0) == "mild"
        assert _classify(-10.0) == "mild"

    def test_moderate(self):
        assert _classify(16.0) == "moderate"
        assert _classify(30.0) == "moderate"
        assert _classify(-20.0) == "moderate"

    def test_severe(self):
        assert _classify(31.0) == "severe"
        assert _classify(-50.0) == "severe"
        assert _classify(100.0) == "severe"


# ---------------------------------------------------------------------------
# recording
# ---------------------------------------------------------------------------


class TestRecording:
    def test_single_record(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        c.record(0.0)
        assert c.sample_count == 1
        assert c.total_recorded == 1

    def test_multiple_records(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        for ts in [0.0, 15.0, 30.0]:
            c.record(ts)
        assert c.sample_count == 3
        assert c.total_recorded == 3

    def test_window_eviction(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=5)
        for i in range(10):
            c.record(float(i * 15))
        assert c.sample_count == 5
        assert c.total_recorded == 10

    def test_record_now_uses_clock(self):
        fake_time = [1000.0]
        c = CadenceDriftCompensator(
            target_interval=15.0, window=10, clock=lambda: fake_time[0]
        )
        c.record_now()
        assert c.sample_count == 1

    def test_record_returns_total(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=5)
        assert c.record(0.0) == 1
        assert c.record(15.0) == 2
        # after window eviction, total keeps counting
        for i in range(5):
            assert c.record(float((i + 2) * 15)) == i + 3


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_target_interval(self):
        with pytest.raises(ValueError, match="target_interval must be positive"):
            CadenceDriftCompensator(target_interval=0.0)

    def test_negative_target_interval(self):
        with pytest.raises(ValueError, match="target_interval must be positive"):
            CadenceDriftCompensator(target_interval=-5.0)

    def test_invalid_window(self):
        with pytest.raises(ValueError, match="window must be >= 2"):
            CadenceDriftCompensator(target_interval=15.0, window=1)

    def test_invalid_horizon_samples(self):
        with pytest.raises(ValueError, match="horizon_samples must be >= 1"):
            CadenceDriftCompensator(target_interval=15.0, horizon_samples=0)


# ---------------------------------------------------------------------------
# analysis — nominal cadence
# ---------------------------------------------------------------------------


class TestNominalCadence:
    def test_perfect_cadence(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        for i in range(10):
            c.record(float(i * 15))
        r = c.report()
        assert r.severity == "nominal"
        assert r.actual_interval == 15.0
        assert abs(r.drift_pct) < 0.1
        assert abs(r.compensation_factor - 1.0) < 0.001

    def test_near_perfect_cadence(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        # 14.8s average — within 5% tolerance
        for i in range(10):
            c.record(float(i) * 14.8)
        r = c.report()
        assert r.severity == "nominal"
        assert r.drift_direction == "fast"

    def test_insufficient_data(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        c.record(0.0)
        r = c.report()
        assert r.severity == "nominal"
        assert r.actual_interval == 0.0
        assert "insufficient data" in r.detail


# ---------------------------------------------------------------------------
# analysis — drifting cadence
# ---------------------------------------------------------------------------


class TestDriftingCadence:
    def test_mild_slow_drift(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        # ~16s average = ~6.7% drift
        for i in range(10):
            c.record(float(i) * 16.0)
        r = c.report()
        assert r.severity == "mild"
        assert r.drift_direction == "slow"
        assert r.compensation_factor < 1.0  # compensate by going faster

    def test_mild_fast_drift(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        # ~14s average = ~-6.7% drift
        for i in range(10):
            c.record(float(i) * 14.0)
        r = c.report()
        assert r.severity == "mild"
        assert r.drift_direction == "fast"
        assert r.compensation_factor > 1.0  # compensate by going slower

    def test_moderate_drift(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        # ~18s average = ~20% drift
        for i in range(10):
            c.record(float(i) * 18.0)
        r = c.report()
        assert r.severity == "moderate"
        assert r.drift_pct > 15.0

    def test_severe_drift(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        # ~25s average = ~66.7% drift
        for i in range(10):
            c.record(float(i) * 25.0)
        r = c.report()
        assert r.severity == "severe"
        assert r.drift_pct > 30.0


# ---------------------------------------------------------------------------
# compensation factor
# ---------------------------------------------------------------------------


class TestCompensationFactor:
    def test_no_drift_no_compensation(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        for i in range(10):
            c.record(float(i * 15))
        r = c.report()
        assert abs(r.compensation_factor - 1.0) < 0.001

    def test_compensation_proportional(self):
        """larger drift → larger compensation."""
        c_small = CadenceDriftCompensator(target_interval=15.0, window=10)
        c_large = CadenceDriftCompensator(target_interval=15.0, window=10)
        for i in range(10):
            c_small.record(float(i) * 16.0)  # ~6.7% drift
            c_large.record(float(i) * 20.0)  # ~33% drift
        r_small = c_small.report()
        r_large = c_large.report()
        # large drift should have stronger correction
        assert r_large.compensation_factor < r_small.compensation_factor

    def test_compensation_clamped_low(self):
        """compensation never goes below 50% of target."""
        c = CadenceDriftCompensator(target_interval=15.0, window=5, horizon_samples=2)
        # extreme: 100s intervals vs 15s target
        for i in range(5):
            c.record(float(i) * 100.0)
        r = c.report()
        # factor should be clamped at 0.5 minimum
        assert r.compensation_factor >= 0.5

    def test_compensation_clamped_high(self):
        """compensation never goes above 200% of target."""
        c = CadenceDriftCompensator(target_interval=15.0, window=5, horizon_samples=2)
        # extreme: 1s intervals vs 15s target (way too fast)
        for i in range(5):
            c.record(float(i) * 1.0)
        r = c.report()
        # factor should be clamped at 2.0 maximum
        assert r.compensation_factor <= 2.0


# ---------------------------------------------------------------------------
# adjusted_interval
# ---------------------------------------------------------------------------


class TestAdjustedInterval:
    def test_no_report_returns_target(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        assert c.adjusted_interval() == 15.0

    def test_adjusted_after_report(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        for i in range(10):
            c.record(float(i) * 16.0)
        c.report()
        adj = c.adjusted_interval()
        assert adj < 15.0  # compensate by going faster

    def test_adjusted_reflects_latest_report(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=5)
        # first window: slow
        for i in range(5):
            c.record(float(i) * 18.0)
        c.report()
        first_adj = c.adjusted_interval()
        # second window: nominal
        c._timestamps.clear()
        for i in range(5):
            c.record(float(i) * 15.0)
        c.report()
        second_adj = c.adjusted_interval()
        # second adjustment should be closer to target
        assert abs(second_adj - 15.0) < abs(first_adj - 15.0)


# ---------------------------------------------------------------------------
# history and summary
# ---------------------------------------------------------------------------


class TestHistoryAndSummary:
    def test_empty_summary(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        s = c.summary()
        assert s["total_reports"] == 0
        assert s["nominal_count"] == 0

    def test_history_grows(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=5)
        for i in range(5):
            c.record(float(i) * 15.0)
        c.report()
        assert len(c.history) == 1
        # second batch
        c._timestamps.clear()
        for i in range(5):
            c.record(float(i) * 20.0)
        c.report()
        assert len(c.history) == 2

    def test_summary_counts(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=5)
        # report 1: nominal
        for i in range(5):
            c.record(float(i) * 15.0)
        c.report()
        # report 2: drift
        c._timestamps.clear()
        for i in range(5):
            c.record(float(i) * 20.0)
        c.report()
        s = c.summary()
        assert s["total_reports"] == 2
        assert s["nominal_count"] == 1
        assert s["drift_count"] == 1

    def test_summary_max_drift(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=5)
        for i in range(5):
            c.record(float(i) * 16.0)
        c.report()
        c._timestamps.clear()
        for i in range(5):
            c.record(float(i) * 25.0)
        c.report()
        s = c.summary()
        assert s["max_drift_pct"] > 50.0


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_identical_timestamps(self):
        """all same timestamp → 0 interval → extreme fast drift."""
        c = CadenceDriftCompensator(target_interval=15.0, window=5)
        for _ in range(5):
            c.record(100.0)
        r = c.report()
        assert r.actual_interval == 0.0
        assert r.severity == "severe"

    def test_very_large_window(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=1000)
        for i in range(1000):
            c.record(float(i) * 15.0)
        r = c.report()
        assert r.severity == "nominal"
        assert r.samples == 1000

    def test_non_uniform_intervals(self):
        """mixed intervals average out."""
        c = CadenceDriftCompensator(target_interval=15.0, window=6)
        # intervals: 10, 20, 10, 20, 10 → average 14s, mild fast drift
        ts = [0.0, 10.0, 30.0, 40.0, 60.0, 70.0]
        for t in ts:
            c.record(t)
        r = c.report()
        assert r.actual_interval == pytest.approx(14.0)
        assert r.severity == "mild"
        assert r.drift_direction == "fast"

    def test_reset(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=10)
        for i in range(10):
            c.record(float(i) * 15.0)
        c.report()
        c.reset()
        assert c.sample_count == 0
        assert c.total_recorded == 0
        assert len(c.history) == 0
        assert c.adjusted_interval() == 15.0

    def test_window_exactly_two(self):
        c = CadenceDriftCompensator(target_interval=15.0, window=2)
        c.record(0.0)
        c.record(15.0)
        r = c.report()
        assert r.severity == "nominal"
        assert r.actual_interval == 15.0
