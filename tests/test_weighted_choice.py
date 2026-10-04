"""Tests for snippets/weighted_choice.py — weighted random selection."""

from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from weighted_choice import WeightedChoice  # noqa: E402


def test_single_item_always_picked():
    wc = WeightedChoice([("only", 1.0)])
    for _ in range(20):
        assert wc.pick() == "only"


def test_zero_weight_item_never_picked():
    wc = WeightedChoice([("a", 1.0), ("b", 0.0)])
    rng = random.Random(42)
    results = {wc.pick(rng) for _ in range(200)}
    assert results == {"a"}


def test_proportional_distribution():
    """With weights 1:3, 'b' should appear ~75% of the time."""
    wc = WeightedChoice([("a", 1), ("b", 3)])
    rng = random.Random(123)
    counts = Counter(wc.pick(rng) for _ in range(4000))
    ratio = counts["b"] / counts.get("a", 1)
    # expect ~3.0; allow generous margin for randomness
    assert 2.0 < ratio < 4.5


def test_pick_n_returns_correct_count():
    wc = WeightedChoice([("x", 1), ("y", 1), ("z", 1)])
    assert len(wc.pick_n(10)) == 10


def test_empty_raises():
    with pytest.raises(ValueError, match="at least one"):
        WeightedChoice([])


def test_negative_weight_raises():
    with pytest.raises(ValueError, match="must be >= 0"):
        WeightedChoice([("a", -1)])


def test_all_zero_weights_raises():
    with pytest.raises(ValueError, match="total weight must be > 0"):
        WeightedChoice([("a", 0), ("b", 0)])


def test_total_weight_property():
    wc = WeightedChoice([("a", 2), ("b", 3), ("c", 5)])
    assert wc.total_weight == 10


def test_items_and_weights():
    wc = WeightedChoice([("a", 2), ("b", 3)])
    assert wc.items() == ["a", "b"]
    assert wc.weights() == [2, 3]


def test_probability():
    wc = WeightedChoice([("a", 1), ("b", 2), ("c", 3)])
    assert abs(wc.probability("a") - 1 / 6) < 1e-9
    assert abs(wc.probability("b") - 2 / 6) < 1e-9
    assert abs(wc.probability("c") - 3 / 6) < 1e-9


def test_probability_unknown_item_raises():
    wc = WeightedChoice([("a", 1)])
    with pytest.raises(ValueError, match="not in collection"):
        wc.probability("z")


def test_len():
    wc = WeightedChoice([("a", 1), ("b", 2), ("c", 3)])
    assert len(wc) == 3


def test_repr_contains_items():
    wc = WeightedChoice([("x", 1)])
    assert "x" in repr(wc)


def test_deterministic_with_seed():
    wc = WeightedChoice([("a", 1), ("b", 1), ("c", 1)])
    seq1 = [wc.pick(random.Random(99)) for _ in range(20)]
    seq2 = [wc.pick(random.Random(99)) for _ in range(20)]
    assert seq1 == seq2
