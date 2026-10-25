"""Tests for iamai/stall_forecaster.py — stall prediction from gap patterns."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.stall_forecaster import (  # noqa: E402
    CV_WARN,
    DEFAULT_WARN_THRESHOLD,
    MIN_SAMPLES,
    PROXIMITY_WARN_RATIO,
    RiskReport,
    TREND_THRESHOLD,
    _clamp,
    _coefficient_of_variation,
    _simple_linear_slope,
    forecast_from_log,
    forecast_stall,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestSimpleLinearSlope:
    """Unit tests for the OLS slope helper."""

    def test_constant_values(self):
        assert _simple_linear_slope([100, 100, 100, 100]) == 0.0

    def test_increasing_values(self):
        slope = _simple_linear_slope([10, 20, 30, 40])
        assert slope == pytest.approx(10.0, abs=0.01)

    def test_decreasing_values(self):
        slope = _simple_linear_slope([40, 30, 20, 10])
        assert slope == pytest.approx(-10.0, abs=0.01)

    def test_single_value(self):
        assert _simple_linear_slope([42.0]) == 0.0

    def test_empty(self):
        assert _simple_linear_slope([]) == 0.0

    def test_two_values(self):
        slope = _simple_linear_slope([10, 20])
        assert slope == pytest.approx(10.0, abs=0.01)


class TestCoefficientOfVariation:
    """Unit tests for the CV helper."""

    def test_constant_values(self):
        assert _coefficient_of_variation([5, 5, 5, 5]) == 0.0

    def test_known_cv(self):
        # mean=10, population stdev=5 → CV=0.5
        values = [5, 15]
        cv = _coefficient_of_variation(values)
        assert cv == pytest.approx(0.5, abs=0.01)

    def test_single_value(self):
        assert _coefficient_of_variation([42.0]) == 0.0

    def test_zero_mean(self):
        assert _coefficient_of_variation([0, 0, 0]) == 0.0

    def test_high_volatility(self):
        cv = _coefficient_of_variation([10, 100, 10, 100])
        assert cv > 0.5


class TestClamp:
    """Unit tests for the clamp helper."""

    def test_within_range(self):
        assert _clamp(0.5) == 0.5

    def test_below_min(self):
        assert _clamp(-1.0) == 0.0

    def test_above_max(self):
        assert _clamp(2.0) == 1.0

    def test_at_boundaries(self):
        assert _clamp(0.0) == 0.0
        assert _clamp(1.0) == 1.0


# ---------------------------------------------------------------------------
# forecast_stall — edge cases
# ---------------------------------------------------------------------------


class TestForecastEdgeCases:
    """Edge cases: empty input, insufficient samples."""

    def test_empty_gaps(self):
        report = forecast_stall([])
        assert report.risk_score == 0.0
        assert report.risk_level == "low"
        assert "no data" in report.reasons
        assert report.sample_size == 0

    def test_single_gap(self):
        report = forecast_stall([600.0])
        assert report.risk_level == "low"
        assert report.sample_size == 1
        assert any("insufficient" in r for r in report.reasons)

    def test_two_gaps_below_min(self):
        report = forecast_stall([600.0, 610.0])
        assert report.risk_level == "low"
        assert report.sample_size == 2

    def test_exactly_min_samples(self):
        report = forecast_stall([600.0, 610.0, 605.0])
        assert report.sample_size == 3
        assert report.risk_level == "low"  # stable gaps, no signals


# ---------------------------------------------------------------------------
# forecast_stall — healthy patterns
# ---------------------------------------------------------------------------


class TestForecastHealthy:
    """Stable, low gaps produce low risk."""

    def test_perfectly_stable(self):
        gaps = [600.0] * 10
        report = forecast_stall(gaps)
        assert report.risk_level == "low"
        assert report.risk_score == 0.0
        assert report.trend_slope == 0.0

    def test_stable_with_noise(self):
        gaps = [595, 600, 605, 598, 602, 601, 599, 603, 597, 600]
        report = forecast_stall(gaps)
        assert report.risk_level == "low"
        assert report.risk_score < 0.2

    def test_short_gaps(self):
        gaps = [15, 14, 16, 15, 15, 14, 16]
        report = forecast_stall(gaps)
        assert report.risk_level == "low"
        assert report.latest_gap == 16


# ---------------------------------------------------------------------------
# forecast_stall — trend signal
# ---------------------------------------------------------------------------


class TestForecastTrend:
    """Upward-trending gaps trigger the trend signal."""

    def test_strong_upward_trend(self):
        # Gaps increasing by ~50s each commit
        gaps = [600, 650, 700, 750, 800, 850, 900, 950]
        report = forecast_stall(gaps)
        assert report.trend_slope > TREND_THRESHOLD
        assert any("upward trend" in r for r in report.reasons)
        assert report.risk_score > 0.0

    def test_mild_trend_below_threshold(self):
        # Gaps increasing by ~10s each — below TREND_THRESHOLD (30)
        gaps = [600, 610, 620, 630, 640, 650, 660]
        report = forecast_stall(gaps)
        assert report.trend_slope < TREND_THRESHOLD
        assert not any("upward trend" in r for r in report.reasons)

    def test_downward_trend_no_flag(self):
        gaps = [1000, 900, 800, 700, 600, 500]
        report = forecast_stall(gaps)
        assert report.trend_slope < 0
        assert not any("upward trend" in r for r in report.reasons)


# ---------------------------------------------------------------------------
# forecast_stall — volatility signal
# ---------------------------------------------------------------------------


class TestForecastVolatility:
    """Erratic gaps trigger the volatility signal."""

    def test_erratic_gaps(self):
        gaps = [100, 900, 50, 1100, 200, 800]
        report = forecast_stall(gaps)
        assert report.cv > CV_WARN
        assert any("erratic" in r for r in report.reasons)

    def test_moderate_variation(self):
        gaps = [550, 600, 650, 580, 620, 610]
        report = forecast_stall(gaps)
        assert report.cv < CV_WARN
        assert not any("erratic" in r for r in report.reasons)


# ---------------------------------------------------------------------------
# forecast_stall — proximity signal
# ---------------------------------------------------------------------------


class TestForecastProximity:
    """Recent gap nearing the warn threshold triggers proximity signal."""

    def test_near_threshold(self):
        # Default warn=1200, proximity floor = 0.6*1200 = 720
        gaps = [600, 600, 600, 600, 600, 900]
        report = forecast_stall(gaps)
        assert report.latest_gap > DEFAULT_WARN_THRESHOLD * PROXIMITY_WARN_RATIO
        assert any("nearing threshold" in r for r in report.reasons)

    def test_well_below_threshold(self):
        gaps = [200, 200, 200, 200, 200]
        report = forecast_stall(gaps)
        assert not any("nearing threshold" in r for r in report.reasons)

    def test_above_threshold(self):
        gaps = [600, 600, 600, 600, 1300]
        report = forecast_stall(gaps)
        assert any("nearing threshold" in r for r in report.reasons)
        assert report.risk_score > 0.0


# ---------------------------------------------------------------------------
# forecast_stall — combined signals and risk levels
# ---------------------------------------------------------------------------


class TestForecastRiskLevels:
    """Risk level boundaries work correctly."""

    def test_high_risk(self):
        # Strong trend + erratic + near threshold
        gaps = [400, 600, 500, 900, 700, 1100]
        report = forecast_stall(gaps)
        assert report.risk_level in ("medium", "high")
        assert report.risk_score > 0.2

    def test_medium_risk(self):
        # Moderate trend, some proximity
        gaps = [600, 650, 700, 750, 800]
        report = forecast_stall(gaps)
        # Should have some trend signal but not extreme
        assert report.risk_score < 0.8

    def test_score_bounded(self):
        # Extreme inputs shouldn't push score above 1.0
        gaps = [100, 500, 200, 1000, 300, 1500]
        report = forecast_stall(gaps)
        assert 0.0 <= report.risk_score <= 1.0

    def test_custom_thresholds(self):
        gaps = [100, 120, 140, 160, 180]
        # With very low trend threshold, this should flag
        report = forecast_stall(gaps, trend_threshold=5.0)
        assert any("upward trend" in r for r in report.reasons)


# ---------------------------------------------------------------------------
# RiskReport methods
# ---------------------------------------------------------------------------


class TestRiskReport:
    """RiskReport output methods."""

    def test_summary_healthy(self):
        report = RiskReport(risk_score=0.0, risk_level="low", reasons=[])
        assert report.summary() == "low risk (0.00): healthy"

    def test_summary_with_reasons(self):
        report = RiskReport(
            risk_score=0.45,
            risk_level="medium",
            reasons=["upward trend (+50.0 s/commit)", "erratic gaps (CV=0.55)"],
        )
        s = report.summary()
        assert "medium risk" in s
        assert "upward trend" in s
        assert "erratic" in s

    def test_as_dict(self):
        report = RiskReport(
            risk_score=0.333,
            risk_level="medium",
            reasons=["test reason"],
            sample_size=10,
            latest_gap=750.5,
            mean_gap=600.2,
            trend_slope=25.0,
            cv=0.35,
        )
        d = report.as_dict()
        assert d["risk_score"] == 0.333
        assert d["risk_level"] == "medium"
        assert d["reasons"] == ["test reason"]
        assert d["sample_size"] == 10
        assert d["latest_gap"] == 750.5
        assert d["mean_gap"] == 600.2
        assert d["trend_slope"] == 25.0
        assert d["cv"] == 0.35


# ---------------------------------------------------------------------------
# forecast_from_log
# ---------------------------------------------------------------------------


class TestForecastFromLog:
    """forecast_from_log reads JSONL and produces valid reports."""

    def test_missing_file(self, tmp_path):
        report = forecast_from_log(str(tmp_path / "nonexistent.jsonl"))
        assert report.risk_level == "low"
        assert "not found" in report.reasons[0]

    def test_empty_file(self, tmp_path):
        log = tmp_path / "strokes.jsonl"
        log.write_text("")
        report = forecast_from_log(str(log))
        assert report.risk_level == "low"

    def test_single_entry(self, tmp_path):
        log = tmp_path / "strokes.jsonl"
        log.write_text(json.dumps({"at": "2026-10-08T12:00:00+00:00"}) + "\n")
        report = forecast_from_log(str(log))
        assert report.risk_level == "low"
        assert "insufficient" in report.reasons[0]

    def test_multiple_entries(self, tmp_path):
        log = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(25):
            ts = f"2026-10-08T12:{i:02d}:00+00:00"
            lines.append(json.dumps({"at": ts}))
        log.write_text("\n".join(lines) + "\n")
        report = forecast_from_log(str(log), last_n=20)
        assert report.sample_size > 0
        assert report.risk_level in ("low", "medium", "high")

    def test_malformed_lines_skipped(self, tmp_path):
        log = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"at": "2026-10-08T12:00:00+00:00"}),
            "not json",
            json.dumps({"at": "2026-10-08T12:01:00+00:00"}),
            json.dumps({"wrong_key": "value"}),
            json.dumps({"at": "2026-10-08T12:02:00+00:00"}),
        ]
        log.write_text("\n".join(lines) + "\n")
        report = forecast_from_log(str(log))
        # Should still work with the 3 valid entries
        assert report.risk_level in ("low", "medium", "high")


# ---------------------------------------------------------------------------
# Parametric edge: custom min_samples
# ---------------------------------------------------------------------------


class TestCustomMinSamples:
    """Custom min_samples changes the cutoff."""

    def test_custom_min_samples(self):
        gaps = [600, 610, 605]
        report = forecast_stall(gaps, min_samples=5)
        assert any("insufficient" in r for r in report.reasons)

    def test_custom_min_samples_met(self):
        gaps = [600, 610, 605, 600, 608]
        report = forecast_stall(gaps, min_samples=5)
        assert report.sample_size == 5
        assert not any("insufficient" in r for r in report.reasons)
