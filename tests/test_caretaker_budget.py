"""Tests for iamai.caretaker_budget — caretaker visit cost tracker."""

import pytest

from iamai.caretaker_budget import (
    CaretakerBudget,
    _classify,
    _linreg,
    _score_visit,
    DEFAULT_THRESHOLDS,
    DEFAULT_WEIGHTS,
)


# ---------------------------------------------------------------------------
# _score_visit
# ---------------------------------------------------------------------------

class TestScoreVisit:
    def test_zero_visit(self):
        score = _score_visit(
            {"minutes": 0, "commits": 0, "restarts": 0},
            DEFAULT_WEIGHTS,
            DEFAULT_THRESHOLDS,
        )
        assert score == 0.0

    def test_exactly_at_thresholds(self):
        score = _score_visit(
            {"minutes": 15, "commits": 3, "restarts": 1},
            DEFAULT_WEIGHTS,
            DEFAULT_THRESHOLDS,
        )
        # Each dimension at threshold → score = sum of weights = 1.0
        assert abs(score - 1.0) < 1e-9

    def test_double_thresholds(self):
        score = _score_visit(
            {"minutes": 30, "commits": 6, "restarts": 2},
            DEFAULT_WEIGHTS,
            DEFAULT_THRESHOLDS,
        )
        # Each dimension at 2x → score = 2.0
        assert abs(score - 2.0) < 1e-9

    def test_half_thresholds(self):
        score = _score_visit(
            {"minutes": 7.5, "commits": 1.5, "restarts": 0.5},
            DEFAULT_WEIGHTS,
            DEFAULT_THRESHOLDS,
        )
        assert abs(score - 0.5) < 1e-9

    def test_missing_dimension_defaults_to_zero(self):
        score = _score_visit(
            {"minutes": 15},  # commits and restarts missing
            DEFAULT_WEIGHTS,
            DEFAULT_THRESHOLDS,
        )
        # Only minutes contributes: 0.4 * (15/15) = 0.4
        assert abs(score - 0.4) < 1e-9

    def test_custom_weights_and_thresholds(self):
        score = _score_visit(
            {"minutes": 10, "commits": 5, "restarts": 0},
            {"minutes": 0.5, "commits": 0.5},
            {"minutes": 10, "commits": 5},
        )
        # minutes: 0.5 * 1.0 = 0.5, commits: 0.5 * 1.0 = 0.5 → 1.0
        assert abs(score - 1.0) < 1e-9

    def test_zero_threshold_treated_as_one(self):
        score = _score_visit(
            {"minutes": 5},
            {"minutes": 1.0},
            {"minutes": 0},  # zero threshold → treated as 1
        )
        assert abs(score - 5.0) < 1e-9


# ---------------------------------------------------------------------------
# _linreg
# ---------------------------------------------------------------------------

class TestLinreg:
    def test_perfect_positive(self):
        slope, r2 = _linreg([1.0, 2.0, 3.0, 4.0, 5.0])
        assert abs(slope - 1.0) < 1e-9
        assert abs(r2 - 1.0) < 1e-9

    def test_perfect_negative(self):
        slope, r2 = _linreg([5.0, 4.0, 3.0, 2.0, 1.0])
        assert abs(slope - (-1.0)) < 1e-9
        assert abs(r2 - 1.0) < 1e-9

    def test_flat(self):
        slope, r2 = _linreg([3.0, 3.0, 3.0, 3.0])
        assert abs(slope) < 1e-9
        assert abs(r2) < 1e-9

    def test_single_point(self):
        slope, r2 = _linreg([7.0])
        assert slope == 0.0
        assert r2 == 0.0

    def test_empty(self):
        slope, r2 = _linreg([])
        assert slope == 0.0
        assert r2 == 0.0

    def test_noisy_upward(self):
        slope, r2 = _linreg([0.5, 1.2, 0.8, 1.9, 2.1])
        assert slope > 0
        assert 0 < r2 < 1


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_frugal(self):
        assert _classify(0.3, 1.0) == "frugal"
        assert _classify(0.0, 1.0) == "frugal"
        assert _classify(0.49, 1.0) == "frugal"

    def test_normal(self):
        assert _classify(0.5, 1.0) == "normal"
        assert _classify(1.0, 1.0) == "normal"
        assert _classify(1.2, 1.0) == "normal"

    def test_expensive(self):
        assert _classify(1.21, 1.0) == "expensive"
        assert _classify(1.5, 1.0) == "expensive"
        assert _classify(2.0, 1.0) == "expensive"

    def test_overrun(self):
        assert _classify(2.01, 1.0) == "overrun"
        assert _classify(5.0, 1.0) == "overrun"


# ---------------------------------------------------------------------------
# CaretakerBudget — recording
# ---------------------------------------------------------------------------

class TestRecording:
    def test_empty_budget(self):
        b = CaretakerBudget()
        assert b.count == 0
        assert b.scores() == []

    def test_record_returns_score(self):
        b = CaretakerBudget()
        score = b.record({"minutes": 5, "commits": 1, "restarts": 0})
        assert isinstance(score, float)
        assert score > 0
        assert b.count == 1

    def test_multiple_records(self):
        b = CaretakerBudget()
        b.record({"minutes": 5, "commits": 1, "restarts": 0})
        b.record({"minutes": 10, "commits": 2, "restarts": 0})
        b.record({"minutes": 30, "commits": 5, "restarts": 2})
        assert b.count == 3

    def test_window_bounds(self):
        b = CaretakerBudget(window_size=3)
        for i in range(5):
            b.record({"minutes": i + 1, "commits": 1, "restarts": 0})
        assert b.count == 3
        # Oldest two should have been evicted
        scores = b.scores()
        assert len(scores) == 3


# ---------------------------------------------------------------------------
# CaretakerBudget — analysis
# ---------------------------------------------------------------------------

class TestAnalysis:
    def test_empty_analyse(self):
        b = CaretakerBudget()
        a = b.analyse()
        assert a["verdict"] == "insufficient"
        assert a["count"] == 0
        assert a["avg_cost"] == 0.0

    def test_single_frugal_visit(self):
        b = CaretakerBudget()
        b.record({"minutes": 2, "commits": 0, "restarts": 0})
        a = b.analyse()
        assert a["verdict"] == "frugal"
        assert a["count"] == 1
        assert a["avg_cost"] > 0

    def test_normal_visit(self):
        b = CaretakerBudget()
        b.record({"minutes": 15, "commits": 3, "restarts": 1})
        a = b.analyse()
        assert a["verdict"] == "normal"
        assert abs(a["latest_score"] - 1.0) < 1e-4

    def test_expensive_visit(self):
        b = CaretakerBudget()
        b.record({"minutes": 25, "commits": 5, "restarts": 2})
        a = b.analyse()
        assert a["verdict"] == "expensive"

    def test_overrun_visit(self):
        b = CaretakerBudget()
        b.record({"minutes": 60, "commits": 10, "restarts": 4})
        a = b.analyse()
        assert a["verdict"] == "overrun"

    def test_trend_stable(self):
        b = CaretakerBudget()
        # All visits identical → flat line → stable
        for _ in range(5):
            b.record({"minutes": 10, "commits": 2, "restarts": 0})
        a = b.analyse()
        assert a["trend"] == "stable"
        assert abs(a["trend_slope"]) < 0.02

    def test_trend_rising(self):
        b = CaretakerBudget()
        for i in range(8):
            b.record({"minutes": 5 + i * 5, "commits": 1 + i, "restarts": i // 2})
        a = b.analyse()
        assert a["trend"] == "rising"
        assert a["trend_slope"] > 0.02

    def test_trend_falling(self):
        b = CaretakerBudget()
        for i in range(8):
            b.record({"minutes": 50 - i * 5, "commits": 8 - i, "restarts": 3 - i // 3})
        a = b.analyse()
        assert a["trend"] == "falling"
        assert a["trend_slope"] < -0.02

    def test_streak_expensive(self):
        b = CaretakerBudget()
        # Two cheap visits, then three expensive ones
        b.record({"minutes": 3, "commits": 1, "restarts": 0})
        b.record({"minutes": 3, "commits": 1, "restarts": 0})
        b.record({"minutes": 30, "commits": 6, "restarts": 2})
        b.record({"minutes": 45, "commits": 8, "restarts": 3})
        b.record({"minutes": 50, "commits": 10, "restarts": 3})
        a = b.analyse()
        assert a["streak_expensive"] == 3

    def test_streak_zero_when_mixed(self):
        b = CaretakerBudget()
        b.record({"minutes": 30, "commits": 6, "restarts": 2})
        b.record({"minutes": 3, "commits": 1, "restarts": 0})  # breaks streak
        b.record({"minutes": 30, "commits": 6, "restarts": 2})
        a = b.analyse()
        assert a["streak_expensive"] == 1

    def test_median_odd(self):
        b = CaretakerBudget()
        b.record({"minutes": 5, "commits": 1, "restarts": 0})
        b.record({"minutes": 15, "commits": 3, "restarts": 1})
        b.record({"minutes": 30, "commits": 6, "restarts": 2})
        a = b.analyse()
        # 3 items → median is the middle score (the second one)
        scores = sorted(b.scores())
        assert abs(a["median_cost"] - scores[1]) < 1e-4

    def test_median_even(self):
        b = CaretakerBudget()
        b.record({"minutes": 5, "commits": 1, "restarts": 0})
        b.record({"minutes": 30, "commits": 6, "restarts": 2})
        a = b.analyse()
        assert a["median_cost"] > 0


# ---------------------------------------------------------------------------
# CaretakerBudget — report
# ---------------------------------------------------------------------------

class TestReport:
    def test_empty_report(self):
        b = CaretakerBudget()
        assert b.report() == "no visits recorded"

    def test_report_contains_verdict(self):
        b = CaretakerBudget()
        b.record({"minutes": 5, "commits": 1, "restarts": 0})
        r = b.report()
        assert "frugal" in r
        assert "1 visit(s)" in r

    def test_report_format(self):
        b = CaretakerBudget()
        b.record({"minutes": 15, "commits": 3, "restarts": 1})
        b.record({"minutes": 20, "commits": 4, "restarts": 1})
        r = b.report()
        assert "normal" in r or "expensive" in r
        assert "2 visit(s)" in r
        assert "trend" in r


# ---------------------------------------------------------------------------
# CaretakerBudget — custom config
# ---------------------------------------------------------------------------

class TestCustomConfig:
    def test_custom_thresholds(self):
        b = CaretakerBudget(
            thresholds={"minutes": 30, "commits": 6, "restarts": 2}
        )
        # Visit that would be "normal" under defaults is "frugal" with generous thresholds
        score = b.record({"minutes": 5, "commits": 1, "restarts": 0})
        assert score < 0.5

    def test_custom_weights(self):
        b = CaretakerBudget(
            weights={"minutes": 0.8, "commits": 0.1, "restarts": 0.1}
        )
        score = b.record({"minutes": 30, "commits": 1, "restarts": 0})
        # Heavy weight on minutes → high score
        assert score > 1.0

    def test_window_size(self):
        b = CaretakerBudget(window_size=5)
        for i in range(10):
            b.record({"minutes": i + 1, "commits": 1, "restarts": 0})
        assert b.count == 5
