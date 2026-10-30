"""Tests for snippets/backoff.py — exponential delay sequence with jitter."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from backoff import Backoff  # noqa: E402


# ---------------------------------------------------------------------------
# construction / validation
# ---------------------------------------------------------------------------


def test_default_construction():
    b = Backoff()
    assert b.base == 1.0
    assert b.max_delay == 30.0
    assert b.strategy == "none"
    assert b.attempt == 0


def test_invalid_base_raises():
    with pytest.raises(ValueError, match="base must be > 0"):
        Backoff(base=0)
    with pytest.raises(ValueError, match="base must be > 0"):
        Backoff(base=-1.0)


def test_max_less_than_base_raises():
    with pytest.raises(ValueError, match="max_delay must be >= base"):
        Backoff(base=5.0, max_delay=3.0)


def test_unknown_strategy_raises():
    with pytest.raises(ValueError, match="unknown strategy"):
        Backoff(strategy="turbo")


# ---------------------------------------------------------------------------
# strategy="none" — deterministic exponential
# ---------------------------------------------------------------------------


def test_none_produces_powers_of_two():
    b = Backoff(base=1.0, max_delay=64.0, strategy="none")
    delays = [b.next() for _ in range(7)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0]


def test_none_caps_at_max():
    b = Backoff(base=1.0, max_delay=10.0, strategy="none")
    delays = [b.next() for _ in range(6)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]


def test_none_single_step_cap():
    b = Backoff(base=1.0, max_delay=1.0, strategy="none")
    assert b.next() == 1.0
    assert b.next() == 1.0


# ---------------------------------------------------------------------------
# strategy="full" — uniform in [0, raw]
# ---------------------------------------------------------------------------


def test_full_within_bounds():
    import random

    b = Backoff(base=2.0, max_delay=20.0, strategy="full", rng=random.Random(42))
    for _ in range(50):
        d = b.next()
        raw = min(2.0 * (2 ** (b.attempt - 1)), 20.0)
        assert 0.0 <= d <= raw + 1e-9


def test_full_first_delay_bounded():
    import random

    b = Backoff(base=1.0, max_delay=10.0, strategy="full", rng=random.Random(0))
    d = b.next()
    assert 0.0 <= d <= 1.0


# ---------------------------------------------------------------------------
# strategy="equal" — uniform in [raw/2, raw]
# ---------------------------------------------------------------------------


def test_equal_within_bounds():
    import random

    b = Backoff(base=4.0, max_delay=32.0, strategy="equal", rng=random.Random(99))
    for _ in range(50):
        d = b.next()
        raw = min(4.0 * (2 ** (b.attempt - 1)), 32.0)
        assert raw / 2 - 1e-9 <= d <= raw + 1e-9


def test_equal_never_less_than_half():
    import random

    b = Backoff(base=2.0, max_delay=16.0, strategy="equal", rng=random.Random(7))
    for _ in range(30):
        d = b.next()
        raw = min(2.0 * (2 ** (b.attempt - 1)), 16.0)
        assert d >= raw / 2 - 1e-9


# ---------------------------------------------------------------------------
# delays() — preview without side effects
# ---------------------------------------------------------------------------


def test_delays_does_not_mutate_attempt():
    b = Backoff(base=1.0, max_delay=8.0, strategy="none")
    preview = list(b.delays(4))
    assert preview == [1.0, 2.0, 4.0, 8.0]
    assert b.attempt == 0  # unchanged

    # next() still starts from the beginning
    assert b.next() == 1.0


def test_delays_zero():
    b = Backoff(base=1.0, max_delay=10.0, strategy="none")
    assert list(b.delays(0)) == []
    assert b.attempt == 0


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


def test_reset_restarts_sequence():
    b = Backoff(base=1.0, max_delay=10.0, strategy="none")
    b.next()  # 1.0
    b.next()  # 2.0
    b.next()  # 4.0
    assert b.attempt == 3

    b.reset()
    assert b.attempt == 0
    assert b.next() == 1.0


def test_reset_on_fresh_backoff_is_noop():
    b = Backoff()
    b.reset()
    assert b.attempt == 0


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


def test_repr():
    b = Backoff(base=2.0, max_delay=20.0, strategy="full")
    r = repr(b)
    assert "base=2.0" in r
    assert "max=20.0" in r
    assert "full" in r
    assert "attempt=0" in r


# ---------------------------------------------------------------------------
# realistic scenario: push retry coordination
# ---------------------------------------------------------------------------


def test_push_retry_scenario():
    """Simulate retrying a git push with capped exponential backoff."""
    import random

    b = Backoff(base=0.5, max_delay=8.0, strategy="equal", rng=random.Random(123))
    delays = [b.next() for _ in range(6)]

    # each delay should be >= half the raw value and <= raw (capped)
    for i, d in enumerate(delays):
        raw = min(0.5 * (2 ** i), 8.0)
        assert raw / 2 - 1e-9 <= d <= raw + 1e-9

    # after 6 attempts, we've backed off significantly
    assert delays[-1] >= 4.0  # raw at attempt 5 is min(0.5*32, 8)=8, half=4
