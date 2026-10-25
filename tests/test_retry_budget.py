"""Tests for snippets/retry_budget.py — time-budgeted retry without real sleep."""

from __future__ import annotations

import pytest

from snippets.retry_budget import retry_with_budget


# --- happy path ---

def test_returns_value_on_first_success():
    assert retry_with_budget(lambda: "hello", budget=1.0, sleep=lambda _: None) == "hello"


def test_returns_value_after_transient_failures():
    counter = {"n": 0}

    def flaky():
        counter["n"] += 1
        if counter["n"] < 3:
            raise RuntimeError("transient")
        return "recovered"

    result = retry_with_budget(flaky, budget=5.0, base_delay=0.001, sleep=lambda _: None)
    assert result == "recovered"
    assert counter["n"] == 3


# --- budget exhaustion ---

def test_raises_last_exception_when_budget_exhausted():
    def always_fails():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        retry_with_budget(
            always_fails,
            budget=0.01,
            base_delay=0.001,
            sleep=lambda _: None,
        )


def test_stops_trying_when_delay_exceeds_remaining_budget():
    """If the next sleep would overshoot the budget, we stop instead of sleeping past it."""
    counter = {"n": 0}

    def failing():
        counter["n"] += 1
        raise OSError("timeout")

    # budget=0.05, base_delay=0.1 → first sleep already exceeds remaining
    with pytest.raises(OSError):
        retry_with_budget(
            failing,
            budget=0.05,
            base_delay=0.1,
            sleep=lambda _: None,
        )
    # should have tried once, then given up because delay > remaining
    assert counter["n"] == 1


# --- validation ---

def test_zero_budget_raises():
    with pytest.raises(ValueError, match="budget must be > 0"):
        retry_with_budget(lambda: 1, budget=0)


def test_negative_budget_raises():
    with pytest.raises(ValueError, match="budget must be > 0"):
        retry_with_budget(lambda: 1, budget=-1)


def test_zero_base_delay_raises():
    with pytest.raises(ValueError, match="base_delay must be > 0"):
        retry_with_budget(lambda: 1, budget=1.0, base_delay=0)


# --- backoff shape ---

def test_backoff_delays_are_exponential():
    delays: list[float] = []
    clock = {"t": 0.0}

    def tick():
        clock["t"] += 0.001
        return clock["t"]

    def failing():
        raise OSError("timeout")

    with pytest.raises(OSError):
        retry_with_budget(
            failing,
            budget=100.0,
            base_delay=1.0,
            max_delay=100.0,
            sleep=lambda d: delays.append(d),
            now=tick,
        )

    # delays should be 1, 2, 4, 8, ...
    for i in range(min(5, len(delays))):
        assert delays[i] == min(1.0 * (2 ** i), 100.0)


def test_max_delay_caps_exponential_growth():
    delays: list[float] = []
    clock = {"t": 0.0}

    def tick():
        clock["t"] += 0.001
        return clock["t"]

    def failing():
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        retry_with_budget(
            failing,
            budget=1000.0,
            base_delay=1.0,
            max_delay=4.0,
            sleep=lambda d: delays.append(d),
            now=tick,
        )

    assert all(d <= 4.0 for d in delays)


# --- exception filtering ---

def test_only_retries_specified_exception():
    counter = {"n": 0}

    def mixed_errors():
        counter["n"] += 1
        if counter["n"] == 1:
            raise ValueError("retryable")
        raise TypeError("not retryable")

    with pytest.raises(TypeError, match="not retryable"):
        retry_with_budget(
            mixed_errors,
            budget=5.0,
            base_delay=0.001,
            exc=ValueError,
            sleep=lambda _: None,
        )
    assert counter["n"] == 2


def test_first_success_wins():
    """Even if an exception would be retryable, success on first try returns immediately."""
    assert retry_with_budget(lambda: 99, budget=1.0) == 99
