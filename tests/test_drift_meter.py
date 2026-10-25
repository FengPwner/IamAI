"""Tests for iamai.drift_meter module."""

from __future__ import annotations

import pytest

from iamai.drift_meter import (
    GROWING,
    NONE,
    PULL_NOW,
    SHRINKING,
    STABLE,
    WATCH,
    DriftMeter,
)


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------

class TestInit:
    def test_defaults(self):
        dm = DriftMeter()
        assert dm.history == 50
        assert dm.count == 0
        assert dm.ahead == 0
        assert dm.behind == 0
        assert dm.ratio == 0.0
        assert dm.total_drift == 0
        assert dm.alert == NONE

    def test_custom_params(self):
        dm = DriftMeter(history=10, watch_behind=1, pull_now_behind=3)
        assert dm.history == 10
        assert dm.watch_behind == 1
        assert dm.pull_now_behind == 3


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------

class TestMeasure:
    def test_single_clean(self):
        dm = DriftMeter()
        snap = dm.measure(ahead=2, behind=0)
        assert snap.ahead == 2
        assert snap.behind == 0
        assert dm.count == 1
        assert dm.ahead == 2
        assert dm.behind == 0

    def test_single_diverged(self):
        dm = DriftMeter()
        snap = dm.measure(ahead=1, behind=3)
        assert snap.ahead == 1
        assert snap.behind == 3
        assert snap.total == 4
        assert snap.ratio == 3.0

    def test_negative_clamped(self):
        dm = DriftMeter()
        snap = dm.measure(ahead=-5, behind=-2)
        assert snap.ahead == 0
        assert snap.behind == 0

    def test_multiple_measurements(self):
        dm = DriftMeter()
        dm.measure(ahead=1, behind=0)
        dm.measure(ahead=2, behind=0)
        dm.measure(ahead=1, behind=1)
        assert dm.count == 3
        assert dm.ahead == 1
        assert dm.behind == 1

    def test_history_ring_eviction(self):
        dm = DriftMeter(history=3)
        for i in range(5):
            dm.measure(ahead=i, behind=0)
        assert dm.count == 3
        # oldest two (0, 1) evicted; latest is 4
        assert dm.ahead == 4


# ---------------------------------------------------------------------------
# ratio
# ---------------------------------------------------------------------------

class TestRatio:
    def test_zero_ahead_zero_behind(self):
        dm = DriftMeter()
        dm.measure(ahead=0, behind=0)
        assert dm.ratio == 0.0  # 0 / max(0, 1) = 0

    def test_ahead_only(self):
        dm = DriftMeter()
        dm.measure(ahead=5, behind=0)
        assert dm.ratio == 0.0

    def test_behind_only(self):
        dm = DriftMeter()
        dm.measure(ahead=0, behind=3)
        assert dm.ratio == 3.0  # 3 / max(0, 1) = 3

    def test_equal_divergence(self):
        dm = DriftMeter()
        dm.measure(ahead=3, behind=3)
        assert dm.ratio == 1.0

    def test_behind_double(self):
        dm = DriftMeter()
        dm.measure(ahead=2, behind=4)
        assert dm.ratio == 2.0


# ---------------------------------------------------------------------------
# alert
# ---------------------------------------------------------------------------

class TestAlert:
    def test_none_when_empty(self):
        dm = DriftMeter()
        assert dm.alert == NONE

    def test_none_when_synced(self):
        dm = DriftMeter()
        dm.measure(ahead=0, behind=0)
        assert dm.alert == NONE

    def test_none_ahead_only(self):
        dm = DriftMeter()
        dm.measure(ahead=5, behind=0)
        assert dm.alert == NONE

    def test_watch_on_behind_count(self):
        dm = DriftMeter()
        dm.measure(ahead=2, behind=2)
        # ratio 1.0 >= watch_ratio but < pull_now_ratio; behind 2 >= watch_behind
        assert dm.alert == WATCH

    def test_watch_on_ratio(self):
        dm = DriftMeter(watch_ratio=0.5)
        dm.measure(ahead=2, behind=1)
        assert dm.alert == WATCH  # ratio 0.5 >= watch_ratio 0.5

    def test_pull_now_on_behind_count(self):
        dm = DriftMeter()
        dm.measure(ahead=0, behind=5)
        assert dm.alert == PULL_NOW

    def test_pull_now_on_ratio(self):
        dm = DriftMeter()
        dm.measure(ahead=1, behind=2)
        # ratio = 2.0 >= pull_now_ratio default 2.0
        assert dm.alert == PULL_NOW

    def test_pull_now_overrides_watch(self):
        dm = DriftMeter()
        dm.measure(ahead=0, behind=10)
        assert dm.alert == PULL_NOW

    def test_custom_thresholds(self):
        dm = DriftMeter(watch_behind=1, pull_now_behind=2)
        dm.measure(ahead=0, behind=1)
        assert dm.alert == WATCH
        dm.measure(ahead=0, behind=2)
        assert dm.alert == PULL_NOW


# ---------------------------------------------------------------------------
# trend
# ---------------------------------------------------------------------------

class TestTrend:
    def test_stable_when_empty(self):
        dm = DriftMeter()
        assert dm.trend == STABLE

    def test_stable_with_one(self):
        dm = DriftMeter()
        dm.measure(ahead=1, behind=1)
        assert dm.trend == STABLE

    def test_growing(self):
        dm = DriftMeter()
        dm.measure(ahead=1, behind=0)  # total 1
        dm.measure(ahead=1, behind=2)  # total 3
        assert dm.trend == GROWING

    def test_shrinking(self):
        dm = DriftMeter()
        dm.measure(ahead=2, behind=5)  # total 7
        dm.measure(ahead=1, behind=1)  # total 2
        assert dm.trend == SHRINKING

    def test_stable_same_total(self):
        dm = DriftMeter()
        dm.measure(ahead=2, behind=1)  # total 3
        dm.measure(ahead=1, behind=2)  # total 3
        assert dm.trend == STABLE


# ---------------------------------------------------------------------------
# peak & avg
# ---------------------------------------------------------------------------

class TestPeakAvg:
    def test_peak_behind_empty(self):
        dm = DriftMeter()
        assert dm.peak_behind == 0

    def test_peak_behind(self):
        dm = DriftMeter()
        dm.measure(ahead=0, behind=2)
        dm.measure(ahead=0, behind=8)
        dm.measure(ahead=0, behind=3)
        assert dm.peak_behind == 8

    def test_avg_total_empty(self):
        dm = DriftMeter()
        assert dm.avg_total == 0.0

    def test_avg_total(self):
        dm = DriftMeter()
        dm.measure(ahead=1, behind=0)  # total 1
        dm.measure(ahead=2, behind=1)  # total 3
        dm.measure(ahead=0, behind=2)  # total 2
        assert dm.avg_total == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# advise
# ---------------------------------------------------------------------------

class TestAdvise:
    def test_no_data(self):
        dm = DriftMeter()
        assert "no data" in dm.advise()

    def test_synced(self):
        dm = DriftMeter()
        dm.measure(ahead=0, behind=0)
        assert "synced" in dm.advise()

    def test_queued_for_push(self):
        dm = DriftMeter()
        dm.measure(ahead=3, behind=0)
        advice = dm.advise()
        assert "3 commit(s)" in advice
        assert "push" in advice

    def test_watch_advice(self):
        dm = DriftMeter()
        dm.measure(ahead=2, behind=2)
        advice = dm.advise()
        assert "watch" in advice
        assert "2" in advice

    def test_pull_now_diverged(self):
        dm = DriftMeter()
        dm.measure(ahead=2, behind=5)
        advice = dm.advise()
        assert "pull now" in advice
        assert "rebase" in advice

    def test_pull_now_behind_only(self):
        dm = DriftMeter()
        dm.measure(ahead=0, behind=6)
        advice = dm.advise()
        assert "pull now" in advice
        assert "fast-forward" in advice


# ---------------------------------------------------------------------------
# snapshot dataclass
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_total(self):
        dm = DriftMeter()
        snap = dm.measure(ahead=3, behind=4)
        assert snap.total == 7

    def test_ratio_property(self):
        dm = DriftMeter()
        snap = dm.measure(ahead=2, behind=6)
        assert snap.ratio == 3.0

    def test_latest(self):
        dm = DriftMeter()
        assert dm.latest is None
        snap = dm.measure(ahead=1, behind=1)
        assert dm.latest is snap
