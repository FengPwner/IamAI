#!/usr/bin/env python3
"""Tests for stroke_phase_alignment.py — commit-cycle phase analysis."""

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_phase_alignment import (
    PhaseAlignmentReport,
    _parse_ts,
    _to_epoch_seconds,
    analyze,
    classify_alignment,
    compute_phase,
    phase_histogram,
    rayleigh_test,
    rush_score,
    shannon_entropy,
    warmup_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 11, 19, 2, 0, 0, tzinfo=timezone.utc)
_BASE_EPOCH = _BASE.timestamp()


def _ts(offset_seconds: float) -> str:
    """Return an ISO-8601 timestamp offset from a fixed base."""
    dt = _BASE + timedelta(seconds=offset_seconds)
    return dt.isoformat()


def _make_strokes(offsets: list, kind: str = "thought") -> list:
    """Build a list of stroke dicts from second-offsets."""
    return [
        {"seq": i, "at": _ts(s), "kind": kind, "text": f"stroke {i}"}
        for i, s in enumerate(offsets)
    ]


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    def test_iso_with_tz(self):
        dt = _parse_ts("2026-11-19T02:00:00+00:00")
        assert dt.year == 2026
        assert dt.month == 11

    def test_z_suffix(self):
        dt = _parse_ts("2026-11-19T02:00:00Z")
        assert dt.tzinfo is not None

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_ts("not-a-date")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _parse_ts("")


class TestToEpochSeconds:
    def test_roundtrip(self):
        dt = datetime(2026, 11, 19, 2, 0, 0, tzinfo=timezone.utc)
        sec = _to_epoch_seconds(dt)
        assert isinstance(sec, float)
        assert sec > 0


# ---------------------------------------------------------------------------
# compute_phase
# ---------------------------------------------------------------------------

class TestComputePhase:
    def test_on_boundary(self):
        # epoch=0, period=600: t=0 → phase=0, t=600 → phase=0, t=300 → 0.5
        assert compute_phase(0.0, 600.0, 0.0) == 0.0
        assert compute_phase(600.0, 600.0, 0.0) == 0.0
        assert compute_phase(300.0, 600.0, 0.0) == pytest.approx(0.5)

    def test_with_epoch_offset(self):
        # epoch=100, period=600: t=100 → phase=0, t=400 → phase=0.5
        assert compute_phase(100.0, 600.0, 100.0) == pytest.approx(0.0)
        assert compute_phase(400.0, 600.0, 100.0) == pytest.approx(0.5)

    def test_wraps_around(self):
        # t=700 with period=600, epoch=0 → phase = 700%600/600 = 100/600
        assert compute_phase(700.0, 600.0, 0.0) == pytest.approx(100 / 600)

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError):
            compute_phase(100.0, 0.0)

    def test_negative_period_raises(self):
        with pytest.raises(ValueError):
            compute_phase(100.0, -1.0)

    def test_phase_range(self):
        # Phase should always be in [0, 1).
        for t in [0, 1, 59, 60, 599, 600, 601, 1200, 9999]:
            p = compute_phase(float(t), 600.0, 0.0)
            assert 0.0 <= p < 1.0


# ---------------------------------------------------------------------------
# phase_histogram
# ---------------------------------------------------------------------------

class TestPhaseHistogram:
    def test_uniform_distribution(self):
        # 10 phases evenly spaced across 10 bins → 1 each.
        phases = [i / 10 + 0.05 for i in range(10)]
        bins = phase_histogram(phases, 10)
        assert bins == [1] * 10

    def test_all_in_first_bin(self):
        phases = [0.01, 0.02, 0.03, 0.04, 0.05]
        bins = phase_histogram(phases, 10)
        assert bins[0] == 5
        assert sum(bins[1:]) == 0

    def test_all_in_last_bin(self):
        phases = [0.91, 0.92, 0.95, 0.99, 0.999]
        bins = phase_histogram(phases, 10)
        assert bins[-1] == 5
        assert sum(bins[:-1]) == 0

    def test_total_equals_input_length(self):
        phases = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 0.99]
        bins = phase_histogram(phases, 10)
        assert sum(bins) == len(phases)

    def test_empty_phases(self):
        bins = phase_histogram([], 10)
        assert bins == [0] * 10

    def test_single_bin(self):
        phases = [0.1, 0.5, 0.9]
        bins = phase_histogram(phases, 1)
        assert bins == [3]

    def test_invalid_bins_raises(self):
        with pytest.raises(ValueError):
            phase_histogram([0.5], 0)


# ---------------------------------------------------------------------------
# shannon_entropy
# ---------------------------------------------------------------------------

class TestShannonEntropy:
    def test_uniform_max_entropy(self):
        # 10 bins with equal counts → entropy = log2(10) ≈ 3.32
        counts = [10] * 10
        ent = shannon_entropy(counts)
        assert ent == pytest.approx(math.log2(10), abs=1e-9)

    def test_single_bin_zero_entropy(self):
        # All counts in one bin → entropy = 0.
        counts = [100, 0, 0, 0, 0]
        assert shannon_entropy(counts) == 0.0

    def test_empty_counts(self):
        assert shannon_entropy([]) == 0.0

    def test_two_equal_bins(self):
        counts = [50, 50]
        assert shannon_entropy(counts) == pytest.approx(1.0)

    def test_asymmetric(self):
        counts = [75, 25]
        ent = shannon_entropy(counts)
        # Should be between 0 and 1.
        assert 0 < ent < 1.0


# ---------------------------------------------------------------------------
# rayleigh_test
# ---------------------------------------------------------------------------

class TestRayleighTest:
    def test_uniform_phases_low_r(self):
        # Evenly spaced phases → r ≈ 0.
        phases = [i / 100 for i in range(100)]
        r, p = rayleigh_test(phases)
        assert r < 0.05
        assert p > 0.5

    def test_clustered_phases_high_r(self):
        # All phases near 0.5 → r ≈ 1.
        phases = [0.5 + 0.01 * i for i in range(-5, 6)]
        phases = [p % 1.0 for p in phases]
        r, p = rayleigh_test(phases)
        assert r > 0.8
        assert p < 0.05

    def test_single_phase(self):
        r, p = rayleigh_test([0.5])
        assert r == 0.0
        assert p == 1.0

    def test_empty_phases(self):
        r, p = rayleigh_test([])
        assert r == 0.0
        assert p == 1.0

    def test_r_in_unit_interval(self):
        phases = [0.1, 0.3, 0.5, 0.7, 0.9]
        r, p = rayleigh_test(phases)
        assert 0.0 <= r <= 1.0
        assert 0.0 <= p <= 1.0


# ---------------------------------------------------------------------------
# rush_score and warmup_score
# ---------------------------------------------------------------------------

class TestRushScore:
    def test_all_rushing(self):
        phases = [0.8, 0.85, 0.9, 0.95, 0.99]
        assert rush_score(phases) == 1.0

    def test_none_rushing(self):
        phases = [0.0, 0.1, 0.3, 0.5, 0.7]
        assert rush_score(phases) == 0.0

    def test_partial(self):
        phases = [0.1, 0.3, 0.5, 0.7, 0.9]
        assert rush_score(phases) == pytest.approx(0.2)

    def test_empty(self):
        assert rush_score([]) == 0.0

    def test_custom_threshold(self):
        phases = [0.6, 0.7, 0.8, 0.9]
        assert rush_score(phases, threshold=0.6) == 1.0
        assert rush_score(phases, threshold=0.85) == pytest.approx(0.25)


class TestWarmupScore:
    def test_all_warming_up(self):
        phases = [0.0, 0.05, 0.1, 0.15, 0.19]
        assert warmup_score(phases) == 1.0

    def test_none_warming_up(self):
        phases = [0.3, 0.5, 0.7, 0.8, 0.9]
        assert warmup_score(phases) == 0.0

    def test_partial(self):
        phases = [0.1, 0.3, 0.5, 0.7, 0.9]
        assert warmup_score(phases) == pytest.approx(0.2)

    def test_empty(self):
        assert warmup_score([]) == 0.0

    def test_boundary_excluded(self):
        # threshold=0.2: phase 0.2 is NOT < 0.2, so excluded.
        phases = [0.0, 0.2]
        assert warmup_score(phases, threshold=0.2) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# classify_alignment
# ---------------------------------------------------------------------------

class TestClassifyAlignment:
    def test_pre_commit_rush(self):
        assert classify_alignment(0.5, 0.1, 0.2, 0.3) == "pre_commit_rush"

    def test_post_commit_warmup(self):
        assert classify_alignment(0.1, 0.5, 0.2, 0.3) == "post_commit_warmup"

    def test_phase_locked(self):
        assert classify_alignment(0.1, 0.1, 0.5, 0.01) == "phase_locked"

    def test_uniform(self):
        assert classify_alignment(0.1, 0.1, 0.1, 0.5) == "uniform"

    def test_rush_beats_warmup(self):
        # Both high → rush wins.
        assert classify_alignment(0.5, 0.5, 0.5, 0.01) == "pre_commit_rush"

    def test_rush_beats_phase_locked(self):
        assert classify_alignment(0.5, 0.1, 0.5, 0.01) == "pre_commit_rush"


# ---------------------------------------------------------------------------
# Full analyze() integration tests
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_basic_uniform(self):
        """Strokes evenly distributed across the cycle should be uniform."""
        # 40 strokes, each 15s apart, over a 600s cycle = exactly 1 full cycle.
        offsets = [i * 15 for i in range(40)]
        strokes = _make_strokes(offsets)
        report = analyze(strokes, batch_period=600.0, epoch=_BASE_EPOCH)

        assert report.total_strokes == 40
        assert report.alignment_class == "uniform"
        assert report.entropy_ratio > 0.8  # Near-maximum entropy.
        assert report.rayleigh_r < 0.2

    def test_pre_commit_rush_detected(self):
        """Strokes clustered in the last 20% of the cycle."""
        # All strokes in the last 120s of a 600s cycle.
        offsets = [480 + i * 2 for i in range(40)]
        strokes = _make_strokes(offsets)
        report = analyze(strokes, batch_period=600.0, epoch=_BASE_EPOCH)

        assert report.alignment_class == "pre_commit_rush"
        assert report.rush_score > 0.35

    def test_post_commit_warmup_detected(self):
        """Strokes clustered in the first 20% of the cycle."""
        offsets = [i * 2 for i in range(40)]  # 0–78s, all in first 13%.
        strokes = _make_strokes(offsets)
        report = analyze(strokes, batch_period=600.0, epoch=_BASE_EPOCH)

        assert report.alignment_class == "post_commit_warmup"
        assert report.warmup_score > 0.35

    def test_single_stroke(self):
        """Fewer than 2 strokes should return a default report."""
        strokes = _make_strokes([0])
        report = analyze(strokes, batch_period=600.0, epoch=_BASE_EPOCH)
        assert report.total_strokes == 1
        assert report.alignment_class == "uniform"

    def test_empty_strokes(self):
        strokes = []
        report = analyze(strokes)
        assert report.total_strokes == 0
        assert report.alignment_class == "uniform"

    def test_histogram_bins_sum(self):
        offsets = [i * 15 for i in range(100)]
        strokes = _make_strokes(offsets)
        report = analyze(strokes, batch_period=600.0, epoch=_BASE_EPOCH)
        assert sum(report.phase_bins) == report.total_strokes
        assert len(report.phase_bins) == 10

    def test_custom_n_bins(self):
        offsets = [i * 15 for i in range(50)]
        strokes = _make_strokes(offsets)
        report = analyze(strokes, batch_period=600.0, epoch=_BASE_EPOCH, n_bins=20)
        assert len(report.phase_bins) == 20
        assert report.max_entropy == pytest.approx(math.log2(20))

    def test_entropy_ratio_bounded(self):
        offsets = [i * 15 for i in range(60)]
        strokes = _make_strokes(offsets)
        report = analyze(strokes, batch_period=600.0, epoch=_BASE_EPOCH)
        assert 0.0 <= report.entropy_ratio <= 1.0

    def test_peak_fraction_bounded(self):
        offsets = [i * 15 for i in range(60)]
        strokes = _make_strokes(offsets)
        report = analyze(strokes, batch_period=600.0, epoch=_BASE_EPOCH)
        assert 0.0 <= report.peak_fraction <= 1.0

    def test_report_dataclass_defaults(self):
        r = PhaseAlignmentReport()
        assert r.batch_period == 600.0
        assert r.n_bins == 10
        assert r.alignment_class == "uniform"
        assert r.phases == []
        assert r.phase_bins == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_two_strokes_same_phase(self):
        """Two strokes at exactly the same phase."""
        offsets = [0, 600]  # Both at phase 0.
        strokes = _make_strokes(offsets)
        report = analyze(strokes, batch_period=600.0, epoch=_BASE_EPOCH)
        assert report.total_strokes == 2
        assert report.entropy == 0.0  # All in one bin.

    def test_large_batch_period(self):
        """Batch period larger than the total observation window."""
        offsets = [i * 15 for i in range(10)]  # 0–135s.
        strokes = _make_strokes(offsets)
        report = analyze(strokes, batch_period=3600.0, epoch=_BASE_EPOCH)
        assert report.total_strokes == 10
        # All strokes in the first 4% of the cycle → warmup.
        assert report.warmup_score == 1.0

    def test_phase_never_exactly_one(self):
        """Ensure no phase equals exactly 1.0."""
        offsets = [599, 1199, 1799]
        strokes = _make_strokes(offsets)
        report = analyze(strokes, batch_period=600.0, epoch=_BASE_EPOCH)
        for p in report.phases:
            assert p < 1.0

    def test_custom_epoch(self):
        offsets = [0, 300, 600]
        strokes = _make_strokes(offsets)
        # With epoch shifted by 300s, the phases should shift.
        report_a = analyze(strokes, batch_period=600.0, epoch=_BASE_EPOCH)
        report_b = analyze(strokes, batch_period=600.0, epoch=_BASE_EPOCH + 300)
        # Phases should differ.
        assert report_a.phases != report_b.phases


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
