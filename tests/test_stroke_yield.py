"""Tests for iamai.stroke_yield module."""

from __future__ import annotations

import pytest

from iamai.stroke_yield import StrokeYield, YieldSnapshot


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_defaults(self):
        sy = StrokeYield()
        assert sy._cadence_s == 15.0
        assert sy._window_s == 3600.0

    def test_custom_params(self):
        sy = StrokeYield(cadence_s=30, window_s=7200)
        assert sy._cadence_s == 30.0
        assert sy._window_s == 7200.0

    def test_negative_cadence_raises(self):
        with pytest.raises(ValueError, match="cadence_s"):
            StrokeYield(cadence_s=-1)

    def test_zero_cadence_raises(self):
        with pytest.raises(ValueError, match="cadence_s"):
            StrokeYield(cadence_s=0)

    def test_negative_window_raises(self):
        with pytest.raises(ValueError, match="window_s"):
            StrokeYield(window_s=-100)

    def test_zero_window_raises(self):
        with pytest.raises(ValueError, match="window_s"):
            StrokeYield(window_s=0)


# ---------------------------------------------------------------------------
# Observe
# ---------------------------------------------------------------------------

class TestObserve:
    def test_single_observation(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=4, elapsed_s=60)
        assert sy.total_actual == 4
        assert sy.total_elapsed == 60.0

    def test_multiple_observations(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=4, elapsed_s=60)
        sy.observe(count=3, elapsed_s=60)
        assert sy.total_actual == 7
        assert sy.total_elapsed == 120.0

    def test_negative_count_clamped_to_zero(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=-5, elapsed_s=60)
        assert sy.total_actual == 0

    def test_zero_elapsed_ignored(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=10, elapsed_s=0)
        assert sy.total_actual == 0
        assert sy.total_elapsed == 0.0

    def test_negative_elapsed_ignored(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=10, elapsed_s=-5)
        assert sy.total_actual == 0

    def test_zero_count_is_valid(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=0, elapsed_s=60)
        assert sy.total_actual == 0
        assert sy.total_elapsed == 60.0


# ---------------------------------------------------------------------------
# Yield ratio
# ---------------------------------------------------------------------------

class TestYieldRatio:
    def test_no_observations_returns_one(self):
        sy = StrokeYield()
        assert sy.yield_ratio() == 1.0

    def test_perfect_yield(self):
        sy = StrokeYield(cadence_s=15)
        # 4 strokes in 60 seconds = 4 expected → ratio = 1.0
        sy.observe(count=4, elapsed_s=60)
        assert sy.yield_ratio() == pytest.approx(1.0)

    def test_half_yield(self):
        sy = StrokeYield(cadence_s=15)
        # 2 strokes in 60 seconds = 4 expected → ratio = 0.5
        sy.observe(count=2, elapsed_s=60)
        assert sy.yield_ratio() == pytest.approx(0.5)

    def test_over_yield_capped_at_two(self):
        sy = StrokeYield(cadence_s=15)
        # 100 strokes in 60 seconds → ratio would be 25.0, capped at 2.0
        sy.observe(count=100, elapsed_s=60)
        assert sy.yield_ratio() == 2.0

    def test_mixed_observations(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=4, elapsed_s=60)   # 4/4
        sy.observe(count=2, elapsed_s=60)   # 2/4
        # total: 6 actual, 8 expected → 0.75
        assert sy.yield_ratio() == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_thriving(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=5, elapsed_s=60)   # 5/4 = 1.25
        assert sy.classify() == "thriving"

    def test_healthy_boundary(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=3, elapsed_s=60)   # 3/4 = 0.75
        assert sy.classify() == "healthy"

    def test_healthy_above_boundary(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=3, elapsed_s=55)   # 3/3.67 ≈ 0.818
        assert sy.classify() == "healthy"

    def test_degraded(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=2, elapsed_s=60)   # 2/4 = 0.5
        assert sy.classify() == "degraded"

    def test_degraded_boundary(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=1, elapsed_s=60)   # 1/4 = 0.25 → nope, starved
        # Actually 0.25 < 0.40, so it's starved
        assert sy.classify() == "starved"

    def test_starved(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=1, elapsed_s=120)  # 1/8 = 0.125
        assert sy.classify() == "starved"

    def test_no_observations_is_thriving(self):
        sy = StrokeYield()
        assert sy.classify() == "thriving"


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_fields(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=3, elapsed_s=60)
        snap = sy.snapshot()
        assert isinstance(snap, YieldSnapshot)
        assert snap.actual == 3
        assert snap.expected == pytest.approx(4.0)
        assert snap.ratio == pytest.approx(0.75, abs=0.01)
        assert snap.band == "healthy"

    def test_snapshot_to_dict(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=4, elapsed_s=60)
        d = sy.snapshot().to_dict()
        assert "actual" in d
        assert "expected" in d
        assert "ratio" in d
        assert "band" in d
        assert d["band"] == "thriving"


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_format(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=3, elapsed_s=60)
        s = sy.summary()
        assert "healthy" in s
        assert "yield" in s
        assert "75.0%" in s

    def test_summary_empty(self):
        sy = StrokeYield()
        s = sy.summary()
        assert "thriving" in s


# ---------------------------------------------------------------------------
# Window eviction
# ---------------------------------------------------------------------------

class TestWindowEviction:
    def test_old_slots_evicted(self):
        sy = StrokeYield(cadence_s=15, window_s=120)
        # First observation: 100 seconds ago, will be evicted
        sy.observe(count=0, elapsed_s=100)
        # Second observation: 60 seconds, within window
        sy.observe(count=4, elapsed_s=60)
        # Third: another 60 seconds
        sy.observe(count=4, elapsed_s=60)
        # Window is 120s; first slot (100s) should be evicted
        # Remaining: 60+60=120s, 4+4=8 actual, 8 expected → 1.0
        assert sy.yield_ratio() == pytest.approx(1.0)

    def test_single_slot_never_evicted(self):
        sy = StrokeYield(cadence_s=15, window_s=60)
        sy.observe(count=1, elapsed_s=300)
        # Even though 300s > 60s window, the single slot stays
        # (eviction preserves at least one slot)
        assert sy.yield_ratio() > 0


# ---------------------------------------------------------------------------
# Lifetime stats
# ---------------------------------------------------------------------------

class TestLifetime:
    def test_lifetime_ratio(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=4, elapsed_s=60)
        sy.observe(count=4, elapsed_s=60)
        assert sy.lifetime_ratio() == pytest.approx(1.0)

    def test_lifetime_no_observations(self):
        sy = StrokeYield()
        assert sy.lifetime_ratio() == 1.0

    def test_lifetime_not_windowed(self):
        """Lifetime includes all data even outside window."""
        sy = StrokeYield(cadence_s=15, window_s=60)
        sy.observe(count=0, elapsed_s=120)   # outside window
        sy.observe(count=4, elapsed_s=60)    # inside window
        # Lifetime: 4 actual / (180/15=12 expected) = 0.333
        assert sy.lifetime_ratio() == pytest.approx(4 / 12)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_everything(self):
        sy = StrokeYield(cadence_s=15)
        sy.observe(count=10, elapsed_s=120)
        sy.reset()
        assert sy.total_actual == 0
        assert sy.total_elapsed == 0.0
        assert sy.yield_ratio() == 1.0
        assert sy.classify() == "thriving"
