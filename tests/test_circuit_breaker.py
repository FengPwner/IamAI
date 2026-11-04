"""Tests for snippets/circuit_breaker.py — three-state failure protection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from circuit_breaker import CircuitBreaker, CircuitOpenError  # noqa: E402


# -- initial state ----------------------------------------------------------


def test_starts_closed():
    cb = CircuitBreaker(threshold=3, clock=lambda: 0.0)
    assert cb.state == "closed"
    assert cb.failures == 0


def test_allow_request_when_closed():
    cb = CircuitBreaker(threshold=3, clock=lambda: 0.0)
    assert cb.allow_request() is True


# -- failure accumulation ---------------------------------------------------


def test_single_failure_stays_closed():
    cb = CircuitBreaker(threshold=3, clock=lambda: 0.0)
    cb.record_failure()
    assert cb.state == "closed"
    assert cb.failures == 1


def test_threshold_opens_circuit():
    cb = CircuitBreaker(threshold=3, clock=lambda: 100.0)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == "open"
    assert cb.failures == 3


def test_open_circuit_rejects_requests():
    cb = CircuitBreaker(threshold=2, clock=lambda: 100.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.allow_request() is False


# -- cooldown and half_open -------------------------------------------------


def test_cooldown_transitions_to_half_open():
    now = [100.0]
    cb = CircuitBreaker(threshold=2, cooldown=10.0, clock=lambda: now[0])
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    now[0] = 111.0
    assert cb.state == "half_open"


def test_half_open_allows_one_request():
    now = [100.0]
    cb = CircuitBreaker(threshold=2, cooldown=10.0, clock=lambda: now[0])
    cb.record_failure()
    cb.record_failure()
    now[0] = 111.0
    assert cb.allow_request() is True


def test_half_open_success_closes():
    now = [100.0]
    cb = CircuitBreaker(threshold=2, cooldown=10.0, clock=lambda: now[0])
    cb.record_failure()
    cb.record_failure()
    now[0] = 111.0
    assert cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed"
    assert cb.failures == 0


def test_half_open_failure_reopens():
    now = [100.0]
    cb = CircuitBreaker(threshold=2, cooldown=10.0, clock=lambda: now[0])
    cb.record_failure()
    cb.record_failure()
    now[0] = 111.0
    assert cb.state == "half_open"
    cb.record_failure()
    assert cb.state == "open"
    assert cb.failures == 3


# -- before cooldown expires ------------------------------------------------


def test_stays_open_before_cooldown():
    now = [100.0]
    cb = CircuitBreaker(threshold=2, cooldown=10.0, clock=lambda: now[0])
    cb.record_failure()
    cb.record_failure()
    now[0] = 109.0  # 1 second before cooldown
    assert cb.state == "open"
    assert cb.allow_request() is False


# -- call() integration -----------------------------------------------------


def test_call_passes_through_when_closed():
    cb = CircuitBreaker(threshold=3, clock=lambda: 0.0)
    result = cb.call(lambda x: x * 2, 21)
    assert result == 42


def test_call_records_success():
    cb = CircuitBreaker(threshold=3, clock=lambda: 0.0)
    cb.record_failure()
    cb.call(lambda: "ok")
    assert cb.state == "closed"
    assert cb.failures == 0


def test_call_records_failure():
    cb = CircuitBreaker(threshold=2, clock=lambda: 0.0)

    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        cb.call(boom)
    assert cb.failures == 1


def test_call_rejects_when_open():
    cb = CircuitBreaker(threshold=1, clock=lambda: 100.0)
    cb.record_failure()
    with pytest.raises(CircuitOpenError):
        cb.call(lambda: "unreachable")


# -- reset ------------------------------------------------------------------


def test_reset_closes_breaker():
    cb = CircuitBreaker(threshold=2, clock=lambda: 100.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    cb.reset()
    assert cb.state == "closed"
    assert cb.failures == 0


# -- validation -------------------------------------------------------------


def test_threshold_must_be_positive():
    with pytest.raises(ValueError, match="threshold"):
        CircuitBreaker(threshold=0)


def test_cooldown_must_be_nonnegative():
    with pytest.raises(ValueError, match="cooldown"):
        CircuitBreaker(cooldown=-1)


# -- edge: threshold=1 ------------------------------------------------------


def test_single_failure_threshold():
    cb = CircuitBreaker(threshold=1, clock=lambda: 100.0)
    cb.record_failure()
    assert cb.state == "open"
