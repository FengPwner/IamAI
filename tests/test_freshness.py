"""Tests for snippets/freshness.py — content freshness tracker."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from freshness import FreshnessTracker, classify, freshness  # noqa: E402


# ---------------------------------------------------------------------------
# freshness()
# ---------------------------------------------------------------------------


class TestFreshness:
    def test_zero_seconds_is_fresh(self):
        assert freshness(0, half_life=60) == 1.0

    def test_negative_seconds_is_fresh(self):
        assert freshness(-100, half_life=60) == 1.0

    def test_one_half_life(self):
        assert abs(freshness(60, half_life=60) - 0.5) < 1e-9

    def test_two_half_lives(self):
        assert abs(freshness(120, half_life=60) - 0.25) < 1e-9

    def test_ten_half_lives_is_near_zero(self):
        assert freshness(600, half_life=60) < 0.01

    def test_invalid_half_life_raises(self):
        with pytest.raises(ValueError, match="half_life must be > 0"):
            freshness(10, half_life=0)
        with pytest.raises(ValueError, match="half_life must be > 0"):
            freshness(10, half_life=-5)

    def test_monotonic_decay(self):
        scores = [freshness(s, half_life=60) for s in range(0, 300, 10)]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# classify()
# ---------------------------------------------------------------------------


class TestClassify:
    def test_fresh(self):
        assert classify(1.0) == "fresh"
        assert classify(0.75) == "fresh"

    def test_warming(self):
        assert classify(0.74) == "warming"
        assert classify(0.5) == "warming"

    def test_stale(self):
        assert classify(0.49) == "stale"
        assert classify(0.2) == "stale"

    def test_ancient(self):
        assert classify(0.19) == "ancient"
        assert classify(0.0) == "ancient"


# ---------------------------------------------------------------------------
# FreshnessTracker
# ---------------------------------------------------------------------------


class TestFreshnessTracker:
    def test_empty_tracker_has_perfect_score(self):
        t = FreshnessTracker(half_life=60)
        assert t.score(clock=lambda: 100.0) == 1.0

    def test_invalid_half_life_raises(self):
        with pytest.raises(ValueError, match="half_life must be > 0"):
            FreshnessTracker(half_life=0)

    def test_touch_records_item(self):
        t = FreshnessTracker(half_life=60)
        t.touch("writer", clock=lambda: 0.0)
        assert "writer" in t.items()

    def test_score_uses_minimum(self):
        t = FreshnessTracker(half_life=60)
        t.touch("recent", clock=lambda: 50.0)  # 10s old at t=60
        t.touch("old", clock=lambda: 0.0)        # 60s old at t=60
        score = t.score(clock=lambda: 60.0)
        assert abs(score - 0.5) < 1e-9  # old item dominates

    def test_stalest_returns_oldest_item(self):
        t = FreshnessTracker(half_life=60)
        t.touch("writer", clock=lambda: 10.0)
        t.touch("caretaker", clock=lambda: 50.0)
        assert t.stalest(clock=lambda: 60.0) == "writer"

    def test_stalest_empty_returns_none(self):
        t = FreshnessTracker(half_life=60)
        assert t.stalest(clock=lambda: 0.0) is None

    def test_items_sorted(self):
        t = FreshnessTracker(half_life=60)
        t.touch("zebra", clock=lambda: 0.0)
        t.touch("alpha", clock=lambda: 0.0)
        t.touch("middle", clock=lambda: 0.0)
        assert t.items() == ["alpha", "middle", "zebra"]

    def test_ages_returns_dict(self):
        t = FreshnessTracker(half_life=60)
        t.touch("a", clock=lambda: 10.0)
        t.touch("b", clock=lambda: 20.0)
        ages = t.ages(clock=lambda: 30.0)
        assert ages["a"] == 20.0
        assert ages["b"] == 10.0

    def test_report_format(self):
        t = FreshnessTracker(half_life=60)
        t.touch("writer", clock=lambda: 0.0)
        report = t.report(clock=lambda: 0.0)
        assert "fresh" in report
        assert "writer" in report

    def test_repr(self):
        t = FreshnessTracker(half_life=300)
        assert "half_life=300" in repr(t)
        assert "items=0" in repr(t)
        t.touch("x", clock=lambda: 0.0)
        assert "items=1" in repr(t)

    def test_touch_updates_existing_item(self):
        t = FreshnessTracker(half_life=60)
        t.touch("writer", clock=lambda: 0.0)
        t.touch("writer", clock=lambda: 50.0)  # refresh
        score = t.score(clock=lambda: 60.0)
        # writer is now only 10s old, should be very fresh
        assert score > 0.85
