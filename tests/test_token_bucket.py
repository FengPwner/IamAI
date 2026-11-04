"""Tests for snippets/token_bucket.py — smooth rate limiter with burst support."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from token_bucket import TokenBucket  # noqa: E402


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_starts_full(self) -> None:
        b = TokenBucket(capacity=10, rate=1)
        assert b.tokens == 10

    def test_zero_capacity_raises(self) -> None:
        with pytest.raises(ValueError, match="capacity"):
            TokenBucket(capacity=0, rate=1)

    def test_negative_capacity_raises(self) -> None:
        with pytest.raises(ValueError, match="capacity"):
            TokenBucket(capacity=-1, rate=1)

    def test_zero_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="rate"):
            TokenBucket(capacity=10, rate=0)

    def test_negative_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="rate"):
            TokenBucket(capacity=10, rate=-5)

    def test_fractional_capacity(self) -> None:
        b = TokenBucket(capacity=0.5, rate=0.1)
        assert b.tokens == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# try_acquire
# ---------------------------------------------------------------------------


class TestTryAcquire:
    def test_acquire_from_full_bucket(self) -> None:
        b = TokenBucket(capacity=5, rate=1)
        assert b.try_acquire(1) is True
        assert b.tokens == pytest.approx(4.0, abs=0.1)

    def test_acquire_multiple_at_once(self) -> None:
        b = TokenBucket(capacity=10, rate=1)
        assert b.try_acquire(5) is True
        assert b.tokens == pytest.approx(5.0, abs=0.1)

    def test_acquire_fails_when_empty(self) -> None:
        b = TokenBucket(capacity=3, rate=1)
        b.drain()
        assert b.try_acquire(1) is False

    def test_acquire_fails_when_insufficient(self) -> None:
        b = TokenBucket(capacity=5, rate=1)
        b.try_acquire(4)
        assert b.try_acquire(3) is False

    def test_acquire_zero_raises(self) -> None:
        b = TokenBucket(capacity=5, rate=1)
        with pytest.raises(ValueError, match="n must be positive"):
            b.try_acquire(0)

    def test_acquire_negative_raises(self) -> None:
        b = TokenBucket(capacity=5, rate=1)
        with pytest.raises(ValueError, match="n must be positive"):
            b.try_acquire(-1)

    def test_exact_capacity_succeeds(self) -> None:
        b = TokenBucket(capacity=5, rate=1)
        assert b.try_acquire(5) is True
        assert b.tokens == pytest.approx(0.0, abs=0.1)


# ---------------------------------------------------------------------------
# refill behaviour
# ---------------------------------------------------------------------------


class TestRefill:
    def test_tokens_refill_over_time(self) -> None:
        b = TokenBucket(capacity=10, rate=100)  # 100 tokens/sec for fast test
        b.drain()
        time.sleep(0.05)  # ~5 tokens should refill
        assert b.tokens >= 3  # at least 3 (allowing timing slack)

    def test_tokens_never_exceed_capacity(self) -> None:
        b = TokenBucket(capacity=5, rate=1000)
        b.drain()
        time.sleep(0.1)
        assert b.tokens <= 5.0

    def test_long_idle_caps_at_capacity(self) -> None:
        """Even after a long idle, bucket never holds more than capacity."""
        b = TokenBucket(capacity=5, rate=1000)
        # Simulate time passing by manipulating internals
        b._last_refill = time.monotonic() - 3600  # 1 hour ago
        assert b.tokens == pytest.approx(5.0)

    def test_fractional_refill(self) -> None:
        b = TokenBucket(capacity=10, rate=10)  # 10/sec
        b.drain()
        time.sleep(0.05)  # ~0.5 tokens
        t = b.tokens
        assert 0.2 <= t <= 1.0  # generous bounds for CI jitter


# ---------------------------------------------------------------------------
# acquire (blocking)
# ---------------------------------------------------------------------------


class TestAcquire:
    def test_acquire_succeeds_immediately_when_full(self) -> None:
        b = TokenBucket(capacity=5, rate=1)
        start = time.monotonic()
        assert b.acquire(1) is True
        assert time.monotonic() - start < 0.1

    def test_acquire_waits_for_refill(self) -> None:
        b = TokenBucket(capacity=10, rate=100)  # 100/sec → 0.01s per token
        b.drain()
        start = time.monotonic()
        assert b.acquire(1) is True
        elapsed = time.monotonic() - start
        assert elapsed >= 0.005  # had to wait at least a bit

    def test_acquire_timeout_expires(self) -> None:
        b = TokenBucket(capacity=1, rate=0.1)  # very slow: 1 token per 10s
        b.drain()
        start = time.monotonic()
        result = b.acquire(1, timeout=0.05)
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed < 0.5  # didn't hang

    def test_acquire_more_than_capacity_fails_fast(self) -> None:
        b = TokenBucket(capacity=5, rate=1)
        assert b.acquire(6, timeout=10) is False  # impossible, shouldn't wait

    def test_acquire_zero_raises(self) -> None:
        b = TokenBucket(capacity=5, rate=1)
        with pytest.raises(ValueError):
            b.acquire(0)

    def test_acquire_negative_raises(self) -> None:
        b = TokenBucket(capacity=5, rate=1)
        with pytest.raises(ValueError):
            b.acquire(-2)


# ---------------------------------------------------------------------------
# drain & reset
# ---------------------------------------------------------------------------


class TestDrainAndReset:
    def test_drain_empties_bucket(self) -> None:
        b = TokenBucket(capacity=10, rate=1)
        consumed = b.drain()
        assert consumed == pytest.approx(10.0, abs=0.1)
        assert b.tokens == pytest.approx(0.0, abs=0.1)

    def test_drain_returns_actual_tokens(self) -> None:
        b = TokenBucket(capacity=10, rate=1)
        b.try_acquire(3)
        consumed = b.drain()
        assert consumed == pytest.approx(7.0, abs=0.2)

    def test_reset_fills_to_capacity(self) -> None:
        b = TokenBucket(capacity=10, rate=1)
        b.drain()
        b.reset()
        assert b.tokens == pytest.approx(10.0, abs=0.1)

    def test_drain_then_acquire_fails(self) -> None:
        b = TokenBucket(capacity=5, rate=1)
        b.drain()
        assert b.try_acquire(1) is False


# ---------------------------------------------------------------------------
# concurrency
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_acquire_does_not_overspend(self) -> None:
        """Multiple threads racing to acquire should not exceed capacity."""
        b = TokenBucket(capacity=100, rate=0.0001)  # near-zero refill
        results: list[bool] = []
        lock = threading.Lock()

        def worker() -> None:
            acquired = b.try_acquire(1)
            with lock:
                results.append(acquired)

        threads = [threading.Thread(target=worker) for _ in range(150)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successful = sum(1 for r in results if r)
        # At most capacity tokens should have been available
        assert successful <= 101  # 100 + 1 for tiny refill

    def test_concurrent_drain_and_acquire(self) -> None:
        """Drain and acquire racing should not corrupt state."""
        b = TokenBucket(capacity=50, rate=0.0001)
        errors: list[Exception] = []

        def drainer() -> None:
            try:
                b.drain()
            except Exception as e:
                errors.append(e)

        def acquirer() -> None:
            try:
                b.try_acquire(1)
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(20):
            threads.append(threading.Thread(target=drainer))
            threads.append(threading.Thread(target=acquirer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # Bucket should still be in a valid state
        assert 0 <= b.tokens <= 50
