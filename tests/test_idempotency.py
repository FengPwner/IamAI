"""Tests for snippets/idempotency.py — duplicate rejection with TTL."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from idempotency import IdempotencyStore  # noqa: E402


def test_accept_new_key():
    s = IdempotencyStore(ttl=60.0, clock=lambda: 100.0)
    assert s.accept("a") is True
    assert len(s) == 1


def test_reject_duplicate():
    s = IdempotencyStore(ttl=60.0, clock=lambda: 100.0)
    s.accept("a")
    assert s.accept("a") is False


def test_expired_key_is_reaccepted():
    now = [100.0]
    s = IdempotencyStore(ttl=10.0, clock=lambda: now[0])
    s.accept("a")
    now[0] = 111.0  # past TTL
    assert s.accept("a") is True


def test_record_and_result():
    s = IdempotencyStore(ttl=60.0, clock=lambda: 0.0)
    s.accept("x")
    s.record("x", {"status": "done"})
    assert s.result("x") == {"status": "done"}


def test_result_missing_key():
    s = IdempotencyStore(ttl=60.0, clock=lambda: 0.0)
    assert s.result("nope") is None


def test_record_unknown_key_raises():
    s = IdempotencyStore(ttl=60.0, clock=lambda: 0.0)
    with pytest.raises(KeyError):
        s.record("ghost", 42)


def test_evict_removes_expired():
    now = [0.0]
    s = IdempotencyStore(ttl=5.0, clock=lambda: now[0])
    s.accept("old")
    now[0] = 10.0
    s.accept("new")
    purged = s.evict()
    assert purged == 1
    assert len(s) == 1
    assert s.result("new") is None  # accepted but no result recorded


def test_negative_ttl_raises():
    with pytest.raises(ValueError):
        IdempotencyStore(ttl=-1.0)


def test_zero_ttl_rejects_immediately():
    now = [0.0]
    s = IdempotencyStore(ttl=0.0, clock=lambda: now[0])
    s.accept("a")
    # same timestamp -> elapsed == 0, not < 0 -> not duplicate
    assert s.accept("a") is True


def test_multiple_keys_independent():
    s = IdempotencyStore(ttl=60.0, clock=lambda: 0.0)
    s.accept("a")
    s.accept("b")
    s.accept("c")
    assert len(s) == 3
    assert s.accept("b") is False
    assert s.accept("d") is True
