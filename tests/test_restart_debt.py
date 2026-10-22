"""Tests for iamai.restart_debt — accumulated cost of process restarts."""

from __future__ import annotations

import pytest

from iamai.restart_debt import (
    DEFAULT_RESTART_COST,
    DebtReport,
    RestartDebt,
    _classify_severity,
)


# ---------------------------------------------------------------------------
# _classify_severity
# ---------------------------------------------------------------------------

class TestClassifySeverity:
    def test_clean_zero(self):
        assert _classify_severity(0) == "clean"

    def test_clean_below_threshold(self):
        assert _classify_severity(299) == "clean"

    def test_low_at_boundary(self):
        assert _classify_severity(300) == "low"

    def test_low_mid_range(self):
        assert _classify_severity(500) == "low"

    def test_moderate_at_boundary(self):
        assert _classify_severity(900) == "moderate"

    def test_moderate_mid_range(self):
        assert _classify_severity(1200) == "moderate"

    def test_high_at_boundary(self):
        assert _classify_severity(1800) == "high"

    def test_high_mid_range(self):
        assert _classify_severity(2500) == "high"

    def test_critical_at_boundary(self):
        assert _classify_severity(3600) == "critical"

    def test_critical_far_above(self):
        assert _classify_severity(10000) == "critical"


# ---------------------------------------------------------------------------
# RestartDebt — initial state
# ---------------------------------------------------------------------------

class TestInitialState:
    def test_no_events_debt_zero(self):
        tracker = RestartDebt()
        assert tracker.debt_score(now_s=1000) == 0.0

    def test_no_events_severity_clean(self):
        tracker = RestartDebt()
        assert tracker.severity(now_s=1000) == "clean"

    def test_no_events_paydown_zero(self):
        tracker = RestartDebt()
        assert tracker.paydown_eta(now_s=1000) == 0.0

    def test_no_events_restart_count_zero(self):
        tracker = RestartDebt()
        assert tracker.restart_count() == 0

    def test_no_events_trend_stable(self):
        tracker = RestartDebt()
        assert tracker.trend(now_s=1000) == "stable"


# ---------------------------------------------------------------------------
# RestartDebt — single restart
# ---------------------------------------------------------------------------

class TestSingleRestart:
    def test_debt_equals_cost_at_restart_time(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        # at restart time, uptime = 0, debt = cost
        assert tracker.debt_score(now_s=1000) == DEFAULT_RESTART_COST

    def test_debt_decays_with_uptime(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        # after 100s uptime, debt = cost - 100
        debt = tracker.debt_score(now_s=1100)
        assert debt == DEFAULT_RESTART_COST - 100

    def test_debt_fully_paid_after_cost_seconds(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        # after cost seconds of uptime, debt = 0
        debt = tracker.debt_score(now_s=1000 + DEFAULT_RESTART_COST)
        assert debt == 0.0

    def test_debt_clamped_to_zero(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        # way past cost, still zero
        debt = tracker.debt_score(now_s=1000 + DEFAULT_RESTART_COST * 10)
        assert debt == 0.0

    def test_restart_count_one(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        assert tracker.restart_count() == 1


# ---------------------------------------------------------------------------
# RestartDebt — multiple restarts
# ---------------------------------------------------------------------------

class TestMultipleRestarts:
    def test_debt_accumulates(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        tracker.record_restart(now_s=1100)
        # gross = 2 * cost, uptime from last restart = 0
        debt = tracker.debt_score(now_s=1100)
        assert debt == 2 * DEFAULT_RESTART_COST

    def test_debt_decay_from_last_restart(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        tracker.record_restart(now_s=1100)
        # uptime from 1100, 50s passed
        debt = tracker.debt_score(now_s=1150)
        assert debt == 2 * DEFAULT_RESTART_COST - 50

    def test_three_restarts(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        tracker.record_restart(now_s=1100)
        tracker.record_restart(now_s=1200)
        debt = tracker.debt_score(now_s=1200)
        assert debt == 3 * DEFAULT_RESTART_COST

    def test_restart_count_three(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        tracker.record_restart(now_s=1100)
        tracker.record_restart(now_s=1200)
        assert tracker.restart_count() == 3


# ---------------------------------------------------------------------------
# RestartDebt — severity classification
# ---------------------------------------------------------------------------

class TestSeverityClassification:
    def test_fresh_restart_is_high_or_above(self):
        tracker = RestartDebt(restart_cost_s=2000)
        tracker.record_restart(now_s=1000)
        # debt = 2000, which is "high"
        assert tracker.severity(now_s=1000) == "high"

    def test_after_uptime_severity_drops(self):
        tracker = RestartDebt(restart_cost_s=2000)
        tracker.record_restart(now_s=1000)
        # after 1500s uptime, debt = 500 → "low"
        assert tracker.severity(now_s=2500) == "low"

    def test_fully_paid_is_clean(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        assert tracker.severity(now_s=1000 + DEFAULT_RESTART_COST + 1) == "clean"


# ---------------------------------------------------------------------------
# RestartDebt — paydown ETA
# ---------------------------------------------------------------------------

class TestPaydownEta:
    def test_no_restarts_eta_zero(self):
        tracker = RestartDebt()
        assert tracker.paydown_eta(now_s=1000) == 0.0

    def test_no_uptime_eta_none(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        # now_s = restart time → uptime = 0
        assert tracker.paydown_eta(now_s=1000) is None

    def test_with_uptime_eta_equals_debt(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        tracker.record_restart(now_s=1100)
        # 2 restarts, uptime from 1100 = 50s
        eta = tracker.paydown_eta(now_s=1150)
        debt = tracker.debt_score(now_s=1150)
        assert eta == debt

    def test_fully_paid_eta_zero(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        assert tracker.paydown_eta(now_s=1000 + DEFAULT_RESTART_COST + 100) == 0.0


# ---------------------------------------------------------------------------
# RestartDebt — custom restart cost
# ---------------------------------------------------------------------------

class TestCustomCost:
    def test_custom_cost(self):
        tracker = RestartDebt(restart_cost_s=100)
        tracker.record_restart(now_s=1000)
        assert tracker.debt_score(now_s=1000) == 100

    def test_custom_cost_decay(self):
        tracker = RestartDebt(restart_cost_s=100)
        tracker.record_restart(now_s=1000)
        assert tracker.debt_score(now_s=1050) == 50

    def test_zero_cost(self):
        tracker = RestartDebt(restart_cost_s=0)
        tracker.record_restart(now_s=1000)
        assert tracker.debt_score(now_s=1000) == 0.0

    def test_negative_cost_raises(self):
        with pytest.raises(ValueError):
            RestartDebt(restart_cost_s=-1)


# ---------------------------------------------------------------------------
# RestartDebt — buffer limits
# ---------------------------------------------------------------------------

class TestBufferLimits:
    def test_buffer_trims_oldest(self):
        tracker = RestartDebt(buffer_size=3)
        tracker.record_restart(now_s=100)
        tracker.record_restart(now_s=200)
        tracker.record_restart(now_s=300)
        tracker.record_restart(now_s=400)  # pushes out 100
        assert tracker.restart_count() == 3

    def test_buffer_size_one_raises(self):
        with pytest.raises(ValueError):
            RestartDebt(buffer_size=0)

    def test_small_buffer_works(self):
        tracker = RestartDebt(buffer_size=1, restart_cost_s=100)
        tracker.record_restart(now_s=100)
        tracker.record_restart(now_s=200)
        # only the latest event remains
        assert tracker.restart_count() == 1
        assert tracker.debt_score(now_s=200) == 100


# ---------------------------------------------------------------------------
# RestartDebt — trend analysis
# ---------------------------------------------------------------------------

class TestTrend:
    def test_no_events_stable(self):
        tracker = RestartDebt()
        assert tracker.trend(now_s=1000) == "stable"

    def test_increasing_restarts_accumulating(self):
        tracker = RestartDebt()
        # first half: 1 restart, second half: 3 restarts
        tracker.record_restart(now_s=500)   # in first half
        tracker.record_restart(now_s=800)   # in second half
        tracker.record_restart(now_s=900)   # in second half
        tracker.record_restart(now_s=950)   # in second half
        # lookback=1000, mid=500. events at 500 is in first half [0,500)
        # Actually: t_start = 0, mid = 500
        # first_half: [0, 500) → none (500 not < 500)
        # second_half: [500, 1000] → all 4
        assert tracker.trend(now_s=1000, lookback=1000) == "accumulating"

    def test_decreasing_restarts_paying_down(self):
        tracker = RestartDebt()
        # first half: 3 restarts, second half: 1 restart
        tracker.record_restart(now_s=100)
        tracker.record_restart(now_s=200)
        tracker.record_restart(now_s=300)
        tracker.record_restart(now_s=800)
        # lookback=1000, t_start=0, mid=500
        # first_half [0, 500): 100, 200, 300 → 3
        # second_half [500, 1000]: 800 → 1
        assert tracker.trend(now_s=1000, lookback=1000) == "paying_down"

    def test_equal_restarts_stable(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=250)   # first half
        tracker.record_restart(now_s=750)   # second half
        assert tracker.trend(now_s=1000, lookback=1000) == "stable"


# ---------------------------------------------------------------------------
# DebtReport — frozen dataclass
# ---------------------------------------------------------------------------

class TestDebtReport:
    def test_report_is_frozen(self):
        report = DebtReport(
            debt_s=100.0,
            severity="clean",
            restart_count=1,
            uptime_s=200.0,
            paydown_eta_s=100.0,
        )
        with pytest.raises(AttributeError):
            report.debt_s = 200.0  # type: ignore[misc]

    def test_summary_no_restarts(self):
        report = DebtReport(
            debt_s=0.0,
            severity="clean",
            restart_count=0,
            uptime_s=0.0,
            paydown_eta_s=0.0,
        )
        assert "no restarts" in report.summary()

    def test_summary_with_restarts(self):
        report = DebtReport(
            debt_s=500.0,
            severity="low",
            restart_count=2,
            uptime_s=100.0,
            paydown_eta_s=500.0,
        )
        s = report.summary()
        assert "500s" in s
        assert "low" in s
        assert "2 restart(s)" in s

    def test_summary_no_uptime(self):
        report = DebtReport(
            debt_s=300.0,
            severity="low",
            restart_count=1,
            uptime_s=0.0,
            paydown_eta_s=None,
        )
        assert "N/A" in report.summary()


# ---------------------------------------------------------------------------
# RestartDebt — snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_matches_individual_queries(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        tracker.record_restart(now_s=1100)
        snap = tracker.snapshot(now_s=1200)
        assert snap.debt_s == tracker.debt_score(now_s=1200)
        assert snap.severity == tracker.severity(now_s=1200)
        assert snap.paydown_eta_s == tracker.paydown_eta(now_s=1200)
        assert snap.restart_count == tracker.restart_count()

    def test_snapshot_summary(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        snap = tracker.snapshot(now_s=1100)
        s = snap.summary()
        assert "restart debt" in s


# ---------------------------------------------------------------------------
# RestartDebt — edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_now_before_restart(self):
        """Querying before any restart should give zero debt."""
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        assert tracker.debt_score(now_s=500) == 0.0

    def test_multiple_restarts_at_same_time(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        tracker.record_restart(now_s=1000)
        # two restarts at same time → debt = 2 * cost
        assert tracker.debt_score(now_s=1000) == 2 * DEFAULT_RESTART_COST

    def test_summary_method(self):
        tracker = RestartDebt()
        tracker.record_restart(now_s=1000)
        s = tracker.summary(now_s=1100)
        assert isinstance(s, str)
        assert len(s) > 0
