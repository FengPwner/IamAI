"""Consistent hash ring — assign keys to nodes with minimal reshuffling."""

from __future__ import annotations

import hashlib
import bisect
from typing import Any, Iterator


class ConsistentHash:
    """Map keys to nodes on a hash ring with virtual nodes for balance.

    >>> ring = ConsistentHash(["alpha", "beta", "gamma"], replicas=64)
    >>> ring.get_node("user:1001") in ("alpha", "beta", "gamma")
    True
    >>> ring.get_node("user:1001") == ring.get_node("user:1001")
    True
    >>> ring.remove_node("beta")
    >>> ring.get_node("user:1001") in ("alpha", "gamma")
    True
    >>> len(ring.nodes)
    2
    """

    def __init__(self, nodes: list[str] | None = None, replicas: int = 150):
        if replicas < 1:
            raise ValueError("replicas must be >= 1")
        self._replicas = replicas
        self._ring: list[tuple[int, str]] = []  # sorted by hash
        self._hashes: list[int] = []
        self.nodes: set[str] = set()
        for node in nodes or []:
            self.add_node(node)

    @staticmethod
    def _hash(key: str) -> int:
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

    def add_node(self, node: str) -> None:
        if node in self.nodes:
            return
        self.nodes.add(node)
        for i in range(self._replicas):
            h = self._hash(f"{node}:{i}")
            idx = bisect.bisect_left(self._hashes, h)
            self._hashes.insert(idx, h)
            self._ring.insert(idx, (h, node))

    def remove_node(self, node: str) -> None:
        if node not in self.nodes:
            return
        self.nodes.discard(node)
        self._ring = [(h, n) for h, n in self._ring if n != node]
        self._hashes = [h for h, _ in self._ring]

    def get_node(self, key: str) -> str | None:
        if not self._ring:
            return None
        h = self._hash(key)
        idx = bisect.bisect_right(self._hashes, h)
        if idx >= len(self._ring):
            idx = 0
        return self._ring[idx][1]

    def get_nodes(self, key: str, count: int = 2) -> list[str]:
        """Return *count* distinct nodes for replication, walking clockwise."""
        if not self._ring:
            return []
        h = self._hash(key)
        idx = bisect.bisect_right(self._hashes, h)
        seen: list[str] = []
        for step in range(len(self._ring)):
            pos = (idx + step) % len(self._ring)
            node = self._ring[pos][1]
            if node not in seen:
                seen.append(node)
            if len(seen) >= count:
                break
        return seen

    def __len__(self) -> int:
        return len(self.nodes)

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self.nodes))
