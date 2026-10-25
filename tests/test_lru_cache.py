"""Tests for snippets/lru_cache.py — same contract, no threads."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from lru_cache import LRUCache, lru_memoize  # noqa: E402


def test_basic_get_put():
    c = LRUCache(capacity=3)
    c.put("x", 10)
    c.put("y", 20)
    assert c.get("x") == 10
    assert c.get("y") == 20
    assert c.get("z") is None


def test_eviction_drops_lru():
    c = LRUCache(capacity=2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3)  # evicts "a"
    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_access_refreshes_recency():
    c = LRUCache(capacity=2)
    c.put("a", 1)
    c.put("b", 2)
    c.get("a")     # "a" is now most recently used
    c.put("c", 3)  # evicts "b", not "a"
    assert c.get("a") == 1
    assert c.get("b") is None
    assert c.get("c") == 3


def test_update_existing_key():
    c = LRUCache(capacity=2)
    c.put("a", 1)
    c.put("a", 99)
    assert c.get("a") == 99
    assert len(c) == 1


def test_capacity_one():
    c = LRUCache(capacity=1)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") is None
    assert c.get("b") == 2


def test_invalid_capacity():
    with pytest.raises(ValueError):
        LRUCache(capacity=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=-5)


def test_contains():
    c = LRUCache(capacity=3)
    c.put("a", 1)
    assert "a" in c
    assert "b" not in c


def test_keys_lru_order():
    c = LRUCache(capacity=3)
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3)
    assert c.keys() == ["a", "b", "c"]
    c.get("a")  # refresh "a"
    assert c.keys() == ["b", "c", "a"]


def test_clear():
    c = LRUCache(capacity=3)
    c.put("a", 1)
    c.put("b", 2)
    c.clear()
    assert len(c) == 0
    assert c.get("a") is None


def test_memoize_caches_results():
    call_count = [0]

    @lru_memoize(capacity=4)
    def expensive(n):
        call_count[0] += 1
        return n * n

    assert expensive(3) == 9
    assert expensive(3) == 9
    assert call_count[0] == 1

    assert expensive(4) == 16
    assert call_count[0] == 2


def test_memoize_eviction():
    call_count = [0]

    @lru_memoize(capacity=2)
    def double(n):
        call_count[0] += 1
        return n * 2

    double(1)  # miss
    double(2)  # miss
    double(1)  # hit
    assert call_count[0] == 2

    double(3)  # miss, evicts 2
    double(2)  # miss again (was evicted)
    assert call_count[0] == 4
