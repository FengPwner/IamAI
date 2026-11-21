"""Tests for iamai.commit_gap_analyzer — commit gap health classification."""

from __future__ import annotations

import math

import pytest

from iamai.commit_gap_analyzer import (
    NOMINAL,
    JITTER,
    STALL,
    OUTAGE,
    GapClass,
    GapDiagnostics,
    classify_gap,
    classify_gaps,
    gaps_from_timestamps,
    diagnose,
    _shannon_entropy,
    _count_recoveries,
    NOMINAL_UPPER,
    JITTER_UPPER,
    STALL_UPPER,
)


# ---------------------------------------------------------------------------
# single gap classification
# ---------------------------------------------------------------------------


class TestClassifyGap:
    def test_nominal_exact_cadence(self):
        gc = classify_gap(600.0, 600.0)
        assert gc.band == NOMINAL
        assert gc.ratio == pytest.approx(1.0)

    def test_nominal_within_tolerance(self):
        gc = classify_gap(770.0, 600.0)  # ratio ≈ 1.283
        assert gc.band == NOMINAL
        assert gc.ratio == pytest.approx(770.0 / 600.0)

    def test_nominal_upper_boundary(self):
        gc = classify_gap(600.0 * NOMINAL_UPPER, 600.0)
        assert gc.band == NOMINAL

    def test_jitter_just_above_nominal(self):
        gc = classify_gap(600.0 * NOMINAL_UPPER + 1, 600.0)
        assert gc.band == JITTER

    def test_jitter_mid_range(self):
        gc = classify_gap(1200.0, 600.0)  # ratio = 2.0
        assert gc.band == JITTER

    def test_jitter_upper_boundary(self):
        gc = classify_gap(600.0 * JITTER_UPPER, 600.0)
        assert gc.band == JITTER

    def test_stall_just_above_jitter(self):
        gc = classify_gap(600.0 * JITTER_UPPER + 1, 600.0)
        assert gc.band == STALL

    def test_stall_mid_range(self):
        gc = classify_gap(4200.0, 600.0)  # ratio = 7.0
        assert gc.band == STALL

    def test_stall_upper_boundary(self):
        gc = classify_gap(600.0 * STALL_UPPER, 600.0)
        assert gc.band == STALL

    def test_outage_above_stall(self):
        gc = classify_gap(600.0 * STALL_UPPER + 1, 600.0)
        assert gc.band == OUTAGE

    def test_outage_extreme(self):
        gc = classify_gap(86400.0, 600.0)  # 24 hours
        assert gc.band == OUTAGE
        assert gc.ratio == pytest.approx(144.0)

    def test_zero_gap(self):
        gc = classify_gap(0.0, 600.0)
        assert gc.band == NOMINAL
        assert gc.ratio == 0.0

    def test_gap_seconds_stored(self):
        gc = classify_gap(1234.5, 600.0)
        assert gc.gap_seconds == pytest.approx(1234.5)


class TestClassifyGapValidation:
    def test_negative_gap_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            classify_gap(-1.0, 600.0)

    def test_zero_cadence_raises(self):
        with pytest.raises(ValueError, match="positive"):
            classify_gap(600.0, 0.0)

    def test_negative_cadence_raises(self):
        with pytest.raises(ValueError, match="positive"):
            classify_gap(600.0, -100.0)


class TestClassifyGapCustomCadence:
    def test_five_minute_cadence(self):
        gc = classify_gap(300.0, 300.0)
        assert gc.band == NOMINAL

    def test_fifteen_minute_cadence_stall(self):
        gc = classify_gap(900.0 * 5, 900.0)  # ratio = 5.0
        assert gc.band == STALL

    def test_one_hour_cadence_outage(self):
        gc = classify_gap(3600.0 * 20, 3600.0)  # ratio = 20
        assert gc.band == OUTAGE


# ---------------------------------------------------------------------------
# batch classification
# ---------------------------------------------------------------------------


class TestClassifyGaps:
    def test_empty_list(self):
        assert classify_gaps([]) == []

    def test_single_gap(self):
        result = classify_gaps([600.0], 600.0)
        assert len(result) == 1
        assert result[0].band == NOMINAL

    def test_mixed_bands(self):
        gaps = [600.0, 1500.0, 4200.0, 86400.0]
        result = classify_gaps(gaps, 600.0)
        assert len(result) == 4
        assert result[0].band == NOMINAL
        assert result[1].band == JITTER
        assert result[2].band == STALL
        assert result[3].band == OUTAGE

    def test_all_nominal(self):
        gaps = [600.0, 610.0, 590.0, 605.0]
        result = classify_gaps(gaps, 600.0)
        assert all(gc.band == NOMINAL for gc in result)


# ---------------------------------------------------------------------------
# timestamp → gap conversion
# ---------------------------------------------------------------------------


class TestGapsFromTimestamps:
    def test_empty(self):
        assert gaps_from_timestamps([]) == []

    def test_single_timestamp(self):
        assert gaps_from_timestamps([1000.0]) == []

    def test_two_timestamps(self):
        assert gaps_from_timestamps([1000.0, 1600.0]) == [600.0]

    def test_three_timestamps(self):
        result = gaps_from_timestamps([0.0, 600.0, 1200.0])
        assert result == [600.0, 600.0]

    def test_irregular_intervals(self):
        ts = [0.0, 600.0, 2400.0, 2400.0, 9000.0]
        result = gaps_from_timestamps(ts)
        assert result == [600.0, 1800.0, 0.0, 6600.0]

    def test_preserves_order(self):
        ts = [100.0, 200.0, 500.0, 1000.0]
        result = gaps_from_timestamps(ts)
        assert result == [100.0, 300.0, 500.0]


# ---------------------------------------------------------------------------
# series-level diagnostics
# ---------------------------------------------------------------------------


class TestDiagnose:
    def test_empty_gaps(self):
        d = diagnose([])
        assert d.total_gaps == 0
        assert d.cadence_adherence == 0.0
        assert d.mean_gap_ratio == 0.0
        assert d.stall_rate == 0.0
        assert d.gap_entropy == 0.0
        assert d.recovery_count == 0

    def test_all_nominal(self):
        gaps = [600.0] * 10
        d = diagnose(gaps, 600.0)
        assert d.total_gaps == 10
        assert d.band_counts[NOMINAL] == 10
        assert d.cadence_adherence == 1.0
        assert d.stall_rate == 0.0
        assert d.mean_gap_ratio == pytest.approx(1.0)
        assert d.gap_entropy == pytest.approx(0.0)
        assert d.recovery_count == 0

    def test_all_outage(self):
        gaps = [10000.0] * 5
        d = diagnose(gaps, 600.0)
        assert d.total_gaps == 5
        assert d.band_counts[OUTAGE] == 5
        assert d.cadence_adherence == 0.0
        assert d.stall_rate == 1.0
        assert d.recovery_count == 0

    def test_perfect_recovery(self):
        # outage → nominal → nominal → outage → nominal
        gaps = [10000.0, 600.0, 600.0, 10000.0, 600.0]
        d = diagnose(gaps, 600.0)
        assert d.total_gaps == 5
        assert d.recovery_count == 2

    def test_no_recovery_in_streak(self):
        # nominal → stall → stall → stall
        gaps = [600.0, 4200.0, 4200.0, 4200.0]
        d = diagnose(gaps, 600.0)
        assert d.recovery_count == 0

    def test_mixed_diagnostics(self):
        # 2 nominal, 1 jitter, 1 stall, 1 outage
        gaps = [600.0, 700.0, 1500.0, 4200.0, 10000.0]
        d = diagnose(gaps, 600.0)
        assert d.total_gaps == 5
        assert d.band_counts[NOMINAL] == 2
        assert d.band_counts[JITTER] == 1
        assert d.band_counts[STALL] == 1
        assert d.band_counts[OUTAGE] == 1
        assert d.cadence_adherence == pytest.approx(3.0 / 5)
        assert d.stall_rate == pytest.approx(2.0 / 5)
        assert d.worst_gap == 10000.0
        assert d.worst_band == OUTAGE
        # recovery: stall → outage is not recovery, outage→end is not recovery
        assert d.recovery_count == 0

    def test_entropy_max_uniform(self):
        # 4 bands, roughly equal → entropy ≈ 2.0 bits
        # 1 of each band
        gaps = [600.0, 1500.0, 4200.0, 10000.0]
        d = diagnose(gaps, 600.0)
        assert d.gap_entropy == pytest.approx(2.0, abs=0.01)

    def test_entropy_zero_single_band(self):
        gaps = [600.0, 600.0, 600.0]
        d = diagnose(gaps, 600.0)
        assert d.gap_entropy == pytest.approx(0.0)

    def test_worst_gap_outage(self):
        gaps = [600.0, 600.0, 99999.0]
        d = diagnose(gaps, 600.0)
        assert d.worst_gap == 99999.0
        assert d.worst_band == OUTAGE

    def test_mean_gap_ratio_calculation(self):
        gaps = [300.0, 600.0, 1200.0]
        d = diagnose(gaps, 600.0)
        expected = (0.5 + 1.0 + 2.0) / 3
        assert d.mean_gap_ratio == pytest.approx(expected)


# ---------------------------------------------------------------------------
# shannon entropy helper
# ---------------------------------------------------------------------------


class TestShannonEntropy:
    def test_empty(self):
        assert _shannon_entropy({}) == 0.0

    def test_single_category(self):
        assert _shannon_entropy({"a": 10}) == pytest.approx(0.0)

    def test_two_equal(self):
        assert _shannon_entropy({"a": 5, "b": 5}) == pytest.approx(1.0)

    def test_four_equal(self):
        assert _shannon_entropy({"a": 1, "b": 1, "c": 1, "d": 1}) == pytest.approx(2.0)

    def test_skewed(self):
        # 99:1 → low entropy
        h = _shannon_entropy({"a": 99, "b": 1})
        assert 0 < h < 1.0


# ---------------------------------------------------------------------------
# recovery counter
# ---------------------------------------------------------------------------


class TestCountRecoveries:
    def test_empty(self):
        assert _count_recoveries([]) == 0

    def test_single(self):
        assert _count_recoveries([NOMINAL]) == 0

    def test_no_transitions(self):
        assert _count_recoveries([NOMINAL, NOMINAL, JITTER]) == 0

    def test_stall_to_nominal(self):
        assert _count_recoveries([STALL, NOMINAL]) == 1

    def test_outage_to_jitter(self):
        assert _count_recoveries([OUTAGE, JITTER]) == 1

    def test_nominal_to_stall_not_recovery(self):
        assert _count_recoveries([NOMINAL, STALL]) == 0

    def test_multiple_recoveries(self):
        bands = [OUTAGE, NOMINAL, STALL, JITTER, NOMINAL]
        assert _count_recoveries(bands) == 2

    def test_consecutive_degraded_no_recovery(self):
        bands = [STALL, STALL, OUTAGE, OUTAGE]
        assert _count_recoveries(bands) == 0


# ---------------------------------------------------------------------------
# integration: timestamps → diagnostics
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_healthy_rhythm(self):
        ts = [0, 600, 1200, 1800, 2400, 3000, 3600]
        gaps = gaps_from_timestamps(ts)
        d = diagnose(gaps, 600.0)
        assert d.cadence_adherence == 1.0
        assert d.stall_rate == 0.0
        assert d.recovery_count == 0

    def test_one_stall_recovery(self):
        # normal, normal, stall (3600s gap), normal, normal
        ts = [0, 600, 1200, 4800, 5400, 6000]
        gaps = gaps_from_timestamps(ts)
        d = diagnose(gaps, 600.0)
        assert d.band_counts[STALL] == 1
        assert d.recovery_count == 1

    def test_long_outage_then_recovery(self):
        # normal, 24h gap, normal, normal
        ts = [0, 600, 87000, 87600, 88200]
        gaps = gaps_from_timestamps(ts)
        d = diagnose(gaps, 600.0)
        assert d.band_counts[OUTAGE] == 1
        assert d.recovery_count == 1
        assert d.worst_gap == 86400.0

    def test_cascading_degradation(self):
        # normal → jitter → stall → outage (no recovery)
        ts = [0, 600, 1800, 5400, 20000]
        gaps = gaps_from_timestamps(ts)
        d = diagnose(gaps, 600.0)
        assert d.recovery_count == 0
        assert d.stall_rate > 0
        assert d.worst_band == OUTAGE
