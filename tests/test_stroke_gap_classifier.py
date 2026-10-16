"""Tests for iamai.stroke_gap_classifier.

Covers: classify(), worst_band(), StrokeGapHistogram (record, counts,
total, worst, summarize, reset), edge cases, and error handling.
"""

import pytest
from iamai.stroke_gap_classifier import (
    BAND_ORDER,
    StrokeGapHistogram,
    classify,
    worst_band,
)


# ── classify() ────────────────────────────────────────────────────────


class TestClassify:
    """classify() pure-function tests with default 15 s cadence."""

    def test_zero_gap_is_normal(self):
        assert classify(0) == "normal"

    def test_small_gap_is_normal(self):
        assert classify(10) == "normal"
        assert classify(14.9) == "normal"
        assert classify(29.9) == "normal"  # < 2× cadence

    def test_exactly_2x_is_stretched(self):
        assert classify(30.0) == "stretched"

    def test_stretched_range(self):
        assert classify(35) == "stretched"
        assert classify(50) == "stretched"
        assert classify(74.9) == "stretched"  # < 5× cadence

    def test_exactly_5x_is_micro_stall(self):
        assert classify(75.0) == "micro_stall"

    def test_micro_stall_range(self):
        assert classify(80) == "micro_stall"
        assert classify(200) == "micro_stall"
        assert classify(449.9) == "micro_stall"  # < 30× cadence

    def test_exactly_30x_is_stall(self):
        assert classify(450.0) == "stall"

    def test_stall_range(self):
        assert classify(500) == "stall"
        assert classify(1000) == "stall"
        assert classify(1799.9) == "stall"  # < 120× cadence

    def test_exactly_120x_is_reclaimed(self):
        assert classify(1800.0) == "reclaimed"

    def test_large_gap_is_reclaimed(self):
        assert classify(2700) == "reclaimed"
        assert classify(3600) == "reclaimed"
        assert classify(86400) == "reclaimed"

    def test_negative_gap_raises(self):
        with pytest.raises(ValueError, match="gap_s must be >= 0"):
            classify(-1)

    def test_zero_cadence_raises(self):
        with pytest.raises(ValueError, match="cadence_s must be > 0"):
            classify(15, cadence_s=0)

    def test_negative_cadence_raises(self):
        with pytest.raises(ValueError, match="cadence_s must be > 0"):
            classify(15, cadence_s=-5)

    def test_custom_cadence_30s(self):
        """With a 30 s cadence, 45 s gap should be normal (< 2× = 60 s)."""
        assert classify(45, cadence_s=30) == "normal"
        assert classify(60, cadence_s=30) == "stretched"
        assert classify(150, cadence_s=30) == "micro_stall"  # 5× = 150

    def test_custom_cadence_60s(self):
        """With a 60 s cadence, 3599 s should be stall (< 120× = 7200 s)."""
        assert classify(3599, cadence_s=60) == "stall"
        assert classify(7200, cadence_s=60) == "reclaimed"


# ── worst_band() ──────────────────────────────────────────────────────


class TestWorstBand:
    def test_empty_list_returns_normal(self):
        assert worst_band([]) == "normal"

    def test_all_normal(self):
        assert worst_band([10, 15, 20]) == "normal"

    def test_mixed_returns_worst(self):
        assert worst_band([10, 80, 3600]) == "reclaimed"

    def test_single_stretch(self):
        assert worst_band([45]) == "stretched"

    def test_custom_cadence(self):
        # 500/60 ≈ 8.3× → micro_stall; need 1800+ for stall at 60s cadence
        assert worst_band([100, 200, 500], cadence_s=60) == "micro_stall"
        assert worst_band([1800], cadence_s=60) == "stall"


# ── StrokeGapHistogram ───────────────────────────────────────────────


class TestStrokeGapHistogram:
    def test_empty_histogram(self):
        h = StrokeGapHistogram()
        assert h.total == 0
        assert h.worst == "normal"
        assert h.counts() == {b: 0 for b in BAND_ORDER}

    def test_record_returns_band(self):
        h = StrokeGapHistogram()
        assert h.record(15) == "normal"
        assert h.record(80) == "micro_stall"

    def test_total_increments(self):
        h = StrokeGapHistogram()
        h.record(10)
        h.record(10)
        h.record(10)
        assert h.total == 3

    def test_counts_accumulate(self):
        h = StrokeGapHistogram()
        h.record(10)   # normal
        h.record(12)   # normal
        h.record(35)   # stretched
        h.record(80)   # micro_stall
        h.record(500)  # stall
        h.record(3600) # reclaimed
        counts = h.counts()
        assert counts["normal"] == 2
        assert counts["stretched"] == 1
        assert counts["micro_stall"] == 1
        assert counts["stall"] == 1
        assert counts["reclaimed"] == 1

    def test_counts_returns_copy(self):
        """Mutating the returned dict must not affect the histogram."""
        h = StrokeGapHistogram()
        h.record(10)
        c = h.counts()
        c["normal"] = 999
        assert h.counts()["normal"] == 1

    def test_worst_tracks_highest_severity(self):
        h = StrokeGapHistogram()
        h.record(10)
        assert h.worst == "normal"
        h.record(80)
        assert h.worst == "micro_stall"
        h.record(3600)
        assert h.worst == "reclaimed"
        # Adding a normal doesn't lower it
        h.record(10)
        assert h.worst == "reclaimed"

    def test_max_gap(self):
        h = StrokeGapHistogram()
        h.record(10)
        h.record(500)
        h.record(200)
        assert h._max_gap == 500

    def test_min_gap(self):
        h = StrokeGapHistogram()
        h.record(500)
        h.record(10)
        h.record(200)
        assert h._min_gap == 10

    def test_summarize_empty(self):
        h = StrokeGapHistogram()
        s = h.summarize()
        assert s["total"] == 0
        assert s["worst"] == "normal"
        assert s["mean_gap_s"] is None
        assert s["max_gap_s"] == 0.0

    def test_summarize_with_data(self):
        h = StrokeGapHistogram(cadence_s=15)
        h.record(10)
        h.record(20)
        h.record(30)
        s = h.summarize()
        assert s["total"] == 3
        assert s["cadence_s"] == 15
        assert s["mean_gap_s"] == 20.0
        assert s["max_gap_s"] == 30.0
        assert s["min_gap_s"] == 10.0
        assert s["worst"] == "stretched"
        assert isinstance(s["bands"], dict)

    def test_summarize_mean_rounded(self):
        h = StrokeGapHistogram()
        h.record(10)
        h.record(11)
        h.record(12)
        assert h.summarize()["mean_gap_s"] == 11.0

    def test_reset_clears_everything(self):
        h = StrokeGapHistogram()
        h.record(10)
        h.record(3600)
        h.record(80)
        h.reset()
        assert h.total == 0
        assert h.worst == "normal"
        assert h._max_gap == 0.0
        assert h._min_gap is None
        assert all(v == 0 for v in h.counts().values())

    def test_record_after_reset_works(self):
        h = StrokeGapHistogram()
        h.record(10)
        h.reset()
        h.record(80)
        assert h.total == 1
        assert h.counts()["micro_stall"] == 1

    def test_negative_gap_raises(self):
        h = StrokeGapHistogram()
        with pytest.raises(ValueError):
            h.record(-5)

    def test_custom_cadence(self):
        """With 30 s cadence, a 45 s gap should be normal."""
        h = StrokeGapHistogram(cadence_s=30)
        band = h.record(45)
        assert band == "normal"
        assert h.summarize()["cadence_s"] == 30


# ── BAND_ORDER ────────────────────────────────────────────────────────


class TestBandOrder:
    def test_order_is_ascending_severity(self):
        assert BAND_ORDER == ["normal", "stretched", "micro_stall", "stall", "reclaimed"]

    def test_all_bands_covered(self):
        """Every band in the order should be reachable by classify()."""
        test_gaps = [10, 35, 80, 500, 3600]
        bands = [classify(g) for g in test_gaps]
        assert set(bands) == set(BAND_ORDER)
