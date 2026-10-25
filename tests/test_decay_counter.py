"""Tests for iamai.decay_counter -- exponential freshness tracking."""

import math
import pytest

from iamai.decay_counter import DecayCounter, freshness_score


# ---------------------------------------------------------------------------
# DecayCounter basics
# ---------------------------------------------------------------------------

class TestDecayCounterBasics:
    def test_initial_value_is_zero(self):
        c = DecayCounter(half_life=60.0)
        assert c.read(now=0.0) == 0.0

    def test_single_bump(self):
        c = DecayCounter(half_life=60.0)
        v = c.bump(now=10.0)
        assert v == 1.0

    def test_read_after_bump_at_same_time(self):
        c = DecayCounter(half_life=60.0)
        c.bump(now=5.0)
        assert c.read(now=5.0) == 1.0

    def test_total_bumps(self):
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        c.bump(now=1.0)
        c.bump(now=2.0)
        assert c._total_bumps == 3


# ---------------------------------------------------------------------------
# Exponential decay
# ---------------------------------------------------------------------------

class TestExponentialDecay:
    def test_half_life_exact(self):
        """After exactly one half-life, value should be ~0.5."""
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        assert abs(c.read(now=60.0) - 0.5) < 1e-6

    def test_two_half_lives(self):
        """After two half-lives, value should be ~0.25."""
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        assert abs(c.read(now=120.0) - 0.25) < 1e-6

    def test_three_half_lives(self):
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        assert abs(c.read(now=180.0) - 0.125) < 1e-6

    def test_decay_rate_property(self):
        c = DecayCounter(half_life=100.0)
        expected = math.log(2) / 100.0
        assert abs(c.decay_rate - expected) < 1e-10

    def test_read_before_any_bump(self):
        c = DecayCounter(half_life=60.0)
        assert c.read(now=999.0) == 0.0

    def test_read_with_negative_elapsed(self):
        """Reading at a time before the last bump should not increase value."""
        c = DecayCounter(half_life=60.0)
        c.bump(now=100.0)
        # read at t=50 (before the bump) -- elapsed is clamped to 0
        assert c.read(now=50.0) == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Multiple bumps with decay
# ---------------------------------------------------------------------------

class TestMultipleBumps:
    def test_accumulation(self):
        """Two bumps close together should accumulate."""
        c = DecayCounter(half_life=600.0)
        c.bump(now=0.0)
        v = c.bump(now=1.0)  # barely decayed, so ~1.997
        assert v > 1.9

    def test_separated_bumps(self):
        """Bumps one half-life apart: first decays to 0.5, then +1 = 1.5."""
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        v = c.bump(now=60.0)
        assert abs(v - 1.5) < 1e-6

    def test_rapid_bumps(self):
        """Many rapid bumps should accumulate close to their count."""
        c = DecayCounter(half_life=3600.0)
        for i in range(10):
            c.bump(now=float(i))
        # With half-life=3600 and bumps 1s apart, decay is negligible
        assert c.read(now=10.0) > 9.5

    def test_custom_weight(self):
        c = DecayCounter(half_life=60.0)
        v = c.bump(now=0.0, weight=5.0)
        assert v == 5.0
        assert abs(c.read(now=60.0) - 2.5) < 1e-6


# ---------------------------------------------------------------------------
# Max value ceiling
# ---------------------------------------------------------------------------

class TestMaxValue:
    def test_clamped_at_max(self):
        c = DecayCounter(half_life=60.0, max_value=3.0)
        for _ in range(10):
            c.bump(now=0.0)
        assert c.read(now=0.0) == 3.0

    def test_no_ceiling_by_default(self):
        c = DecayCounter(half_life=60.0)
        for _ in range(100):
            c.bump(now=0.0)
        assert c.read(now=0.0) == 100.0

    def test_max_value_zero_means_no_ceiling(self):
        c = DecayCounter(half_life=60.0, max_value=0.0)
        c.bump(now=0.0, weight=999.0)
        assert c.read(now=0.0) == 999.0


# ---------------------------------------------------------------------------
# Freshness checks
# ---------------------------------------------------------------------------

class TestFreshness:
    def test_is_fresh_right_after_bump(self):
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        assert c.is_fresh(now=0.0, threshold=0.5) is True

    def test_is_stale_after_long_wait(self):
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        assert c.is_fresh(now=600.0, threshold=0.5) is False

    def test_time_until_stale_basic(self):
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        # Value=1.0, threshold=0.5 => one half-life until stale
        t = c.time_until_stale(now=0.0, threshold=0.5)
        assert abs(t - 60.0) < 1e-4

    def test_time_until_stale_already_stale(self):
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        assert c.time_until_stale(now=600.0, threshold=0.5) == 0.0

    def test_time_until_stale_nonpositive_threshold(self):
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        assert c.time_until_stale(now=0.0, threshold=0.0) == float("inf")

    def test_default_threshold(self):
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        # Default threshold is 0.5
        assert c.is_fresh(now=30.0) is True
        assert c.is_fresh(now=90.0) is False


# ---------------------------------------------------------------------------
# Summary and reset
# ---------------------------------------------------------------------------

class TestSummaryAndReset:
    def test_summary_keys(self):
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        s = c.summary(now=30.0)
        expected_keys = {"value", "half_life", "max_value", "total_bumps", "is_fresh", "time_until_stale"}
        assert set(s.keys()) == expected_keys

    def test_summary_value_decayed(self):
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        s = c.summary(now=60.0)
        assert abs(s["value"] - 0.5) < 1e-4

    def test_reset_clears_everything(self):
        c = DecayCounter(half_life=60.0)
        c.bump(now=0.0)
        c.bump(now=10.0)
        c.reset()
        assert c.read(now=100.0) == 0.0
        assert c._total_bumps == 0
        assert c._last_bump == -1.0


# ---------------------------------------------------------------------------
# freshness_score (one-shot analysis)
# ---------------------------------------------------------------------------

class TestFreshnessScore:
    def test_empty_events(self):
        result = freshness_score([], half_life=60.0, now=100.0)
        assert result["value"] == 0.0
        assert result["is_fresh"] is False
        assert result["total_events"] == 0

    def test_recent_events_are_fresh(self):
        events = [0.0, 10.0, 20.0, 30.0]
        result = freshness_score(events, half_life=60.0, now=35.0)
        assert result["is_fresh"] is True
        assert result["total_events"] == 4
        assert result["events_in_window"] == 4  # all within 180s window

    def test_old_events_are_stale(self):
        events = [0.0, 10.0]
        result = freshness_score(events, half_life=10.0, now=1000.0)
        assert result["is_fresh"] is False

    def test_events_in_window(self):
        events = [0.0, 100.0, 200.0, 1000.0]
        result = freshness_score(events, half_life=60.0, now=1010.0)
        # Window = 180s, cutoff = 1010 - 180 = 830
        # Only event at 1000.0 is within window
        assert result["events_in_window"] == 1

    def test_half_life_in_result(self):
        result = freshness_score([0.0], half_life=42.0, now=1.0)
        assert result["half_life"] == 42.0
