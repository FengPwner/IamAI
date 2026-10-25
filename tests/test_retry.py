"""Tests for snippets/retry.py — exponential backoff without real sleep."""

from __future__ import annotations

import pytest

from snippets.retry import retry


# --- happy path ---

def test_returns_value_on_first_success():
    assert retry(lambda: "hello", attempts=3, sleep=lambda _: None) == "hello"


def test_returns_value_after_transient_failures():
    counter = {"n": 0}

    def flaky():
        counter["n"] += 1
        if counter["n"] < 3:
            raise RuntimeError("transient")
        return "recovered"

    result = retry(flaky, attempts=5, base_delay=0.001, sleep=lambda _: None)
    assert result == "recovered"
    assert counter["n"] == 3


# --- failure path ---

def test_raises_last_exception_when_attempts_exhausted():
    def always_fails():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        retry(always_fails, attempts=3, base_delay=0.001, sleep=lambda _: None)


def test_single_attempt_does_not_retry():
    counter = {"n": 0}

    def once():
        counter["n"] += 1
        raise RuntimeError("dead")

    with pytest.raises(RuntimeError, match="dead"):
        retry(once, attempts=1)
    assert counter["n"] == 1


# --- backoff timing ---

def test_backoff_delays_are_exponential():
    delays: list[float] = []

    def failing():
        raise OSError("timeout")

    with pytest.raises(OSError):
        retry(
            failing,
            attempts=4,
            base_delay=1.0,
            max_delay=100.0,
            sleep=lambda d: delays.append(d),
        )
    # 3 retries: 1.0, 2.0, 4.0
    assert delays == [1.0, 2.0, 4.0]


def test_max_delay_caps_exponential_growth():
    delays: list[float] = []

    def failing():
        raise OSError("timeout")

    with pytest.raises(OSError):
        retry(
            failing,
            attempts=5,
            base_delay=10.0,
            max_delay=15.0,
            sleep=lambda d: delays.append(d),
        )
    # 4 retries: 10, 15(cap), 15(cap), 15(cap)
    assert all(d <= 15.0 for d in delays)
    assert delays[0] == 10.0


# --- edge cases ---

def test_attempts_must_be_at_least_one():
    with pytest.raises(ValueError, match="attempts"):
        retry(lambda: 1, attempts=0)


def test_only_catches_specified_exception_type():
    counter = {"n": 0}

    def wrong_type():
        counter["n"] += 1
        raise TypeError("wrong")

    # Should not catch TypeError when exc=ValueError
    with pytest.raises(TypeError, match="wrong"):
        retry(wrong_type, attempts=5, exc=ValueError, sleep=lambda _: None)
    # Should have failed on first attempt without retrying
    assert counter["n"] == 1
