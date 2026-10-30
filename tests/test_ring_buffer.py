"""Tests for snippets/ring_buffer.py — fixed-size circular buffer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from ring_buffer import RingBuffer  # noqa: E402


def test_basic_push_and_iter():
    rb = RingBuffer[int](capacity=3)
    rb.push(1)
    rb.push(2)
    rb.push(3)
    assert list(rb) == [1, 2, 3]


def test_overwrite_evicts_oldest():
    rb = RingBuffer[str](capacity=3)
    rb.push("a")
    rb.push("b")
    rb.push("c")
    evicted = rb.push("d")
    assert evicted == "a"
    assert list(rb) == ["b", "c", "d"]


def test_overwrite_multiple_wraps():
    rb = RingBuffer[int](capacity=2)
    rb.push(1)
    rb.push(2)
    rb.push(3)  # evicts 1
    rb.push(4)  # evicts 2
    rb.push(5)  # evicts 3
    assert list(rb) == [4, 5]


def test_pop_returns_oldest():
    rb = RingBuffer[int](capacity=5)
    for v in [10, 20, 30]:
        rb.push(v)
    assert rb.pop() == 10
    assert rb.pop() == 20
    assert list(rb) == [30]


def test_pop_empty_raises():
    rb = RingBuffer[int](capacity=3)
    with pytest.raises(IndexError):
        rb.pop()


def test_peek_does_not_remove():
    rb = RingBuffer[int](capacity=3)
    rb.push(7)
    rb.push(8)
    assert rb.peek() == 7
    assert rb.size == 2


def test_peek_empty_raises():
    rb = RingBuffer[int](capacity=3)
    with pytest.raises(IndexError):
        rb.peek()


def test_capacity_property():
    rb = RingBuffer[int](capacity=4)
    assert rb.capacity == 4


def test_size_and_full():
    rb = RingBuffer[int](capacity=2)
    assert rb.is_empty
    assert not rb.is_full
    rb.push(1)
    assert rb.size == 1
    assert not rb.is_full
    rb.push(2)
    assert rb.is_full
    assert rb.size == 2


def test_len():
    rb = RingBuffer[int](capacity=5)
    assert len(rb) == 0
    rb.push(1)
    rb.push(2)
    assert len(rb) == 2


def test_invalid_capacity():
    with pytest.raises(ValueError):
        RingBuffer[int](capacity=0)
    with pytest.raises(ValueError):
        RingBuffer[int](capacity=-1)


def test_pop_after_overwrite():
    rb = RingBuffer[int](capacity=3)
    for v in [1, 2, 3]:
        rb.push(v)
    rb.push(4)  # evicts 1
    assert rb.pop() == 2  # oldest remaining
    assert rb.pop() == 3
    assert rb.pop() == 4
    assert rb.is_empty


def test_repr():
    rb = RingBuffer[int](capacity=3)
    rb.push(1)
    rb.push(2)
    assert "RingBuffer" in repr(rb)
    assert "[1, 2]" in repr(rb)


def test_capacity_one():
    rb = RingBuffer[int](capacity=1)
    assert rb.push(1) is None
    assert rb.is_full
    assert rb.push(2) == 1  # evicts 1
    assert list(rb) == [2]
    assert rb.pop() == 2
    assert rb.is_empty
