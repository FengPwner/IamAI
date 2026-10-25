"""Tests for iamai/stall_postmortem.py — stall pattern analysis."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.stall_postmortem import (  # noqa: E402
    Postmortem,
    StallEvent,
    _classify_trend,
    _simple_slope,
    analyse_stalls,
)


# ---------------------------------------------------------------------------
# _simple_slope
# ---------------------------------------------------------------------------

class TestSimpleSlope:
    def test_constant(self):
        assert _simple_slope([100, 100, 100, 100]) == 0.0

    def test_increasing(self):
        slope = _simple_slope([10, 20, 30, 40])
        assert slope == pytest.approx(10.0, abs=0.01)

    def test_decreasing(self):
        slope = _simple_slope([40, 30, 20, 10])
        assert slope == pytest.approx(-10.0, abs=0.01)

    def test_single_value(self):
        assert _simple_slope([42.0]) == 0.0

    def test_empty(self):
        assert _simple_slope([]) == 0.0

    def test_two_values(self):
        slope = _simple_slope([10, 30])
        assert slope == pytest.approx(20.0, abs=0.01)


# ---------------------------------------------------------------------------
# _classify_trend
# ---------------------------------------------------------------------------

class TestClassifyTrend:
    def test_stable_when_slope_near_zero(self):
        assert _classify_trend(5.0, 100.0) == "stable"

    def test_stable_at_exact_boundary(self):
        assert _classify_trend(10.0, 100.0) == "stable"

    def test_worsening_positive_slope(self):
        assert _classify_trend(50.0, 100.0) == "worsening"

    def test_improving_negative_slope(self):
        assert _classify_trend(-50.0, 100.0) == "improving"

    def test_zero_mean_is_stable(self):
        assert _classify_trend(10.0, 0.0) == "stable"

    def test_just_over_boundary_worsening(self):
        assert _classify_trend(11.0, 100.0) == "worsening"

    def test_just_under_boundary_improving(self):
        assert _classify_trend(-11.0, 100.0) == "improving"


# ---------------------------------------------------------------------------
# analyse_stalls — empty input
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_returns_zero_count(self):
        pm = analyse_stalls([])
        assert pm.count == 0

    def test_all_defaults(self):
        pm = analyse_stalls([])
        assert pm.mttr == 0.0
        assert pm.mean_gap == 0.0
        assert pm.max_gap == 0.0
        assert pm.severity_trend == "stable"
        assert pm.recovery_trend == "stable"
        assert pm.dominant_cause == "none"
        assert pm.insufficient_data is False

    def test_summary_mentions_no_events(self):
        pm = analyse_stalls([])
        assert "no stall" in pm.summary.lower()


# ---------------------------------------------------------------------------
# analyse_stalls — single event
# ---------------------------------------------------------------------------

class TestSingleEvent:
    def test_count_is_one(self):
        events = [StallEvent(gap_s=120, recovery_s=30, cause="crash")]
        pm = analyse_stalls(events)
        assert pm.count == 1

    def test_insufficient_data_flag(self):
        events = [StallEvent(gap_s=120, recovery_s=30, cause="crash")]
        pm = analyse_stalls(events)
        assert pm.insufficient_data is True

    def test_mttr_equals_recovery(self):
        events = [StallEvent(gap_s=120, recovery_s=45, cause="crash")]
        pm = analyse_stalls(events)
        assert pm.mttr == 45.0

    def test_trends_default_to_stable(self):
        events = [StallEvent(gap_s=120, recovery_s=30, cause="crash")]
        pm = analyse_stalls(events)
        assert pm.severity_trend == "stable"
        assert pm.recovery_trend == "stable"

    def test_dominant_cause_is_the_only_cause(self):
        events = [StallEvent(gap_s=120, recovery_s=30, cause="oom")]
        pm = analyse_stalls(events)
        assert pm.dominant_cause == "oom"

    def test_summary_format(self):
        events = [StallEvent(gap_s=120, recovery_s=30, cause="crash")]
        pm = analyse_stalls(events)
        assert "single stall" in pm.summary
        assert "120s" in pm.summary


# ---------------------------------------------------------------------------
# analyse_stalls — multiple events, worsening pattern
# ---------------------------------------------------------------------------

class TestWorseningPattern:
    @pytest.fixture
    def worsening_events(self):
        return [
            StallEvent(gap_s=120, recovery_s=20, cause="reclaimed"),
            StallEvent(gap_s=300, recovery_s=35, cause="reclaimed"),
            StallEvent(gap_s=900, recovery_s=50, cause="reclaimed"),
            StallEvent(gap_s=2700, recovery_s=60, cause="reclaimed"),
        ]

    def test_count(self, worsening_events):
        pm = analyse_stalls(worsening_events)
        assert pm.count == 4

    def test_severity_worsening(self, worsening_events):
        pm = analyse_stalls(worsening_events)
        assert pm.severity_trend == "worsening"

    def test_recovery_worsening(self, worsening_events):
        pm = analyse_stalls(worsening_events)
        assert pm.recovery_trend == "worsening"

    def test_mttr(self, worsening_events):
        pm = analyse_stalls(worsening_events)
        expected = (20 + 35 + 50 + 60) / 4
        assert pm.mttr == pytest.approx(expected)

    def test_max_gap(self, worsening_events):
        pm = analyse_stalls(worsening_events)
        assert pm.max_gap == 2700

    def test_dominant_cause(self, worsening_events):
        pm = analyse_stalls(worsening_events)
        assert pm.dominant_cause == "reclaimed"


# ---------------------------------------------------------------------------
# analyse_stalls — multiple events, improving pattern
# ---------------------------------------------------------------------------

class TestImprovingPattern:
    @pytest.fixture
    def improving_events(self):
        return [
            StallEvent(gap_s=2700, recovery_s=120, cause="crash"),
            StallEvent(gap_s=900, recovery_s=60, cause="crash"),
            StallEvent(gap_s=300, recovery_s=30, cause="reclaimed"),
            StallEvent(gap_s=60, recovery_s=15, cause="unknown"),
        ]

    def test_severity_improving(self, improving_events):
        pm = analyse_stalls(improving_events)
        assert pm.severity_trend == "improving"

    def test_recovery_improving(self, improving_events):
        pm = analyse_stalls(improving_events)
        assert pm.recovery_trend == "improving"

    def test_mixed_causes(self, improving_events):
        pm = analyse_stalls(improving_events)
        assert pm.cause_counts == {"crash": 2, "reclaimed": 1, "unknown": 1}
        assert pm.dominant_cause == "crash"


# ---------------------------------------------------------------------------
# analyse_stalls — stable pattern
# ---------------------------------------------------------------------------

class TestStablePattern:
    def test_constant_gaps_are_stable(self):
        events = [
            StallEvent(gap_s=600, recovery_s=30, cause="reclaimed"),
            StallEvent(gap_s=600, recovery_s=30, cause="reclaimed"),
            StallEvent(gap_s=600, recovery_s=30, cause="reclaimed"),
        ]
        pm = analyse_stalls(events)
        assert pm.severity_trend == "stable"
        assert pm.recovery_trend == "stable"

    def test_near_constant_gaps_are_stable(self):
        events = [
            StallEvent(gap_s=600, recovery_s=30, cause="reclaimed"),
            StallEvent(gap_s=610, recovery_s=31, cause="reclaimed"),
            StallEvent(gap_s=595, recovery_s=29, cause="reclaimed"),
        ]
        pm = analyse_stalls(events)
        assert pm.severity_trend == "stable"


# ---------------------------------------------------------------------------
# analyse_stalls — cause analysis
# ---------------------------------------------------------------------------

class TestCauseAnalysis:
    def test_single_cause_dominant(self):
        events = [
            StallEvent(gap_s=100, recovery_s=10, cause="reclaimed"),
            StallEvent(gap_s=200, recovery_s=20, cause="crash"),
            StallEvent(gap_s=300, recovery_s=30, cause="reclaimed"),
            StallEvent(gap_s=400, recovery_s=40, cause="reclaimed"),
        ]
        pm = analyse_stalls(events)
        assert pm.dominant_cause == "reclaimed"
        assert pm.cause_counts["reclaimed"] == 3
        assert pm.cause_counts["crash"] == 1

    def test_tie_breaks_by_first_in_counter(self):
        events = [
            StallEvent(gap_s=100, recovery_s=10, cause="crash"),
            StallEvent(gap_s=200, recovery_s=20, cause="oom"),
        ]
        pm = analyse_stalls(events)
        # Both have count 1; Counter picks whichever max() finds first
        assert pm.dominant_cause in ("crash", "oom")
        assert pm.cause_counts == {"crash": 1, "oom": 1}


# ---------------------------------------------------------------------------
# analyse_stalls — summary format
# ---------------------------------------------------------------------------

class TestSummaryFormat:
    def test_summary_contains_key_metrics(self):
        events = [
            StallEvent(gap_s=300, recovery_s=30, cause="reclaimed"),
            StallEvent(gap_s=600, recovery_s=45, cause="reclaimed"),
        ]
        pm = analyse_stalls(events)
        assert "2 stalls" in pm.summary
        assert "mttr" in pm.summary
        assert "reclaimed" in pm.summary

    def test_summary_contains_trends(self):
        events = [
            StallEvent(gap_s=100, recovery_s=10, cause="crash"),
            StallEvent(gap_s=500, recovery_s=50, cause="crash"),
        ]
        pm = analyse_stalls(events)
        assert "worsening" in pm.summary or "improving" in pm.summary or "stable" in pm.summary


# ---------------------------------------------------------------------------
# StallEvent / Postmortem — frozen dataclass
# ---------------------------------------------------------------------------

class TestFrozenDataclasses:
    def test_stall_event_is_frozen(self):
        e = StallEvent(gap_s=100, recovery_s=10, cause="test")
        with pytest.raises(AttributeError):
            e.gap_s = 200  # type: ignore

    def test_postmortem_is_frozen(self):
        pm = analyse_stalls([StallEvent(gap_s=100, recovery_s=10)])
        with pytest.raises(AttributeError):
            pm.count = 99  # type: ignore

    def test_default_cause_is_unknown(self):
        e = StallEvent(gap_s=100, recovery_s=10)
        assert e.cause == "unknown"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_gap(self):
        events = [StallEvent(gap_s=0, recovery_s=5, cause="glitch")]
        pm = analyse_stalls(events)
        assert pm.mean_gap == 0.0
        assert pm.max_gap == 0.0

    def test_zero_recovery(self):
        events = [
            StallEvent(gap_s=100, recovery_s=0, cause="instant"),
            StallEvent(gap_s=200, recovery_s=0, cause="instant"),
        ]
        pm = analyse_stalls(events)
        assert pm.mttr == 0.0

    def test_very_large_gap(self):
        events = [
            StallEvent(gap_s=86400, recovery_s=300, cause="extended_outage"),
            StallEvent(gap_s=86400, recovery_s=300, cause="extended_outage"),
        ]
        pm = analyse_stalls(events)
        assert pm.max_gap == 86400
        assert pm.severity_trend == "stable"

    def test_many_events(self):
        events = [
            StallEvent(gap_s=float(i * 10), recovery_s=float(i), cause="test")
            for i in range(1, 51)
        ]
        pm = analyse_stalls(events)
        assert pm.count == 50
        # slope=10, mean=255 → ratio≈0.039, within ±10% → stable
        assert pm.severity_trend == "stable"

    def test_many_events_clearly_worsening(self):
        # gaps double each time: clear exponential growth
        events = [
            StallEvent(gap_s=float(2 ** i), recovery_s=10.0, cause="test")
            for i in range(1, 11)
        ]
        pm = analyse_stalls(events)
        assert pm.count == 10
        assert pm.severity_trend == "worsening"
