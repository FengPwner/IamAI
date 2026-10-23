"""Tests for iamai.thought_reservoir."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from iamai.thought_reservoir import (
    DEFAULT_SEEDS,
    RECENT_AVOID_HOURS,
    Reservoir,
    _gini,
    _hours_since,
    default_reservoir,
    make_seed,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
ONE_HOUR_AGO = NOW - timedelta(hours=1)
ONE_DAY_AGO = NOW - timedelta(hours=24)
TWO_DAYS_AGO = NOW - timedelta(hours=48)


def _seed(text: str, **overrides) -> dict:
    """Quick seed factory for tests."""
    s = make_seed(text, now=NOW)
    s.update(overrides)
    return s


# ---------------------------------------------------------------------------
# make_seed
# ---------------------------------------------------------------------------


class TestMakeSeed:
    def test_basic_fields(self):
        s = make_seed("hello world")
        assert s["text"] == "hello world"
        assert s["use_count"] == 0
        assert s["last_used_at"] is None
        assert len(s["id"]) == 12
        assert "created_at" in s

    def test_with_tags(self):
        s = make_seed("tagged", tags=["a", "b"])
        assert s["tags"] == ["a", "b"]

    def test_without_tags(self):
        s = make_seed("no tags")
        assert s["tags"] == []

    def test_unique_ids(self):
        ids = {make_seed(f"s{i}")["id"] for i in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# Reservoir — basic operations
# ---------------------------------------------------------------------------


class TestReservoirBasic:
    def test_empty_reservoir(self):
        r = Reservoir()
        assert r.size == 0
        assert r.seeds == []

    def test_register(self):
        r = Reservoir()
        s = r.register("test thought", now=NOW)
        assert r.size == 1
        assert s["text"] == "test thought"
        assert s["use_count"] == 0

    def test_register_multiple(self):
        r = Reservoir()
        r.register("one", now=NOW)
        r.register("two", now=NOW)
        r.register("three", now=NOW)
        assert r.size == 3

    def test_mark_used(self):
        r = Reservoir()
        s = r.register("mark me", now=NOW)
        result = r.mark_used(s["id"], now=ONE_HOUR_AGO)
        assert result is True
        assert r.seeds[0]["use_count"] == 1
        assert r.seeds[0]["last_used_at"] == ONE_HOUR_AGO.isoformat()

    def test_mark_used_twice(self):
        r = Reservoir()
        s = r.register("mark me", now=NOW)
        r.mark_used(s["id"], now=NOW)
        r.mark_used(s["id"], now=NOW)
        assert r.seeds[0]["use_count"] == 2

    def test_mark_used_not_found(self):
        r = Reservoir()
        result = r.mark_used("nonexistent", now=NOW)
        assert result is False

    def test_remove(self):
        r = Reservoir()
        s = r.register("remove me", now=NOW)
        result = r.remove(s["id"])
        assert result is True
        assert r.size == 0

    def test_remove_not_found(self):
        r = Reservoir()
        r.register("keep me", now=NOW)
        result = r.remove("nonexistent")
        assert result is False
        assert r.size == 1


# ---------------------------------------------------------------------------
# Reservoir — sampling
# ---------------------------------------------------------------------------


class TestReservoirSampling:
    def test_sample_empty(self):
        r = Reservoir()
        result = r.sample(1, rng=random.Random(42), now=NOW)
        assert result == []

    def test_sample_returns_copies(self):
        r = Reservoir()
        r.register("original", now=NOW)
        samples = r.sample(1, rng=random.Random(42), now=NOW)
        assert len(samples) == 1
        assert samples[0]["text"] == "original"
        # Modifying the sample should not affect the reservoir
        samples[0]["text"] = "modified"
        assert r.seeds[0]["text"] == "original"

    def test_sample_uniform(self):
        r = Reservoir()
        for i in range(10):
            r.register(f"seed {i}", now=NOW)
        rng = random.Random(42)
        samples = r.sample(100, strategy="uniform", rng=rng, now=NOW)
        assert len(samples) == 100
        # Check all seeds appear at least once with uniform sampling
        texts = {s["text"] for s in samples}
        assert len(texts) == 10

    def test_sample_stale_bias(self):
        r = Reservoir()
        # Seed A was just used, seed B was never used
        a = r.register("fresh", now=NOW)
        b = r.register("stale", now=NOW)
        r.mark_used(a["id"], now=NOW)
        # b was never used → infinite staleness → should dominate
        rng = random.Random(42)
        samples = r.sample(50, strategy="stale_bias", rng=rng, now=NOW)
        stale_count = sum(1 for s in samples if s["text"] == "stale")
        # Stale seed should get most of the samples
        assert stale_count > 40

    def test_sample_recent_avoid(self):
        r = Reservoir()
        a = r.register("just used", now=NOW)
        b = r.register("old", now=NOW)
        r.mark_used(a["id"], now=NOW)
        # a was used NOW, which is < RECENT_AVOID_HOURS ago
        rng = random.Random(42)
        samples = r.sample(20, strategy="recent_avoid", rng=rng, now=NOW)
        texts = [s["text"] for s in samples]
        # Only b should be sampled since a is too recent
        assert all(t == "old" for t in texts)

    def test_sample_unknown_strategy(self):
        r = Reservoir()
        r.register("test", now=NOW)
        with pytest.raises(ValueError, match="unknown strategy"):
            r.sample(1, strategy="bogus", rng=random.Random(42), now=NOW)

    def test_sample_n_clamped_to_1(self):
        r = Reservoir()
        r.register("only", now=NOW)
        samples = r.sample(0, rng=random.Random(42), now=NOW)
        assert len(samples) == 1

    def test_sample_with_replacement(self):
        r = Reservoir()
        r.register("single", now=NOW)
        samples = r.sample(10, rng=random.Random(42), now=NOW)
        assert len(samples) == 10
        assert all(s["text"] == "single" for s in samples)

    def test_sample_deterministic_with_rng(self):
        r = Reservoir()
        for i in range(5):
            r.register(f"seed {i}", now=NOW)
        s1 = r.sample(3, strategy="uniform", rng=random.Random(123), now=NOW)
        s2 = r.sample(3, strategy="uniform", rng=random.Random(123), now=NOW)
        assert [s["text"] for s in s1] == [s["text"] for s in s2]


# ---------------------------------------------------------------------------
# Stale query
# ---------------------------------------------------------------------------


class TestStale:
    def test_all_stale_when_empty(self):
        r = Reservoir()
        assert r.stale(now=NOW) == []

    def test_never_used_is_stale(self):
        r = Reservoir()
        r.register("unused", now=TWO_DAYS_AGO)
        stale = r.stale(threshold_hours=24, now=NOW)
        assert len(stale) == 1
        assert stale[0]["text"] == "unused"

    def test_recently_used_is_not_stale(self):
        r = Reservoir()
        s = r.register("fresh", now=NOW)
        r.mark_used(s["id"], now=NOW)
        stale = r.stale(threshold_hours=24, now=NOW)
        assert len(stale) == 0

    def test_old_use_is_stale(self):
        r = Reservoir()
        s = r.register("old use", now=TWO_DAYS_AGO)
        r.mark_used(s["id"], now=TWO_DAYS_AGO)
        stale = r.stale(threshold_hours=24, now=NOW)
        assert len(stale) == 1

    def test_custom_threshold(self):
        r = Reservoir()
        s = r.register("mid", now=NOW)
        r.mark_used(s["id"], now=NOW - timedelta(hours=12))
        stale_6h = r.stale(threshold_hours=6, now=NOW)
        stale_24h = r.stale(threshold_hours=24, now=NOW)
        assert len(stale_6h) == 1
        assert len(stale_24h) == 0


# ---------------------------------------------------------------------------
# Gini coefficient
# ---------------------------------------------------------------------------


class TestGini:
    def test_perfectly_even(self):
        assert _gini([10, 10, 10, 10]) == 0.0

    def test_maximally_uneven(self):
        # One item has all the weight
        g = _gini([0, 0, 0, 100])
        assert g > 0.7

    def test_empty(self):
        assert _gini([]) == 0.0

    def test_single(self):
        assert _gini([42]) == 0.0

    def test_all_zero(self):
        assert _gini([0, 0, 0]) == 0.0

    def test_symmetric(self):
        # Order doesn't matter
        g1 = _gini([1, 2, 3, 4])
        g2 = _gini([4, 3, 2, 1])
        assert abs(g1 - g2) < 1e-10


# ---------------------------------------------------------------------------
# _hours_since
# ---------------------------------------------------------------------------


class TestHoursSince:
    def test_none_returns_inf(self):
        assert _hours_since(None, NOW) == float("inf")

    def test_zero_hours(self):
        assert _hours_since(NOW, NOW) == 0.0

    def test_one_hour(self):
        assert _hours_since(ONE_HOUR_AGO, NOW) == pytest.approx(1.0)

    def test_one_day(self):
        assert _hours_since(ONE_DAY_AGO, NOW) == pytest.approx(24.0)

    def test_future_clamped_to_zero(self):
        future = NOW + timedelta(hours=5)
        assert _hours_since(future, NOW) == 0.0


# ---------------------------------------------------------------------------
# Health analysis
# ---------------------------------------------------------------------------


class TestHealth:
    def test_empty_reservoir(self):
        r = Reservoir()
        h = r.health(now=NOW)
        assert h["score"] == 0.0
        assert h["grade"] == "barren"
        assert h["size"] == 0
        assert h["richness"] == 0.0
        assert h["evenness"] == 0.0
        assert h["freshness"] == 0.0

    def test_single_unused_seed(self):
        r = Reservoir(target_size=1)
        r.register("only", now=NOW)
        h = r.health(now=NOW)
        assert h["richness"] == 1.0
        # Gini([0]) = 0, so evenness = 1 - 0 = 1.0
        assert h["evenness"] == 1.0
        # Never used → freshness = 0
        assert h["freshness"] == 0.0

    def test_full_reservoir_all_used(self):
        r = Reservoir(target_size=3)
        for i in range(3):
            s = r.register(f"seed {i}", now=NOW)
            r.mark_used(s["id"], now=NOW)
        h = r.health(now=NOW)
        assert h["richness"] == 1.0
        assert h["evenness"] == 1.0  # all used once → Gini = 0
        assert h["freshness"] == 1.0  # all used within 24h
        assert h["grade"] == "fertile"

    def test_uneven_usage(self):
        r = Reservoir(target_size=2)
        a = r.register("popular", now=NOW)
        r.register("ignored", now=NOW)
        # Mark 'popular' many times
        for _ in range(100):
            r.mark_used(a["id"], now=NOW)
        h = r.health(now=NOW)
        # Gini([100, 0]) for 2 items = 0.5, evenness = 0.5
        assert h["evenness"] <= 0.6

    def test_grade_boundaries(self):
        # Test that grades are correctly assigned
        r = Reservoir(target_size=1)
        s = r.register("test", now=NOW)
        r.mark_used(s["id"], now=NOW)
        h = r.health(now=NOW)
        assert h["grade"] == "fertile"  # score should be 1.0

    def test_stale_grade(self):
        r = Reservoir(target_size=100)
        # 3 seeds out of 100 target → richness = 0.03
        for i in range(3):
            s = r.register(f"seed {i}", now=TWO_DAYS_AGO)
            r.mark_used(s["id"], now=TWO_DAYS_AGO)
        # Used 48h ago → freshness = 0
        h = r.health(now=NOW)
        # richness ≈ 0.03, evenness = 1.0, freshness = 0
        # score = 0.35*0.03 + 0.35*1.0 + 0.30*0 ≈ 0.36
        assert h["grade"] in ("stale", "adequate")

    def test_report_format(self):
        r = Reservoir(target_size=5)
        r.register("hello", now=NOW)
        report = r.report(now=NOW)
        assert "reservoir" in report
        assert "seeds" in report
        assert "target" in report


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_to_list_roundtrip(self):
        r = Reservoir(target_size=10)
        r.register("seed one", tags=["a"], now=NOW)
        r.register("seed two", tags=["b", "c"], now=NOW)
        data = r.to_list()
        assert len(data) == 2

        r2 = Reservoir.from_list(data, target_size=10)
        assert r2.size == 2
        assert r2.seeds[0]["text"] == "seed one"
        assert r2.seeds[1]["tags"] == ["b", "c"]

    def test_to_list_returns_copies(self):
        r = Reservoir()
        r.register("test", now=NOW)
        data = r.to_list()
        data[0]["text"] = "modified"
        assert r.seeds[0]["text"] == "test"


# ---------------------------------------------------------------------------
# Default reservoir
# ---------------------------------------------------------------------------


class TestDefaultReservoir:
    def test_default_has_seeds(self):
        r = default_reservoir(now=NOW)
        assert r.size == len(DEFAULT_SEEDS)
        assert r.size >= 20

    def test_default_seeds_have_tags(self):
        r = default_reservoir(now=NOW)
        for s in r.seeds:
            assert "default" in s["tags"]

    def test_default_seeds_are_unique(self):
        texts = [s["text"] for s in default_reservoir(now=NOW).seeds]
        assert len(texts) == len(set(texts))

    def test_default_reservoir_health(self):
        r = default_reservoir(target_size=30, now=NOW)
        h = r.health(now=NOW)
        assert h["size"] == len(DEFAULT_SEEDS)
        assert h["richness"] == 1.0  # 30 seeds >= target 30
        assert h["grade"] in ("adequate", "fertile")

    def test_custom_target_size(self):
        r = default_reservoir(target_size=100, now=NOW)
        h = r.health(now=NOW)
        assert h["target_size"] == 100
        assert h["richness"] < 1.0  # 30 seeds < target 100
