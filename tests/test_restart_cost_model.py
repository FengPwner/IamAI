"""Tests for iamai.restart_cost_model — restart cost quantification.

Covers:
- Single restart event scoring (dead zone, lost strokes, warm-up)
- Zero-cost restart (instant recovery, no backlog)
- High-cost restart (long dead zone, many lost strokes)
- Aggregate summary across multiple events
- Verdict classification thresholds
- Edge cases: no events, no first stroke, negative intervals
- Custom weights and scales
- Convenience functions (cost_report, cost_summary)
"""

import math

import pytest

from iamai.restart_cost_model import (
    RestartCost,
    RestartCostModel,
    RestartEvent,
    cost_report,
    cost_summary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def model():
    """A fresh model with default settings."""
    return RestartCostModel(expected_cadence=15.0)


@pytest.fixture
def cheap_event():
    """A restart with a 60-second dead zone and instant recovery."""
    return RestartEvent(
        death_time=1700000000,
        restart_time=1700000060,
        first_stroke_after=1700000075,  # one cadence after restart
        backlog_files=0,
        strokes_before=1000,
        strokes_after=1000,
        label="cheap",
    )


@pytest.fixture
def expensive_event():
    """A restart with a 1-hour dead zone and heavy backlog."""
    return RestartEvent(
        death_time=1700000000,
        restart_time=1700003600,
        first_stroke_after=1700003900,  # 300s warm-up
        backlog_files=15,
        strokes_before=1000,
        strokes_after=1000,
        label="expensive",
    )


# ---------------------------------------------------------------------------
# Single-event scoring
# ---------------------------------------------------------------------------

class TestSingleEvent:
    def test_dead_zone_computed(self, model, cheap_event):
        rc = model.add_event(cheap_event)
        assert rc.dead_zone_s == 60.0

    def test_lost_strokes_estimated(self, model, cheap_event):
        rc = model.add_event(cheap_event)
        # 60s dead zone / 15s cadence = 4 expected strokes, 0 produced
        assert rc.lost_strokes == 4

    def test_recovery_overhead(self, model, cheap_event):
        rc = model.add_event(cheap_event)
        assert rc.recovery_overhead_s == 15.0  # one cadence

    def test_cost_positive(self, model, cheap_event):
        rc = model.add_event(cheap_event)
        assert rc.cost > 0.0

    def test_cost_bounded(self, model, expensive_event):
        rc = model.add_event(expensive_event)
        assert 0.0 <= rc.cost < 1.0

    def test_expensive_costs_more(self, model, cheap_event, expensive_event):
        rc_cheap = model.add_event(cheap_event)
        model2 = RestartCostModel(expected_cadence=15.0)
        rc_expensive = model2.add_event(expensive_event)
        assert rc_expensive.cost > rc_cheap.cost


class TestZeroCostRestart:
    def test_instant_restart_zero_backlog(self, model):
        event = RestartEvent(
            death_time=1000,
            restart_time=1000,
            first_stroke_after=1015,
            backlog_files=0,
            strokes_before=500,
            strokes_after=500,
        )
        rc = model.add_event(event)
        assert rc.dead_zone_s == 0.0
        assert rc.lost_strokes == 0
        # warm-up is 15s so there's still a small warm-up cost
        assert rc.cost < 0.02  # near-zero but not exactly zero

    def test_perfect_restart(self, model):
        """Zero dead zone, zero backlog, zero warm-up."""
        event = RestartEvent(
            death_time=1000,
            restart_time=1000,
            first_stroke_after=1000,
            backlog_files=0,
            strokes_before=500,
            strokes_after=500,
        )
        rc = model.add_event(event)
        assert rc.cost == 0.0


class TestNoFirstStroke:
    def test_warm_up_defaults_to_cadence_times_four(self, model):
        event = RestartEvent(
            death_time=1000,
            restart_time=1060,
            first_stroke_after=None,  # no stroke yet
            backlog_files=0,
            strokes_before=500,
            strokes_after=500,
        )
        rc = model.add_event(event)
        assert rc.recovery_overhead_s == 60.0  # 15 * 4


class TestNegativeIntervals:
    def test_death_after_restart_clamped(self, model):
        """If death_time > restart_time (clock skew), dead zone is 0."""
        event = RestartEvent(
            death_time=2000,
            restart_time=1000,
            first_stroke_after=1015,
            backlog_files=0,
            strokes_before=100,
            strokes_after=100,
        )
        rc = model.add_event(event)
        assert rc.dead_zone_s == 0.0

    def test_first_stroke_before_restart_clamped(self, model):
        """If first stroke timestamp predates restart, warm-up is 0."""
        event = RestartEvent(
            death_time=1000,
            restart_time=2000,
            first_stroke_after=1500,
            backlog_files=0,
            strokes_before=100,
            strokes_after=101,
        )
        rc = model.add_event(event)
        assert rc.recovery_overhead_s == 0.0


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_empty_model(self, model):
        s = model.summary()
        assert s["restarts"] == 0
        assert s["mean_cost"] == 0.0
        assert s["total_lost_strokes"] == 0
        assert s["verdict"] == "no_data"

    def test_single_event_summary(self, model, cheap_event):
        model.add_event(cheap_event)
        s = model.summary()
        assert s["restarts"] == 1
        assert s["mean_cost"] > 0
        assert s["total_lost_strokes"] == 4
        assert s["mean_dead_zone_s"] == 60.0
        assert s["verdict"] in ("negligible", "acceptable", "concerning", "critical")

    def test_multiple_events(self, model, cheap_event, expensive_event):
        model.add_event(cheap_event)
        model.add_event(expensive_event)
        s = model.summary()
        assert s["restarts"] == 2
        # mean should be between the two individual costs
        assert s["mean_cost"] < s["worst_cost"]

    def test_worst_cost_is_max(self, model, cheap_event, expensive_event):
        model.add_event(cheap_event)
        model.add_event(expensive_event)
        costs = model.costs()
        assert model.worst_cost == max(c.cost for c in costs)

    def test_total_lost_strokes_sums(self, model, cheap_event, expensive_event):
        model.add_event(cheap_event)
        model.add_event(expensive_event)
        assert model.total_lost_strokes == (
            model.costs()[0].lost_strokes + model.costs()[1].lost_strokes
        )


# ---------------------------------------------------------------------------
# Verdict thresholds
# ---------------------------------------------------------------------------

class TestVerdict:
    def test_no_data(self, model):
        assert model._verdict() == "no_data"

    def test_negligible(self):
        model = RestartCostModel(expected_cadence=15.0)
        model.add_event(RestartEvent(
            death_time=1000, restart_time=1000,
            first_stroke_after=1000,
        ))
        assert model._verdict() == "negligible"

    def test_acceptable(self, model, cheap_event):
        model.add_event(cheap_event)
        assert model._verdict() in ("negligible", "acceptable")

    def test_concerning(self):
        model = RestartCostModel(expected_cadence=15.0)
        # Several moderately bad restarts
        for i in range(5):
            model.add_event(RestartEvent(
                death_time=i * 1000,
                restart_time=i * 1000 + 600,
                first_stroke_after=i * 1000 + 800,
                backlog_files=5,
                strokes_before=i * 100,
                strokes_after=i * 100,
            ))
        assert model._verdict() in ("concerning", "critical")

    def test_critical(self):
        model = RestartCostModel(expected_cadence=15.0)
        # Catastrophic restarts
        for i in range(3):
            model.add_event(RestartEvent(
                death_time=i * 10000,
                restart_time=i * 10000 + 7200,  # 2h dead zone
                first_stroke_after=i * 10000 + 7800,
                backlog_files=20,
                strokes_before=i * 500,
                strokes_after=i * 500,
            ))
        assert model._verdict() == "critical"


# ---------------------------------------------------------------------------
# Custom weights and scales
# ---------------------------------------------------------------------------

class TestCustomWeights:
    def test_heavy_backlog_weight(self, cheap_event):
        model_back = RestartCostModel(
            expected_cadence=15.0,
            weights={"dead": 0.1, "lost": 0.1, "back": 0.7, "warm": 0.1},
        )
        model_default = RestartCostModel(expected_cadence=15.0)

        event = RestartEvent(
            death_time=1000, restart_time=1060,
            first_stroke_after=1075,
            backlog_files=8,
            strokes_before=500, strokes_after=500,
        )
        rc_back = model_back.add_event(event)
        rc_default = model_default.add_event(event)
        # With heavy backlog weight, cost should be higher for events
        # with backlog > 0
        assert rc_back.cost > rc_default.cost

    def test_custom_scales(self, cheap_event):
        model = RestartCostModel(
            expected_cadence=15.0,
            scales={"dead": 60.0},  # 60s = full-scale (was 3600s)
        )
        rc = model.add_event(cheap_event)
        # With a much smaller dead-zone scale, the normalised dead-zone
        # value is much higher, so cost should be higher than default.
        default_model = RestartCostModel(expected_cadence=15.0)
        rc_default = default_model.add_event(cheap_event)
        assert rc.cost > rc_default.cost


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

class TestConvenienceFunctions:
    def test_cost_report_empty(self, model):
        assert cost_report(model) == "no restart events recorded"

    def test_cost_report_with_data(self, model, cheap_event):
        model.add_event(cheap_event)
        report = cost_report(model)
        assert "1 restart(s)" in report
        assert "verdict:" in report

    def test_cost_summary(self, cheap_event, expensive_event):
        s = cost_summary([cheap_event, expensive_event], expected_cadence=15.0)
        assert s["restarts"] == 2
        assert s["total_lost_strokes"] > 0

    def test_cost_summary_empty(self):
        s = cost_summary([], expected_cadence=15.0)
        assert s["restarts"] == 0
        assert s["verdict"] == "no_data"


# ---------------------------------------------------------------------------
# Batch operations
# ---------------------------------------------------------------------------

class TestBatchOperations:
    def test_add_events(self, model, cheap_event, expensive_event):
        results = model.add_events([cheap_event, expensive_event])
        assert len(results) == 2
        assert model.restarts == 2

    def test_add_empty_list(self, model):
        results = model.add_events([])
        assert results == []
        assert model.restarts == 0

    def test_costs_returns_copy(self, model, cheap_event):
        model.add_event(cheap_event)
        costs1 = model.costs()
        costs2 = model.costs()
        assert costs1 is not costs2
        assert len(costs1) == len(costs2)


# ---------------------------------------------------------------------------
# Edge cases with strokes_after > strokes_before
# ---------------------------------------------------------------------------

class TestStrokeGainDuringDeadZone:
    def test_strokes_produced_during_dead_zone(self, model):
        """If the writer somehow produced strokes during dead zone,
        lost strokes should be reduced."""
        event = RestartEvent(
            death_time=1000,
            restart_time=1060,  # 60s dead zone = 4 expected
            first_stroke_after=1075,
            backlog_files=0,
            strokes_before=500,
            strokes_after=502,  # 2 strokes appeared somehow
        )
        rc = model.add_event(event)
        assert rc.lost_strokes == 2  # 4 expected - 2 actual

    def test_more_strokes_than_expected(self, model):
        """If more strokes were produced than expected, lost = 0."""
        event = RestartEvent(
            death_time=1000,
            restart_time=1060,  # 60s dead zone = 4 expected
            first_stroke_after=1075,
            backlog_files=0,
            strokes_before=500,
            strokes_after=510,  # 10 strokes appeared (> 4 expected)
        )
        rc = model.add_event(event)
        assert rc.lost_strokes == 0
