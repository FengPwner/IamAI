"""Tests for the Throttle snippet — driven with a fake clock for determinism."""

import pytest
from snippets.throttle import Throttle


class FakeClock:
    def __init__(self):
        self._t = 0.0

    def __call__(self) -> float:
        return self._t

    def advance(self, dt: float):
        self._t += dt


def test_first_call_fires_immediately():
    calls = []
    clock = FakeClock()
    t = Throttle(lambda: calls.append("x"), interval=1.0, clock=clock)
    assert t() is True
    assert len(calls) == 1


def test_rapid_calls_are_suppressed():
    calls = []
    clock = FakeClock()
    t = Throttle(lambda: calls.append("x"), interval=1.0, clock=clock)
    t()
    clock.advance(0.5)
    assert t() is False
    clock.advance(0.3)
    assert t() is False
    assert len(calls) == 1


def test_fires_again_after_interval():
    calls = []
    clock = FakeClock()
    t = Throttle(lambda: calls.append("x"), interval=1.0, clock=clock)
    t()
    clock.advance(0.99)
    assert t() is False
    clock.advance(0.02)  # now at 1.01
    assert t() is True
    assert len(calls) == 2


def test_remaining_decreases_with_time():
    clock = FakeClock()
    t = Throttle(lambda: None, interval=2.0, clock=clock)
    t()
    assert t.remaining == pytest.approx(2.0)
    clock.advance(1.0)
    assert t.remaining == pytest.approx(1.0)
    clock.advance(1.5)
    assert t.remaining == 0.0


def test_remaining_before_first_call():
    t = Throttle(lambda: None, interval=5.0, clock=FakeClock())
    assert t.remaining == 0.0


def test_zero_interval_always_fires():
    calls = []
    clock = FakeClock()
    t = Throttle(lambda: calls.append(1), interval=0, clock=clock)
    assert t() is True
    assert t() is True
    assert len(calls) == 2


def test_negative_interval_rejected():
    with pytest.raises(ValueError, match="interval must be >= 0"):
        Throttle(lambda: None, interval=-1)
