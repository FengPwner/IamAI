"""Tests for snippets/fuse.py — one-shot, non-resettable circuit breaker."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from fuse import Fuse  # noqa: E402


# ---------------------------------------------------------------------------
# construction / validation
# ---------------------------------------------------------------------------


def test_default_construction():
    f = Fuse()
    assert f.limit == 3
    assert f.failures == 0
    assert f.blown is False
    assert f.remaining == 3


def test_limit_one():
    f = Fuse(limit=1)
    assert f.limit == 1
    assert f.remaining == 1


def test_limit_zero_raises():
    with pytest.raises(ValueError, match="limit must be >= 1"):
        Fuse(limit=0)


def test_limit_negative_raises():
    with pytest.raises(ValueError, match="limit must be >= 1"):
        Fuse(limit=-5)


# ---------------------------------------------------------------------------
# allow() — gate behavior
# ---------------------------------------------------------------------------


def test_allow_when_intact():
    f = Fuse(limit=2)
    assert f.allow() is True


def test_allow_after_one_failure():
    f = Fuse(limit=3)
    f.record_failure()
    assert f.allow() is True


def test_allow_after_blown():
    f = Fuse(limit=2)
    f.record_failure()
    f.record_failure()
    assert f.allow() is False


def test_allow_stays_false_after_more_failures():
    f = Fuse(limit=1)
    f.record_failure()
    assert f.allow() is False
    # extra failures after blown should be no-ops
    f.record_failure()
    f.record_failure()
    assert f.allow() is False


# ---------------------------------------------------------------------------
# record_failure() — counting and blowing
# ---------------------------------------------------------------------------


def test_single_failure_not_blown():
    f = Fuse(limit=3)
    f.record_failure()
    assert f.failures == 1
    assert f.blown is False


def test_failures_below_limit():
    f = Fuse(limit=5)
    for _ in range(4):
        f.record_failure()
    assert f.failures == 4
    assert f.blown is False
    assert f.remaining == 1


def test_failures_reach_limit():
    f = Fuse(limit=3)
    for _ in range(3):
        f.record_failure()
    assert f.failures == 3
    assert f.blown is True
    assert f.remaining == 0


def test_failures_capped_at_limit():
    f = Fuse(limit=2)
    for _ in range(10):
        f.record_failure()
    assert f.failures == 2  # capped, doesn't keep counting
    assert f.blown is True


def test_remaining_decreases():
    f = Fuse(limit=4)
    assert f.remaining == 4
    f.record_failure()
    assert f.remaining == 3
    f.record_failure()
    assert f.remaining == 2


# ---------------------------------------------------------------------------
# record_success() — no reset
# ---------------------------------------------------------------------------


def test_success_does_not_reset():
    f = Fuse(limit=3)
    f.record_failure()
    f.record_failure()
    f.record_success()
    assert f.failures == 2
    assert f.blown is False


def test_success_after_blown_stays_blown():
    f = Fuse(limit=1)
    f.record_failure()
    assert f.blown is True
    f.record_success()
    assert f.blown is True  # no recovery


# ---------------------------------------------------------------------------
# on_blow callback
# ---------------------------------------------------------------------------


def test_on_blow_fires_exactly_once():
    calls = []
    f = Fuse(limit=2, on_blow=lambda: calls.append("blown"))
    f.record_failure()
    assert len(calls) == 0  # not yet
    f.record_failure()
    assert calls == ["blown"]  # fires on the threshold


def test_on_blow_not_called_again_after_more_failures():
    calls = []
    f = Fuse(limit=1, on_blow=lambda: calls.append(1))
    f.record_failure()
    assert len(calls) == 1
    f.record_failure()
    f.record_failure()
    assert len(calls) == 1  # still 1


def test_no_on_blow_callback():
    f = Fuse(limit=1)
    f.record_failure()  # should not raise
    assert f.blown is True


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


def test_repr_intact():
    f = Fuse(limit=3)
    r = repr(f)
    assert "3 remaining" in r
    assert "BLOWN" not in r


def test_repr_blown():
    f = Fuse(limit=1)
    f.record_failure()
    assert "BLOWN" in repr(f)


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


def test_limit_one_blows_immediately():
    f = Fuse(limit=1)
    assert f.allow() is True
    f.record_failure()
    assert f.allow() is False
    assert f.blown is True


def test_large_limit():
    f = Fuse(limit=1000)
    for _ in range(999):
        f.record_failure()
    assert f.blown is False
    f.record_failure()
    assert f.blown is True


def test_mixed_success_and_failure():
    f = Fuse(limit=3)
    f.record_failure()
    f.record_success()
    f.record_failure()
    f.record_success()
    f.record_success()
    assert f.failures == 2
    assert f.blown is False
    f.record_failure()
    assert f.failures == 3
    assert f.blown is True
