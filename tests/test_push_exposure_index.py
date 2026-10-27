"""Tests for push_exposure_index — composite risk scoring."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.push_exposure_index import (
    exposure_index,
    _score_dimension,
    _band,
    WEIGHTS,
    THRESHOLDS,
)


# ---------------------------------------------------------------------------
# _score_dimension
# ---------------------------------------------------------------------------

class TestScoreDimension:
    def test_zero_returns_zero(self):
        assert _score_dimension(0, [10, 50, 150]) == 0.0

    def test_negative_returns_zero(self):
        assert _score_dimension(-5, [10, 50, 150]) == 0.0

    def test_at_low_threshold_returns_25(self):
        assert _score_dimension(10, [10, 50, 150]) == pytest.approx(25.0)

    def test_at_mid_threshold_returns_50(self):
        assert _score_dimension(50, [10, 50, 150]) == pytest.approx(50.0)

    def test_at_high_threshold_returns_75(self):
        assert _score_dimension(150, [10, 50, 150]) == pytest.approx(75.0)

    def test_at_double_high_caps_at_100(self):
        assert _score_dimension(300, [10, 50, 150]) == pytest.approx(100.0)

    def test_beyond_double_high_stays_100(self):
        assert _score_dimension(9999, [10, 50, 150]) == pytest.approx(100.0)

    def test_between_low_and_mid(self):
        score = _score_dimension(30, [10, 50, 150])
        assert 25.0 < score < 50.0

    def test_between_mid_and_high(self):
        score = _score_dimension(100, [10, 50, 150])
        assert 50.0 < score < 75.0

    def test_monotonically_increasing(self):
        thresholds = [10, 50, 150]
        prev = -1.0
        for val in [0, 1, 5, 10, 25, 50, 75, 150, 200, 300]:
            cur = _score_dimension(val, thresholds)
            assert cur >= prev
            prev = cur


# ---------------------------------------------------------------------------
# _band
# ---------------------------------------------------------------------------

class TestBand:
    def test_safe_band(self):
        assert _band(0) == "safe"
        assert _band(19) == "safe"

    def test_caution_band(self):
        assert _band(20) == "caution"
        assert _band(49) == "caution"

    def test_warning_band(self):
        assert _band(50) == "warning"
        assert _band(74) == "warning"

    def test_critical_band(self):
        assert _band(75) == "critical"
        assert _band(100) == "critical"


# ---------------------------------------------------------------------------
# exposure_index — composite score
# ---------------------------------------------------------------------------

class TestExposureIndex:
    def test_all_zeros_is_safe(self):
        result = exposure_index()
        assert result["score"] == 0
        assert result["band"] == "safe"
        assert result["dimensions"]["commit_volume"] == 0.0

    def test_returns_all_dimension_keys(self):
        result = exposure_index(unpushed_count=5)
        assert set(result["dimensions"]) == set(WEIGHTS.keys())

    def test_score_bounded_0_to_100(self):
        # extreme inputs
        result = exposure_index(
            unpushed_count=99999,
            oldest_unpushed_hours=9999.0,
            estimated_work_hours=9999.0,
            blockage_hours=9999.0,
        )
        assert 0 <= result["score"] <= 100

    def test_realistic_high_risk_scenario(self):
        """the situation on 2026-10-27: 117 commits, ~72h old, ~48h work,
        blockage persisting ~96h.  should land in warning or critical."""
        result = exposure_index(
            unpushed_count=117,
            oldest_unpushed_hours=72.0,
            estimated_work_hours=48.0,
            blockage_hours=96.0,
        )
        assert result["band"] in ("warning", "critical")
        assert result["score"] >= 50

    def test_small_lag_is_safe(self):
        result = exposure_index(
            unpushed_count=3,
            oldest_unpushed_hours=1.0,
            estimated_work_hours=0.5,
            blockage_hours=0.0,
        )
        assert result["band"] == "safe"
        assert result["score"] < 20

    def test_summary_contains_key_numbers(self):
        result = exposure_index(
            unpushed_count=42,
            oldest_unpushed_hours=12.0,
            estimated_work_hours=8.0,
            blockage_hours=24.0,
        )
        assert "42" in result["summary"]
        assert "12h" in result["summary"]
        assert "8h" in result["summary"]

    def test_weight_sum_is_one(self):
        total = sum(WEIGHTS.values())
        assert total == pytest.approx(1.0)

    def test_each_threshold_list_has_three_elements(self):
        for dim, th in THRESHOLDS.items():
            assert len(th) == 3, f"{dim} thresholds must have 3 values"

    def test_score_increases_with_volume(self):
        low = exposure_index(unpushed_count=5)
        high = exposure_index(unpushed_count=100)
        assert high["score"] > low["score"]

    def test_score_increases_with_time(self):
        low = exposure_index(oldest_unpushed_hours=2.0)
        high = exposure_index(oldest_unpushed_hours=100.0)
        assert high["score"] > low["score"]

    def test_score_increases_with_work_hours(self):
        low = exposure_index(estimated_work_hours=1.0)
        high = exposure_index(estimated_work_hours=80.0)
        assert high["score"] > low["score"]

    def test_score_increases_with_blockage_age(self):
        low = exposure_index(blockage_hours=1.0)
        high = exposure_index(blockage_hours=200.0)
        assert high["score"] > low["score"]


# ---------------------------------------------------------------------------
# integration-style: current repo scenario
# ---------------------------------------------------------------------------

class TestCurrentScenario:
    """Snapshot tests using the actual state of the repo on 2026-10-27."""

    def test_current_exposure_is_critical(self):
        """117 commits trapped, SSH key missing for days."""
        result = exposure_index(
            unpushed_count=117,
            oldest_unpushed_hours=72.0,
            estimated_work_hours=48.0,
            blockage_hours=96.0,
        )
        # this should be at least warning, likely critical
        assert result["score"] >= 50
        assert "trapped" in result["summary"]

    def test_if_push_works_score_drops_to_zero(self):
        """After a successful push, all dimensions collapse."""
        result = exposure_index(
            unpushed_count=0,
            oldest_unpushed_hours=0.0,
            estimated_work_hours=0.0,
            blockage_hours=0.0,
        )
        assert result["score"] == 0
        assert result["band"] == "safe"
