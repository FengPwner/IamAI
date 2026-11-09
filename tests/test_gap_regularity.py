"""Tests for iamai.gap_regularity — 48 test cases."""

import math
import statistics
from datetime import datetime, timezone, timedelta

import pytest

from iamai.gap_regularity import (
    DEFAULT_MAX_EXPECTED,
    _autocorr_lag1,
    _classify,
    _clamp,
    _empty_report,
    _gaps,
    _percentile,
    _to_epoch,
    analyse_gaps,
    brief,
    regularity_summary,
)


# ── _to_epoch ────────────────────────────────────────────────────────────

class TestToEpoch:
    def test_int_passthrough(self):
        assert _to_epoch(1700000000) == 1700000000.0

    def test_float_passthrough(self):
        assert _to_epoch(1700000000.5) == 1700000000.5

    def test_datetime_naive(self):
        dt = datetime(2023, 11, 14, 22, 0, 0)
        result = _to_epoch(dt)
        assert isinstance(result, float)
        assert result > 0

    def test_datetime_aware(self):
        dt = datetime(2023, 11, 14, 22, 0, 0, tzinfo=timezone.utc)
        result = _to_epoch(dt)
        assert abs(result - 1699999200.0) < 1.0

    def test_iso8601_string(self):
        ts = "2023-11-14T22:00:00+00:00"
        result = _to_epoch(ts)
        assert abs(result - 1699999200.0) < 1.0

    def test_iso8601_no_tz(self):
        ts = "2023-11-14T22:00:00"
        result = _to_epoch(ts)
        assert isinstance(result, float)

    def test_iso8601_microseconds(self):
        ts = "2023-11-14T22:00:00.123456+00:00"
        result = _to_epoch(ts)
        assert isinstance(result, float)

    def test_space_separated(self):
        ts = "2023-11-14 22:00:00"
        result = _to_epoch(ts)
        assert isinstance(result, float)

    def test_unsupported_type(self):
        with pytest.raises(TypeError):
            _to_epoch([1, 2, 3])


# ── _gaps ────────────────────────────────────────────────────────────────

class TestGaps:
    def test_normal_gaps(self):
        ts = [100.0, 115.0, 130.0, 145.0]
        assert _gaps(ts) == [15.0, 15.0, 15.0]

    def test_single_timestamp(self):
        assert _gaps([100.0]) == []

    def test_empty(self):
        assert _gaps([]) == []

    def test_negative_gap_dropped(self):
        """Clock-skew or duplicate timestamps should be filtered."""
        ts = [100.0, 90.0, 110.0]
        result = _gaps(ts)
        assert all(g > 0 for g in result)

    def test_zero_gap_dropped(self):
        ts = [100.0, 100.0, 115.0]
        result = _gaps(ts)
        assert 0.0 not in result
        assert len(result) == 1

    def test_irregular_spacing(self):
        ts = [0.0, 10.0, 15.0, 100.0]
        assert _gaps(ts) == [10.0, 5.0, 85.0]


# ── _autocorr_lag1 ──────────────────────────────────────────────────────

class TestAutocorrLag1:
    def test_constant_series(self):
        """Constant series → variance=0 → autocorr=0."""
        assert _autocorr_lag1([5.0, 5.0, 5.0, 5.0]) == 0.0

    def test_too_short(self):
        assert _autocorr_lag1([1.0, 2.0]) == 0.0

    def test_empty(self):
        assert _autocorr_lag1([]) == 0.0

    def test_positive_autocorrelation(self):
        """Trending series should have positive autocorrelation."""
        series = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        result = _autocorr_lag1(series)
        assert result > 0.0

    def test_negative_autocorrelation(self):
        """Alternating series should have negative autocorrelation."""
        series = [1.0, 10.0, 1.0, 10.0, 1.0, 10.0, 1.0, 10.0]
        result = _autocorr_lag1(series)
        assert result < 0.0


# ── _percentile ──────────────────────────────────────────────────────────

class TestPercentile:
    def test_p50_is_median(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _percentile(vals, 50) == 3.0

    def test_p0_is_min(self):
        vals = [3.0, 1.0, 5.0]
        assert _percentile(vals, 0) == 1.0

    def test_p100_is_max(self):
        vals = [3.0, 1.0, 5.0]
        assert _percentile(vals, 100) == 5.0

    def test_empty_returns_zero(self):
        assert _percentile([], 50) == 0.0

    def test_interpolation(self):
        vals = [10.0, 20.0, 30.0, 40.0]
        result = _percentile(vals, 75)
        assert 30.0 <= result <= 40.0


# ── _clamp ───────────────────────────────────────────────────────────────

class TestClamp:
    def test_within_range(self):
        assert _clamp(0.5) == 0.5

    def test_below_zero(self):
        assert _clamp(-1.0) == 0.0

    def test_above_one(self):
        assert _clamp(2.5) == 1.0

    def test_custom_range(self):
        assert _clamp(5.0, 0.0, 10.0) == 5.0

    def test_exact_boundary(self):
        assert _clamp(0.0) == 0.0
        assert _clamp(1.0) == 1.0


# ── _classify ────────────────────────────────────────────────────────────

class TestClassify:
    def test_stalled_high_median(self):
        result = _classify(0.9, 0.1, 0.0, 0.1, 1500.0, 1300.0)
        assert result == "stalled"

    def test_stalled_burst_pattern(self):
        result = _classify(0.4, 1.5, 0.8, 0.6, 300.0, 100.0)
        assert result == "stalled"

    def test_clockwork(self):
        result = _classify(0.85, 0.1, 0.05, 0.05, 15.0, 15.0)
        assert result == "clockwork"

    def test_steady(self):
        result = _classify(0.65, 0.4, 0.2, 0.2, 20.0, 18.0)
        assert result == "steady"

    def test_organic(self):
        result = _classify(0.45, 0.7, 0.4, 0.3, 30.0, 25.0)
        assert result == "organic"

    def test_erratic(self):
        result = _classify(0.2, 1.5, 0.7, 0.4, 200.0, 100.0)
        assert result == "erratic"

    def test_boundary_clockwork(self):
        result = _classify(0.80, 0.2, 0.1, 0.1, 15.0, 15.0)
        assert result == "clockwork"

    def test_boundary_steady(self):
        result = _classify(0.60, 0.5, 0.2, 0.3, 20.0, 18.0)
        assert result == "steady"


# ── _empty_report ────────────────────────────────────────────────────────

class TestEmptyReport:
    def test_zero_samples(self):
        report = _empty_report(0)
        assert report["count"] == 0
        assert report["verdict"] == "insufficient"

    def test_one_sample(self):
        report = _empty_report(1)
        assert report["count"] == 0

    def test_all_fields_present(self):
        report = _empty_report(5)
        expected_keys = {
            "count", "mean_gap", "median_gap", "std_gap", "cv",
            "p95_gap", "autocorr_lag1", "burst_ratio",
            "regularity_score", "verdict",
        }
        assert set(report.keys()) == expected_keys


# ── analyse_gaps ─────────────────────────────────────────────────────────

class TestAnalyseGaps:
    def _make_timestamps(self, n: int, interval: float = 15.0, start: float = 1700000000.0):
        """Generate n evenly spaced timestamps."""
        return [start + i * interval for i in range(n)]

    def test_perfect_clockwork(self):
        ts = self._make_timestamps(50, interval=15.0)
        report = analyse_gaps(ts)
        assert report["verdict"] == "clockwork"
        assert report["cv"] < 0.05
        assert report["regularity_score"] >= 0.80

    def test_too_few_timestamps(self):
        report = analyse_gaps([1700000000.0])
        assert report["verdict"] == "insufficient"

    def test_empty_input(self):
        report = analyse_gaps([])
        assert report["verdict"] == "insufficient"
        assert report["count"] == 0

    def test_string_timestamps(self):
        ts = [
            "2023-11-14T22:00:00+00:00",
            "2023-11-14T22:00:15+00:00",
            "2023-11-14T22:00:30+00:00",
            "2023-11-14T22:00:45+00:00",
            "2023-11-14T22:01:00+00:00",
        ]
        report = analyse_gaps(ts)
        assert report["count"] == 4
        assert report["median_gap"] == 15.0

    def test_erratic_with_stalls(self):
        """Timestamps with occasional huge gaps should score poorly."""
        base = self._make_timestamps(40, interval=15.0)
        # Insert 5 stalls (20-minute gaps)
        stalled = base + [base[-1] + 1200 * i + 15 for i in range(1, 6)]
        stalled.sort()
        report = analyse_gaps(stalled)
        assert report["regularity_score"] < 0.60
        assert report["p95_gap"] > 500

    def test_report_keys(self):
        ts = self._make_timestamps(20)
        report = analyse_gaps(ts)
        expected_keys = {
            "count", "mean_gap", "median_gap", "std_gap", "cv",
            "p95_gap", "autocorr_lag1", "burst_ratio",
            "regularity_score", "verdict",
        }
        assert set(report.keys()) == expected_keys

    def test_count_is_n_minus_one(self):
        ts = self._make_timestamps(100)
        report = analyse_gaps(ts)
        assert report["count"] == 99

    def test_custom_max_expected(self):
        """Lower max_expected makes the p95 penalty harsher."""
        ts = self._make_timestamps(30, interval=15.0)
        # Add a few 5-minute gaps
        ts_with_gaps = ts + [ts[-1] + 300, ts[-1] + 600]
        ts_with_gaps.sort()
        strict = analyse_gaps(ts_with_gaps, max_expected=60)
        lenient = analyse_gaps(ts_with_gaps, max_expected=600)
        assert strict["regularity_score"] <= lenient["regularity_score"]

    def test_unsorted_input_handled(self):
        """Out-of-order timestamps should be sorted internally."""
        ts = [100.0, 130.0, 115.0, 145.0, 160.0]
        report = analyse_gaps(ts)
        assert report["count"] >= 3


# ── regularity_summary ──────────────────────────────────────────────────

class TestRegularitySummary:
    def _make_timestamps(self, n: int, interval: float = 15.0, start: float = 1700000000.0):
        return [start + i * interval for i in range(n)]

    def test_stable_trend(self):
        """Perfectly regular timestamps → stable or improving."""
        ts = self._make_timestamps(300, interval=15.0)
        summary = regularity_summary(ts, windows=[50, 200])
        assert summary["trend"] in ("stable", "improving")
        assert 50 in summary["windows"]
        assert 200 in summary["windows"]

    def test_degrading_trend(self):
        """Start regular, end erratic → degrading."""
        # 800 good strokes at 15s cadence
        good = self._make_timestamps(800, interval=15.0)
        # 80 erratic strokes with massive variable gaps
        bad = [good[-1] + 200]
        import random as _rng
        _rng.seed(7)
        for _ in range(79):
            gap = _rng.choice([5.0, 15.0, 800.0, 1500.0, 15.0, 2000.0])
            bad.append(bad[-1] + gap)
        ts = good + bad
        summary = regularity_summary(ts, windows=[50, 500])
        # The recent (50) window is all bad; the older (500) is mostly good
        assert summary["trend"] == "degrading"

    def test_default_windows(self):
        ts = self._make_timestamps(300)
        summary = regularity_summary(ts)
        assert 50 in summary["windows"]
        assert 200 in summary["windows"]

    def test_single_window(self):
        ts = self._make_timestamps(100)
        summary = regularity_summary(ts, windows=[50])
        assert summary["trend"] == "insufficient"

    def test_small_input(self):
        ts = self._make_timestamps(30)
        summary = regularity_summary(ts, windows=[50, 200])
        # Both windows get the same 30 timestamps
        assert 50 in summary["windows"]


# ── brief ────────────────────────────────────────────────────────────────

class TestBrief:
    def test_output_format(self):
        report = {
            "regularity_score": 0.8234,
            "verdict": "clockwork",
            "count": 99,
            "median_gap": 15.0,
        }
        result = brief(report)
        assert "regularity=0.82" in result
        assert "clockwork" in result
        assert "99" in result
        assert "15s" in result

    def test_zero_report(self):
        report = _empty_report(0)
        result = brief(report)
        assert "insufficient" in result


# ── Integration: realistic scenarios ─────────────────────────────────────

class TestRealisticScenarios:
    def test_healthy_writer_67_strokes(self):
        """Simulate ~16 minutes of writing at 15s cadence."""
        import random
        random.seed(42)
        ts = [1700000000.0]
        for _ in range(66):
            gap = 15.0 + random.gauss(0, 1.5)  # small jitter
            ts.append(ts[-1] + max(gap, 1.0))
        report = analyse_gaps(ts)
        assert report["verdict"] in ("clockwork", "steady")
        assert report["regularity_score"] >= 0.60

    def test_writer_with_one_restart_gap(self):
        """Simulate a writer that ran fine, stalled for 30min, then resumed."""
        ts = [1700000000.0 + i * 15.0 for i in range(40)]
        # 30-minute stall
        stall_end = ts[-1] + 1800.0
        ts.extend(stall_end + i * 15.0 for i in range(1, 21))
        report = analyse_gaps(ts)
        assert report["burst_ratio"] > 0
        # The stall gap (1800s) should be detectable as an outlier
        assert report["mean_gap"] > 30.0  # well above 15s cadence
        assert report["std_gap"] > 100.0  # huge variance from the stall

    def test_datetime_objects_input(self):
        """Accept datetime objects directly."""
        base = datetime(2023, 11, 14, 22, 0, 0, tzinfo=timezone.utc)
        ts = [base + timedelta(seconds=15 * i) for i in range(20)]
        report = analyse_gaps(ts)
        assert report["count"] == 19
        assert abs(report["median_gap"] - 15.0) < 0.1

    def test_mixed_format_strings(self):
        """All ISO variants should parse correctly."""
        ts = [
            "2023-11-14T22:00:00+00:00",
            "2023-11-14T22:00:15+00:00",
            "2023-11-14T22:00:30+00:00",
            "2023-11-14T22:00:45+00:00",
        ]
        report = analyse_gaps(ts)
        assert report["mean_gap"] == 15.0
