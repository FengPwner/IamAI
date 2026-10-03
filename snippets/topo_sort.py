"""Topological sort with cycle detection — no deps, Kahn's algorithm."""

from __future__ import annotations

from collections import deque
from typing import Hashable, Iterable, Mapping, TypeVar

T = TypeVar("T", bound=Hashable)


def topo_sort(graph: Mapping[T, Iterable[T]]) -> list[T]:
    """Return nodes in dependency order; raise ValueError on cycles.

    `graph` maps each node to the set of nodes it depends on (its prerequisites).
    Nodes that appear only as values but not as keys are treated as having no
    prerequisites.

    >>> topo_sort({"a": ["b"], "b": ["c"], "c": []})
    ['c', 'b', 'a']
    >>> topo_sort({"x": [], "y": ["x"]})
    ['x', 'y']
    >>> topo_sort({})
    []
    >>> topo_sort({"a": ["b"], "b": ["a"]})
    Traceback (most recent call last):
        ...
    ValueError: cycle detected among ['a', 'b']
    """
    # Collect all nodes (including leaf prerequisites not present as keys).
    all_nodes: set[T] = set(graph)
    for deps in graph.values():
        all_nodes.update(deps)

    # Build adjacency list and in-degree count (edge: dep -> node).
    in_degree: dict[T, int] = {n: 0 for n in all_nodes}
    fwd: dict[T, list[T]] = {n: [] for n in all_nodes}
    for node, deps in graph.items():
        in_degree[node] = len(deps)
        for dep in deps:
            fwd[dep].append(node)

    # Deterministic seeding: iterating a bare set makes the output order
    # vary per process (hash randomization), which flakes doctests.
    queue: deque[T] = deque(sorted(n for n in all_nodes if in_degree[n] == 0))
    result: list[T] = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for dependent in fwd[node]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(all_nodes):
        stuck = {n for n in all_nodes if in_degree[n] > 0}
        raise ValueError(f"cycle detected among {sorted(stuck)}")

    return result
