"""Tests for snippets/window_counter.py — sliding window event counter."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from window_counter import WindowCounter  # noqa: E402


def _make_clock(start: float = 0.0):
    """Return a mutable clock function and its time list."""
    t = [start]
    return (lambda: t[0]), t


def test_tick_and_count_basic():
    clock, t = _make_clock(100.0)
    c = WindowCounter(window=10.0, clock=clock)
    c.tick()
    c.tick()
    c.tick()
    assert c.count() == 3


def test_events_evicted_after_window():
    clock, t = _make_clock(0.0)
    c = WindowCounter(window=5.0, clock=clock)
    c.tick()
    t[0] = 3.0
    c.tick()
    t[0] = 6.0  # first event at t=0 is now outside window=5
    assert c.count() == 1  # only the t=3 event remains


def test_all_events_expire():
    clock, t = _make_clock(0.0)
    c = WindowCounter(window=2.0, clock=clock)
    c.tick()
    c.tick()
    t[0] = 100.0
    assert c.count() == 0


def test_rate_empty_window():
    clock, _ = _make_clock(0.0)
    c = WindowCounter(window=10.0, clock=clock)
    assert c.rate() == 0.0


def test_rate_single_event():
    clock, _ = _make_clock(0.0)
    c = WindowCounter(window=10.0, clock=clock)
    c.tick()
    assert c.rate() == pytest.approx(0.1)  # 1 event / 10s window


def test_rate_multiple_events():
    clock, t = _make_clock(0.0)
    c = WindowCounter(window=10.0, clock=clock)
    for i in range(5):
        t[0] = float(i)
        c.tick()
    # 5 events over span [0..4], effective window = max(4, 10) = 10
    assert c.rate() == pytest.approx(0.5)


def test_tick_batch():
    clock, _ = _make_clock(0.0)
    c = WindowCounter(window=60.0, clock=clock)
    c.tick(n=10)
    assert c.count() == 10


def test_tick_invalid_n():
    clock, _ = _make_clock(0.0)
    c = WindowCounter(window=10.0, clock=clock)
    with pytest.raises(ValueError):
        c.tick(n=0)
    with pytest.raises(ValueError):
        c.tick(n=-3)


def test_invalid_window():
    with pytest.raises(ValueError):
        WindowCounter(window=0)
    with pytest.raises(ValueError):
        WindowCounter(window=-1.0)


def test_reset():
    clock, _ = _make_clock(0.0)
    c = WindowCounter(window=10.0, clock=clock)
    c.tick()
    c.tick()
    c.reset()
    assert c.count() == 0
    assert c.rate() == 0.0


def test_window_property():
    c = WindowCounter(window=42.0)
    assert c.window == 42.0


def test_boundary_event_exactly_at_cutoff():
    """Event exactly at cutoff (now - window) should be evicted."""
    clock, t = _make_clock(10.0)
    c = WindowCounter(window=5.0, clock=clock)
    c.tick()  # at t=10
    t[0] = 15.0  # cutoff = 15 - 5 = 10, event at 10 is <= cutoff
    assert c.count() == 0
