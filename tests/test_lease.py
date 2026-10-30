"""Tests for snippets/lease.py — time-bounded exclusive lease."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from lease import Lease  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class FakeClock:
    """Controllable monotonic clock for deterministic tests."""

    def __init__(self, start: float = 0.0):
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# ---------------------------------------------------------------------------
# acquire / release
# ---------------------------------------------------------------------------

def test_acquire_grants_to_first_caller():
    clk = FakeClock()
    ls = Lease(ttl=10.0, clock=clk)
    assert ls.acquire("alice") is True
    assert ls.holder == "alice"


def test_acquire_rejects_second_caller():
    clk = FakeClock()
    ls = Lease(ttl=10.0, clock=clk)
    ls.acquire("alice")
    assert ls.acquire("bob") is False
    assert ls.holder == "alice"


def test_release_by_holder():
    clk = FakeClock()
    ls = Lease(ttl=10.0, clock=clk)
    ls.acquire("alice")
    assert ls.release("alice") is True
    assert ls.holder is None


def test_release_by_non_holder_is_noop():
    clk = FakeClock()
    ls = Lease(ttl=10.0, clock=clk)
    ls.acquire("alice")
    assert ls.release("bob") is False
    assert ls.holder == "alice"


def test_release_on_free_lease():
    ls = Lease(ttl=10.0, clock=FakeClock())
    assert ls.release("nobody") is False


# ---------------------------------------------------------------------------
# expiration
# ---------------------------------------------------------------------------

def test_lease_expires_after_ttl():
    clk = FakeClock()
    ls = Lease(ttl=5.0, clock=clk)
    ls.acquire("alice")
    clk.advance(4.9)
    assert ls.holder == "alice"
    clk.advance(0.2)  # now at 5.1 — past TTL
    assert ls.holder is None


def test_new_caller_after_expiration():
    clk = FakeClock()
    ls = Lease(ttl=3.0, clock=clk)
    ls.acquire("alice")
    clk.advance(3.1)
    assert ls.acquire("bob") is True
    assert ls.holder == "bob"


def test_remaining_counts_down():
    clk = FakeClock()
    ls = Lease(ttl=10.0, clock=clk)
    ls.acquire("alice")
    assert ls.remaining == pytest.approx(10.0)
    clk.advance(4.0)
    assert ls.remaining == pytest.approx(6.0)
    clk.advance(7.0)  # past TTL
    assert ls.remaining == 0.0


# ---------------------------------------------------------------------------
# renewal
# ---------------------------------------------------------------------------

def test_same_holder_can_renew():
    clk = FakeClock()
    ls = Lease(ttl=5.0, clock=clk)
    ls.acquire("alice")
    clk.advance(3.0)
    assert ls.acquire("alice") is True  # renewal
    assert ls.remaining == pytest.approx(5.0)  # TTL reset


def test_renewal_does_not_help_other_caller():
    clk = FakeClock()
    ls = Lease(ttl=5.0, clock=clk)
    ls.acquire("alice")
    clk.advance(2.0)
    ls.acquire("alice")  # renew
    clk.advance(2.0)
    assert ls.acquire("bob") is False  # still held


# ---------------------------------------------------------------------------
# force release
# ---------------------------------------------------------------------------

def test_force_release_clears_regardless():
    clk = FakeClock()
    ls = Lease(ttl=10.0, clock=clk)
    ls.acquire("alice")
    ls.force_release()
    assert ls.holder is None
    assert ls.acquire("bob") is True


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def test_zero_ttl_rejected():
    with pytest.raises(ValueError):
        Lease(ttl=0)


def test_negative_ttl_rejected():
    with pytest.raises(ValueError):
        Lease(ttl=-5)


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------

def test_repr_free():
    ls = Lease(ttl=10.0, clock=FakeClock())
    assert "free" in repr(ls)


def test_repr_held():
    clk = FakeClock()
    ls = Lease(ttl=10.0, clock=clk)
    ls.acquire("alice")
    r = repr(ls)
    assert "alice" in r
    assert "10.0s" in r
