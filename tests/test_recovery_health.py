"""Tests for iamai.recovery_health — post-stall recovery assessment.

Covers: dead writer, full recovery, limping, stutter detection,
edge cases (single gap, two gaps, zero cadence, very large gaps),
and summary format validation.
"""

import pytest

from iamai.recovery_health import (
    RecoveryReport,
    _detect_stutter,
    _std_dev,
    assess_recovery,
)


# ---------------------------------------------------------------------------
# Dead writer
# ---------------------------------------------------------------------------

class TestDead:
    def test_empty_gaps_is_dead(self):
        r = assess_recovery([], target_cadence=15)
        assert r.verdict == "dead"
        assert r.sample_count == 0
        assert r.mean_gap == 0.0

    def test_dead_summary_mentions_dead(self):
        r = assess_recovery([])
        assert "dead" in r.summary.lower()

    def test_dead_ratio_zero(self):
        r = assess_recovery([])
        assert r.ratio == 0.0


# ---------------------------------------------------------------------------
# Full recovery
# ---------------------------------------------------------------------------

class TestFullRecovery:
    def test_perfect_cadence(self):
        gaps = [15, 15, 15, 15, 15]
        r = assess_recovery(gaps, target_cadence=15)
        assert r.verdict == "full"
        assert r.ratio == pytest.approx(1.0)

    def test_near_cadence(self):
        gaps = [14, 16, 15, 14, 17]
        r = assess_recovery(gaps, target_cadence=15)
        assert r.verdict == "full"
        assert r.ratio < 1.2

    def test_slightly_slow_but_healthy(self):
        gaps = [18, 19, 17, 18, 20]
        r = assess_recovery(gaps, target_cadence=15)
        assert r.verdict == "full"
        assert r.ratio < _LIMP_THRESHOLD()

    def test_full_summary_contains_verdict(self):
        gaps = [15, 15, 15]
        r = assess_recovery(gaps, target_cadence=15)
        assert "full" in r.summary

    def test_jitter_low_for_stable(self):
        gaps = [15, 15, 15, 15]
        r = assess_recovery(gaps, target_cadence=15)
        assert r.jitter < 1.0


# ---------------------------------------------------------------------------
# Limping recovery
# ---------------------------------------------------------------------------

class TestLimping:
    def test_clearly_limping(self):
        gaps = [45, 50, 40, 55, 42]
        r = assess_recovery(gaps, target_cadence=15)
        assert r.verdict == "limping"
        assert r.ratio > 2.0

    def test_limping_boundary(self):
        # mean = 31, ratio = 31/15 ≈ 2.07 → limping
        gaps = [30, 32, 31, 30, 32]
        r = assess_recovery(gaps, target_cadence=15)
        assert r.verdict == "limping"

    def test_limping_summary(self):
        gaps = [40, 40, 40]
        r = assess_recovery(gaps, target_cadence=15)
        assert "limping" in r.summary


# ---------------------------------------------------------------------------
# Stutter recovery
# ---------------------------------------------------------------------------

class TestStutter:
    def test_alternating_pattern(self):
        # Very slow then very fast → stutter
        gaps = [120, 5, 90, 3, 60]
        r = assess_recovery(gaps, target_cadence=15)
        assert r.verdict == "stutter"

    def test_initial_delay_then_catchup(self):
        # First gap huge, rest fast
        gaps = [300, 5, 5, 5, 5]
        r = assess_recovery(gaps, target_cadence=15)
        assert r.verdict == "stutter"

    def test_high_cv_detected(self):
        # Coefficient of variation > 0.6
        gaps = [10, 50, 10, 50, 10]
        r = assess_recovery(gaps, target_cadence=15)
        assert r.verdict == "stutter"


# ---------------------------------------------------------------------------
# Detect stutter helper
# ---------------------------------------------------------------------------

class TestDetectStutter:
    def test_empty(self):
        assert _detect_stutter([], 15) is False

    def test_uniform(self):
        assert _detect_stutter([15, 15, 15], 15) is False

    def test_has_slow_and_fast(self):
        assert _detect_stutter([100, 5], 15) is True

    def test_high_cv(self):
        assert _detect_stutter([10, 50, 10, 50], 15) is True

    def test_zero_mean(self):
        assert _detect_stutter([0, 0, 0], 15) is False


# ---------------------------------------------------------------------------
# Standard deviation helper
# ---------------------------------------------------------------------------

class TestStdDev:
    def test_single_value(self):
        assert _std_dev([5.0]) == 0.0

    def test_uniform(self):
        assert _std_dev([3, 3, 3, 3]) == 0.0

    def test_known_value(self):
        # std dev of [2, 4, 4, 4, 5, 5, 7, 9] = 2.0
        result = _std_dev([2, 4, 4, 4, 5, 5, 7, 9])
        assert result == pytest.approx(2.0)

    def test_two_values(self):
        # std dev of [0, 10] = 5.0
        assert _std_dev([0, 10]) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Insufficient data
# ---------------------------------------------------------------------------

class TestInsufficientData:
    def test_single_gap_flagged(self):
        r = assess_recovery([15], target_cadence=15)
        assert r.insufficient_data is True
        assert r.sample_count == 1

    def test_two_gaps_flagged(self):
        r = assess_recovery([15, 16], target_cadence=15)
        assert r.insufficient_data is True

    def test_three_gaps_ok(self):
        r = assess_recovery([15, 15, 15], target_cadence=15)
        assert r.insufficient_data is False

    def test_single_gap_classified_anyway(self):
        # Even with 1 gap we still get a verdict
        r = assess_recovery([50], target_cadence=15)
        assert r.verdict in ("full", "limping", "stutter", "dead")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_target_cadence(self):
        # Should not crash
        r = assess_recovery([15, 15, 15], target_cadence=0)
        assert r.ratio == 0.0

    def test_very_large_gaps(self):
        gaps = [10000, 20000, 15000]
        r = assess_recovery(gaps, target_cadence=15)
        assert r.verdict == "limping"
        assert r.mean_gap > 1000

    def test_fractional_gaps(self):
        gaps = [15.5, 14.8, 15.2]
        r = assess_recovery(gaps, target_cadence=15)
        assert r.verdict == "full"

    def test_large_sample(self):
        gaps = [15 + (i % 3) for i in range(100)]
        r = assess_recovery(gaps, target_cadence=15)
        assert r.sample_count == 100
        assert r.verdict == "full"

    def test_custom_cadence(self):
        # Target 60s, gaps around 60s → full
        gaps = [58, 62, 60, 59, 61]
        r = assess_recovery(gaps, target_cadence=60)
        assert r.verdict == "full"


# ---------------------------------------------------------------------------
# Dataclass constraints
# ---------------------------------------------------------------------------

class TestDataclass:
    def test_report_is_frozen(self):
        r = assess_recovery([15, 15, 15], target_cadence=15)
        with pytest.raises(AttributeError):
            r.verdict = "changed"

    def test_report_fields(self):
        r = assess_recovery([15, 15, 15], target_cadence=15)
        assert hasattr(r, "verdict")
        assert hasattr(r, "mean_gap")
        assert hasattr(r, "target_cadence")
        assert hasattr(r, "ratio")
        assert hasattr(r, "jitter")
        assert hasattr(r, "sample_count")
        assert hasattr(r, "insufficient_data")
        assert hasattr(r, "summary")


# ---------------------------------------------------------------------------
# Summary format
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_not_empty(self):
        r = assess_recovery([15, 15, 15, 15], target_cadence=15)
        assert len(r.summary) > 0

    def test_summary_contains_verdict(self):
        for gaps, expected in [
            ([15, 15, 15, 15], "full"),
            ([50, 50, 50, 50], "limping"),
            ([], "dead"),
        ]:
            r = assess_recovery(gaps, target_cadence=15)
            assert expected in r.summary

    def test_summary_contains_target(self):
        r = assess_recovery([15, 15, 15], target_cadence=15)
        assert "15" in r.summary

    def test_summary_contains_sample_count(self):
        gaps = [15, 16, 17, 18]
        r = assess_recovery(gaps, target_cadence=15)
        assert "4" in r.summary or "gaps" in r.summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _LIMP_THRESHOLD():
    """Return the limp ratio threshold (2.0) + small tolerance."""
    return 2.1
