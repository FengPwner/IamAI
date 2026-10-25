"""Tests for iamai.gap_budget — cumulative timing drift tracker."""

from __future__ import annotations

import time

import pytest

from iamai.gap_budget import GapBudget


# ------------------------------------------------------------------
# Construction
# ------------------------------------------------------------------


class TestConstruction:
    """GapBudget instantiation and validation."""

    def test_default_cadence(self):
        gb = GapBudget()
        assert gb.cadence_s == 15.0

    def test_custom_cadence(self):
        gb = GapBudget(cadence_s=30)
        assert gb.cadence_s == 30.0

    def test_zero_cadence_rejected(self):
        with pytest.raises(ValueError, match="cadence_s must be > 0"):
            GapBudget(cadence_s=0)

    def test_negative_cadence_rejected(self):
        with pytest.raises(ValueError, match="cadence_s must be > 0"):
            GapBudget(cadence_s=-5)

    def test_default_thresholds(self):
        gb = GapBudget()
        assert gb.deficit_warn == 300.0
        assert gb.deficit_crit == 900.0

    def test_custom_thresholds(self):
        gb = GapBudget(deficit_warn=100, deficit_crit=500)
        assert gb.deficit_warn == 100.0
        assert gb.deficit_crit == 500.0

    def test_warn_must_be_positive(self):
        with pytest.raises(ValueError, match="deficit_warn must be > 0"):
            GapBudget(deficit_warn=0)

    def test_crit_must_exceed_warn(self):
        with pytest.raises(ValueError, match="deficit_crit.*must exceed"):
            GapBudget(deficit_warn=500, deficit_crit=100)

    def test_initial_state_empty(self):
        gb = GapBudget()
        assert gb.total_deficit == 0.0
        assert gb.total_surplus == 0.0
        assert gb.net_drift == 0.0
        assert gb.worst_gap == 0.0
        assert gb._count == 0


# ------------------------------------------------------------------
# Recording
# ------------------------------------------------------------------


class TestRecording:
    """Gap recording mechanics."""

    def test_record_single_deficit(self):
        gb = GapBudget(cadence_s=15)
        gb.record(20)  # 5 s excess
        assert gb.total_deficit == 5.0
        assert gb.total_surplus == 0.0

    def test_record_single_surplus(self):
        gb = GapBudget(cadence_s=15)
        gb.record(10)  # 5 s short
        assert gb.total_deficit == 0.0
        assert gb.total_surplus == 5.0

    def test_record_exact_cadence(self):
        gb = GapBudget(cadence_s=15)
        gb.record(15)  # exact → 0 excess (classified as zero-magnitude deficit)
        assert gb.total_deficit == 0.0
        assert gb.total_surplus == 0.0
        assert gb.deficit_count == 1  # zero-magnitude deficit still counted
        assert gb._count == 1

    def test_record_zero_gap(self):
        gb = GapBudget(cadence_s=15)
        gb.record(0)  # 15 s surplus
        assert gb.total_surplus == 15.0

    def test_record_negative_rejected(self):
        gb = GapBudget()
        with pytest.raises(ValueError, match="gap_s must be >= 0"):
            gb.record(-1)

    def test_record_many(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([20, 10, 30, 5])
        # deficits: 5 + 15 = 20; surpluses: 5 + 10 = 15
        assert gb.total_deficit == 20.0
        assert gb.total_surplus == 15.0
        assert gb._count == 4

    def test_count_increments(self):
        gb = GapBudget()
        gb.record(15)
        gb.record(16)
        gb.record(14)
        assert gb._count == 3

    def test_deficit_count(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([20, 10, 30, 14, 5])
        # deficits at: 20 (5 excess), 30 (15 excess) → 2 deficits
        # 14 and 10 and 5 are surpluses; exact cadence (15) counts as deficit
        assert gb.deficit_count == 2

    def test_surplus_count(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([20, 10, 30, 14, 5])
        # surpluses at: 10 (5 short), 14 (1 short), 5 (10 short) → 3 surpluses
        assert gb.surplus_count == 3


# ------------------------------------------------------------------
# Net drift
# ------------------------------------------------------------------


class TestNetDrift:
    """Cumulative drift calculations."""

    def test_net_drift_positive(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([30, 10])
        # deficit 15, surplus 5 → net 10
        assert gb.net_drift == 10.0

    def test_net_drift_negative(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([16, 5])
        # deficit 1, surplus 10 → net -9
        assert gb.net_drift == -9.0

    def test_net_drift_zero_balanced(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([20, 10])
        # deficit 5, surplus 5 → net 0
        assert gb.net_drift == 0.0

    def test_net_drift_accumulates(self):
        gb = GapBudget(cadence_s=15)
        for _ in range(10):
            gb.record(25)  # 10 s deficit each
        assert gb.net_drift == 100.0


# ------------------------------------------------------------------
# Worst gap
# ------------------------------------------------------------------


class TestWorstGap:
    """Worst single deficit tracking."""

    def test_worst_single(self):
        gb = GapBudget(cadence_s=15)
        gb.record(100)
        assert gb.worst_gap == 85.0

    def test_worst_among_many(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([20, 300, 50, 16])
        assert gb.worst_gap == 285.0

    def test_worst_no_deficits(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([10, 12, 14])
        assert gb.worst_gap == 0.0

    def test_worst_only_surpluses(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([1, 2, 3])
        assert gb.worst_gap == 0.0


# ------------------------------------------------------------------
# Mean metrics
# ------------------------------------------------------------------


class TestMeanMetrics:
    """Average deficit and surplus calculations."""

    def test_mean_deficit(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([25, 35])  # deficits: 10, 20
        assert gb.mean_deficit == 15.0

    def test_mean_deficit_no_deficits(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([10, 5])
        assert gb.mean_deficit == 0.0

    def test_mean_surplus(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([10, 5])  # surpluses: 5, 10
        assert gb.mean_surplus == 7.5

    def test_mean_surplus_no_surpluses(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([20, 30])
        assert gb.mean_surplus == 0.0


# ------------------------------------------------------------------
# Drift rate
# ------------------------------------------------------------------


class TestDriftRate:
    """Drift rate (seconds drift per second elapsed)."""

    def test_drift_rate_no_data(self):
        gb = GapBudget()
        assert gb.drift_rate == 0.0

    def test_drift_rate_single_observation(self):
        gb = GapBudget()
        gb.record(20)
        # Only one observation → no elapsed time → 0
        assert gb.drift_rate == 0.0

    def test_drift_rate_positive(self):
        gb = GapBudget(cadence_s=15)
        gb.record(100)  # big deficit
        time.sleep(1.1)  # ensure elapsed > 1s for drift_rate calculation
        gb.record(100)  # another big deficit
        # drift_rate should be positive (170s deficit over ~1.1s)
        assert gb.drift_rate > 0

    def test_drift_rate_window_too_short(self):
        """If elapsed < 1s, drift_rate returns 0."""
        gb = GapBudget(cadence_s=15)
        # Two records nearly instant
        gb.record(100)
        gb.record(100)
        # elapsed likely < 1s → 0.0
        elapsed = gb._last_recorded - gb._first_recorded
        if elapsed < 1.0:
            assert gb.drift_rate == 0.0


# ------------------------------------------------------------------
# Health classification
# ------------------------------------------------------------------


class TestHealth:
    """Health tier classification."""

    def test_healthy_initial(self):
        gb = GapBudget()
        assert gb.health() == "healthy"

    def test_healthy_small_drift(self):
        gb = GapBudget(cadence_s=15, deficit_warn=300, deficit_crit=900)
        gb.record_many([20, 10])  # net 0
        assert gb.health() == "healthy"

    def test_strained(self):
        gb = GapBudget(cadence_s=15, deficit_warn=100, deficit_crit=500)
        # Create net drift of 200
        gb.record(215)  # deficit 200
        assert gb.health() == "strained"

    def test_exhausted(self):
        gb = GapBudget(cadence_s=15, deficit_warn=100, deficit_crit=500)
        gb.record(515)  # deficit 500
        assert gb.health() == "exhausted"

    def test_healthy_uses_abs_drift(self):
        """Negative drift (writer running fast) is also checked."""
        gb = GapBudget(cadence_s=15, deficit_warn=100, deficit_crit=500)
        # net_drift = -300 (massive surplus)
        gb.record(0)  # surplus 15
        gb.record(0)  # surplus 15
        # ... need more
        for _ in range(18):
            gb.record(0)  # 15 s surplus each → total 300 surplus
        # net_drift = -300 → abs = 300 > 100 → strained
        assert gb.health() == "strained"

    def test_custom_thresholds(self):
        gb = GapBudget(cadence_s=15, deficit_warn=10, deficit_crit=50)
        gb.record(30)  # deficit 15
        assert gb.health() == "strained"
        gb.record(65)  # deficit 50 → total 65
        assert gb.health() == "exhausted"


# ------------------------------------------------------------------
# Summarize
# ------------------------------------------------------------------


class TestSummarize:
    """summarize() output structure and values."""

    def test_summarize_keys(self):
        gb = GapBudget()
        s = gb.summarize()
        expected_keys = {
            "count", "cadence_s", "total_deficit", "total_surplus",
            "net_drift", "worst_gap", "mean_deficit", "mean_surplus",
            "drift_rate", "deficit_count", "surplus_count", "health",
        }
        assert set(s.keys()) == expected_keys

    def test_summarize_values(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([20, 10])
        s = gb.summarize()
        assert s["count"] == 2
        assert s["cadence_s"] == 15.0
        assert s["total_deficit"] == 5.0
        assert s["total_surplus"] == 5.0
        assert s["net_drift"] == 0.0
        assert s["worst_gap"] == 5.0
        assert s["deficit_count"] == 1
        assert s["surplus_count"] == 1
        assert s["health"] == "healthy"

    def test_summarize_empty(self):
        gb = GapBudget()
        s = gb.summarize()
        assert s["count"] == 0
        assert s["total_deficit"] == 0.0
        assert s["health"] == "healthy"


# ------------------------------------------------------------------
# Report line
# ------------------------------------------------------------------


class TestReportLine:
    """Human-readable report_line output."""

    def test_report_line_format(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([20, 10, 100])
        line = gb.report_line()
        assert "gap_budget:" in line
        assert "net_drift" in line
        assert "deficit" in line
        assert "surplus" in line
        assert "worst" in line
        assert "rate" in line

    def test_report_line_healthy(self):
        gb = GapBudget(cadence_s=15)
        gb.record(16)
        line = gb.report_line()
        assert "healthy" in line

    def test_report_line_exhausted(self):
        gb = GapBudget(cadence_s=15, deficit_warn=10, deficit_crit=50)
        gb.record(200)
        line = gb.report_line()
        assert "exhausted" in line


# ------------------------------------------------------------------
# Reset
# ------------------------------------------------------------------


class TestReset:
    """Reset functionality."""

    def test_reset_clears_all(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([20, 10, 100, 5])
        assert gb._count > 0
        gb.reset()
        assert gb._count == 0
        assert gb.total_deficit == 0.0
        assert gb.total_surplus == 0.0
        assert gb.net_drift == 0.0
        assert gb.worst_gap == 0.0
        assert gb._first_recorded is None
        assert gb._last_recorded is None
        assert gb.health() == "healthy"

    def test_reset_then_record(self):
        gb = GapBudget(cadence_s=15)
        gb.record_many([100, 200])
        gb.reset()
        gb.record(20)
        assert gb._count == 1
        assert gb.total_deficit == 5.0
        assert gb.total_surplus == 0.0


# ------------------------------------------------------------------
# Integration: realistic stroke stream
# ------------------------------------------------------------------


class TestIntegration:
    """End-to-end scenarios mimicking real writer behaviour."""

    def test_healthy_stream(self):
        """A well-behaved writer with minor jitter stays healthy."""
        gb = GapBudget(cadence_s=15)
        # Simulate 20 strokes at ~15s ± 2s
        import random
        rng = random.Random(42)
        for _ in range(20):
            gap = 15 + rng.uniform(-2, 2)
            gb.record(gap)
        assert gb.health() == "healthy"
        assert gb.worst_gap < 5.0

    def test_stall_then_recover(self):
        """Writer stalls once (gap=1500s) then resumes normal cadence."""
        gb = GapBudget(cadence_s=15, deficit_warn=300, deficit_crit=900)
        # 10 normal strokes (slightly under cadence → surpluses)
        for _ in range(10):
            gb.record(14)
        # One massive stall
        gb.record(1500)
        # Recovery — 10 more normal strokes
        for _ in range(10):
            gb.record(14)
        # deficit from stall: 1485; surplus from 20 normal: 20 × 1 = 20
        # net_drift = 1485 - 20 = 1465 → exhausted
        assert gb.health() == "exhausted"
        assert gb.worst_gap == 1485.0
        assert gb.deficit_count == 1  # only the stall was a deficit

    def test_frequent_micro_stalls(self):
        """Many small stalls accumulate into strained budget."""
        gb = GapBudget(cadence_s=15, deficit_warn=100, deficit_crit=500)
        # 50 strokes each 5s over cadence = 250s total deficit
        for _ in range(50):
            gb.record(20)
        assert gb.total_deficit == 250.0
        assert gb.health() == "strained"

    def test_compensated_drift(self):
        """Deficits and surpluses roughly cancel → healthy."""
        gb = GapBudget(cadence_s=15)
        for _ in range(10):
            gb.record(25)  # +10 deficit
        for _ in range(10):
            gb.record(5)   # +10 surplus
        assert abs(gb.net_drift) < 0.01

    def test_report_after_many(self):
        """Summarize and report_line work after extended use."""
        gb = GapBudget(cadence_s=15)
        import random
        rng = random.Random(123)
        for _ in range(100):
            gb.record(max(0, 15 + rng.gauss(0, 5)))
        s = gb.summarize()
        assert s["count"] == 100
        assert s["health"] in ("healthy", "strained", "exhausted")
        line = gb.report_line()
        assert "gap_budget:" in line
