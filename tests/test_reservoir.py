"""Tests for snippets/reservoir.py — 21 tests covering uniform and weighted sampling."""

from __future__ import annotations

import pytest

from snippets.reservoir import Reservoir


# ---------------------------------------------------------------------------
# basic construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_default_k(self):
        r = Reservoir()
        assert r._k == 100

    def test_custom_k(self):
        r = Reservoir(k=5)
        assert r._k == 5

    def test_k_zero_raises(self):
        with pytest.raises(ValueError, match="k must be >= 1"):
            Reservoir(k=0)

    def test_k_negative_raises(self):
        with pytest.raises(ValueError, match="k must be >= 1"):
            Reservoir(k=-3)

    def test_repr_uniform(self):
        r = Reservoir(k=10)
        assert "uniform" in repr(r)
        assert "k=10" in repr(r)

    def test_repr_weighted(self):
        r = Reservoir(k=5, weighted=True)
        assert "weighted" in repr(r)


# ---------------------------------------------------------------------------
# uniform sampling
# ---------------------------------------------------------------------------

class TestUniformSampling:
    def test_fewer_than_k(self):
        r = Reservoir(k=10, seed=0)
        for i in range(5):
            r.add(i)
        assert r.size == 5
        assert r.seen == 5
        assert sorted(r.sample) == [0, 1, 2, 3, 4]

    def test_exactly_k(self):
        r = Reservoir(k=5, seed=1)
        for i in range(5):
            r.add(i)
        assert r.size == 5
        assert r.seen == 5

    def test_more_than_k(self):
        r = Reservoir(k=3, seed=42)
        for i in range(100):
            r.add(i)
        assert r.size == 3
        assert r.seen == 100

    def test_sample_size_capped(self):
        r = Reservoir(k=1)
        for i in range(50):
            r.add(i)
        assert len(r.sample) == 1
        assert r.seen == 50

    def test_deterministic_with_seed(self):
        """Same seed → same sample."""
        a = Reservoir(k=5, seed=99)
        b = Reservoir(k=5, seed=99)
        data = list(range(200))
        for x in data:
            a.add(x)
            b.add(x)
        assert a.sample == b.sample

    def test_different_seeds_differ(self):
        a = Reservoir(k=10, seed=1)
        b = Reservoir(k=10, seed=2)
        for i in range(500):
            a.add(i)
            b.add(i)
        assert a.sample != b.sample

    def test_len(self):
        r = Reservoir(k=7)
        for i in range(20):
            r.add(i)
        assert len(r) == 7

    def test_iter(self):
        r = Reservoir(k=3, seed=7)
        for i in range(10):
            r.add(i)
        items = list(r)
        assert len(items) == 3


# ---------------------------------------------------------------------------
# add_many
# ---------------------------------------------------------------------------

class TestAddMany:
    def test_add_many_uniform(self):
        r = Reservoir(k=5, seed=10)
        r.add_many(list(range(50)))
        assert r.seen == 50
        assert r.size == 5

    def test_add_many_with_weights(self):
        r = Reservoir(k=3, seed=20, weighted=True)
        r.add_many(["a", "b", "c"], weights=[1.0, 2.0, 3.0])
        assert r.seen == 3
        assert r.size == 3

    def test_add_many_weight_length_mismatch(self):
        r = Reservoir(k=5, weighted=True)
        with pytest.raises(ValueError, match="same length"):
            r.add_many([1, 2, 3], weights=[1.0, 2.0])


# ---------------------------------------------------------------------------
# weighted sampling
# ---------------------------------------------------------------------------

class TestWeightedSampling:
    def test_weight_zero_raises(self):
        r = Reservoir(k=5, weighted=True)
        with pytest.raises(ValueError, match="weight must be > 0"):
            r.add("x", weight=0)

    def test_weight_negative_raises(self):
        r = Reservoir(k=5, weighted=True)
        with pytest.raises(ValueError, match="weight must be > 0"):
            r.add("x", weight=-1)

    def test_weighted_heavy_items_dominate(self):
        """Items with very high weight should appear more often across trials."""
        heavy_count = 0
        trials = 200
        for seed in range(trials):
            r = Reservoir(k=1, seed=seed, weighted=True)
            r.add("light", weight=1.0)
            r.add("heavy", weight=100.0)
            if r.sample[0] == "heavy":
                heavy_count += 1
        # heavy should win the vast majority of the time
        assert heavy_count > trials * 0.8

    def test_weighted_equal_weights_behaves_uniform(self):
        """With equal weights, weighted mode should still produce valid samples."""
        r = Reservoir(k=5, seed=30, weighted=True)
        for i in range(100):
            r.add(i, weight=1.0)
        assert r.size == 5
        assert r.seen == 100

    def test_weighted_deterministic(self):
        a = Reservoir(k=4, seed=55, weighted=True)
        b = Reservoir(k=4, seed=55, weighted=True)
        for i in range(300):
            a.add(i, weight=float(i + 1))
            b.add(i, weight=float(i + 1))
        assert a.sample == b.sample
