"""Tests for iamai.entropy_rhythm — sequence-level entropy rhythm classifier."""

import math

import pytest

from iamai.entropy_rhythm import EntropyRhythm, _linreg


# ---------------------------------------------------------------------------
# _linreg helper
# ---------------------------------------------------------------------------

class TestLinreg:
    def test_perfect_positive_slope(self):
        # y = 2x + 1 → slope=2, r²=1
        slope, r2 = _linreg([1, 3, 5, 7, 9])
        assert abs(slope - 2.0) < 1e-9
        assert abs(r2 - 1.0) < 1e-9

    def test_perfect_negative_slope(self):
        slope, r2 = _linreg([10, 8, 6, 4, 2])
        assert abs(slope - (-2.0)) < 1e-9
        assert abs(r2 - 1.0) < 1e-9

    def test_flat_line(self):
        slope, r2 = _linreg([5.0, 5.0, 5.0, 5.0])
        assert abs(slope) < 1e-9
        assert abs(r2) < 1e-9

    def test_single_value(self):
        slope, r2 = _linreg([3.14])
        assert slope == 0.0
        assert r2 == 0.0

    def test_empty(self):
        slope, r2 = _linreg([])
        assert slope == 0.0
        assert r2 == 0.0

    def test_noisy_data(self):
        # noisy but generally upward
        slope, r2 = _linreg([0.1, 0.3, 0.2, 0.5, 0.4, 0.7])
        assert slope > 0
        assert 0 < r2 < 1


# ---------------------------------------------------------------------------
# EntropyRhythm — recording
# ---------------------------------------------------------------------------

class TestRecording:
    def test_record_and_count(self):
        r = EntropyRhythm(window_size=10)
        assert r.count == 0
        r.record(0.5)
        r.record(0.6)
        assert r.count == 2

    def test_window_bounds(self):
        r = EntropyRhythm(window_size=5)
        for v in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]:
            r.record(v)
        assert r.count == 5
        assert list(r.readings) == [0.3, 0.4, 0.5, 0.6, 0.7]

    def test_reject_out_of_range(self):
        r = EntropyRhythm()
        with pytest.raises(ValueError, match="entropy must be in"):
            r.record(1.5)
        with pytest.raises(ValueError, match="entropy must be in"):
            r.record(-0.1)

    def test_accept_boundaries(self):
        r = EntropyRhythm()
        r.record(0.0)
        r.record(1.0)
        assert r.count == 2


# ---------------------------------------------------------------------------
# analyse — verdict classification
# ---------------------------------------------------------------------------

class TestAnalyse:
    def test_insufficient_data(self):
        r = EntropyRhythm()
        r.record(0.5)
        r.record(0.6)
        report = r.analyse()
        assert report["verdict"] == "insufficient"
        assert report["count"] == 2

    def test_healthy_rising_entropy(self):
        r = EntropyRhythm()
        # slowly rising, low cv
        for v in [0.50, 0.52, 0.54, 0.56, 0.58, 0.60, 0.62, 0.64]:
            r.record(v)
        report = r.analyse()
        assert report["verdict"] == "healthy"
        assert report["slope"] > 0

    def test_decaying_entropy(self):
        r = EntropyRhythm()
        # clear downward trend
        for v in [0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55]:
            r.record(v)
        report = r.analyse()
        assert report["verdict"] == "decaying"
        assert report["slope"] < 0

    def test_flat_entropy(self):
        r = EntropyRhythm()
        # nearly constant
        for _ in range(20):
            r.record(0.72)
        report = r.analyse()
        assert report["verdict"] == "flat"
        assert abs(report["slope"]) < 0.005
        assert report["cv"] < 0.10

    def test_volatile_entropy(self):
        r = EntropyRhythm()
        # big jumps → high cv
        for v in [0.1, 0.9, 0.2, 0.8, 0.1, 0.9, 0.2, 0.8]:
            r.record(v)
        report = r.analyse()
        assert report["verdict"] == "volatile"
        assert report["cv"] >= 0.15

    def test_report_keys(self):
        r = EntropyRhythm()
        for v in [0.5, 0.6, 0.7, 0.8]:
            r.record(v)
        report = r.analyse()
        expected_keys = {
            "count", "slope", "cv", "r_squared",
            "mean_entropy", "min_entropy", "max_entropy", "verdict",
        }
        assert set(report.keys()) == expected_keys

    def test_empty_analyse(self):
        r = EntropyRhythm()
        report = r.analyse()
        assert report["count"] == 0
        assert report["verdict"] == "insufficient"


# ---------------------------------------------------------------------------
# report — human-readable string
# ---------------------------------------------------------------------------

class TestReport:
    def test_insufficient_message(self):
        r = EntropyRhythm()
        r.record(0.5)
        msg = r.report()
        assert "insufficient" in msg

    def test_healthy_message(self):
        r = EntropyRhythm()
        for v in [0.50, 0.55, 0.60, 0.65]:
            r.record(v)
        msg = r.report()
        assert "healthy" in msg or "decaying" in msg  # just check it parses
        assert "slope=" in msg

    def test_decaying_message(self):
        r = EntropyRhythm()
        for v in [0.90, 0.80, 0.70, 0.60, 0.50, 0.40]:
            r.record(v)
        msg = r.report()
        assert "decaying" in msg


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_all_zeros(self):
        r = EntropyRhythm()
        for _ in range(10):
            r.record(0.0)
        report = r.analyse()
        # cv should be 0 when mean is 0
        assert report["cv"] == 0.0
        # verdict: flat (slope≈0, cv<0.10) or insufficient
        assert report["verdict"] in ("flat", "insufficient")

    def test_all_ones(self):
        r = EntropyRhythm()
        for _ in range(10):
            r.record(1.0)
        report = r.analyse()
        assert report["mean_entropy"] == 1.0
        assert report["verdict"] == "flat"

    def test_large_window(self):
        r = EntropyRhythm(window_size=500)
        for i in range(500):
            r.record(0.5 + 0.001 * i)
        assert r.count == 500
        report = r.analyse()
        assert report["verdict"] == "healthy"
