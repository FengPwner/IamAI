"""Tests for iamai.stall_predictor — stall risk estimation.

28 tests covering:
  - stall_risk: normal, stalled, edge cases
  - risk_tier: all four tiers + boundary values
  - stall_assessment: integration + recommendation text
  - error handling: too few intervals, zero baseline
  - clamp behavior
"""

import pytest
from datetime import datetime, timezone

from iamai.stall_predictor import (
    stall_risk,
    risk_tier,
    stall_assessment,
    _clamp,
)


# ── _clamp ──────────────────────────────────────────────────────

class TestClamp:
    def test_within_range(self):
        assert _clamp(0.5, 0.0, 1.0) == 0.5

    def test_below_range(self):
        assert _clamp(-0.5, 0.0, 1.0) == 0.0

    def test_above_range(self):
        assert _clamp(1.5, 0.0, 1.0) == 1.0

    def test_at_lower_bound(self):
        assert _clamp(0.0, 0.0, 1.0) == 0.0

    def test_at_upper_bound(self):
        assert _clamp(1.0, 0.0, 1.0) == 1.0


# ── stall_risk ──────────────────────────────────────────────────

class TestStallRisk:
    def test_on_schedule(self):
        """Elapsed equals median → risk is 0."""
        intervals = [600.0, 600.0, 600.0, 600.0, 600.0]
        assert stall_risk(intervals, 600.0) == 0.0

    def test_early(self):
        """Elapsed less than median → risk is 0 (clamped)."""
        intervals = [600.0, 600.0, 600.0]
        assert stall_risk(intervals, 300.0) == 0.0

    def test_half_overdue(self):
        """Elapsed is 1.5x median → risk is 0.5."""
        intervals = [600.0, 600.0, 600.0]
        assert stall_risk(intervals, 900.0) == pytest.approx(0.5)

    def test_fully_overdue(self):
        """Elapsed is 2x median → risk is 1.0."""
        intervals = [600.0, 600.0, 600.0]
        assert stall_risk(intervals, 1200.0) == 1.0

    def test_way_overdue_clamped(self):
        """Elapsed is 5x median → risk is clamped to 1.0."""
        intervals = [600.0, 600.0, 600.0]
        assert stall_risk(intervals, 3000.0) == 1.0

    def test_variable_intervals_uses_median(self):
        """Median of [100, 200, 600, 800, 1000] = 600."""
        intervals = [100.0, 200.0, 600.0, 800.0, 1000.0]
        # elapsed = 600 → ratio = 1.0 → risk = 0.0
        assert stall_risk(intervals, 600.0) == 0.0
        # elapsed = 900 → ratio = 1.5 → risk = 0.5
        assert stall_risk(intervals, 900.0) == pytest.approx(0.5)

    def test_too_few_intervals_raises(self):
        with pytest.raises(ValueError, match="need >= 3"):
            stall_risk([600.0, 600.0], 600.0)

    def test_empty_intervals_raises(self):
        with pytest.raises(ValueError, match="need >= 3"):
            stall_risk([], 600.0)

    def test_zero_baseline_raises(self):
        with pytest.raises(ValueError, match="baseline must be > 0"):
            stall_risk([0.0, 0.0, 0.0], 100.0)

    def test_small_elapsed_is_zero_risk(self):
        intervals = [600.0, 600.0, 600.0]
        assert stall_risk(intervals, 0.0) == 0.0

    def test_exact_boundary_risk_0_25(self):
        """ratio = 1.25 → risk = 0.25."""
        intervals = [600.0, 600.0, 600.0]
        assert stall_risk(intervals, 750.0) == pytest.approx(0.25)

    def test_exact_boundary_risk_0_85(self):
        """ratio = 1.85 → risk = 0.85."""
        intervals = [600.0, 600.0, 600.0]
        assert stall_risk(intervals, 1110.0) == pytest.approx(0.85)


# ── risk_tier ───────────────────────────────────────────────────

class TestRiskTier:
    def test_low(self):
        assert risk_tier(0.0) == "low"
        assert risk_tier(0.24) == "low"

    def test_medium(self):
        assert risk_tier(0.25) == "medium"
        assert risk_tier(0.59) == "medium"

    def test_high(self):
        assert risk_tier(0.60) == "high"
        assert risk_tier(0.84) == "high"

    def test_critical(self):
        assert risk_tier(0.85) == "critical"
        assert risk_tier(1.0) == "critical"


# ── stall_assessment ────────────────────────────────────────────

class TestStallAssessment:
    def test_healthy_assessment(self):
        intervals = [600.0, 600.0, 600.0, 600.0, 600.0]
        result = stall_assessment(intervals, 620.0)
        assert result["tier"] == "low"
        assert result["risk"] == pytest.approx(0.0333, abs=0.01)
        assert result["baseline"] == 600.0
        assert "no action" in result["recommendation"]

    def test_stalled_assessment(self):
        intervals = [600.0, 600.0, 600.0, 600.0, 600.0]
        result = stall_assessment(intervals, 1500.0)
        assert result["tier"] == "critical"
        assert result["risk"] == 1.0
        assert "immediate restart" in result["recommendation"]

    def test_overdue_assessment(self):
        intervals = [600.0, 600.0, 600.0]
        result = stall_assessment(intervals, 900.0)
        assert result["tier"] == "medium"
        assert result["risk"] == pytest.approx(0.5)
        assert "check writer" in result["recommendation"]

    def test_high_risk_assessment(self):
        intervals = [600.0, 600.0, 600.0]
        result = stall_assessment(intervals, 1080.0)
        assert result["tier"] == "high"
        assert result["risk"] == pytest.approx(0.8)
        assert "restart recommended" in result["recommendation"]

    def test_assessed_at_default(self):
        intervals = [600.0, 600.0, 600.0]
        result = stall_assessment(intervals, 600.0)
        assert "assessed_at" in result
        # Should be a valid ISO timestamp
        datetime.fromisoformat(result["assessed_at"])

    def test_assessed_at_custom_now(self):
        now = datetime(2026, 10, 18, 19, 0, 0, tzinfo=timezone.utc)
        intervals = [600.0, 600.0, 600.0]
        result = stall_assessment(intervals, 600.0, now=now)
        assert "2026-10-18" in result["assessed_at"]

    def test_ratio_field(self):
        intervals = [600.0, 600.0, 600.0]
        result = stall_assessment(intervals, 900.0)
        assert result["ratio"] == pytest.approx(1.5)

    def test_elapsed_field(self):
        intervals = [600.0, 600.0, 600.0]
        result = stall_assessment(intervals, 750.0)
        assert result["elapsed"] == 750.0
