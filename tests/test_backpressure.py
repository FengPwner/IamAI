"""Tests for snippets/backpressure.py — adaptive rate control."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from backpressure import Backpressure  # noqa: E402


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


class TestInit:
    def test_defaults(self):
        bp = Backpressure()
        assert bp.low_water == 0.6
        assert bp.high_water == 0.9

    def test_custom_waters(self):
        bp = Backpressure(low_water=0.3, high_water=0.7)
        assert bp.low_water == 0.3
        assert bp.high_water == 0.7

    def test_invalid_waters_raises(self):
        with pytest.raises(ValueError):
            Backpressure(low_water=0.8, high_water=0.5)
        with pytest.raises(ValueError):
            Backpressure(low_water=-0.1, high_water=0.9)
        with pytest.raises(ValueError):
            Backpressure(low_water=0.5, high_water=1.1)
        with pytest.raises(ValueError):
            Backpressure(low_water=0.5, high_water=0.5)


# ---------------------------------------------------------------------------
# green zone
# ---------------------------------------------------------------------------


class TestGreenZone:
    def test_zero_load_always_admits(self):
        bp = Backpressure()
        assert bp.admit(0.0) is True

    def test_below_low_water_always_admits(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        results = [bp.admit(0.3) for _ in range(100)]
        assert all(results)

    def test_just_below_low_water(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        assert bp.admit(0.499) is True


# ---------------------------------------------------------------------------
# red zone
# ---------------------------------------------------------------------------


class TestRedZone:
    def test_full_load_always_rejects(self):
        bp = Backpressure()
        assert bp.admit(1.0) is False

    def test_above_high_water_always_rejects(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        results = [bp.admit(0.95) for _ in range(100)]
        assert not any(results)

    def test_at_high_water_rejects(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        assert bp.admit(0.9) is False

    def test_above_one_raises(self):
        bp = Backpressure()
        with pytest.raises(ValueError):
            bp.admit(1.1)


# ---------------------------------------------------------------------------
# yellow zone
# ---------------------------------------------------------------------------


class TestYellowZone:
    def test_midpoint_admits_roughly_half(self):
        bp = Backpressure(low_water=0.5, high_water=0.9, rng=random.Random(42))
        results = [bp.admit(0.7) for _ in range(1000)]
        admit_count = sum(results)
        assert 400 < admit_count < 600

    def test_near_low_water_admits_most(self):
        bp = Backpressure(low_water=0.5, high_water=0.9, rng=random.Random(42))
        results = [bp.admit(0.55) for _ in range(1000)]
        admit_count = sum(results)
        assert admit_count > 800

    def test_near_high_water_rejects_most(self):
        bp = Backpressure(low_water=0.5, high_water=0.9, rng=random.Random(42))
        results = [bp.admit(0.85) for _ in range(1000)]
        admit_count = sum(results)
        assert admit_count < 200

    def test_deterministic_with_seeded_rng(self):
        bp1 = Backpressure(low_water=0.5, high_water=0.9, rng=random.Random(99))
        bp2 = Backpressure(low_water=0.5, high_water=0.9, rng=random.Random(99))
        results1 = [bp1.admit(0.7) for _ in range(50)]
        results2 = [bp2.admit(0.7) for _ in range(50)]
        assert results1 == results2


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------


class TestStats:
    def test_initial_stats_zero(self):
        bp = Backpressure()
        s = bp.stats()
        assert s["admitted"] == 0
        assert s["rejected"] == 0
        assert s["total"] == 0
        assert s["rejection_rate"] == 0.0

    def test_stats_after_green(self):
        bp = Backpressure()
        bp.admit(0.1)
        bp.admit(0.2)
        s = bp.stats()
        assert s["admitted"] == 2
        assert s["rejected"] == 0
        assert s["total"] == 2
        assert s["rejection_rate"] == 0.0

    def test_stats_after_red(self):
        bp = Backpressure()
        bp.admit(0.95)
        bp.admit(0.98)
        s = bp.stats()
        assert s["admitted"] == 0
        assert s["rejected"] == 2
        assert s["total"] == 2
        assert s["rejection_rate"] == 1.0

    def test_stats_mixed(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        bp.admit(0.3)  # green
        bp.admit(0.95)  # red
        s = bp.stats()
        assert s["admitted"] == 1
        assert s["rejected"] == 1
        assert s["total"] == 2
        assert s["rejection_rate"] == 0.5

    def test_reset_stats(self):
        bp = Backpressure()
        bp.admit(0.1)
        bp.admit(0.95)
        bp.reset_stats()
        s = bp.stats()
        assert s["total"] == 0
        assert s["rejection_rate"] == 0.0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_region_green(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        assert bp.region(0.3) == "green"

    def test_region_yellow(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        assert bp.region(0.7) == "yellow"

    def test_region_red(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        assert bp.region(0.95) == "red"

    def test_region_boundary_low(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        assert bp.region(0.5) == "yellow"

    def test_region_boundary_high(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        assert bp.region(0.9) == "red"

    def test_throttle_factor_green(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        assert bp.throttle_factor(0.3) == 1.0

    def test_throttle_factor_yellow_midpoint(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        assert bp.throttle_factor(0.7) == pytest.approx(0.5)

    def test_throttle_factor_red(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        assert bp.throttle_factor(0.95) == 0.0

    def test_throttle_factor_boundary_low(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        assert bp.throttle_factor(0.5) == 1.0

    def test_throttle_factor_boundary_high(self):
        bp = Backpressure(low_water=0.5, high_water=0.9)
        assert bp.throttle_factor(0.9) == 0.0


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_narrow_yellow_zone(self):
        bp = Backpressure(low_water=0.89, high_water=0.9, rng=random.Random(42))
        results = [bp.admit(0.895) for _ in range(1000)]
        admit_count = sum(results)
        assert 400 < admit_count < 600

    def test_full_range_waters(self):
        bp = Backpressure(low_water=0.0, high_water=1.0)
        assert bp.admit(0.0) is True
        assert bp.admit(0.5) in (True, False)
        assert bp.admit(1.0) is False

    def test_load_boundary_values(self):
        bp = Backpressure()
        assert bp.admit(0.0) is True
        assert bp.admit(1.0) is False

    def test_negative_load_raises(self):
        bp = Backpressure()
        with pytest.raises(ValueError):
            bp.admit(-0.1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
