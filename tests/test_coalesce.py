"""Tests for snippets/coalesce.py — time-window batch coalescer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from coalesce import Coalescer  # noqa: E402


# ---------------------------------------------------------------------------
# window lifecycle
# ---------------------------------------------------------------------------


def test_first_add_opens_window():
    c = Coalescer(lambda _: None, window=5.0, clock=lambda: 0.0)
    assert c.add("x") is True
    assert c.window_open is True
    assert c.pending == 1


def test_subsequent_adds_do_not_reopen():
    c = Coalescer(lambda _: None, window=5.0, clock=lambda: 0.0)
    c.add("a")
    assert c.add("b") is False
    assert c.add("c") is False
    assert c.pending == 3


def test_tick_returns_none_before_window_expires():
    results = []
    c = Coalescer(results.append, window=10.0, clock=lambda: 0.0)
    c.add("a")
    assert c.tick(clock=lambda: 5.0) is None
    assert results == []


def test_tick_delivers_after_window_expires():
    results = []
    c = Coalescer(results.append, window=2.0, clock=lambda: 0.0)
    c.add("a")
    c.add("b")
    delivered = c.tick(clock=lambda: 2.0)
    assert delivered == ["a", "b"]
    assert results == [["a", "b"]]
    assert c.pending == 0
    assert c.window_open is False


def test_tick_returns_none_when_empty():
    c = Coalescer(lambda _: None, window=1.0, clock=lambda: 0.0)
    assert c.tick() is None


# ---------------------------------------------------------------------------
# flush
# ---------------------------------------------------------------------------


def test_flush_delivers_immediately():
    results = []
    c = Coalescer(results.append, window=999.0, clock=lambda: 0.0)
    c.add("a")
    c.add("b")
    delivered = c.flush()
    assert delivered == ["a", "b"]
    assert results == [["a", "b"]]
    assert c.pending == 0


def test_flush_returns_none_when_empty():
    c = Coalescer(lambda _: None, window=1.0)
    assert c.flush() is None


# ---------------------------------------------------------------------------
# multiple windows
# ---------------------------------------------------------------------------


def test_new_window_opens_after_delivery():
    time_box = [0.0]
    results = []
    c = Coalescer(results.append, window=1.0, clock=lambda: time_box[0])

    # first window
    c.add("a")
    time_box[0] = 1.0
    c.tick()
    assert results == [["a"]]

    # second window
    assert c.add("b") is True  # new window
    assert c.pending == 1
    time_box[0] = 2.0
    c.tick()
    assert results == [["a"], ["b"]]


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


def test_zero_window_delivers_immediately():
    results = []
    c = Coalescer(results.append, window=0.0, clock=lambda: 0.0)
    c.add("a")
    c.tick(clock=lambda: 0.0)
    assert results == [["a"]]


def test_negative_window_rejected():
    with pytest.raises(ValueError):
        Coalescer(lambda _: None, window=-1)


def test_preserves_insertion_order():
    results = []
    c = Coalescer(results.append, window=1.0, clock=lambda: 0.0)
    for item in range(20):
        c.add(item)
    c.tick(clock=lambda: 1.0)
    assert results == [list(range(20))]


def test_callback_receives_copy_not_reference():
    """Mutating the delivered list must not affect internal state."""
    delivered_batches = []

    def cb(batch):
        batch.append("MUTATED")
        delivered_batches.append(batch)

    c = Coalescer(cb, window=1.0, clock=lambda: 0.0)
    c.add("a")
    result = c.tick(clock=lambda: 1.0)
    assert result == ["a"]  # returned list is clean
    assert delivered_batches[0] == ["a", "MUTATED"]  # callback got its own copy


def test_pending_property():
    c = Coalescer(lambda _: None, window=5.0, clock=lambda: 0.0)
    assert c.pending == 0
    c.add("x")
    assert c.pending == 1
    c.add("y")
    assert c.pending == 2
    c.flush()
    assert c.pending == 0
