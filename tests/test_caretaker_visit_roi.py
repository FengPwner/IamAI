"""Tests for iamai.caretaker_visit_roi — caretaker visit ROI analysis.

Tests cover:
- VisitYield scoring (default and custom weights)
- VisitYield properties (total_outputs, is_empty)
- VisitRecord validation (kind, cost)
- VisitRecord ROI calculation
- CaretakerVisitROI aggregate metrics (mean, median, max, overall)
- Kind breakdown (counts, best/worst, ratios)
- Trend calculation (improving, declining, stable)
- Health grading (productive, healthy, surviving, struggling, idle)
- Convenience functions (roi_report, visit_scorecard)
- Edge cases (empty tracker, single visit, zero-cost rejection)
"""

import pytest

from iamai.caretaker_visit_roi import (
    DEFAULT_WEIGHTS,
    VALID_KINDS,
    CaretakerVisitROI,
    VisitRecord,
    VisitYield,
    roi_report,
    visit_scorecard,
)


# --- VisitYield ---


class TestVisitYield:
    def test_default_score_all_zero(self):
        y = VisitYield()
        assert y.score == 0.0

    def test_default_score_commits_only(self):
        y = VisitYield(commits_pushed=3)
        assert y.score == 3.0  # 3 * 1.0

    def test_default_score_modules_only(self):
        y = VisitYield(modules_added=2)
        assert y.score == 6.0  # 2 * 3.0

    def test_default_score_tests_only(self):
        y = VisitYield(tests_added=10)
        assert y.score == 5.0  # 10 * 0.5

    def test_default_score_backlog_only(self):
        y = VisitYield(backlog_cleared=4)
        assert y.score == 2.0  # 4 * 0.5

    def test_default_score_notes_only(self):
        y = VisitYield(notes_written=5)
        assert y.score == pytest.approx(1.0)  # 5 * 0.2

    def test_default_score_mixed(self):
        y = VisitYield(commits_pushed=2, modules_added=1, tests_added=25)
        expected = 2 * 1.0 + 1 * 3.0 + 25 * 0.5
        assert y.score == pytest.approx(expected)

    def test_custom_weights(self):
        y = VisitYield(commits_pushed=2, modules_added=1)
        custom = {"commit": 2.0, "module": 5.0, "test": 0.0, "backlog_item": 0.0, "note": 0.0}
        assert y.score_with(custom) == pytest.approx(2 * 2.0 + 1 * 5.0)

    def test_custom_weights_missing_keys_fallback(self):
        y = VisitYield(commits_pushed=1, modules_added=1)
        custom = {"commit": 2.0}
        # module falls back to default 3.0
        assert y.score_with(custom) == pytest.approx(1 * 2.0 + 1 * 3.0)

    def test_total_outputs(self):
        y = VisitYield(commits_pushed=2, modules_added=1, tests_added=10)
        assert y.total_outputs == 13

    def test_total_outputs_empty(self):
        y = VisitYield()
        assert y.total_outputs == 0

    def test_is_empty_true(self):
        y = VisitYield()
        assert y.is_empty is True

    def test_is_empty_false_with_commit(self):
        y = VisitYield(commits_pushed=1)
        assert y.is_empty is False

    def test_is_empty_false_with_note(self):
        y = VisitYield(notes_written=1)
        assert y.is_empty is False

    def test_frozen(self):
        y = VisitYield(commits_pushed=1)
        with pytest.raises(AttributeError):
            y.commits_pushed = 2


# --- VisitRecord ---


class TestVisitRecord:
    def test_basic_creation(self):
        v = VisitRecord(visit_id=1, kind="feature", commits_pushed=2)
        assert v.visit_id == 1
        assert v.kind == "feature"
        assert v.commits_pushed == 2

    def test_default_kind_is_maintenance(self):
        v = VisitRecord(visit_id=1)
        assert v.kind == "maintenance"

    def test_default_cost_is_one(self):
        v = VisitRecord(visit_id=1)
        assert v.cost == 1.0

    def test_all_valid_kinds(self):
        for kind in VALID_KINDS:
            v = VisitRecord(visit_id=1, kind=kind)
            assert v.kind == kind

    def test_invalid_kind_raises(self):
        with pytest.raises(ValueError, match="kind must be one of"):
            VisitRecord(visit_id=1, kind="invalid")

    def test_zero_cost_raises(self):
        with pytest.raises(ValueError, match="cost must be positive"):
            VisitRecord(visit_id=1, cost=0)

    def test_negative_cost_raises(self):
        with pytest.raises(ValueError, match="cost must be positive"):
            VisitRecord(visit_id=1, cost=-1.0)

    def test_yield_property(self):
        v = VisitRecord(
            visit_id=1,
            kind="feature",
            commits_pushed=3,
            modules_added=1,
            tests_added=20,
        )
        y = v.yield_
        assert isinstance(y, VisitYield)
        assert y.commits_pushed == 3
        assert y.modules_added == 1
        assert y.tests_added == 20

    def test_roi_ratio_simple(self):
        v = VisitRecord(visit_id=1, kind="feature", commits_pushed=2, cost=1.0)
        assert v.roi_ratio == pytest.approx(2.0)

    def test_roi_ratio_high_cost(self):
        v = VisitRecord(visit_id=1, kind="feature", commits_pushed=4, cost=2.0)
        assert v.roi_ratio == pytest.approx(2.0)

    def test_roi_ratio_zero_output(self):
        v = VisitRecord(visit_id=1, kind="observation", cost=1.0)
        assert v.roi_ratio == 0.0

    def test_frozen(self):
        v = VisitRecord(visit_id=1)
        with pytest.raises(AttributeError):
            v.visit_id = 2

    def test_timestamp_optional(self):
        v = VisitRecord(visit_id=1)
        assert v.timestamp is None

    def test_timestamp_set(self):
        v = VisitRecord(visit_id=1, timestamp=1699500000.0)
        assert v.timestamp == 1699500000.0


# --- CaretakerVisitROI: basic operations ---


class TestTrackerBasic:
    def test_empty_tracker(self):
        t = CaretakerVisitROI()
        assert t.count == 0
        assert t.records == ()

    def test_record_single(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=2))
        assert t.count == 1

    def test_record_many(self):
        t = CaretakerVisitROI()
        visits = [
            VisitRecord(visit_id=1, kind="feature", commits_pushed=2),
            VisitRecord(visit_id=2, kind="recovery", commits_pushed=1),
        ]
        t.record_many(visits)
        assert t.count == 2

    def test_records_are_tuple(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1))
        assert isinstance(t.records, tuple)

    def test_records_preserve_order(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=10))
        t.record(VisitRecord(visit_id=20))
        assert t.records[0].visit_id == 10
        assert t.records[1].visit_id == 20


# --- CaretakerVisitROI: aggregate ROI ---


class TestTrackerROI:
    def test_mean_roi_empty(self):
        t = CaretakerVisitROI()
        assert t.mean_roi == 0.0

    def test_mean_roi_single(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=3))
        assert t.mean_roi == pytest.approx(3.0)

    def test_mean_roi_multiple(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=4))
        t.record(VisitRecord(visit_id=2, kind="recovery", commits_pushed=2))
        assert t.mean_roi == pytest.approx(3.0)  # (4 + 2) / 2

    def test_median_roi_odd(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=1))
        t.record(VisitRecord(visit_id=2, kind="feature", commits_pushed=3))
        t.record(VisitRecord(visit_id=3, kind="feature", commits_pushed=5))
        assert t.median_roi == pytest.approx(3.0)

    def test_median_roi_even(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=2))
        t.record(VisitRecord(visit_id=2, kind="feature", commits_pushed=4))
        assert t.median_roi == pytest.approx(3.0)  # (2 + 4) / 2

    def test_median_roi_empty(self):
        t = CaretakerVisitROI()
        assert t.median_roi == 0.0

    def test_max_roi(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=2))
        t.record(VisitRecord(visit_id=2, kind="feature", commits_pushed=8))
        t.record(VisitRecord(visit_id=3, kind="feature", commits_pushed=4))
        assert t.max_roi == pytest.approx(8.0)

    def test_max_roi_empty(self):
        t = CaretakerVisitROI()
        assert t.max_roi == 0.0

    def test_total_yield_score(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=3))
        t.record(VisitRecord(visit_id=2, kind="recovery", commits_pushed=1))
        assert t.total_yield_score == pytest.approx(4.0)

    def test_total_cost(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, cost=1.0))
        t.record(VisitRecord(visit_id=2, cost=2.5))
        assert t.total_cost == pytest.approx(3.5)

    def test_overall_roi(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=4, cost=1.0))
        t.record(VisitRecord(visit_id=2, kind="recovery", commits_pushed=2, cost=1.0))
        assert t.overall_roi == pytest.approx(3.0)  # 6 / 2

    def test_overall_roi_with_cost(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=6, cost=2.0))
        t.record(VisitRecord(visit_id=2, kind="feature", commits_pushed=4, cost=3.0))
        # total yield = 10, total cost = 5
        assert t.overall_roi == pytest.approx(2.0)


# --- CaretakerVisitROI: kind breakdown ---


class TestTrackerKinds:
    def test_kind_counts(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature"))
        t.record(VisitRecord(visit_id=2, kind="recovery"))
        t.record(VisitRecord(visit_id=3, kind="feature"))
        assert t.kind_counts == {"feature": 2, "recovery": 1}

    def test_kind_counts_empty(self):
        t = CaretakerVisitROI()
        assert t.kind_counts == {}

    def test_kind_mean_roi(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=6))
        t.record(VisitRecord(visit_id=2, kind="feature", commits_pushed=4))
        t.record(VisitRecord(visit_id=3, kind="recovery", commits_pushed=1))
        means = t.kind_mean_roi
        assert means["feature"] == pytest.approx(5.0)
        assert means["recovery"] == pytest.approx(1.0)

    def test_best_kind(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", modules_added=1))
        t.record(VisitRecord(visit_id=2, kind="recovery", commits_pushed=1))
        assert t.best_kind == "feature"

    def test_best_kind_empty(self):
        t = CaretakerVisitROI()
        assert t.best_kind is None

    def test_worst_kind(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", modules_added=1))
        t.record(VisitRecord(visit_id=2, kind="observation"))
        assert t.worst_kind == "observation"

    def test_worst_kind_empty(self):
        t = CaretakerVisitROI()
        assert t.worst_kind is None

    def test_maintenance_ratio_all_maintenance(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="recovery"))
        t.record(VisitRecord(visit_id=2, kind="maintenance"))
        assert t.maintenance_ratio == pytest.approx(1.0)

    def test_maintenance_ratio_none(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature"))
        t.record(VisitRecord(visit_id=2, kind="observation"))
        assert t.maintenance_ratio == pytest.approx(0.0)

    def test_maintenance_ratio_half(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature"))
        t.record(VisitRecord(visit_id=2, kind="recovery"))
        assert t.maintenance_ratio == pytest.approx(0.5)

    def test_maintenance_ratio_empty(self):
        t = CaretakerVisitROI()
        assert t.maintenance_ratio == 0.0

    def test_feature_ratio(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature"))
        t.record(VisitRecord(visit_id=2, kind="recovery"))
        t.record(VisitRecord(visit_id=3, kind="feature"))
        t.record(VisitRecord(visit_id=4, kind="feature"))
        assert t.feature_ratio == pytest.approx(0.75)

    def test_feature_ratio_empty(self):
        t = CaretakerVisitROI()
        assert t.feature_ratio == 0.0

    def test_empty_visit_ratio(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="observation"))
        t.record(VisitRecord(visit_id=2, kind="feature", commits_pushed=1))
        t.record(VisitRecord(visit_id=3, kind="maintenance"))
        assert t.empty_visit_ratio == pytest.approx(2 / 3)

    def test_empty_visit_ratio_no_empty(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=1))
        assert t.empty_visit_ratio == pytest.approx(0.0)

    def test_empty_visit_ratio_empty_tracker(self):
        t = CaretakerVisitROI()
        assert t.empty_visit_ratio == 0.0


# --- CaretakerVisitROI: trend ---


class TestTrackerTrend:
    def test_trend_improving(self):
        t = CaretakerVisitROI()
        # ROI: 1, 2, 3, 4, 5 — clearly improving
        for i in range(5):
            t.record(VisitRecord(visit_id=i, kind="feature", commits_pushed=i + 1))
        assert t.roi_trend > 0
        assert t.trend_label == "improving"

    def test_trend_declining(self):
        t = CaretakerVisitROI()
        # ROI: 5, 4, 3, 2, 1 — declining
        for i in range(5):
            t.record(VisitRecord(visit_id=i, kind="feature", commits_pushed=5 - i))
        assert t.roi_trend < 0
        assert t.trend_label == "declining"

    def test_trend_stable(self):
        t = CaretakerVisitROI()
        # ROI: 3, 3, 3, 3 — flat
        for i in range(4):
            t.record(VisitRecord(visit_id=i, kind="feature", commits_pushed=3))
        assert t.roi_trend == pytest.approx(0.0)
        assert t.trend_label == "stable"

    def test_trend_single_visit(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=5))
        assert t.roi_trend == 0.0
        assert t.trend_label == "stable"

    def test_trend_empty(self):
        t = CaretakerVisitROI()
        assert t.roi_trend == 0.0
        assert t.trend_label == "stable"

    def test_trend_two_visits(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=2))
        t.record(VisitRecord(visit_id=2, kind="feature", commits_pushed=4))
        assert t.roi_trend > 0


# --- CaretakerVisitROI: health grade ---


class TestHealthGrade:
    def test_idle(self):
        t = CaretakerVisitROI()
        assert t.health_grade == "idle"

    def test_productive(self):
        t = CaretakerVisitROI()
        # high ROI, low maintenance
        for i in range(4):
            t.record(VisitRecord(visit_id=i, kind="feature", modules_added=1))
        assert t.mean_roi >= 3.0
        assert t.maintenance_ratio < 0.5
        assert t.health_grade == "productive"

    def test_healthy(self):
        t = CaretakerVisitROI()
        # moderate ROI, some maintenance
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=3))
        t.record(VisitRecord(visit_id=2, kind="feature", commits_pushed=2))
        t.record(VisitRecord(visit_id=3, kind="recovery", commits_pushed=1))
        assert t.health_grade == "healthy"

    def test_surviving(self):
        t = CaretakerVisitROI()
        # ROI >= 1.0 but mostly maintenance
        t.record(VisitRecord(visit_id=1, kind="recovery", commits_pushed=1))
        t.record(VisitRecord(visit_id=2, kind="recovery", commits_pushed=1))
        t.record(VisitRecord(visit_id=3, kind="recovery", commits_pushed=2))
        assert t.health_grade == "surviving"

    def test_struggling(self):
        t = CaretakerVisitROI()
        # very low ROI with high cost
        t.record(VisitRecord(visit_id=1, kind="observation", cost=5.0))
        t.record(VisitRecord(visit_id=2, kind="observation", cost=5.0))
        assert t.mean_roi < 1.0
        assert t.health_grade == "struggling"


# --- convenience functions ---


class TestConvenienceFunctions:
    def test_roi_report_empty(self):
        t = CaretakerVisitROI()
        assert roi_report(t) == "no visits recorded"

    def test_roi_report_with_data(self):
        t = CaretakerVisitROI()
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=3))
        t.record(VisitRecord(visit_id=2, kind="recovery", commits_pushed=1))
        report = roi_report(t)
        assert "2 visits" in report
        assert "mean ROI" in report
        assert "feature" in report

    def test_visit_scorecard_feature(self):
        v = VisitRecord(
            visit_id=560,
            kind="feature",
            commits_pushed=2,
            modules_added=1,
            tests_added=30,
            notes_written=1,
        )
        card = visit_scorecard(v)
        assert "visit 560" in card
        assert "feature" in card
        assert "2 commits" in card
        assert "1 modules" in card
        assert "30 tests" in card
        assert "1 notes" in card

    def test_visit_scorecard_empty(self):
        v = VisitRecord(visit_id=1, kind="observation")
        card = visit_scorecard(v)
        assert "no output" in card

    def test_visit_scorecard_backlog(self):
        v = VisitRecord(visit_id=1, kind="maintenance", backlog_cleared=8)
        card = visit_scorecard(v)
        assert "8 backlog items" in card

    def test_visit_scorecard_roi_value(self):
        v = VisitRecord(visit_id=1, kind="feature", commits_pushed=4, cost=2.0)
        card = visit_scorecard(v)
        assert "ROI 2.00" in card


# --- custom weights ---


class TestCustomWeights:
    def test_tracker_with_custom_weights(self):
        t = CaretakerVisitROI(weights={"commit": 2.0, "module": 10.0})
        t.record(VisitRecord(visit_id=1, kind="feature", modules_added=1))
        # module weight is now 10.0 instead of 3.0
        assert t.total_yield_score == pytest.approx(10.0)

    def test_tracker_custom_weights_partial(self):
        t = CaretakerVisitROI(weights={"note": 1.0})
        t.record(VisitRecord(visit_id=1, kind="feature", commits_pushed=1, notes_written=1))
        # commit stays at default 1.0, note is now 1.0
        assert t.total_yield_score == pytest.approx(2.0)

    def test_default_weights_unchanged(self):
        """Ensure constructing with custom weights doesn't mutate defaults."""
        original_module_weight = DEFAULT_WEIGHTS["module"]
        CaretakerVisitROI(weights={"module": 99.0})
        assert DEFAULT_WEIGHTS["module"] == original_module_weight


# --- integration: realistic visit sequence ---


class TestIntegration:
    def test_typical_caretaker_session(self):
        """Simulate a realistic sequence of caretaker visits."""
        t = CaretakerVisitROI()

        # visit 1: overnight stall recovery
        t.record(VisitRecord(
            visit_id=1, kind="recovery",
            commits_pushed=1, backlog_cleared=8,
            cost=1.0,
        ))

        # visit 2: feature addition
        t.record(VisitRecord(
            visit_id=2, kind="feature",
            commits_pushed=2, modules_added=1, tests_added=37, notes_written=1,
            cost=1.0,
        ))

        # visit 3: quick status check
        t.record(VisitRecord(
            visit_id=3, kind="observation",
            cost=0.5,
        ))

        # visit 4: another feature
        t.record(VisitRecord(
            visit_id=4, kind="feature",
            commits_pushed=2, modules_added=1, tests_added=25, notes_written=1,
            cost=1.0,
        ))

        assert t.count == 4
        assert t.health_grade in ("productive", "healthy")
        assert t.best_kind == "feature"
        assert t.maintenance_ratio < 0.5
        assert t.feature_ratio == pytest.approx(0.5)
        assert t.empty_visit_ratio == pytest.approx(0.25)  # visit 3 is empty

        report = roi_report(t)
        assert "4 visits" in report
