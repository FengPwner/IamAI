"""Tests for snippets.topo_sort: Kahn's algorithm with cycle detection.

Topological sort is the skeleton of build systems, task schedulers, and
migration runners. These tests pin down the contract: empty graphs,
single nodes, chains, diamonds, disconnected components, leaf nodes
that appear only as prerequisites, and the cycle-detection path.
"""

from __future__ import annotations

import pytest
from snippets.topo_sort import topo_sort


# --- basic cases ---------------------------------------------------------


def test_empty_graph():
    assert topo_sort({}) == []


def test_single_node_no_deps():
    assert topo_sort({"a": []}) == ["a"]


def test_simple_chain():
    """a depends on b, b depends on c → c, b, a."""
    result = topo_sort({"a": ["b"], "b": ["c"], "c": []})
    assert result == ["c", "b", "a"]


def test_two_node_chain():
    result = topo_sort({"y": ["x"], "x": []})
    assert result.index("x") < result.index("y")


# --- dependency ordering -------------------------------------------------


def test_diamond_dependency():
    """Diamond: d depends on b and c, both depend on a.

        a
       / \\
      b   c
       \\ /
        d
    """
    graph = {
        "d": ["b", "c"],
        "b": ["a"],
        "c": ["a"],
        "a": [],
    }
    result = topo_sort(graph)
    assert result.index("a") < result.index("b")
    assert result.index("a") < result.index("c")
    assert result.index("b") < result.index("d")
    assert result.index("c") < result.index("d")


def test_disconnected_components():
    """Two independent chains should both appear in output."""
    graph = {"b": ["a"], "a": [], "d": ["c"], "c": []}
    result = topo_sort(graph)
    assert len(result) == 4
    assert result.index("a") < result.index("b")
    assert result.index("c") < result.index("d")


def test_multiple_deps_on_same_node():
    graph = {"x": ["a"], "y": ["a"], "z": ["a"], "a": []}
    result = topo_sort(graph)
    assert result[0] == "a"
    assert set(result[1:]) == {"x", "y", "z"}


# --- leaf prerequisites --------------------------------------------------


def test_leaf_prereq_not_in_keys():
    """Nodes that appear only as values (not as keys) are treated as leaves."""
    graph = {"b": ["a"]}  # "a" is not a key
    result = topo_sort(graph)
    assert result == ["a", "b"]


def test_multiple_leaf_prereqs():
    graph = {"c": ["a", "b"]}  # neither a nor b are keys
    result = topo_sort(graph)
    assert set(result[:2]) == {"a", "b"}
    assert result[2] == "c"


# --- cycle detection -----------------------------------------------------


def test_direct_cycle_raises():
    with pytest.raises(ValueError, match="cycle"):
        topo_sort({"a": ["b"], "b": ["a"]})


def test_self_loop_raises():
    with pytest.raises(ValueError, match="cycle"):
        topo_sort({"a": ["a"]})


def test_indirect_cycle_raises():
    with pytest.raises(ValueError, match="cycle"):
        topo_sort({"a": ["b"], "b": ["c"], "c": ["a"]})


def test_cycle_in_subgraph_raises_even_with_clean_nodes():
    """A cycle anywhere in the graph poisons the whole sort."""
    graph = {
        "x": [],
        "y": ["x"],
        "a": ["b"],
        "b": ["a"],  # cycle between a and b
    }
    with pytest.raises(ValueError, match="cycle"):
        topo_sort(graph)


# --- determinism ---------------------------------------------------------


def test_deterministic_output():
    """Same input should always produce same output (no set-iteration flakiness)."""
    graph = {
        "f": ["d", "e"],
        "d": ["a", "b"],
        "e": ["b", "c"],
        "a": [],
        "b": [],
        "c": [],
    }
    first = topo_sort(graph)
    for _ in range(50):
        assert topo_sort(graph) == first


# --- edge cases ----------------------------------------------------------


def test_node_with_no_dependents():
    """A node that nothing depends on, but has no deps itself."""
    graph = {"a": [], "b": []}
    result = topo_sort(graph)
    assert set(result) == {"a", "b"}


def test_long_chain():
    """Stress test: a chain of 100 nodes."""
    graph = {}
    for i in range(100):
        graph[f"n{i}"] = [f"n{i-1}"] if i > 0 else []
    result = topo_sort(graph)
    assert len(result) == 100
    for i in range(99):
        assert result.index(f"n{i}") < result.index(f"n{i+1}")
