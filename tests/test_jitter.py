"""Tests for snippets/jitter.py — Jitter and jittered_sleep."""

from __future__ import annotations

import random

import pytest

from snippets.jitter import Jitter, jittered_sleep


# ---------------------------------------------------------------------------
# Construction / validation
# ---------------------------------------------------------------------------

class TestJitterInit:
    def test_default_strategy_is_equal(self):
        j = Jitter(interval=10.0)
        assert j.strategy == "equal"

    def test_zero_interval_rejected(self):
        with pytest.raises(ValueError, match="must be > 0"):
            Jitter(interval=0)

    def test_negative_interval_rejected(self):
        with pytest.raises(ValueError, match="must be > 0"):
            Jitter(interval=-5)

    def test_unknown_strategy_rejected(self):
        with pytest.raises(ValueError, match="unknown strategy"):
            Jitter(interval=1.0, strategy="chaos")

    def test_interval_property(self):
        j = Jitter(interval=42.0)
        assert j.interval == 42.0


# ---------------------------------------------------------------------------
# "full" strategy: result in [0, interval]
# ---------------------------------------------------------------------------

class TestFullStrategy:
    def test_within_bounds(self):
        rng = random.Random(7)
        j = Jitter(interval=10.0, strategy="full", rng=rng)
        for _ in range(200):
            v = j.next()
            assert 0 <= v <= 10.0

    def test_covers_range(self):
        """With enough samples we should see values near both ends."""
        rng = random.Random(99)
        j = Jitter(interval=10.0, strategy="full", rng=rng)
        values = [j.next() for _ in range(500)]
        assert min(values) < 1.0
        assert max(values) > 9.0


# ---------------------------------------------------------------------------
# "equal" strategy: result in [interval/2, interval]
# ---------------------------------------------------------------------------

class TestEqualStrategy:
    def test_within_bounds(self):
        rng = random.Random(11)
        j = Jitter(interval=20.0, strategy="equal", rng=rng)
        for _ in range(200):
            v = j.next()
            assert 10.0 <= v <= 20.0

    def test_never_below_half(self):
        rng = random.Random(0)
        j = Jitter(interval=6.0, strategy="equal", rng=rng)
        assert all(j.next() >= 3.0 for _ in range(100))


# ---------------------------------------------------------------------------
# "decorr" strategy: decorrelated exponential back-off
# ---------------------------------------------------------------------------

class TestDecorrStrategy:
    def test_within_bounds(self):
        rng = random.Random(3)
        j = Jitter(interval=10.0, strategy="decorr", rng=rng)
        for _ in range(200):
            v = j.next()
            # lower bound is always interval/2; upper bound is interval*2
            assert 5.0 <= v <= 20.0

    def test_reset_restores_initial_state(self):
        rng = random.Random(5)
        j = Jitter(interval=10.0, strategy="decorr", rng=rng)
        # produce a few values to move _prev away from interval
        for _ in range(5):
            j.next()
        j.reset()
        # after reset, _prev == interval, so first sample should be in
        # [interval/2, interval*2]
        v = j.next()
        assert 5.0 <= v <= 20.0


# ---------------------------------------------------------------------------
# Deterministic seeding
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_seed_same_sequence(self):
        seqs = []
        for _ in range(2):
            rng = random.Random(42)
            j = Jitter(interval=15.0, strategy="equal", rng=rng)
            seqs.append([j.next() for _ in range(10)])
        assert seqs[0] == seqs[1]


# ---------------------------------------------------------------------------
# jittered_sleep convenience wrapper
# ---------------------------------------------------------------------------

class TestJitteredSleep:
    def test_returns_duration_in_range(self):
        rng = random.Random(0)
        slept: list[float] = []
        dur = jittered_sleep(
            4.0,
            strategy="equal",
            sleep_fn=lambda t: slept.append(t),
            rng=rng,
        )
        assert 2.0 <= dur <= 4.0
        assert slept == [dur]

    def test_full_strategy_sleep(self):
        rng = random.Random(1)
        dur = jittered_sleep(
            10.0,
            strategy="full",
            sleep_fn=lambda t: None,
            rng=rng,
        )
        assert 0 <= dur <= 10.0
