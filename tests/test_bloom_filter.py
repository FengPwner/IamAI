"""Tests for snippets/bloom_filter.py — correctness, edge cases, and the probabilistic guarantee."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from bloom_filter import BloomFilter


class TestBasicMembership:
    """Items added must be found; items not added are (almost certainly) absent."""

    def test_added_item_found(self):
        bf = BloomFilter(capacity=100, error_rate=0.01)
        bf.add("alpha")
        assert "alpha" in bf

    def test_missing_item_absent_in_small_set(self):
        bf = BloomFilter(capacity=1000, error_rate=0.001)
        bf.add("present")
        # with capacity=1000 and one item, false positive is negligible
        assert "absent" not in bf

    def test_multiple_items(self):
        bf = BloomFilter(capacity=500, error_rate=0.01)
        items = [f"item_{i}" for i in range(50)]
        for item in items:
            bf.add(item)
        for item in items:
            assert item in bf, f"false negative on {item}"


class TestNoFalseNegatives:
    """The one iron-clad guarantee: if you added it, you'll find it."""

    def test_all_added_items_present(self):
        bf = BloomFilter(capacity=200, error_rate=0.05)
        words = "the quick brown fox jumps over the lazy dog".split()
        for w in words:
            bf.add(w)
        for w in words:
            assert w in bf


class TestFalsePositiveRate:
    """Empirical FP rate should stay near the configured error_rate."""

    def test_fp_rate_within_bounds(self):
        bf = BloomFilter(capacity=500, error_rate=0.05)
        # add 500 items that are "in"
        for i in range(500):
            bf.add(f"in_{i}")
        # probe 5000 items that are NOT in
        false_positives = sum(1 for i in range(5000) if f"out_{i}" in bf)
        observed_rate = false_positives / 5000
        # allow 3x margin — probabilistic, but 3x over is still very unlikely
        assert observed_rate < 0.05 * 3, f"FP rate {observed_rate:.3f} too high"


class TestEdgeCases:
    """Boundary conditions and invalid inputs."""

    def test_empty_filter_contains_nothing(self):
        bf = BloomFilter()
        assert "anything" not in bf

    def test_len_tracks_adds_not_uniques(self):
        bf = BloomFilter()
        bf.add("x")
        bf.add("x")
        assert len(bf) == 2  # counts calls, not unique items

    def test_capacity_zero_raises(self):
        with pytest.raises(ValueError, match="capacity"):
            BloomFilter(capacity=0)

    def test_error_rate_zero_raises(self):
        with pytest.raises(ValueError, match="error_rate"):
            BloomFilter(error_rate=0)

    def test_error_rate_one_raises(self):
        with pytest.raises(ValueError, match="error_rate"):
            BloomFilter(error_rate=1.0)

    def test_fill_ratio_starts_zero(self):
        bf = BloomFilter()
        assert bf.fill_ratio == 0.0

    def test_fill_ratio_grows_with_adds(self):
        bf = BloomFilter(capacity=100, error_rate=0.01)
        before = bf.fill_ratio
        for i in range(20):
            bf.add(f"item_{i}")
        assert bf.fill_ratio > before


class TestDoctests:
    """The pool's own doctests must pass — this is the red gate."""

    def test_doctests(self):
        import doctest
        import snippets.bloom_filter as mod

        results = doctest.testmod(mod, verbose=False)
        assert results.failed == 0, f"{results.failed} doctest(s) failed"
