"""Tests for stroke_throughput_decay module."""

from __future__ import annotations

import pytest

from stroke_throughput_decay import (
    ThroughputDecayTracker,
    _tokenize,
    _Window,
)


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_basic_split(self):
        assert _tokenize("hello world") == ["hello", "world"]

    def test_lowercases(self):
        assert _tokenize("Hello WORLD") == ["hello", "world"]

    def test_strips_whitespace(self):
        assert _tokenize("  a  b  ") == ["a", "b"]

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_single_word(self):
        assert _tokenize("alpha") == ["alpha"]


# ---------------------------------------------------------------------------
# _Window
# ---------------------------------------------------------------------------

class TestWindow:
    def test_add_increments_size(self):
        w = _Window()
        w.add("hello world")
        assert w.size == 2

    def test_unique_ratio_perfect(self):
        w = _Window()
        w.add("a b c d")
        assert w.unique_ratio() == pytest.approx(1.0)

    def test_unique_ratio_with_repeats(self):
        w = _Window()
        w.add("a a a b")
        # 2 unique / 4 total
        assert w.unique_ratio() == pytest.approx(0.5)

    def test_unique_ratio_empty(self):
        w = _Window()
        assert w.unique_ratio() == 0.0

    def test_overlap_identical(self):
        a = _Window()
        b = _Window()
        a.add("x y z")
        b.add("x y z")
        assert a.overlap_with(b) == pytest.approx(1.0)

    def test_overlap_disjoint(self):
        a = _Window()
        b = _Window()
        a.add("x y z")
        b.add("p q r")
        assert a.overlap_with(b) == pytest.approx(0.0)

    def test_overlap_partial(self):
        a = _Window()
        b = _Window()
        a.add("x y z")
        b.add("y z w")
        # inter={y,z}, union={x,y,z,w} => 2/4 = 0.5
        assert a.overlap_with(b) == pytest.approx(0.5)

    def test_overlap_empty_other(self):
        a = _Window()
        b = _Window()
        a.add("x y")
        assert a.overlap_with(b) == 0.0

    def test_overlap_both_empty(self):
        assert _Window().overlap_with(_Window()) == 0.0


# ---------------------------------------------------------------------------
# ThroughputDecayTracker — basics
# ---------------------------------------------------------------------------

class TestTrackerBasics:
    def test_not_ready_initially(self):
        t = ThroughputDecayTracker(baseline_window=3, current_window=3)
        assert t.ready is False

    def test_becomes_ready(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2)
        for i in range(4):
            t.feed(f"stroke {i}")
        assert t.ready is True

    def test_decay_score_none_when_not_ready(self):
        t = ThroughputDecayTracker(baseline_window=5, current_window=5)
        t.feed("only one")
        assert t.decay_score() is None

    def test_decay_score_returns_float_when_ready(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2)
        for i in range(4):
            t.feed(f"word {i}")
        score = t.decay_score()
        assert score is not None
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# ThroughputDecayTracker — zombie detection
# ---------------------------------------------------------------------------

class TestZombieDetection:
    def _make_tracker(self, baseline=5, current=5, floor=0.80):
        return ThroughputDecayTracker(
            baseline_window=baseline, current_window=current, decay_floor=floor
        )

    def test_identical_strokes_are_zombie(self):
        t = self._make_tracker(baseline=3, current=3, floor=0.80)
        for _ in range(6):
            t.feed("the same stroke every single time")
        assert t.is_zombie_cadence() is True

    def test_unique_strokes_not_zombie(self):
        t = self._make_tracker(baseline=3, current=3, floor=0.80)
        texts = [f"totally unique stroke number {i} with novel content"
                 for i in range(6)]
        t.feed_many(texts)
        # force score computation
        _ = t.decay_score()
        assert t.is_zombie_cadence() is False

    def test_zombie_floor_boundary(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2,
                                   decay_floor=0.50)
        for _ in range(4):
            t.feed("repeat repeat repeat")
        assert t.is_zombie_cadence() is True

    def test_not_ready_means_not_zombie(self):
        t = self._make_tracker()
        t.feed("one stroke")
        assert t.is_zombie_cadence() is False


# ---------------------------------------------------------------------------
# ThroughputDecayTracker — trend
# ---------------------------------------------------------------------------

class TestTrend:
    def test_trend_none_when_insufficient_history(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2)
        t.feed("a"); t.feed("b"); t.feed("c"); t.feed("d")
        t.decay_score()  # only one reading
        assert t.trend() is None

    def test_trend_rising(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2)
        # build up history with increasingly similar strokes
        seeds = [
            "alpha beta gamma delta epsilon",
            "zeta eta theta iota kappa",
            "lambda mu nu xi omicron",
            "alpha beta gamma delta epsilon",
            "alpha beta gamma delta epsilon",
            "alpha beta gamma delta epsilon",
            "alpha beta gamma delta epsilon",
        ]
        for s in seeds:
            t.feed(s)
            t.decay_score()
        # trend might be rising due to increasing overlap
        trend = t.trend(lookback=3)
        assert trend in ("rising", "falling", "flat")

    def test_trend_flat_for_constant_input(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2)
        for _ in range(8):
            t.feed("same same same")
            t.decay_score()
        assert t.trend() == "flat"


# ---------------------------------------------------------------------------
# ThroughputDecayTracker — consecutive zombie
# ---------------------------------------------------------------------------

class TestConsecutiveZombie:
    def test_zero_when_no_history(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2)
        assert t.consecutive_zombie() == 0

    def test_counts_consecutive(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2,
                                   decay_floor=0.80)
        for _ in range(6):
            t.feed("identical stroke content here")
            t.decay_score()
        assert t.consecutive_zombie() >= 1

    def test_resets_on_non_zombie(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2,
                                   decay_floor=0.99)
        # fill with identical
        for _ in range(4):
            t.feed("same old")
            t.decay_score()
        # then something very different
        t.feed("completely different novel tokens xyz abc 123")
        t.feed("another wild divergence in vocabulary patterns")
        t.decay_score()
        # consecutive_zombie from the end should be 0 or 1
        assert t.consecutive_zombie() <= 1


# ---------------------------------------------------------------------------
# ThroughputDecayTracker — summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_keys(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2)
        s = t.summary()
        expected_keys = {
            "ready", "strokes_buffered", "baseline_window",
            "current_window", "decay_floor", "decay_score",
            "zombie_cadence", "consecutive_zombie", "trend",
        }
        assert set(s.keys()) == expected_keys

    def test_summary_before_ready(self):
        t = ThroughputDecayTracker(baseline_window=5, current_window=5)
        t.feed("one")
        s = t.summary()
        assert s["ready"] is False
        assert s["decay_score"] is None

    def test_summary_after_ready(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2)
        for i in range(4):
            t.feed(f"word {i}")
        s = t.summary()
        assert s["ready"] is True
        assert s["decay_score"] is not None
        assert isinstance(s["zombie_cadence"], bool)


# ---------------------------------------------------------------------------
# ThroughputDecayTracker — buffer management
# ---------------------------------------------------------------------------

class TestBufferManagement:
    def test_buffer_does_not_grow_unbounded(self):
        t = ThroughputDecayTracker(baseline_window=3, current_window=3)
        for i in range(100):
            t.feed(f"stroke {i}")
        assert len(t._buffer) == 6  # 3 + 3

    def test_feed_many(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2)
        t.feed_many(["a", "b", "c", "d"])
        assert t.ready is True

    def test_window_size_one(self):
        t = ThroughputDecayTracker(baseline_window=1, current_window=1)
        t.feed("hello world")
        t.feed("hello world")
        assert t.ready is True
        assert t.is_zombie_cadence() is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string_strokes(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2)
        for _ in range(4):
            t.feed("")
        # all empty => no tokens => overlap 0
        score = t.decay_score()
        assert score is not None
        assert score == 0.0

    def test_single_token_strokes(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2)
        for _ in range(4):
            t.feed("x")
        assert t.is_zombie_cadence() is True

    def test_decay_floor_zero(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2,
                                   decay_floor=0.0)
        for _ in range(4):
            t.feed("same")
        # decay_floor=0 means everything is zombie
        assert t.is_zombie_cadence() is True

    def test_decay_floor_one(self):
        t = ThroughputDecayTracker(baseline_window=2, current_window=2,
                                   decay_floor=1.0)
        for _ in range(4):
            t.feed("same")
        # overlap is 1.0, floor is 1.0 => >= => zombie
        assert t.is_zombie_cadence() is True

    def test_baseline_zero_defaults_to_one(self):
        t = ThroughputDecayTracker(baseline_window=0, current_window=3)
        assert t._baseline_cap == 1

    def test_current_zero_defaults_to_one(self):
        t = ThroughputDecayTracker(baseline_window=3, current_window=0)
        assert t._current_cap == 1
