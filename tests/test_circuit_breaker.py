"""Tests for snippets/circuit_breaker.py — state machine, edges, and the contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from circuit_breaker import CircuitBreaker, CircuitOpen  # noqa: E402


class TestClosedState:
    """Healthy circuit passes calls through and counts failures."""

    def test_starts_closed(self):
        cb = CircuitBreaker(fail_threshold=3)
        assert cb.state == "closed"

    def test_passes_successful_call(self):
        cb = CircuitBreaker(fail_threshold=3)
        assert cb(lambda: 42) == 42

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(fail_threshold=5)
        for _ in range(4):
            with pytest.raises(RuntimeError):
                cb(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        # 4 failures, threshold is 5 — still closed
        assert cb.state == "closed"
        assert cb.failures == 4
        # one success clears the count
        cb(lambda: "ok")
        assert cb.failures == 0

    def test_failures_below_threshold_stay_closed(self):
        cb = CircuitBreaker(fail_threshold=3)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb(lambda: (_ for _ in ()).throw(ValueError("nope")))
        assert cb.state == "closed"
        assert cb.failures == 2


class TestOpenState:
    """Tripped circuit rejects all calls without touching the target."""

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(fail_threshold=3)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                cb(lambda: (_ for _ in ()).throw(RuntimeError("down")))
        assert cb.state == "open"

    def test_rejects_calls_while_open(self):
        cb = CircuitBreaker(fail_threshold=2)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb(lambda: (_ for _ in ()).throw(RuntimeError("err")))
        probes = []
        with pytest.raises(CircuitOpen) as exc_info:
            cb(lambda: probes.append(1))
        assert len(probes) == 0
        assert exc_info.value.failures == 2

    def test_open_error_carries_metadata(self):
        t = [100.0]
        cb = CircuitBreaker(fail_threshold=1, now=lambda: t[0])
        with pytest.raises(RuntimeError):
            cb(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        with pytest.raises(CircuitOpen) as exc_info:
            cb(lambda: None)
        assert exc_info.value.opened_at == 100.0


class TestHalfOpenState:
    """After recovery timeout, one probe is allowed to test the waters."""

    def test_transitions_to_half_open(self):
        t = [0.0]
        cb = CircuitBreaker(fail_threshold=2, recovery_timeout=10.0, now=lambda: t[0])
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert cb.state == "open"
        t[0] = 15.0
        assert cb.state == "half-open"

    def test_successful_probe_closes_circuit(self):
        t = [0.0]
        cb = CircuitBreaker(fail_threshold=2, recovery_timeout=10.0, now=lambda: t[0])
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        t[0] = 20.0
        assert cb.state == "half-open"
        result = cb(lambda: "recovered")
        assert result == "recovered"
        assert cb.state == "closed"

    def test_failed_probe_reopens_circuit(self):
        t = [0.0]
        cb = CircuitBreaker(fail_threshold=2, recovery_timeout=10.0, now=lambda: t[0])
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        t[0] = 20.0
        with pytest.raises(RuntimeError):
            cb(lambda: (_ for _ in ()).throw(RuntimeError("still broken")))
        assert cb.state == "open"
        assert cb.failures == 3  # failures keep counting


class TestEdgeCases:
    """Validation and boundary conditions."""

    def test_threshold_one_opens_immediately(self):
        cb = CircuitBreaker(fail_threshold=1)
        with pytest.raises(RuntimeError):
            cb(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert cb.state == "open"

    def test_zero_recovery_timeout_is_always_half_open(self):
        cb = CircuitBreaker(fail_threshold=1, recovery_timeout=0.0)
        with pytest.raises(RuntimeError):
            cb(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        # recovery_timeout=0 means half-open immediately
        assert cb.state == "half-open"

    def test_manual_reset(self):
        cb = CircuitBreaker(fail_threshold=1)
        with pytest.raises(RuntimeError):
            cb(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert cb.state == "open"
        cb.reset()
        assert cb.state == "closed"
        assert cb.failures == 0

    def test_rejects_bad_threshold(self):
        with pytest.raises(ValueError):
            CircuitBreaker(fail_threshold=0)

    def test_rejects_negative_timeout(self):
        with pytest.raises(ValueError):
            CircuitBreaker(fail_threshold=1, recovery_timeout=-1)
