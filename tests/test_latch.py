"""Tests for snippets/latch.py — one-shot gate that blocks until released."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from latch import Latch  # noqa: E402


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


def test_default_state_is_waiting():
    latch = Latch()
    assert latch.is_set is False
    assert latch.is_released is False
    assert not latch  # __bool__ → False when waiting
    assert "waiting" in repr(latch)


def test_construct_pre_released():
    latch = Latch(released=True)
    assert latch.is_set is True
    assert latch.is_released is True
    assert latch  # __bool__ → True when released
    assert "released" in repr(latch)


# ---------------------------------------------------------------------------
# release
# ---------------------------------------------------------------------------


def test_release_flips_state():
    latch = Latch()
    latch.release()
    assert latch.is_set is True
    assert "released" in repr(latch)


def test_release_is_idempotent():
    latch = Latch()
    latch.release()
    latch.release()
    latch.release()
    assert latch.is_set is True


# ---------------------------------------------------------------------------
# wait — already released
# ---------------------------------------------------------------------------


def test_wait_returns_immediately_when_released():
    latch = Latch(released=True)
    start = time.monotonic()
    result = latch.wait(timeout=5)
    elapsed = time.monotonic() - start
    assert result is True
    assert elapsed < 0.5  # should be near-instant


def test_wait_no_timeout_when_released():
    latch = Latch(released=True)
    assert latch.wait() is True


# ---------------------------------------------------------------------------
# wait — still blocked
# ---------------------------------------------------------------------------


def test_wait_times_out_when_not_released():
    latch = Latch()
    start = time.monotonic()
    result = latch.wait(timeout=0.1)
    elapsed = time.monotonic() - start
    assert result is False
    assert elapsed >= 0.1
    assert elapsed < 1.0


def test_wait_blocks_until_released():
    latch = Latch()
    results = []

    def waiter():
        results.append(latch.wait(timeout=5))

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.1)  # let the thread block
    latch.release()
    t.join(timeout=2)
    assert not t.is_alive()
    assert results == [True]


# ---------------------------------------------------------------------------
# multi-thread: all waiters unblock
# ---------------------------------------------------------------------------


def test_multiple_waiters_all_unblock():
    latch = Latch()
    results = []
    barrier = threading.Barrier(5)

    def waiter(i):
        barrier.wait()  # sync all threads to start together
        results.append((i, latch.wait(timeout=5)))

    threads = [threading.Thread(target=waiter, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()

    time.sleep(0.2)  # let them all block on the latch
    latch.release()

    for t in threads:
        t.join(timeout=2)

    assert len(results) == 5
    assert all(ok for _, ok in results)


# ---------------------------------------------------------------------------
# race: concurrent releases
# ---------------------------------------------------------------------------


def test_concurrent_releases_no_crash():
    latch = Latch()
    threads = [threading.Thread(target=latch.release) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)
    assert latch.is_set is True


# ---------------------------------------------------------------------------
# __bool__ transitions
# ---------------------------------------------------------------------------


def test_bool_transitions_on_release():
    latch = Latch()
    assert not latch
    latch.release()
    assert latch


# ---------------------------------------------------------------------------
# docstring doctests
# ---------------------------------------------------------------------------


def test_doctest():
    import doctest
    from snippets import latch

    results = doctest.testmod(latch, verbose=False)
    assert results.failed == 0, f"{results.failed} doctest(s) failed"
