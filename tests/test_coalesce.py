"""Tests for coalesce snippet."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "snippets"))

from coalesce import coalesce, coalesce_with_gaps


def test_coalesce_basic():
    """Basic windowing."""
    # 1.0→bucket 0.0, 1.5→bucket 0.0, 2.0→bucket 2.0, 5.0→bucket 4.0
    result = coalesce([1.0, 1.5, 2.0, 5.0], 2.0)
    assert result == [(0.0, 2), (2.0, 1), (4.0, 1)]


def test_coalesce_empty():
    """Empty input."""
    assert coalesce([], 2.0) == []


def test_coalesce_invalid_window():
    """Invalid window size."""
    assert coalesce([1.0, 2.0], 0) == []
    assert coalesce([1.0, 2.0], -1.0) == []


def test_coalesce_single_window():
    """All events in one window."""
    result = coalesce([0.1, 0.5, 0.9], 1.0)
    assert result == [(0.0, 3)]


def test_coalesce_exact_boundaries():
    """Events exactly on window boundaries."""
    result = coalesce([0.0, 1.0, 2.0, 3.0], 1.0)
    assert result == [(0.0, 1), (1.0, 1), (2.0, 1), (3.0, 1)]


def test_coalesce_sparse():
    """Events spread across many windows."""
    result = coalesce([0.0, 10.0, 20.0], 5.0)
    assert result == [(0.0, 1), (10.0, 1), (20.0, 1)]


def test_coalesce_with_gaps_basic():
    """Split into groups when gap exceeds threshold."""
    events = [0.0, 1.0, 2.0, 100.0, 101.0, 102.0]
    groups = coalesce_with_gaps(events, 1.0, 10.0)
    assert len(groups) == 2
    assert groups[0] == [(0.0, 1), (1.0, 1), (2.0, 1)]
    assert groups[1] == [(100.0, 1), (101.0, 1), (102.0, 1)]


def test_coalesce_with_gaps_no_split():
    """No split when gaps are small."""
    events = [0.0, 1.0, 2.0, 3.0]
    groups = coalesce_with_gaps(events, 1.0, 10.0)
    assert len(groups) == 1
    assert groups[0] == [(0.0, 1), (1.0, 1), (2.0, 1), (3.0, 1)]


def test_coalesce_with_gaps_empty():
    """Empty input."""
    assert coalesce_with_gaps([], 1.0, 10.0) == []


def test_coalesce_with_gaps_single_group():
    """Single event."""
    groups = coalesce_with_gaps([5.0], 2.0, 10.0)
    assert len(groups) == 1
    assert groups[0] == [(4.0, 1)]
