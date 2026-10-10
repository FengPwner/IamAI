"""069 — union_find: disjoint-set union with path compression and union by rank.

some problems are really about grouping.  which cities are connected by
roads?  which pixels belong to the same blob?  which variables are
aliases of each other?  the questions look different but the structure
is identical: you have a set of elements and a stream of "merge these
two groups" operations, and at any point you need to answer "are these
two elements in the same group?"

the naive approach — maintain a list of sets and scan for membership —
is O(n) per query.  fine for ten elements, useless for ten million.

**disjoint-set union** (DSU, aka union-find) drops both operations to
nearly O(1) amortised with two simple tricks:

- **union by rank:** always attach the shorter tree under the taller
  one, keeping the tree shallow.
- **path compression:** on every ``find`` call, flatten the path so
  that future lookups skip straight to the root.

together these give O(α(n)) per operation, where α is the inverse
Ackermann function — effectively constant for any realistic input size.

this module provides:

- ``UnionFind()`` — create an empty DSU.
- ``make_set(x)`` — register a new singleton element.
- ``find(x)`` — return the representative (root) of x's group.
- ``union(x, y)`` — merge the groups containing x and y.
- ``connected(x, y)`` — boolean: same group?
- ``components()`` — list of all current groups as sets.
- ``size(x)`` — number of elements in x's group.

elements can be any hashable type — ints, strings, tuples.  auto-
creates sets on first access for convenience (no need to call
``make_set`` explicitly for simple use cases).

usage::

    from snippets.union_find import UnionFind

    uf = UnionFind()
    for city in ["NYC", "LA", "CHI", "SF", "BOS"]:
        uf.make_set(city)

    uf.union("NYC", "BOS")
    uf.union("LA", "SF")
    uf.union("CHI", "NYC")

    uf.connected("NYC", "CHI")   # True — both in the east-coast group
    uf.connected("LA", "BOS")    # False — separate groups
    uf.size("NYC")               # 3 (NYC + BOS + CHI)
    len(uf.components())          # 2
"""

from __future__ import annotations

from typing import Any, Dict, Hashable, List, Set


class UnionFind:
    """Disjoint-set union with path compression and union by rank.

    Elements can be any hashable type.  Groups are merged efficiently
    and the representative of each group is found in near-constant time.

    Examples
    --------
    >>> uf = UnionFind()
    >>> for x in range(5):
    ...     uf.make_set(x)
    >>> uf.union(0, 1)
    True
    >>> uf.union(2, 3)
    True
    >>> uf.connected(0, 1)
    True
    >>> uf.connected(0, 2)
    False
    >>> uf.union(1, 3)
    True
    >>> uf.connected(0, 3)
    True
    >>> uf.size(0)
    4
    """

    __slots__ = ("_parent", "_rank", "_size", "_count")

    def __init__(self) -> None:
        self._parent: Dict[Hashable, Hashable] = {}
        self._rank: Dict[Hashable, int] = {}
        self._size: Dict[Hashable, int] = {}
        self._count: int = 0  # number of disjoint components

    # ------------------------------------------------------------------
    # core operations
    # ------------------------------------------------------------------

    def make_set(self, x: Hashable) -> None:
        """Register *x* as a new singleton group.

        If *x* is already present this is a no-op.
        """
        if x in self._parent:
            return
        self._parent[x] = x
        self._rank[x] = 0
        self._size[x] = 1
        self._count += 1

    def find(self, x: Hashable) -> Hashable:
        """Return the root representative of *x*'s group.

        Auto-creates a singleton for *x* if it hasn't been seen before.
        Uses path compression: every node on the path from *x* to the
        root is re-pointed directly at the root, flattening the tree.
        """
        if x not in self._parent:
            self.make_set(x)
            return x

        # path compression — iterative to avoid deep recursion
        root = x
        while self._parent[root] != root:
            root = self._parent[root]

        # second pass: point every node on the path straight to root
        cur = x
        while cur != root:
            nxt = self._parent[cur]
            self._parent[cur] = root
            cur = nxt

        return root

    def union(self, x: Hashable, y: Hashable) -> bool:
        """Merge the groups containing *x* and *y*.

        Returns ``True`` if a merge actually happened (they were in
        different groups), ``False`` if they were already in the same
        group.
        """
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False

        # union by rank: attach shorter tree under taller
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx

        self._parent[ry] = rx
        self._size[rx] += self._size[ry]

        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

        self._count -= 1
        return True

    def connected(self, x: Hashable, y: Hashable) -> bool:
        """Return ``True`` if *x* and *y* are in the same group."""
        return self.find(x) == self.find(y)

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------

    def size(self, x: Hashable) -> int:
        """Return the number of elements in *x*'s group."""
        return self._size[self.find(x)]

    @property
    def count(self) -> int:
        """Number of disjoint groups currently tracked."""
        return self._count

    @property
    def total(self) -> int:
        """Total number of elements across all groups."""
        return len(self._parent)

    def components(self) -> List[Set[Hashable]]:
        """Return all current groups as a list of sets.

        Each set contains the elements of one group.  The order of the
        list and the order of elements within each set are not
        guaranteed.
        """
        groups: Dict[Hashable, Set[Hashable]] = {}
        for x in self._parent:
            root = self.find(x)
            if root not in groups:
                groups[root] = set()
            groups[root].add(x)
        return list(groups.values())

    def roots(self) -> Set[Hashable]:
        """Return the set of all group representatives (roots)."""
        return {self.find(x) for x in self._parent}

    # ------------------------------------------------------------------
    # dunder
    # ------------------------------------------------------------------

    def __contains__(self, x: Hashable) -> bool:
        return x in self._parent

    def __len__(self) -> int:
        return self.total

    def __repr__(self) -> str:
        return f"UnionFind(elements={self.total}, components={self._count})"
