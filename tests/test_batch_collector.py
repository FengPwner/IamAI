"""Tests for snippets/batch_collector.py — accumulate and flush in batches."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from batch_collector import (  # noqa: E402
    BatchCollector,
    ClosedError,
    FakeClock,
)


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


def test_requires_at_least_one_threshold():
    with pytest.raises(ValueError, match="at least one"):
        BatchCollector(on_flush=lambda b: None)


def test_max_size_must_be_positive():
    with pytest.raises(ValueError, match="max_size"):
        BatchCollector(max_size=0, on_flush=lambda b: None)


def test_flush_interval_must_be_positive():
    with pytest.raises(ValueError, match="flush_interval"):
        BatchCollector(flush_interval=0, on_flush=lambda b: None)


def test_repr():
    bc = BatchCollector(max_size=5, on_flush=lambda b: None)
    assert "BatchCollector" in repr(bc)
    assert "max_size=5" in repr(bc)


# ---------------------------------------------------------------------------
# size-based flushing
# ---------------------------------------------------------------------------


def test_size_flush_at_threshold():
    batches: list[list[str]] = []
    bc = BatchCollector(max_size=3, on_flush=lambda b: batches.append(b))
    bc.add("a")
    bc.add("b")
    assert batches == []
    bc.add("c")
    assert batches == [["a", "b", "c"]]
    assert bc.pending == 0


def test_size_flush_overflow():
    """Items beyond max_size trigger another flush on next add."""
    batches: list[list[int]] = []
    bc = BatchCollector(max_size=2, on_flush=lambda b: batches.append(b))
    for i in range(5):
        bc.add(i)
    # [0,1] flushed, [2,3] flushed, [4] pending
    assert batches == [[0, 1], [2, 3]]
    assert bc.pending == 1


def test_add_returns_true_on_flush():
    bc = BatchCollector(max_size=2, on_flush=lambda b: None)
    assert bc.add(1) is False
    assert bc.add(2) is True


def test_add_many_returns_flush_count():
    batches: list[list[int]] = []
    bc = BatchCollector(max_size=2, on_flush=lambda b: batches.append(b))
    flushes = bc.add_many([1, 2, 3, 4, 5])
    assert flushes == 2
    assert batches == [[1, 2], [3, 4]]


# ---------------------------------------------------------------------------
# time-based flushing
# ---------------------------------------------------------------------------


def test_time_flush_after_interval():
    clock = FakeClock(start=100.0)
    batches: list[list[str]] = []
    bc = BatchCollector(
        flush_interval=10.0, on_flush=lambda b: batches.append(b), clock=clock
    )
    bc.add("x")
    assert batches == []
    clock.advance(9.9)
    bc.tick()
    assert batches == []  # not yet
    clock.advance(0.2)  # now at 110.1 — past interval
    bc.tick()
    assert batches == [["x"]]


def test_time_flush_resets_timer():
    clock = FakeClock(start=0.0)
    batches: list[list[int]] = []
    bc = BatchCollector(
        flush_interval=5.0, on_flush=lambda b: batches.append(b), clock=clock
    )
    bc.add(1)
    clock.advance(5.0)
    bc.tick()
    assert len(batches) == 1

    bc.add(2)
    clock.advance(4.9)  # just under — timer reset at last flush
    bc.tick()
    assert len(batches) == 1  # not flushed yet
    clock.advance(0.2)
    bc.tick()
    assert len(batches) == 2


def test_tick_on_empty_buffer_does_nothing():
    clock = FakeClock()
    called: list[list] = []
    bc = BatchCollector(
        flush_interval=1.0, on_flush=lambda b: called.append(b), clock=clock
    )
    clock.advance(100.0)
    assert bc.tick() is False
    assert called == []


# ---------------------------------------------------------------------------
# combined size + time
# ---------------------------------------------------------------------------


def test_size_fires_before_time():
    clock = FakeClock()
    batches: list[list[int]] = []
    bc = BatchCollector(
        max_size=2,
        flush_interval=60.0,
        on_flush=lambda b: batches.append(b),
        clock=clock,
    )
    bc.add(1)
    bc.add(2)
    # size threshold hit — flushed even though interval hasn't elapsed
    assert batches == [[1, 2]]


# ---------------------------------------------------------------------------
# force flush
# ---------------------------------------------------------------------------


def test_force_flush_empty_returns_false():
    bc = BatchCollector(max_size=10, on_flush=lambda b: None)
    assert bc.flush() is False


def test_force_flush_emits_partial_batch():
    batches: list[list[str]] = []
    bc = BatchCollector(max_size=100, on_flush=lambda b: batches.append(b))
    bc.add("only")
    assert bc.flush() is True
    assert batches == [["only"]]


# ---------------------------------------------------------------------------
# drain
# ---------------------------------------------------------------------------


def test_drain_returns_items_without_callback():
    called: list[list] = []
    bc = BatchCollector(max_size=100, on_flush=lambda b: called.append(b))
    bc.add(1)
    bc.add(2)
    bc.add(3)
    drained = bc.drain()
    assert drained == [1, 2, 3]
    assert called == []
    assert bc.pending == 0


def test_drain_empty():
    bc = BatchCollector(max_size=5, on_flush=lambda b: None)
    assert bc.drain() == []


# ---------------------------------------------------------------------------
# close / context manager
# ---------------------------------------------------------------------------


def test_close_flushes_remaining():
    batches: list[list[int]] = []
    bc = BatchCollector(max_size=100, on_flush=lambda b: batches.append(b))
    bc.add(1)
    bc.add(2)
    count = bc.close()
    assert count == 2
    assert batches == [[1, 2]]
    assert bc.is_closed


def test_close_empty():
    bc = BatchCollector(max_size=5, on_flush=lambda b: None)
    assert bc.close() == 0
    assert bc.is_closed


def test_add_after_close_raises():
    bc = BatchCollector(max_size=5, on_flush=lambda b: None)
    bc.close()
    with pytest.raises(ClosedError):
        bc.add("nope")


def test_context_manager_flushes_on_exit():
    batches: list[list[str]] = []
    with BatchCollector(max_size=100, on_flush=lambda b: batches.append(b)) as bc:
        bc.add("hello")
        bc.add("world")
    assert batches == [["hello", "world"]]
    assert bc.is_closed


# ---------------------------------------------------------------------------
# introspection
# ---------------------------------------------------------------------------


def test_counters():
    bc = BatchCollector(max_size=2, on_flush=lambda b: None)
    assert bc.total_added == 0
    assert bc.total_flushed == 0
    assert bc.flush_count == 0

    bc.add(1)
    assert bc.total_added == 1
    assert bc.total_flushed == 0

    bc.add(2)
    assert bc.total_added == 2
    assert bc.total_flushed == 2
    assert bc.flush_count == 1

    bc.add(3)
    assert bc.total_added == 3
    assert bc.total_flushed == 2
    assert bc.pending == 1


# ---------------------------------------------------------------------------
# exception in callback
# ---------------------------------------------------------------------------


def test_on_flush_exception_clears_buffer():
    """When on_flush raises, the batch has already been removed from the
    buffer.  Callers should wrap on_flush in try/except if they need
    retry semantics."""

    def bad_flush(batch: list[int]) -> None:
        raise RuntimeError("disk full")

    bc = BatchCollector(max_size=2, on_flush=bad_flush)
    bc.add(1)
    with pytest.raises(RuntimeError, match="disk full"):
        bc.add(2)
    # buffer was cleared before on_flush was called
    assert bc.pending == 0
    assert bc.total_flushed == 2


# ---------------------------------------------------------------------------
# thread safety
# ---------------------------------------------------------------------------


def test_concurrent_adds():
    batches: list[list[int]] = []
    lock = threading.Lock()

    def safe_append(batch: list[int]) -> None:
        with lock:
            batches.append(batch)

    bc = BatchCollector(max_size=5, on_flush=safe_append)
    errors: list[Exception] = []

    def worker(start: int) -> None:
        try:
            for i in range(start, start + 50):
                bc.add(i)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i * 50,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    bc.close()
    # 200 items total, batches of 5
    total = sum(len(b) for b in batches)
    assert total == 200


# ---------------------------------------------------------------------------
# edge: max_size=1
# ---------------------------------------------------------------------------


def test_max_size_one_flushes_immediately():
    batches: list[list[int]] = []
    bc = BatchCollector(max_size=1, on_flush=lambda b: batches.append(b))
    bc.add(42)
    assert batches == [[42]]
    bc.add(99)
    assert batches == [[42], [99]]
