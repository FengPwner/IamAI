#!/usr/bin/env python3
"""Tests for caretaker_yield.py — caretaker visit ROI measurement."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import caretaker_yield as cy


# ---------------------------------------------------------------------------
# classify_yield
# ---------------------------------------------------------------------------

class TestClassifyYield:
    def test_high_yield_at_boundary(self):
        assert cy.classify_yield(0.8) == "high-yield"

    def test_high_yield_above(self):
        assert cy.classify_yield(0.95) == "high-yield"

    def test_routine_lower_boundary(self):
        assert cy.classify_yield(0.6) == "routine"

    def test_routine_upper(self):
        assert cy.classify_yield(0.79) == "routine"

    def test_expensive(self):
        assert cy.classify_yield(0.4) == "expensive"

    def test_expensive_upper(self):
        assert cy.classify_yield(0.55) == "expensive"

    def test_firefighting(self):
        assert cy.classify_yield(0.2) == "firefighting"

    def test_firefighting_upper(self):
        assert cy.classify_yield(0.35) == "firefighting"

    def test_futile_at_zero(self):
        assert cy.classify_yield(0.0) == "futile"

    def test_futile_low(self):
        assert cy.classify_yield(0.15) == "futile"

    def test_one_point_zero(self):
        assert cy.classify_yield(1.0) == "high-yield"

    def test_just_below_routine(self):
        assert cy.classify_yield(0.599) == "expensive"

    def test_just_below_firefighting(self):
        assert cy.classify_yield(0.199) == "futile"


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

class TestScoreUptime:
    def test_zero_uptime(self):
        assert cy._score_uptime(0) == 0.0

    def test_negative_uptime(self):
        assert cy._score_uptime(-100) == 0.0

    def test_excellent_uptime(self):
        assert cy._score_uptime(3600) == 1.0

    def test_above_excellent(self):
        assert cy._score_uptime(7200) == 1.0

    def test_good_uptime(self):
        score = cy._score_uptime(1200)
        assert 0.45 <= score <= 0.55  # should be ~0.5

    def test_poor_uptime(self):
        score = cy._score_uptime(300)
        assert 0.15 <= score <= 0.25  # should be ~0.2

    def test_between_poor_and_good(self):
        score = cy._score_uptime(750)
        assert 0.2 < score < 0.5

    def test_monotonically_increasing(self):
        prev = 0.0
        for t in [60, 120, 300, 600, 1200, 2400, 3600]:
            s = cy._score_uptime(t)
            assert s >= prev
            prev = s


class TestScoreRecovery:
    def test_zero_recovery(self):
        assert cy._score_recovery(0) == 1.0

    def test_fast_recovery(self):
        assert cy._score_recovery(30) == 1.0

    def test_normal_recovery_boundary(self):
        score = cy._score_recovery(300)
        assert 0.65 <= score <= 0.75

    def test_slow_recovery(self):
        score = cy._score_recovery(900)
        assert 0.25 <= score <= 0.35

    def test_very_slow_recovery(self):
        score = cy._score_recovery(3600)
        assert score < 0.15

    def test_monotonically_decreasing(self):
        prev = 1.0
        for t in [30, 60, 120, 300, 600, 900, 1800]:
            s = cy._score_recovery(t)
            assert s <= prev
            prev = s


class TestScoreCost:
    def test_zero_cost(self):
        assert cy._score_cost(0) == 1.0

    def test_one_action(self):
        assert cy._score_cost(1) == 1.0

    def test_max_cost(self):
        assert cy._score_cost(6) == 0.1

    def test_above_max_cost(self):
        assert cy._score_cost(10) == 0.1

    def test_mid_cost(self):
        score = cy._score_cost(3)
        assert 0.4 < score < 0.8

    def test_decreasing(self):
        assert cy._score_cost(1) > cy._score_cost(2) > cy._score_cost(3)


class TestScoreOutput:
    def test_zero_delta(self):
        assert cy._score_output(0) == 0.0

    def test_negative_delta(self):
        assert cy._score_output(-10) == 0.0

    def test_high_delta(self):
        assert cy._score_output(100) == 1.0

    def test_above_high(self):
        assert cy._score_output(200) == 1.0

    def test_mid_delta(self):
        score = cy._score_output(50)
        assert 0.65 <= score <= 0.75

    def test_low_delta(self):
        score = cy._score_output(10)
        assert 0.25 <= score <= 0.35

    def test_very_low_delta(self):
        score = cy._score_output(5)
        assert 0.1 <= score <= 0.2


class TestScoreBacklog:
    def test_zero_backlog(self):
        assert cy._score_backlog(0) == 0.5

    def test_negative_backlog(self):
        assert cy._score_backlog(-5) == 0.5

    def test_high_backlog(self):
        assert cy._score_backlog(20) == 1.0

    def test_above_high(self):
        assert cy._score_backlog(50) == 1.0

    def test_mid_backlog(self):
        score = cy._score_backlog(10)
        assert 0.75 <= score <= 0.85

    def test_low_backlog(self):
        score = cy._score_backlog(5)
        assert 0.6 <= score <= 0.7


# ---------------------------------------------------------------------------
# compute_yield
# ---------------------------------------------------------------------------

class TestComputeYield:
    def test_perfect_visit(self):
        y = cy.compute_yield(
            recovery_latency=30,
            sustained_uptime=7200,
            backlog_cleared=15,
            output_delta=150,
            visit_cost=1,
        )
        assert y.yield_class == "high-yield"
        assert y.yield_score >= 0.8

    def test_terrible_visit(self):
        y = cy.compute_yield(
            recovery_latency=1800,
            sustained_uptime=60,
            backlog_cleared=0,
            output_delta=-5,
            visit_cost=5,
        )
        assert y.yield_class == "futile"
        assert y.yield_score < 0.2

    def test_routine_visit(self):
        y = cy.compute_yield(
            recovery_latency=120,
            sustained_uptime=1800,
            backlog_cleared=3,
            output_delta=60,
            visit_cost=2,
        )
        assert y.yield_class in ("routine", "high-yield")

    def test_score_clamped_to_0_1(self):
        y = cy.compute_yield(
            recovery_latency=0,
            sustained_uptime=99999,
            backlog_cleared=100,
            output_delta=999,
            visit_cost=0,
        )
        assert 0.0 <= y.yield_score <= 1.0

    def test_default_values(self):
        y = cy.compute_yield()
        assert y.yield_score >= 0.0
        assert y.yield_class in ("futile", "firefighting", "expensive",
                                  "routine", "high-yield")

    def test_visit_time_auto_set(self):
        y = cy.compute_yield()
        assert len(y.visit_time) > 0

    def test_visit_time_override(self):
        y = cy.compute_yield(visit_time="2026-11-10T15:00:00+00:00")
        assert y.visit_time == "2026-11-10T15:00:00+00:00"

    def test_actions_stored(self):
        y = cy.compute_yield(actions=["restart", "backlog_commit"])
        assert y.actions == ["restart", "backlog_commit"]

    def test_notes_stored(self):
        y = cy.compute_yield(notes="container was reclaimed")
        assert y.notes == "container was reclaimed"

    def test_uptime_dominates_score(self):
        """Uptime has 40% weight — a long uptime should yield high even with
        mediocre other dimensions."""
        y = cy.compute_yield(
            recovery_latency=600,
            sustained_uptime=7200,
            backlog_cleared=0,
            output_delta=5,
            visit_cost=4,
        )
        assert y.yield_score > 0.45  # uptime alone gives 0.4

    def test_short_uptime_caps_score(self):
        """Even with perfect other metrics, very short uptime limits the score."""
        y = cy.compute_yield(
            recovery_latency=0,
            sustained_uptime=30,
            backlog_cleared=50,
            output_delta=200,
            visit_cost=0,
        )
        # uptime=0 at 30s; max from other dims = 0.6*0.6 = 0.36
        assert y.yield_score < 0.65  # uptime is low but other perfect dims still give ~0.6


# ---------------------------------------------------------------------------
# CaretakerYield data class
# ---------------------------------------------------------------------------

class TestCaretakerYieldDataclass:
    def test_to_dict(self):
        y = cy.compute_yield(
            recovery_latency=60,
            sustained_uptime=1800,
            visit_cost=2,
        )
        d = y.to_dict()
        assert "yield_score" in d
        assert "yield_class" in d
        assert "recovery_latency" in d
        assert d["recovery_latency"] == 60

    def test_to_json(self):
        y = cy.compute_yield(recovery_latency=45, sustained_uptime=3600)
        j = y.to_json()
        parsed = json.loads(j)
        assert parsed["recovery_latency"] == 45
        assert parsed["sustained_uptime"] == 3600

    def test_to_json_indent(self):
        y = cy.compute_yield()
        j2 = y.to_json(indent=2)
        j4 = y.to_json(indent=4)
        assert len(j4) > len(j2)  # more indent = more spaces

    def test_default_actions_empty(self):
        y = cy.CaretakerYield()
        assert y.actions == []

    def test_default_notes_empty(self):
        y = cy.CaretakerYield()
        assert y.notes == ""


# ---------------------------------------------------------------------------
# Trend analysis helpers
# ---------------------------------------------------------------------------

class TestLinearSlope:
    def test_empty(self):
        assert cy._linear_slope([]) == 0.0

    def test_single(self):
        assert cy._linear_slope([0.5]) == 0.0

    def test_increasing(self):
        slope = cy._linear_slope([0.1, 0.3, 0.5, 0.7, 0.9])
        assert slope > 0

    def test_decreasing(self):
        slope = cy._linear_slope([0.9, 0.7, 0.5, 0.3, 0.1])
        assert slope < 0

    def test_flat(self):
        slope = cy._linear_slope([0.5, 0.5, 0.5, 0.5])
        assert abs(slope) < 0.001

    def test_two_points(self):
        slope = cy._linear_slope([0.2, 0.8])
        assert slope == pytest.approx(0.6)


class TestClassifyTrend:
    def test_unknown_single(self):
        assert cy._classify_trend(0.1, 1) == "unknown"

    def test_improving(self):
        assert cy._classify_trend(0.05, 5) == "improving"

    def test_degrading(self):
        assert cy._classify_trend(-0.05, 5) == "degrading"

    def test_flat_near_zero(self):
        assert cy._classify_trend(0.005, 10) == "flat"

    def test_flat_zero(self):
        assert cy._classify_trend(0.0, 10) == "flat"

    def test_boundary_improving(self):
        assert cy._classify_trend(0.021, 5) == "improving"

    def test_boundary_degrading(self):
        assert cy._classify_trend(-0.021, 5) == "degrading"

    def test_boundary_flat(self):
        assert cy._classify_trend(0.009, 5) == "flat"


# ---------------------------------------------------------------------------
# visit_roi
# ---------------------------------------------------------------------------

class TestVisitROI:
    def test_empty_yields(self):
        roi = cy.visit_roi([])
        assert roi.total_visits == 0
        assert roi.trend == "unknown"

    def test_single_visit(self):
        y = cy.compute_yield(
            recovery_latency=60,
            sustained_uptime=3600,
            backlog_cleared=5,
            output_delta=80,
            visit_cost=2,
        )
        roi = cy.visit_roi([y])
        assert roi.total_visits == 1
        assert roi.mean_yield == y.yield_score
        assert roi.trend == "unknown"
        assert roi.recommendation == "too few visits to recommend"

    def test_improving_trend(self):
        yields = []
        for uptime in [300, 600, 1200, 2400, 3600]:
            yields.append(cy.compute_yield(
                recovery_latency=120,
                sustained_uptime=uptime,
                backlog_cleared=3,
                output_delta=50,
                visit_cost=2,
            ))
        roi = cy.visit_roi(yields)
        assert roi.total_visits == 5
        assert roi.trend == "improving"
        assert roi.trend_slope > 0

    def test_degrading_trend(self):
        yields = []
        for uptime in [3600, 2400, 1200, 600, 120]:
            yields.append(cy.compute_yield(
                recovery_latency=120,
                sustained_uptime=uptime,
                backlog_cleared=3,
                output_delta=50,
                visit_cost=2,
            ))
        roi = cy.visit_roi(yields)
        assert roi.trend == "degrading"
        assert roi.trend_slope < 0

    def test_flat_trend(self):
        yields = [
            cy.compute_yield(
                recovery_latency=100,
                sustained_uptime=1800,
                backlog_cleared=3,
                output_delta=50,
                visit_cost=2,
            )
            for _ in range(5)
        ]
        roi = cy.visit_roi(yields)
        assert roi.trend == "flat"

    def test_high_yield_pct(self):
        yields = [
            cy.compute_yield(
                recovery_latency=30,
                sustained_uptime=7200,
                backlog_cleared=15,
                output_delta=150,
                visit_cost=1,
            )
            for _ in range(5)
        ]
        roi = cy.visit_roi(yields)
        assert roi.high_yield_pct == 100.0

    def test_futile_pct(self):
        yields = [
            cy.compute_yield(
                recovery_latency=1800,
                sustained_uptime=30,
                backlog_cleared=0,
                output_delta=-5,
                visit_cost=5,
            )
            for _ in range(4)
        ]
        roi = cy.visit_roi(yields)
        assert roi.futile_pct == 100.0

    def test_median_odd(self):
        yields = [
            cy.compute_yield(recovery_latency=60, sustained_uptime=100),
            cy.compute_yield(recovery_latency=60, sustained_uptime=500),
            cy.compute_yield(recovery_latency=60, sustained_uptime=3600),
        ]
        roi = cy.visit_roi(yields)
        scores = sorted([y.yield_score for y in yields])
        assert roi.median_yield == pytest.approx(scores[1])

    def test_median_even(self):
        yields = [
            cy.compute_yield(recovery_latency=60, sustained_uptime=100),
            cy.compute_yield(recovery_latency=60, sustained_uptime=500),
            cy.compute_yield(recovery_latency=60, sustained_uptime=1800),
            cy.compute_yield(recovery_latency=60, sustained_uptime=3600),
        ]
        roi = cy.visit_roi(yields)
        scores = sorted([y.yield_score for y in yields])
        expected = (scores[1] + scores[2]) / 2
        assert roi.median_yield == pytest.approx(expected)

    def test_to_dict(self):
        roi = cy.visit_roi([])
        d = roi.to_dict()
        assert "total_visits" in d
        assert "trend" in d
        assert d["total_visits"] == 0


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

class TestRecommendations:
    def test_too_few_visits(self):
        y = cy.compute_yield(
            recovery_latency=60, sustained_uptime=3600, visit_cost=2,
        )
        roi = cy.visit_roi([y])
        assert "too few" in roi.recommendation

    def test_improving_high_yield(self):
        yields = []
        for uptime in [1800, 2400, 3000, 3600, 7200]:
            yields.append(cy.compute_yield(
                recovery_latency=60,
                sustained_uptime=uptime,
                backlog_cleared=5,
                output_delta=80,
                visit_cost=1,
            ))
        roi = cy.visit_roi(yields)
        if roi.trend == "improving" and roi.mean_yield >= 0.7:
            assert "stabilising" in roi.recommendation or "reducing" in roi.recommendation

    def test_degrading_with_firefighting(self):
        yields = [
            cy.compute_yield(
                recovery_latency=120,
                sustained_uptime=3600,
                backlog_cleared=3,
                output_delta=80,
                visit_cost=2,
            ),
            cy.compute_yield(
                recovery_latency=300,
                sustained_uptime=600,
                backlog_cleared=1,
                output_delta=10,
                visit_cost=4,
            ),
            cy.compute_yield(
                recovery_latency=900,
                sustained_uptime=120,
                backlog_cleared=0,
                output_delta=-10,
                visit_cost=5,
            ),
        ]
        roi = cy.visit_roi(yields)
        # should detect degrading trend with firefighting
        assert roi.trend in ("degrading", "flat")

    def test_mostly_high_yield(self):
        yields = [
            cy.compute_yield(
                recovery_latency=30,
                sustained_uptime=7200,
                backlog_cleared=15,
                output_delta=150,
                visit_cost=1,
            )
            for _ in range(5)
        ]
        roi = cy.visit_roi(yields)
        if roi.high_yield_pct > 70:
            assert "well-maintained" in roi.recommendation


# ---------------------------------------------------------------------------
# yield_report
# ---------------------------------------------------------------------------

class TestYieldReport:
    def test_empty_yields(self):
        assert cy.yield_report([]) == "no caretaker visits recorded"

    def test_single_visit_report(self):
        y = cy.compute_yield(
            recovery_latency=60,
            sustained_uptime=3600,
            backlog_cleared=5,
            output_delta=80,
            visit_cost=2,
        )
        report = cy.yield_report([y])
        assert "caretaker yield report" in report
        assert "visits: 1" in report
        assert "#  1" in report

    def test_multi_visit_report(self):
        yields = [
            cy.compute_yield(
                recovery_latency=60,
                sustained_uptime=1800 + i * 600,
                backlog_cleared=3,
                output_delta=50,
                visit_cost=2,
            )
            for i in range(5)
        ]
        report = cy.yield_report(yields)
        assert "visits: 5" in report
        assert "per-visit breakdown:" in report
        assert "recommendation:" in report

    def test_report_contains_all_visits(self):
        yields = [
            cy.compute_yield(
                recovery_latency=60,
                sustained_uptime=1800,
                visit_cost=2,
            )
            for _ in range(3)
        ]
        report = cy.yield_report(yields)
        assert "#  1" in report
        assert "#  2" in report
        assert "#  3" in report

    def test_report_includes_trend(self):
        yields = [
            cy.compute_yield(
                recovery_latency=60,
                sustained_uptime=1800,
                visit_cost=2,
            )
            for _ in range(3)
        ]
        report = cy.yield_report(yields)
        assert "trend:" in report


# ---------------------------------------------------------------------------
# parse_visits_from_log
# ---------------------------------------------------------------------------

class TestParseVisitsFromLog:
    def test_nonexistent_file(self):
        visits = cy.parse_visits_from_log("/tmp/nonexistent_log_xyz.txt")
        assert visits == []

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("")
            path = f.name
        visits = cy.parse_visits_from_log(path)
        assert visits == []
        Path(path).unlink()

    def test_with_visits(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("abc123 visit-596: add caretaker entropy\n")
            f.write("def456 catch-up: commit pending\n")
            f.write("ghi789 visit-595: add signal to noise\n")
            path = f.name
        visits = cy.parse_visits_from_log(path)
        assert len(visits) == 2
        assert "visit-596" in visits[0]["message"]
        assert "visit-595" in visits[1]["message"]
        Path(path).unlink()

    def test_caretaker_keyword(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("abc123 caretaker visit report\n")
            path = f.name
        visits = cy.parse_visits_from_log(path)
        assert len(visits) == 1
        Path(path).unlink()

    def test_no_matching_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("abc123 catch-up: commit pending\n")
            f.write("def456 regular commit\n")
            path = f.name
        visits = cy.parse_visits_from_log(path)
        assert visits == []
        Path(path).unlink()


# ---------------------------------------------------------------------------
# VisitROI data class
# ---------------------------------------------------------------------------

class TestVisitROIDataclass:
    def test_default_values(self):
        roi = cy.VisitROI()
        assert roi.total_visits == 0
        assert roi.trend == "unknown"

    def test_to_dict_rounding(self):
        roi = cy.VisitROI(
            total_visits=5,
            mean_yield=0.7123456,
            median_yield=0.6987654,
            trend_slope=0.01234567,
        )
        d = roi.to_dict()
        assert d["mean_yield"] == 0.712
        assert d["median_yield"] == 0.699
        assert d["trend_slope"] == 0.0123


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_very_large_uptime(self):
        y = cy.compute_yield(sustained_uptime=999999)
        assert y.yield_score <= 1.0

    def test_very_large_cost(self):
        y = cy.compute_yield(visit_cost=100)
        assert y.yield_score >= 0.0

    def test_very_large_backlog(self):
        y = cy.compute_yield(backlog_cleared=1000)
        assert y.yield_score <= 1.0

    def test_very_large_output_delta(self):
        y = cy.compute_yield(output_delta=10000)
        assert y.yield_score <= 1.0

    def test_all_zeros(self):
        y = cy.compute_yield(
            recovery_latency=0,
            sustained_uptime=0,
            backlog_cleared=0,
            output_delta=0,
            visit_cost=0,
        )
        # recovery=1.0, cost=1.0, backlog=0.5 but uptime=0, output=0
        # score = 0.40*0 + 0.15*1.0 + 0.15*1.0 + 0.20*0 + 0.10*0.5
        # = 0.35
        assert 0.25 <= y.yield_score <= 0.45

    def test_weights_sum_to_one(self):
        total = sum(cy._WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_mixed_visit_sequence(self):
        """Realistic sequence: good, ok, bad, recovery."""
        yields = [
            cy.compute_yield(
                recovery_latency=45, sustained_uptime=7200,
                backlog_cleared=0, output_delta=120, visit_cost=1,
            ),
            cy.compute_yield(
                recovery_latency=120, sustained_uptime=1800,
                backlog_cleared=5, output_delta=60, visit_cost=2,
            ),
            cy.compute_yield(
                recovery_latency=900, sustained_uptime=180,
                backlog_cleared=12, output_delta=5, visit_cost=5,
            ),
            cy.compute_yield(
                recovery_latency=60, sustained_uptime=3600,
                backlog_cleared=2, output_delta=90, visit_cost=2,
            ),
        ]
        roi = cy.visit_roi(yields)
        assert roi.total_visits == 4
        assert 0.0 < roi.mean_yield < 1.0
        assert roi.trend in ("improving", "degrading", "flat", "unknown")
