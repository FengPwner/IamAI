"""Tests for snippets/consistent_hash.py — ring distribution and stability."""

from __future__ import annotations

import sys
from pathlib import Path
from collections import Counter

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from consistent_hash import ConsistentHash  # noqa: E402


def test_empty_ring_returns_none():
    ring = ConsistentHash()
    assert ring.get_node("anything") is None
    assert ring.get_nodes("anything", 3) == []


def test_single_node_always_wins():
    ring = ConsistentHash(["only"])
    for i in range(50):
        assert ring.get_node(f"key:{i}") == "only"


def test_add_node_idempotent():
    ring = ConsistentHash(["a"], replicas=10)
    size_before = len(ring._ring)
    ring.add_node("a")  # duplicate
    assert len(ring._ring) == size_before
    assert len(ring.nodes) == 1


def test_remove_node_not_present_is_noop():
    ring = ConsistentHash(["a", "b"])
    ring.remove_node("z")
    assert len(ring.nodes) == 2


def test_distribution_reasonably_balanced():
    nodes = ["n1", "n2", "n3", "n4"]
    ring = ConsistentHash(nodes, replicas=200)
    counts = Counter(ring.get_node(f"item:{i}") for i in range(10_000))
    # Each node should get roughly 25% — allow 15%–35% range.
    for node in nodes:
        share = counts[node] / 10_000
        assert 0.15 <= share <= 0.35, f"{node} got {share:.1%}, expected ~25%"


def test_stability_most_keys_stick_after_removal():
    """Removing one of many nodes should leave most keys on the same node."""
    nodes = ["alpha", "beta", "gamma", "delta", "epsilon"]
    ring = ConsistentHash(nodes, replicas=200)
    before = {f"k:{i}": ring.get_node(f"k:{i}") for i in range(5000)}
    ring.remove_node("gamma")
    after = {k: ring.get_node(k) for k in before}
    # Keys not previously on gamma should mostly stay put.
    non_gamma = {k: v for k, v in before.items() if v != "gamma"}
    stable = sum(1 for k, v in non_gamma.items() if after[k] == v)
    ratio = stable / len(non_gamma) if non_gamma else 1.0
    assert ratio > 0.85, f"only {ratio:.0%} of non-gamma keys stayed"


def test_get_nodes_returns_distinct():
    ring = ConsistentHash(["a", "b", "c", "d"], replicas=100)
    result = ring.get_nodes("some-key", count=3)
    assert len(result) == 3
    assert len(set(result)) == 3  # all distinct


def test_get_nodes_capped_at_ring_size():
    ring = ConsistentHash(["a", "b"])
    result = ring.get_nodes("key", count=10)
    assert len(result) == 2
    assert set(result) == {"a", "b"}


def test_replicas_validation():
    with pytest.raises(ValueError, match="replicas"):
        ConsistentHash(replicas=0)


def test_len_and_iter():
    ring = ConsistentHash(["c", "a", "b"])
    assert len(ring) == 3
    assert list(ring) == ["a", "b", "c"]  # sorted
