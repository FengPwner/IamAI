"""Tests for snippets/union_find.py — 26 tests covering DSU operations."""

from __future__ import annotations

import pytest

from snippets.union_find import UnionFind


# ---------------------------------------------------------------------------
# construction & make_set
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_empty(self):
        uf = UnionFind()
        assert len(uf) == 0
        assert uf.count == 0

    def test_make_set_single(self):
        uf = UnionFind()
        uf.make_set("a")
        assert "a" in uf
        assert uf.count == 1

    def test_make_set_multiple(self):
        uf = UnionFind()
        for i in range(5):
            uf.make_set(i)
        assert len(uf) == 5
        assert uf.count == 5

    def test_make_set_idempotent(self):
        uf = UnionFind()
        uf.make_set("x")
        uf.make_set("x")
        assert uf.count == 1
        assert len(uf) == 1

    def test_repr(self):
        uf = UnionFind()
        for i in range(3):
            uf.make_set(i)
        assert "elements=3" in repr(uf)
        assert "components=3" in repr(uf)


# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------

class TestFind:
    def test_find_singleton(self):
        uf = UnionFind()
        uf.make_set(42)
        assert uf.find(42) == 42

    def test_find_auto_creates(self):
        """find on unknown element should auto-create a singleton."""
        uf = UnionFind()
        root = uf.find("new")
        assert root == "new"
        assert "new" in uf
        assert uf.count == 1

    def test_find_same_after_union(self):
        uf = UnionFind()
        for i in range(4):
            uf.make_set(i)
        uf.union(0, 1)
        uf.union(2, 3)
        uf.union(1, 3)
        # all should share the same root
        r = uf.find(0)
        assert uf.find(1) == r
        assert uf.find(2) == r
        assert uf.find(3) == r

    def test_find_path_compression(self):
        """After find, nodes on the path should point directly to root."""
        uf = UnionFind()
        # build a chain: 0 -> 1 -> 2 -> 3
        for i in range(4):
            uf.make_set(i)
        # force a deep tree by unioning without rank optimization trigger
        uf._parent[1] = 0
        uf._parent[2] = 1
        uf._parent[3] = 2
        uf._rank[0] = 3
        uf._size[0] = 4
        uf._count = 1

        # before find: 3 -> 2 -> 1 -> 0
        assert uf._parent[3] == 2
        # after find: 3 -> 0 directly
        root = uf.find(3)
        assert root == 0
        assert uf._parent[3] == 0
        assert uf._parent[2] == 0
        assert uf._parent[1] == 0


# ---------------------------------------------------------------------------
# union
# ---------------------------------------------------------------------------

class TestUnion:
    def test_union_returns_true_on_merge(self):
        uf = UnionFind()
        uf.make_set("a")
        uf.make_set("b")
        assert uf.union("a", "b") is True

    def test_union_returns_false_when_same(self):
        uf = UnionFind()
        uf.make_set("a")
        uf.make_set("b")
        uf.union("a", "b")
        assert uf.union("a", "b") is False

    def test_union_reduces_count(self):
        uf = UnionFind()
        for i in range(5):
            uf.make_set(i)
        assert uf.count == 5
        uf.union(0, 1)
        assert uf.count == 4
        uf.union(2, 3)
        assert uf.count == 3
        uf.union(0, 2)
        assert uf.count == 2

    def test_union_by_rank_keeps_balance(self):
        """Union by rank should keep trees shallow."""
        uf = UnionFind()
        for i in range(8):
            uf.make_set(i)
        # pairwise unions: (0,1), (2,3), (4,5), (6,7)
        for a, b in [(0, 1), (2, 3), (4, 5), (6, 7)]:
            uf.union(a, b)
        assert uf.count == 4
        # merge pairs: (0,2), (4,6)
        uf.union(0, 2)
        uf.union(4, 6)
        assert uf.count == 2
        # final merge
        uf.union(0, 4)
        assert uf.count == 1
        # max rank should be ~3 for 8 elements (log2(8))
        max_rank = max(uf._rank.values())
        assert max_rank <= 4

    def test_union_auto_creates(self):
        """union on unknown elements should auto-create them."""
        uf = UnionFind()
        uf.union("x", "y")
        assert "x" in uf
        assert "y" in uf
        assert uf.connected("x", "y")
        assert uf.count == 1


# ---------------------------------------------------------------------------
# connected
# ---------------------------------------------------------------------------

class TestConnected:
    def test_not_connected_initially(self):
        uf = UnionFind()
        uf.make_set("a")
        uf.make_set("b")
        assert not uf.connected("a", "b")

    def test_connected_after_union(self):
        uf = UnionFind()
        uf.make_set("a")
        uf.make_set("b")
        uf.union("a", "b")
        assert uf.connected("a", "b")

    def test_transitive(self):
        uf = UnionFind()
        for x in "abcde":
            uf.make_set(x)
        uf.union("a", "b")
        uf.union("b", "c")
        uf.union("c", "d")
        # a and d should be connected transitively
        assert uf.connected("a", "d")

    def test_disconnected_groups(self):
        uf = UnionFind()
        for i in range(6):
            uf.make_set(i)
        uf.union(0, 1)
        uf.union(2, 3)
        uf.union(4, 5)
        assert not uf.connected(0, 2)
        assert not uf.connected(2, 4)
        assert uf.connected(0, 1)


# ---------------------------------------------------------------------------
# size & components
# ---------------------------------------------------------------------------

class TestSizeAndComponents:
    def test_size_singleton(self):
        uf = UnionFind()
        uf.make_set(10)
        assert uf.size(10) == 1

    def test_size_after_unions(self):
        uf = UnionFind()
        for i in range(6):
            uf.make_set(i)
        uf.union(0, 1)
        uf.union(0, 2)
        assert uf.size(0) == 3
        assert uf.size(1) == 3
        assert uf.size(2) == 3
        assert uf.size(3) == 1

    def test_components_empty(self):
        uf = UnionFind()
        assert uf.components() == []

    def test_components_singletons(self):
        uf = UnionFind()
        for i in range(3):
            uf.make_set(i)
        comps = uf.components()
        assert len(comps) == 3
        assert all(len(c) == 1 for c in comps)

    def test_components_merged(self):
        uf = UnionFind()
        for i in range(5):
            uf.make_set(i)
        uf.union(0, 1)
        uf.union(2, 3)
        comps = uf.components()
        assert len(comps) == 3
        sizes = sorted(len(c) for c in comps)
        assert sizes == [1, 2, 2]

    def test_total(self):
        uf = UnionFind()
        for i in range(10):
            uf.make_set(i)
        assert uf.total == 10
        uf.union(0, 1)
        assert uf.total == 10  # total elements doesn't change

    def test_roots(self):
        uf = UnionFind()
        for i in range(4):
            uf.make_set(i)
        uf.union(0, 1)
        uf.union(2, 3)
        roots = uf.roots()
        assert len(roots) == 2


# ---------------------------------------------------------------------------
# mixed element types
# ---------------------------------------------------------------------------

class TestMixedTypes:
    def test_string_elements(self):
        uf = UnionFind()
        uf.union("hello", "world")
        assert uf.connected("hello", "world")
        assert uf.size("hello") == 2

    def test_tuple_elements(self):
        uf = UnionFind()
        uf.union((0, 0), (0, 1))
        uf.union((0, 1), (1, 1))
        assert uf.connected((0, 0), (1, 1))

    def test_int_elements(self):
        uf = UnionFind()
        for i in range(100):
            uf.make_set(i)
        for i in range(0, 100, 2):
            uf.union(i, i + 1) if i + 1 < 100 else None
        # each pair (0,1), (2,3), ... should be connected
        assert uf.connected(0, 1)
        assert uf.connected(98, 99)
        assert not uf.connected(0, 2)


# ---------------------------------------------------------------------------
# stress
# ---------------------------------------------------------------------------

class TestStress:
    def test_large_union_chain(self):
        """Chain of 10000 unions should complete quickly."""
        n = 10000
        uf = UnionFind()
        for i in range(n):
            uf.make_set(i)
        for i in range(n - 1):
            uf.union(i, i + 1)
        assert uf.count == 1
        assert uf.connected(0, n - 1)
        assert uf.size(0) == n
