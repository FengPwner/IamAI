"""Tests for snippets/median_tracker.py — running median via two heaps."""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from median_tracker import MedianTracker  # noqa: E402


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_fresh_tracker_has_zero_count(self) -> None:
        m = MedianTracker()
        assert m.count == 0

    def test_median_raises_on_empty(self) -> None:
        m = MedianTracker()
        with pytest.raises(ValueError, match="no values added"):
            _ = m.median


# ---------------------------------------------------------------------------
# single value
# ---------------------------------------------------------------------------


class TestSingleValue:
    def test_median_of_one_int(self) -> None:
        m = MedianTracker()
        m.add(42)
        assert m.median == 42

    def test_median_of_one_float(self) -> None:
        m = MedianTracker()
        m.add(3.14)
        assert m.median == pytest.approx(3.14)

    def test_count_after_one_add(self) -> None:
        m = MedianTracker()
        m.add(1)
        assert m.count == 1


# ---------------------------------------------------------------------------
# odd count
# ---------------------------------------------------------------------------


class TestOddCount:
    def test_three_values(self) -> None:
        m = MedianTracker()
        for v in [1, 3, 2]:
            m.add(v)
        assert m.median == 2

    def test_five_values(self) -> None:
        m = MedianTracker()
        for v in [5, 1, 4, 2, 3]:
            m.add(v)
        assert m.median == 3

    def test_seven_ascending(self) -> None:
        m = MedianTracker()
        for v in range(1, 8):
            m.add(v)
        assert m.median == 4


# ---------------------------------------------------------------------------
# even count
# ---------------------------------------------------------------------------


class TestEvenCount:
    def test_two_values(self) -> None:
        m = MedianTracker()
        m.add(1)
        m.add(3)
        assert m.median == pytest.approx(2.0)

    def test_four_values(self) -> None:
        m = MedianTracker()
        for v in [4, 1, 3, 2]:
            m.add(v)
        assert m.median == pytest.approx(2.5)

    def test_six_values(self) -> None:
        m = MedianTracker()
        for v in [6, 5, 4, 3, 2, 1]:
            m.add(v)
        assert m.median == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# duplicates and negatives
# ---------------------------------------------------------------------------


class TestEdgeValues:
    def test_all_same_value(self) -> None:
        m = MedianTracker()
        for _ in range(10):
            m.add(7)
        assert m.median == 7

    def test_negative_values(self) -> None:
        m = MedianTracker()
        for v in [-5, -1, -3]:
            m.add(v)
        assert m.median == -3

    def test_mixed_positive_negative(self) -> None:
        m = MedianTracker()
        for v in [-10, 10, -20, 20, 0]:
            m.add(v)
        assert m.median == 0

    def test_large_values(self) -> None:
        m = MedianTracker()
        m.add(1_000_000_000)
        m.add(-1_000_000_000)
        assert m.median == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# streaming correctness — compare against statistics.median
# ---------------------------------------------------------------------------


class TestStreamingCorrectness:
    def test_matches_statistics_median_at_every_step(self) -> None:
        """Insert 200 values and verify median matches stdlib at each step."""
        import random

        rng = random.Random(0xDEAD_BEEF)
        values = [rng.gauss(0, 100) for _ in range(200)]

        m = MedianTracker()
        for i, v in enumerate(values, start=1):
            m.add(v)
            expected = statistics.median(values[:i])
            assert m.median == pytest.approx(expected), (
                f"mismatch at step {i}: tracker={m.median}, expected={expected}"
            )

    def test_ascending_then_descending(self) -> None:
        m = MedianTracker()
        seq = list(range(1, 51)) + list(range(49, 0, -1))
        for i, v in enumerate(seq, start=1):
            m.add(v)
            expected = statistics.median(seq[:i])
            assert m.median == pytest.approx(expected)


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_resets_count(self) -> None:
        m = MedianTracker()
        for v in range(10):
            m.add(v)
        m.clear()
        assert m.count == 0

    def test_clear_then_median_raises(self) -> None:
        m = MedianTracker()
        m.add(1)
        m.clear()
        with pytest.raises(ValueError):
            _ = m.median

    def test_add_after_clear_works(self) -> None:
        m = MedianTracker()
        for v in range(100):
            m.add(v)
        m.clear()
        m.add(42)
        assert m.median == 42
        assert m.count == 1


# ---------------------------------------------------------------------------
# order independence
# ---------------------------------------------------------------------------


class TestOrderIndependence:
    def test_same_set_different_order_same_median(self) -> None:
        """The median of {1..10} should be 5.5 regardless of insertion order."""
        import random

        values = list(range(1, 11))
        rng = random.Random(42)
        shuffled = values.copy()
        rng.shuffle(shuffled)

        m1 = MedianTracker()
        for v in values:
            m1.add(v)

        m2 = MedianTracker()
        for v in shuffled:
            m2.add(v)

        assert m1.median == pytest.approx(m2.median)
        assert m1.median == pytest.approx(5.5)
