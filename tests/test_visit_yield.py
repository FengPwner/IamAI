"""Tests for iamai.visit_yield — productive fraction of caretaker visits."""

import math

import pytest

from iamai.visit_yield import (
    VisitYield,
    classify_yield,
    yield_detail,
    yield_report,
    yield_trend,
)


# ---------------------------------------------------------------------------
# VisitYield dataclass
# ---------------------------------------------------------------------------

class TestVisitYield:
    def test_basic_yield_ratio(self):
        v = VisitYield(total_actions=5, maintenance_actions=2)
        assert v.yield_ratio == 0.6
        assert v.productive_actions == 3
        assert v.verdict == "thriving"

    def test_zero_actions(self):
        v = VisitYield(total_actions=0, maintenance_actions=0)
        assert v.yield_ratio == 0.0
        assert v.verdict == "firefighting"

    def test_pure_maintenance(self):
        v = VisitYield(total_actions=4, maintenance_actions=4)
        assert v.yield_ratio == 0.0
        assert v.productive_actions == 0
        assert v.verdict == "firefighting"

    def test_pure_productive(self):
        v = VisitYield(total_actions=3, maintenance_actions=0)
        assert v.yield_ratio == 1.0
        assert v.verdict == "thriving"

    def test_maintenance_clamped_to_total(self):
        v = VisitYield(total_actions=3, maintenance_actions=10)
        assert v.maintenance_actions == 3
        assert v.yield_ratio == 0.0

    def test_negative_total_clamped(self):
        v = VisitYield(total_actions=-5, maintenance_actions=2)
        assert v.total_actions == 0
        assert v.maintenance_actions == 0

    def test_negative_maintenance_clamped(self):
        v = VisitYield(total_actions=5, maintenance_actions=-1)
        assert v.maintenance_actions == 0
        assert v.productive_actions == 5

    def test_single_productive_action(self):
        v = VisitYield(total_actions=1, maintenance_actions=0)
        assert v.yield_ratio == 1.0
        assert v.verdict == "thriving"

    def test_boundary_sustaining_low(self):
        # exactly 0.3 → sustaining
        v = VisitYield(total_actions=10, maintenance_actions=7)
        assert v.yield_ratio == 0.3
        assert v.verdict == "sustaining"

    def test_boundary_surviving_low(self):
        # exactly 0.1 → surviving
        v = VisitYield(total_actions=10, maintenance_actions=9)
        assert v.yield_ratio == 0.1
        assert v.verdict == "surviving"

    def test_just_below_thriving(self):
        v = VisitYield(total_actions=10, maintenance_actions=5)
        # 5/10 = 0.5, below 0.6
        assert v.yield_ratio == 0.5
        assert v.verdict == "sustaining"


# ---------------------------------------------------------------------------
# classify_yield
# ---------------------------------------------------------------------------

class TestClassifyYield:
    def test_thriving(self):
        assert classify_yield(0.6) == "thriving"
        assert classify_yield(1.0) == "thriving"
        assert classify_yield(0.85) == "thriving"

    def test_sustaining(self):
        assert classify_yield(0.3) == "sustaining"
        assert classify_yield(0.59) == "sustaining"

    def test_surviving(self):
        assert classify_yield(0.1) == "surviving"
        assert classify_yield(0.29) == "surviving"

    def test_firefighting(self):
        assert classify_yield(0.0) == "firefighting"
        assert classify_yield(0.09) == "firefighting"

    def test_nan_returns_firefighting(self):
        assert classify_yield(float("nan")) == "firefighting"


# ---------------------------------------------------------------------------
# yield_trend
# ---------------------------------------------------------------------------

class TestYieldTrend:
    def test_empty_history(self):
        assert yield_trend([]) == "insufficient"

    def test_single_visit(self):
        v = VisitYield(total_actions=5, maintenance_actions=1)
        assert yield_trend([v]) == "insufficient"

    def test_improving_trend(self):
        old = [VisitYield(total_actions=10, maintenance_actions=9)] * 5  # 0.1
        new = [VisitYield(total_actions=10, maintenance_actions=2)] * 5  # 0.8
        assert yield_trend(old + new) == "improving"

    def test_declining_trend(self):
        old = [VisitYield(total_actions=10, maintenance_actions=1)] * 5  # 0.9
        new = [VisitYield(total_actions=10, maintenance_actions=8)] * 5  # 0.2
        assert yield_trend(old + new) == "declining"

    def test_stable_trend(self):
        visits = [VisitYield(total_actions=10, maintenance_actions=5)] * 10  # 0.5
        assert yield_trend(visits) == "stable"

    def test_small_window(self):
        old = [VisitYield(total_actions=4, maintenance_actions=3)]  # 0.25
        new = [VisitYield(total_actions=4, maintenance_actions=0)]  # 1.0
        assert yield_trend(old + new, window=1) == "improving"


# ---------------------------------------------------------------------------
# yield_report
# ---------------------------------------------------------------------------

class TestYieldReport:
    def test_basic_report(self):
        v = VisitYield(total_actions=5, maintenance_actions=2)
        r = yield_report(v)
        assert "0.60" in r
        assert "thriving" in r
        assert "3 productive" in r
        assert "5 total" in r

    def test_zero_report(self):
        v = VisitYield(total_actions=0)
        r = yield_report(v)
        assert "0.00" in r
        assert "firefighting" in r


# ---------------------------------------------------------------------------
# yield_detail
# ---------------------------------------------------------------------------

class TestYieldDetail:
    def test_detail_with_labels(self):
        v = VisitYield(
            total_actions=4,
            maintenance_actions=2,
            maintenance_labels=["restart_writer", "backlog_commit"],
            productive_labels=["new_module", "new_note"],
        )
        d = yield_detail(v)
        assert "restart_writer" in d
        assert "new_module" in d
        assert "0.50" in d

    def test_detail_without_labels(self):
        v = VisitYield(total_actions=3, maintenance_actions=1)
        d = yield_detail(v)
        # only the summary line, no maintenance/productive sub-lines
        assert d.count("\n") == 0
