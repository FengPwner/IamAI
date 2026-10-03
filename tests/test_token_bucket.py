"""Tests for snippets/token_bucket.py — capacity, refill, burst, and edges."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from token_bucket import TokenBucket  # noqa: E402


class TestBasicConsumption:
    """Bucket starts full and drains on take()."""

    def test_starts_full(self):
        b = TokenBucket(capacity=10, refill_rate=1.0, now=lambda: 0.0)
        assert b.tokens == 10.0

    def test_take_reduces_tokens(self):
        b = TokenBucket(capacity=10, refill_rate=0.0, now=lambda: 0.0)
        assert b.take(3) is True
        assert b.tokens == 7.0

    def test_take_returns_false_when_empty(self):
        b = TokenBucket(capacity=2, refill_rate=0.0, now=lambda: 0.0)
        assert b.take(2) is True
        assert b.take(1) is False

    def test_take_exact_amount(self):
        b = TokenBucket(capacity=5, refill_rate=0.0, now=lambda: 0.0)
        assert b.take(5) is True
        assert b.tokens == 0.0

    def test_take_zero_always_succeeds(self):
        b = TokenBucket(capacity=1, refill_rate=0.0, now=lambda: 0.0)
        b.take(1)  # drain
        assert b.take(0) is True


class TestRefill:
    """Tokens refill over time, capped at capacity."""

    def test_refill_after_time(self):
        t = [100.0]
        b = TokenBucket(capacity=10, refill_rate=2.0, now=lambda: t[0])
        b.take(6)  # 4 remaining
        t[0] = 102.0  # 2s * 2/s = 4 refilled → 8
        assert b.tokens == pytest.approx(8.0)

    def test_refill_capped_at_capacity(self):
        t = [0.0]
        b = TokenBucket(capacity=5, refill_rate=100.0, now=lambda: t[0])
        b.take(2)  # 3 remaining
        t[0] = 999.0  # huge elapsed time
        assert b.tokens == 5.0  # capped

    def test_zero_refill_rate_never_refills(self):
        t = [0.0]
        b = TokenBucket(capacity=3, refill_rate=0.0, now=lambda: t[0])
        b.take(3)
        t[0] = 1e9
        assert b.tokens == 0.0

    def test_partial_token_refill(self):
        t = [0.0]
        b = TokenBucket(capacity=10, refill_rate=1.0, now=lambda: t[0])
        b.take(10)  # empty
        t[0] = 0.5  # half a second → 0.5 tokens
        assert b.tokens == pytest.approx(0.5)


class TestBurst:
    """Bursts up to capacity are allowed."""

    def test_full_burst(self):
        b = TokenBucket(capacity=100, refill_rate=1.0, now=lambda: 0.0)
        assert b.take(100) is True
        assert b.tokens == 0.0

    def test_burst_then_drip(self):
        t = [0.0]
        b = TokenBucket(capacity=10, refill_rate=1.0, now=lambda: t[0])
        b.take(10)  # burst all 10
        # wait 5 seconds
        t[0] = 5.0
        assert b.tokens == pytest.approx(5.0)
        assert b.take(5) is True


class TestReset:
    """reset() refills to capacity and resets the clock."""

    def test_reset_refills(self):
        t = [0.0]
        b = TokenBucket(capacity=5, refill_rate=1.0, now=lambda: t[0])
        b.take(5)
        assert b.tokens == 0.0
        b.reset()
        assert b.tokens == 5.0


class TestEdges:
    """Constructor validation and edge cases."""

    def test_zero_capacity_rejected(self):
        with pytest.raises(ValueError, match="capacity"):
            TokenBucket(capacity=0, refill_rate=1.0)

    def test_negative_capacity_rejected(self):
        with pytest.raises(ValueError, match="capacity"):
            TokenBucket(capacity=-1, refill_rate=1.0)

    def test_negative_refill_rate_rejected(self):
        with pytest.raises(ValueError, match="refill_rate"):
            TokenBucket(capacity=5, refill_rate=-0.1)

    def test_negative_take_rejected(self):
        b = TokenBucket(capacity=5, refill_rate=1.0, now=lambda: 0.0)
        with pytest.raises(ValueError, match="n must be"):
            b.take(-1)

    def test_capacity_property(self):
        b = TokenBucket(capacity=42, refill_rate=1.0, now=lambda: 0.0)
        assert b.capacity == 42
