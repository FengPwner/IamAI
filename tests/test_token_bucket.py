"""Tests for snippets/token_bucket.py — token bucket rate limiter."""

import pytest
from snippets.token_bucket import TokenBucket


class FakeClock:
    """A clock that advances only when told to."""

    def __init__(self, start: float = 0.0):
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# ── basic consume ──────────────────────────────────────────────────────


class TestConsume:
    def test_full_bucket_allows(self):
        b = TokenBucket(capacity=3, refill_rate=1.0, clock=FakeClock())
        # Use real clock for simple cases
        b2 = TokenBucket(capacity=3, refill_rate=1.0)
        assert b2.consume() is True

    def test_empty_bucket_denies(self):
        clk = FakeClock()
        b = TokenBucket(capacity=2, refill_rate=1.0, clock=clk)
        assert b.consume() is True
        assert b.consume() is True
        assert b.consume() is False

    def test_consume_multiple_at_once(self):
        clk = FakeClock()
        b = TokenBucket(capacity=5, refill_rate=1.0, clock=clk)
        assert b.consume(3) is True
        assert b.consume(3) is False
        assert b.consume(2) is True

    def test_consume_zero_raises(self):
        b = TokenBucket(capacity=1, refill_rate=1.0, clock=FakeClock())
        with pytest.raises(ValueError):
            b.consume(0)

    def test_consume_negative_raises(self):
        b = TokenBucket(capacity=1, refill_rate=1.0, clock=FakeClock())
        with pytest.raises(ValueError):
            b.consume(-1)


# ── refill ─────────────────────────────────────────────────────────────


class TestRefill:
    def test_partial_refill(self):
        clk = FakeClock()
        b = TokenBucket(capacity=10, refill_rate=2.0, clock=clk)
        # Drain all tokens
        assert b.consume(10) is True
        assert b.consume() is False
        # Advance 1 second -> 2 tokens
        clk.advance(1.0)
        assert b.consume(2) is True
        assert b.consume() is False

    def test_full_refill(self):
        clk = FakeClock()
        b = TokenBucket(capacity=5, refill_rate=10.0, clock=clk)
        assert b.consume(5) is True
        # Advance 1 second -> 10 tokens, capped at 5
        clk.advance(1.0)
        assert b.tokens == pytest.approx(5.0)

    def test_no_overfill(self):
        clk = FakeClock()
        b = TokenBucket(capacity=3, refill_rate=100.0, clock=clk)
        assert b.consume() is True
        clk.advance(10.0)
        # Should be capped at capacity
        assert b.tokens == pytest.approx(3.0)

    def test_zero_elapsed_no_refill(self):
        clk = FakeClock()
        b = TokenBucket(capacity=2, refill_rate=10.0, clock=clk)
        assert b.consume(2) is True
        # No time advance
        assert b.consume() is False


# ── wait_time ──────────────────────────────────────────────────────────


class TestWaitTime:
    def test_zero_when_available(self):
        clk = FakeClock()
        b = TokenBucket(capacity=5, refill_rate=1.0, clock=clk)
        assert b.wait_time() == 0.0

    def test_correct_wait_when_empty(self):
        clk = FakeClock()
        b = TokenBucket(capacity=1, refill_rate=2.0, clock=clk)
        b.consume()
        assert b.wait_time() == pytest.approx(0.5)

    def test_wait_for_multiple_tokens(self):
        clk = FakeClock()
        b = TokenBucket(capacity=10, refill_rate=5.0, clock=clk)
        b.consume(10)
        # Need 3 tokens at 5/sec = 0.6s
        assert b.wait_time(3) == pytest.approx(0.6)

    def test_wait_zero_raises(self):
        b = TokenBucket(capacity=1, refill_rate=1.0, clock=FakeClock())
        with pytest.raises(ValueError):
            b.wait_time(0)


# ── properties ─────────────────────────────────────────────────────────


class TestProperties:
    def test_capacity(self):
        b = TokenBucket(capacity=7, refill_rate=1.0, clock=FakeClock())
        assert b.capacity == 7

    def test_refill_rate(self):
        b = TokenBucket(capacity=1, refill_rate=3.14, clock=FakeClock())
        assert b.refill_rate == pytest.approx(3.14)

    def test_tokens_after_consume(self):
        clk = FakeClock()
        b = TokenBucket(capacity=5, refill_rate=1.0, clock=clk)
        b.consume(2)
        assert b.tokens == pytest.approx(3.0)


# ── reset ──────────────────────────────────────────────────────────────


class TestReset:
    def test_reset_refills(self):
        clk = FakeClock()
        b = TokenBucket(capacity=5, refill_rate=1.0, clock=clk)
        b.consume(5)
        assert b.consume() is False
        b.reset()
        assert b.tokens == pytest.approx(5.0)
        assert b.consume(5) is True


# ── validation ─────────────────────────────────────────────────────────


class TestValidation:
    def test_capacity_zero_raises(self):
        with pytest.raises(ValueError):
            TokenBucket(capacity=0, refill_rate=1.0)

    def test_capacity_negative_raises(self):
        with pytest.raises(ValueError):
            TokenBucket(capacity=-1, refill_rate=1.0)

    def test_refill_rate_zero_raises(self):
        with pytest.raises(ValueError):
            TokenBucket(capacity=1, refill_rate=0)

    def test_refill_rate_negative_raises(self):
        with pytest.raises(ValueError):
            TokenBucket(capacity=1, refill_rate=-1.0)


# ── burst pattern ──────────────────────────────────────────────────────


class TestBurstPattern:
    """Realistic scenario: burst then throttle."""

    def test_burst_then_throttle(self):
        clk = FakeClock()
        # Allow 5 bursts, refill 1 per second
        b = TokenBucket(capacity=5, refill_rate=1.0, clock=clk)
        # Burst: 5 immediate calls
        results = [b.consume() for _ in range(5)]
        assert all(results)
        # 6th is denied
        assert b.consume() is False
        # Wait 1 second, get 1 token back
        clk.advance(1.0)
        assert b.consume() is True
        assert b.consume() is False
        # Wait 3 seconds, get 3 tokens
        clk.advance(3.0)
        assert b.consume(3) is True
        assert b.consume() is False
