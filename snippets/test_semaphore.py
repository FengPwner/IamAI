#!/usr/bin/env python3
"""Tests for semaphore.py — counting semaphore with FIFO fairness and timeout.

18 tests covering:
- basic acquire/release
- capacity enforcement
- timeout behaviour
- FIFO ordering (no starvation)
- context manager
- thread safety under contention
- edge cases (invalid permits, double release)
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from semaphore import Semaphore


# ---------------------------------------------------------------------------
# basic acquire / release
# ---------------------------------------------------------------------------

def test_initial_state():
    sem = Semaphore(permits=3)
    assert sem.available == 3
    assert sem.capacity == 3


def test_acquire_decrements():
    sem = Semaphore(permits=2)
    assert sem.acquire() is True
    assert sem.available == 1
    assert sem.acquire() is True
    assert sem.available == 0


def test_release_increments():
    sem = Semaphore(permits=2)
    sem.acquire()
    sem.acquire()
    assert sem.available == 0
    sem.release()
    assert sem.available == 1
    sem.release()
    assert sem.available == 2


def test_release_beyond_capacity():
    """Releasing more than capacity is allowed (matches POSIX sem_post)."""
    sem = Semaphore(permits=1)
    sem.release()  # now available=2, above capacity
    assert sem.available == 2


# ---------------------------------------------------------------------------
# blocking and timeout
# ---------------------------------------------------------------------------

def test_acquire_blocks_until_release():
    sem = Semaphore(permits=1)
    sem.acquire()  # take the only permit
    acquired = [False]

    def worker():
        acquired[0] = sem.acquire(timeout=5.0)

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.05)  # let the worker block
    assert acquired[0] is False  # still blocked

    sem.release()
    t.join(timeout=2.0)
    assert acquired[0] is True


def test_timeout_returns_false():
    sem = Semaphore(permits=1)
    sem.acquire()
    start = time.monotonic()
    result = sem.acquire(timeout=0.1)
    elapsed = time.monotonic() - start
    assert result is False
    assert elapsed >= 0.08  # close to 0.1s


def test_zero_timeout_is_nonblocking():
    sem = Semaphore(permits=1)
    sem.acquire()
    assert sem.acquire(timeout=0) is False


def test_timeout_with_release_before_deadline():
    sem = Semaphore(permits=1)
    sem.acquire()
    acquired = [False]

    def worker():
        acquired[0] = sem.acquire(timeout=2.0)

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.1)
    sem.release()
    t.join(timeout=3.0)
    assert acquired[0] is True


# ---------------------------------------------------------------------------
# FIFO fairness
# ---------------------------------------------------------------------------

def test_fifo_ordering():
    """Three waiters should acquire in the order they arrived."""
    sem = Semaphore(permits=1)
    sem.acquire()
    order = []
    lock = threading.Lock()

    def worker(label, delay):
        time.sleep(delay)
        sem.acquire(timeout=5.0)
        with lock:
            order.append(label)
        sem.release()

    threads = [
        threading.Thread(target=worker, args=("A", 0.00)),
        threading.Thread(target=worker, args=("B", 0.05)),
        threading.Thread(target=worker, args=("C", 0.10)),
    ]
    for t in threads:
        t.start()

    time.sleep(0.2)  # all three should be waiting
    sem.release()    # let them go one by one
    for t in threads:
        t.join(timeout=5.0)

    assert order == ["A", "B", "C"], f"expected FIFO, got {order}"


def test_no_starvation_under_contention():
    """Every waiter eventually gets a permit."""
    sem = Semaphore(permits=2)
    sem.acquire()
    sem.acquire()
    got_permit = [0]
    counter_lock = threading.Lock()

    def worker():
        if sem.acquire(timeout=5.0):
            with counter_lock:
                got_permit[0] += 1
            time.sleep(0.02)
            sem.release()

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()

    time.sleep(0.1)
    sem.release()
    sem.release()

    for t in threads:
        t.join(timeout=10.0)

    assert got_permit[0] == 6, f"only {got_permit[0]}/6 workers got permits"


# ---------------------------------------------------------------------------
# context manager
# ---------------------------------------------------------------------------

def test_context_manager():
    sem = Semaphore(permits=1)
    with sem:
        assert sem.available == 0
    assert sem.available == 1


def test_context_manager_exception_releases():
    sem = Semaphore(permits=1)
    try:
        with sem:
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert sem.available == 1


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

def test_invalid_permits():
    try:
        Semaphore(permits=0)
        assert False, "should have raised ValueError"
    except ValueError:
        pass

    try:
        Semaphore(permits=-1)
        assert False, "should have raised ValueError"
    except ValueError:
        pass


def test_repr():
    sem = Semaphore(permits=5)
    assert "permits=5" in repr(sem)
    assert "available=5" in repr(sem)


def test_single_permit():
    """Default semaphore (permits=1) acts as a mutex."""
    sem = Semaphore()
    assert sem.capacity == 1
    sem.acquire()
    assert sem.acquire(timeout=0.01) is False
    sem.release()
    assert sem.acquire(timeout=0.01) is True


# ---------------------------------------------------------------------------
# concurrent stress
# ---------------------------------------------------------------------------

def test_concurrent_acquire_release():
    """20 threads hammering acquire/release; available must stay in bounds."""
    sem = Semaphore(permits=3)
    max_seen = [0]
    current = [0]
    lock = threading.Lock()
    errors = []

    def worker():
        for _ in range(50):
            sem.acquire(timeout=5.0)
            with lock:
                current[0] += 1
                if current[0] > max_seen[0]:
                    max_seen[0] = current[0]
                if current[0] > 3:
                    errors.append(f"over-limit: {current[0]}")
            time.sleep(0.001)
            with lock:
                current[0] -= 1
            sem.release()

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    assert not errors, f"permit violations: {errors}"
    assert sem.available == 3


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed, failed = 0, 0
    for fn in tests:
        name = fn.__name__
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
    print(f"\n{passed} passed, {failed} failed ({len(tests)} total)")
    return failed == 0


if __name__ == "__main__":
    ok = _run_all()
    sys.exit(0 if ok else 1)
