"""Tests for snippets/expiring_dict.py — ExpiringDict with TTL eviction."""

from __future__ import annotations

import time

from snippets.expiring_dict import ExpiringDict


def _fake_clock(values: list[float]):
    """Return a clock function that yields successive values from a list."""
    it = iter(values)

    def clock():
        try:
            return next(it)
        except StopIteration:
            return values[-1]

    return clock


class TestBasicOps:
    def test_set_and_get(self):
        d = ExpiringDict(ttl=60)
        d["key"] = "value"
        assert d["key"] == "value"

    def test_contains(self):
        d = ExpiringDict(ttl=60)
        d["k"] = 1
        assert "k" in d
        assert "missing" not in d

    def test_delete(self):
        d = ExpiringDict(ttl=60)
        d["k"] = 1
        del d["k"]
        assert "k" not in d

    def test_get_default(self):
        d = ExpiringDict(ttl=60)
        assert d.get("nope", 42) == 42

    def test_len_empty(self):
        d = ExpiringDict(ttl=60)
        assert len(d) == 0

    def test_iter(self):
        d = ExpiringDict(ttl=60)
        d["a"] = 1
        d["b"] = 2
        assert sorted(d) == ["a", "b"]


class TestExpiration:
    def test_key_expires_after_ttl(self):
        clk = _fake_clock([0.0, 0.0, 5.0, 5.0])
        d = ExpiringDict(ttl=3.0, clock=clk)
        d["x"] = "hello"
        # at t=0, key is fresh
        assert d.get("x") == "hello"
        # at t=5, key should be expired (ttl=3)
        assert d.get("x") is None

    def test_len_excludes_expired(self):
        clk = _fake_clock([0.0, 0.0, 10.0])
        d = ExpiringDict(ttl=5.0, clock=clk)
        d["a"] = 1
        d["b"] = 2
        # at t=10 both expired
        assert len(d) == 0

    def test_sweep_removes_expired(self):
        clk = _fake_clock([0.0, 0.0, 0.0, 100.0])
        d = ExpiringDict(ttl=1.0, clock=clk)
        d["a"] = 1
        d["b"] = 2
        d["c"] = 3
        removed = d.sweep()
        assert removed == 3
        assert len(d) == 0

    def test_contains_evicts_expired(self):
        clk = _fake_clock([0.0, 10.0])
        d = ExpiringDict(ttl=2.0, clock=clk)
        d["k"] = 1
        assert "k" not in d


class TestTouch:
    def test_touch_refreshes_ttl(self):
        clk = _fake_clock([0.0, 4.0, 4.0, 7.0])
        d = ExpiringDict(ttl=5.0, clock=clk)
        d["k"] = "alive"
        # at t=4, touch resets expiry to t=9
        assert d.touch("k") is True
        # at t=7, key is still alive (would have expired at t=5 without touch)
        assert d.get("k") == "alive"

    def test_touch_missing_key(self):
        d = ExpiringDict(ttl=60)
        assert d.touch("ghost") is False


class TestCollections:
    def test_keys_values_items(self):
        d = ExpiringDict(ttl=60)
        d["x"] = 10
        d["y"] = 20
        assert sorted(d.keys()) == ["x", "y"]
        assert sorted(d.values()) == [10, 20]
        assert sorted(d.items()) == [("x", 10), ("y", 20)]


class TestValidation:
    def test_negative_ttl_raises(self):
        import pytest

        with pytest.raises(ValueError):
            ExpiringDict(ttl=-1)

    def test_zero_ttl_raises(self):
        import pytest

        with pytest.raises(ValueError):
            ExpiringDict(ttl=0)
