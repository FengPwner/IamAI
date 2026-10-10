"""Tests for snippets/cooldown.py — minimum-interval gate."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from cooldown import Cooldown  # noqa: E402


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


def test_initial_state_is_ready():
    c = Cooldown(seconds=10)
    assert c.remaining() == 0.0
    assert c.acquire_count == 0
    assert "ready" in repr(c)


def test_negative_window_raises():
    with pytest.raises(ValueError, match=">= 0"):
        Cooldown(seconds=-1)


def test_zero_window_always_ready():
    c = Cooldown(seconds=0)
    assert c.try_acquire() is True
    assert c.try_acquire() is True
    assert c.try_acquire() is True
    assert c.acquire_count == 3


# ---------------------------------------------------------------------------
# try_acquire — first call succeeds, subsequent blocked
# ---------------------------------------------------------------------------


def test_first_acquire_succeeds():
    c = Cooldown(seconds=60)
    assert c.try_acquire() is True
    assert c.acquire_count == 1


def test_second_acquire_blocked_within_window():
    c = Cooldown(seconds=60)
    c.try_acquire()
    assert c.try_acquire() is False
    assert c.try_acquire() is False
    assert c.acquire_count == 1


def test_acquire_succeeds_after_window_elapsed():
    c = Cooldown(seconds=0.05)
    c.try_acquire()
    time.sleep(0.06)
    assert c.try_acquire() is True
    assert c.acquire_count == 2


def test_multiple_windows():
    c = Cooldown(seconds=0.05)
    acquired = []
    for _ in range(3):
        acquired.append(c.try_acquire())
        time.sleep(0.06)
    assert acquired == [True, True, True]
    assert c.acquire_count == 3


# ---------------------------------------------------------------------------
# remaining
# ---------------------------------------------------------------------------


def test_remaining_zero_before_first_acquire():
    c = Cooldown(seconds=10)
    assert c.remaining() == 0.0


def test_remaining_positive_after_acquire():
    c = Cooldown(seconds=10)
    c.try_acquire()
    assert c.remaining() > 0.0
    assert c.remaining() <= 10.0


def test_remaining_decreases_over_time():
    c = Cooldown(seconds=1.0)
    c.try_acquire()
    r1 = c.remaining()
    time.sleep(0.05)
    r2 = c.remaining()
    assert r2 < r1


def test_remaining_zero_after_window():
    c = Cooldown(seconds=0.05)
    c.try_acquire()
    time.sleep(0.06)
    assert c.remaining() == 0.0


# ---------------------------------------------------------------------------
# force — bypass the gate
# ---------------------------------------------------------------------------


def test_force_resets_cooldown():
    c = Cooldown(seconds=60)
    c.try_acquire()
    assert c.try_acquire() is False
    c.force()
    assert c.try_acquire() is True
    assert c.acquire_count == 2


def test_force_on_fresh_cooldown_is_harmless():
    c = Cooldown(seconds=10)
    c.force()
    assert c.try_acquire() is True


def test_force_preserves_acquire_count():
    c = Cooldown(seconds=10)
    c.try_acquire()
    c.force()
    assert c.acquire_count == 1  # force doesn't count as acquire


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


def test_repr_when_ready():
    c = Cooldown(seconds=5)
    assert "ready" in repr(c)
    assert "5" in repr(c)


def test_repr_when_cooling():
    c = Cooldown(seconds=60)
    c.try_acquire()
    r = repr(c)
    assert "left" in r
    assert "acquires=1" in r


# ---------------------------------------------------------------------------
# monotonic clock — immune to wall-clock jumps
# ---------------------------------------------------------------------------


def test_uses_monotonic_clock():
    """Verify cooldown uses monotonic, not wall-clock time."""
    c = Cooldown(seconds=10)
    c.try_acquire()
    # Even if we mock time.time() to jump forward, cooldown should still block
    with patch("time.time", return_value=time.time() + 999999):
        assert c.try_acquire() is False


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


def test_rapid_fire_only_first_succeeds():
    c = Cooldown(seconds=1.0)
    results = [c.try_acquire() for _ in range(100)]
    assert results[0] is True
    assert all(r is False for r in results[1:])
    assert c.acquire_count == 1


def test_window_property():
    c = Cooldown(seconds=42.5)
    assert c.window == 42.5


def test_acquire_count_survives_force_cycle():
    c = Cooldown(seconds=0.01)
    for _ in range(5):
        c.try_acquire()
        time.sleep(0.02)
    count_before = c.acquire_count
    c.force()
    assert c.acquire_count == count_before
