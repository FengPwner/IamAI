"""Tests for iamai.pool_saturation — detecting when the snippet pool is fully deployed."""

import pytest

from iamai.pool_saturation import (
    _is_exhausted,
    _SATURATION_MARKER,
    measure,
    saturation_report,
)


# ---------------------------------------------------------------------------
# _is_exhausted
# ---------------------------------------------------------------------------

class TestIsExhausted:
    def test_matches_exact_marker(self):
        assert _is_exhausted("stroke 20651: `parse_kv.py` is already in the pool of 9 modules, nothing new to add there")

    def test_matches_marker_in_longer_text(self):
        assert _is_exhausted("blah blah nothing new to add there blah")

    def test_rejects_normal_stroke(self):
        assert not _is_exhausted("stroke 400: 872 python files, 15000 logged thoughts")

    def test_rejects_empty_string(self):
        assert not _is_exhausted("")

    def test_rejects_partial_marker(self):
        assert not _is_exhausted("nothing new to add")  # missing "there"

    def test_case_sensitive(self):
        # The writer always emits lowercase; uppercase should not match.
        assert not _is_exhausted("Nothing New To Add There")


# ---------------------------------------------------------------------------
# measure — basic
# ---------------------------------------------------------------------------

class TestMeasureBasic:
    def test_empty_list(self):
        result = measure([])
        assert result["window"] == 0
        assert result["exhausted"] == 0
        assert result["fraction"] == 0.0
        assert result["verdict"] == "fresh"

    def test_all_normal(self):
        strokes = ["stroke 1: normal work"] * 60
        result = measure(strokes)
        assert result["window"] == 60
        assert result["exhausted"] == 0
        assert result["fraction"] == 0.0
        assert result["verdict"] == "fresh"

    def test_all_exhausted(self):
        strokes = [
            f"stroke {i}: `mod.py` is already in the pool of 9 modules, nothing new to add there"
            for i in range(60)
        ]
        result = measure(strokes)
        assert result["window"] == 60
        assert result["exhausted"] == 60
        assert result["fraction"] == 1.0
        assert result["verdict"] == "saturated"

    def test_window_truncation(self):
        """Only the last `window` strokes should be examined."""
        old = ["nothing new to add there"] * 100
        recent = ["normal work"] * 20
        strokes = old + recent
        result = measure(strokes, window=20)
        assert result["window"] == 20
        assert result["exhausted"] == 0
        assert result["verdict"] == "fresh"

    def test_small_window(self):
        strokes = ["nothing new to add there", "normal", "normal"]
        result = measure(strokes, window=3)
        assert result["window"] == 3
        assert result["exhausted"] == 1
        assert abs(result["fraction"] - 1 / 3) < 0.01


# ---------------------------------------------------------------------------
# measure — verdict thresholds
# ---------------------------------------------------------------------------

class TestMeasureVerdicts:
    def test_fresh_below_10_percent(self):
        # 5 exhausted out of 60 = 8.3% → fresh
        strokes = ["nothing new to add there"] * 5 + ["normal"] * 55
        result = measure(strokes)
        assert result["verdict"] == "fresh"

    def test_warming_between_10_and_25(self):
        # 9 exhausted out of 60 = 15% → warming
        strokes = ["nothing new to add there"] * 9 + ["normal"] * 51
        result = measure(strokes)
        assert result["verdict"] == "warming"

    def test_saturated_above_25(self):
        # 16 exhausted out of 60 = 26.7% → saturated
        strokes = ["nothing new to add there"] * 16 + ["normal"] * 44
        result = measure(strokes)
        assert result["verdict"] == "saturated"

    def test_boundary_exactly_10_percent(self):
        # 6 out of 60 = 10% → warming (>= 0.10)
        strokes = ["nothing new to add there"] * 6 + ["normal"] * 54
        result = measure(strokes)
        assert result["verdict"] == "warming"

    def test_boundary_exactly_25_percent(self):
        # 15 out of 60 = 25% → saturated (>= 0.25)
        strokes = ["nothing new to add there"] * 15 + ["normal"] * 45
        result = measure(strokes)
        assert result["verdict"] == "saturated"


# ---------------------------------------------------------------------------
# measure — realistic patterns
# ---------------------------------------------------------------------------

class TestMeasureRealistic:
    def test_mixed_rotation(self):
        """Simulate 6-kind rotation where every 6th stroke is exhausted."""
        strokes = []
        for i in range(60):
            if i % 6 == 0:
                strokes.append(f"stroke {i}: `mod.py` is already in the pool of 9 modules, nothing new to add there")
            else:
                strokes.append(f"stroke {i}: normal content about the repo")
        result = measure(strokes)
        assert result["exhausted"] == 10
        assert abs(result["fraction"] - 1 / 6) < 0.01
        # 1/6 ≈ 16.7% → warming
        assert result["verdict"] == "warming"

    def test_fully_saturated_rotation(self):
        """All snippet-kind strokes hit already-deployed files (2 of 6 kinds exhausted)."""
        strokes = []
        for i in range(60):
            if i % 6 in (0, 3):  # 2 of 6 kinds
                strokes.append("nothing new to add there")
            else:
                strokes.append("normal stroke")
        result = measure(strokes)
        assert result["exhausted"] == 20
        assert abs(result["fraction"] - 1 / 3) < 0.01
        assert result["verdict"] == "saturated"


# ---------------------------------------------------------------------------
# saturation_report
# ---------------------------------------------------------------------------

class TestSaturationReport:
    def test_fresh_report(self):
        strokes = ["stroke 1: normal work"] * 60
        report = saturation_report(strokes)
        assert "fresh" in report
        assert "0/60" in report
        assert "0.0%" in report

    def test_saturated_report(self):
        strokes = ["nothing new to add there"] * 30 + ["normal"] * 30
        report = saturation_report(strokes)
        assert "saturated" in report
        assert "30/60" in report
        assert "50.0%" in report

    def test_empty_report(self):
        report = saturation_report([])
        assert "fresh" in report
        assert "0/0" in report


# ---------------------------------------------------------------------------
# fraction rounding
# ---------------------------------------------------------------------------

class TestFractionRounding:
    def test_fraction_rounded_to_4_decimals(self):
        strokes = ["nothing new to add there"] * 1 + ["normal"] * 2
        result = measure(strokes, window=3)
        # 1/3 = 0.3333... → 0.3333
        assert result["fraction"] == 0.3333

    def test_fraction_exact_zero(self):
        strokes = ["normal"] * 10
        result = measure(strokes)
        assert result["fraction"] == 0.0
