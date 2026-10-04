"""Tests for snippets/deadman.py — dead man's switch for silent process death."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from deadman import Deadman  # noqa: E402


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


def test_timeout_must_be_positive():
    with pytest.raises(ValueError, match="timeout must be > 0"):
        Deadman(timeout=0.0)
    with pytest.raises(ValueError, match="timeout must be > 0"):
        Deadman(timeout=-5.0)


def test_initial_state_is_never_pinged():
    d = Deadman(timeout=10.0, clock=lambda: 0.0)
    assert d.total_pings == 0
    assert "never-pinged" in repr(d)


# ---------------------------------------------------------------------------
# ping
# ---------------------------------------------------------------------------


def test_ping_increments_counter():
    d = Deadman(timeout=10.0, clock=lambda: 0.0)
    d.ping(clock=lambda: 0.0)
    d.ping(clock=lambda: 1.0)
    d.ping(clock=lambda: 2.0)
    assert d.total_pings == 3


def test_ping_updates_last_ping_time():
    d = Deadman(timeout=10.0, clock=lambda: 0.0)
    d.ping(clock=lambda: 5.0)
    assert d.seconds_since_ping(clock=lambda: 8.0) == 3.0


# ---------------------------------------------------------------------------
# alive / expired
# ---------------------------------------------------------------------------


def test_alive_within_timeout():
    d = Deadman(timeout=10.0, clock=lambda: 0.0)
    d.ping(clock=lambda: 0.0)
    assert d.alive(clock=lambda: 5.0) is True
    assert d.expired(clock=lambda: 5.0) is False


def test_alive_at_exact_boundary():
    d = Deadman(timeout=10.0, clock=lambda: 0.0)
    d.ping(clock=lambda: 0.0)
    assert d.alive(clock=lambda: 10.0) is True


def test_expired_past_timeout():
    d = Deadman(timeout=10.0, clock=lambda: 0.0)
    d.ping(clock=lambda: 0.0)
    assert d.alive(clock=lambda: 10.1) is False
    assert d.expired(clock=lambda: 10.1) is True


def test_never_pinged_expires_from_creation():
    d = Deadman(timeout=5.0, clock=lambda: 0.0)
    assert d.alive(clock=lambda: 3.0) is True
    assert d.alive(clock=lambda: 5.0) is True
    assert d.expired(clock=lambda: 6.0) is True


# ---------------------------------------------------------------------------
# seconds_since_ping
# ---------------------------------------------------------------------------


def test_seconds_since_ping_with_no_ping():
    d = Deadman(timeout=10.0, clock=lambda: 100.0)
    assert d.seconds_since_ping(clock=lambda: 105.0) == 5.0


def test_seconds_since_ping_after_ping():
    d = Deadman(timeout=10.0, clock=lambda: 0.0)
    d.ping(clock=lambda: 20.0)
    assert d.seconds_since_ping(clock=lambda: 25.0) == 5.0


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


def test_reset_clears_state():
    d = Deadman(timeout=10.0, clock=lambda: 0.0)
    d.ping(clock=lambda: 5.0)
    d.ping(clock=lambda: 8.0)
    assert d.total_pings == 2
    d.reset(clock=lambda: 10.0)
    assert d.total_pings == 0
    # after reset, seconds_since_ping counts from reset time
    assert d.seconds_since_ping(clock=lambda: 15.0) == 5.0


def test_reset_makes_switch_expire_from_reset_time():
    d = Deadman(timeout=5.0, clock=lambda: 0.0)
    d.ping(clock=lambda: 0.0)
    d.reset(clock=lambda: 100.0)
    assert d.alive(clock=lambda: 104.0) is True
    assert d.expired(clock=lambda: 106.0) is True


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


def test_repr_alive():
    d = Deadman(timeout=10.0, clock=lambda: 0.0)
    d.ping(clock=lambda: 0.0)
    r = repr(d)
    assert "alive" in r
    assert "pings=1" in r


def test_repr_never_pinged():
    d = Deadman(timeout=10.0, clock=lambda: 0.0)
    r = repr(d)
    assert "never-pinged" in r


# ---------------------------------------------------------------------------
# timeout property
# ---------------------------------------------------------------------------


def test_timeout_property():
    d = Deadman(timeout=42.0, clock=lambda: 0.0)
    assert d.timeout == 42.0


# ---------------------------------------------------------------------------
# realistic scenario: writer heartbeat
# ---------------------------------------------------------------------------


def test_writer_heartbeat_scenario():
    """Simulate a writer that pings every 15s with a 60s timeout."""
    d = Deadman(timeout=60.0, clock=lambda: 0.0)

    # writer pings at t=0, 15, 30, 45
    for t in [0, 15, 30, 45]:
        d.ping(clock=lambda t=t: t)

    assert d.total_pings == 4
    assert d.alive(clock=lambda: 50.0) is True

    # writer dies at t=45, no more pings
    assert d.alive(clock=lambda: 100.0) is True  # still within 60s of last ping
    assert d.expired(clock=lambda: 106.0) is True  # 45+60=105, past that


def test_multiple_deadmans_independent():
    """Two switches track independently — writer vs committer."""
    writer_dm = Deadman(timeout=30.0, clock=lambda: 0.0)
    committer_dm = Deadman(timeout=600.0, clock=lambda: 0.0)

    writer_dm.ping(clock=lambda: 0.0)
    committer_dm.ping(clock=lambda: 0.0)

    # writer dies, committer lives
    assert writer_dm.expired(clock=lambda: 31.0) is True
    assert committer_dm.alive(clock=lambda: 31.0) is True
