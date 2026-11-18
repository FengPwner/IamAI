#!/usr/bin/env python3
"""Tests for stroke_cadence_drift.py — cadence tracking quality analysis."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_cadence_drift import (
    CadenceDriftReport,
    _compute_gaps,
    _extract_timestamps,
    _parse_ts,
    analyze,
    classify_stability,
    classify_trend,
    compute_rolling_means,
    max_consecutive_run,
    ols_slope,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 11, 19, 2, 0, 0, tzinfo=timezone.utc)


def _ts(offset_seconds: float) -> str:
    """Return an ISO-8601 timestamp offset from a fixed base."""
    dt = _BASE + timedelta(seconds=offset_seconds)
    return dt.isoformat()


def _dt(offset_seconds: float) -> datetime:
    return _BASE + timedelta(seconds=offset_seconds)


def _make_strokes(offsets: list, kind: str = "thought") -> list:
    """Build a list of stroke dicts from second-offsets."""
    return [
        {"seq": i, "at": _ts(s), "kind": kind, "text": f"stroke {i}"}
        for i, s in enumerate(offsets)
    ]


def _uniform_offsets(n: int, gap: float = 15.0) -> list:
    """Generate *n* uniformly spaced offsets."""
    return [i * gap for i in range(n)]


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTs:
    def test_iso_with_offset(self):
        dt = _parse_ts("2026-11-19T02:00:00+00:00")
        assert dt.year == 2026
        assert dt.month == 11

    def test_iso_with_z(self):
        dt = _parse_ts("2026-11-19T02:00:00Z")
        assert dt.tzinfo is not None

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_ts("not-a-date")


# ---------------------------------------------------------------------------
# _extract_timestamps / _compute_gaps
# ---------------------------------------------------------------------------

class TestExtractAndGaps:
    def test_extract_sorted(self):
        strokes = _make_strokes([30, 0, 15])
        ts = _extract_timestamps(strokes)
        assert len(ts) == 3
        assert ts[0] < ts[1] < ts[2]

    def test_gaps_uniform(self):
        ts = [_dt(s) for s in [0, 15, 30, 45]]
        gaps = _compute_gaps(ts)
        assert gaps == [15.0, 15.0, 15.0]

    def test_gaps_empty(self):
        assert _compute_gaps([]) == []
        assert _compute_gaps([_dt(0)]) == []

    def test_gaps_variable(self):
        ts = [_dt(s) for s in [0, 10, 30, 35]]
        gaps = _compute_gaps(ts)
        assert gaps == [10.0, 20.0, 5.0]


# ---------------------------------------------------------------------------
# compute_rolling_means
# ---------------------------------------------------------------------------

class TestRollingMeans:
    def test_basic(self):
        gaps = [10, 20, 30, 40, 50]
        means = compute_rolling_means(gaps, window=3)
        # windows: [10,20,30]=20, [20,30,40]=30, [30,40,50]=40
        assert len(means) == 3
        assert means[0] == pytest.approx(20.0)
        assert means[1] == pytest.approx(30.0)
        assert means[2] == pytest.approx(40.0)

    def test_window_larger_than_data(self):
        gaps = [10, 20, 30]
        means = compute_rolling_means(gaps, window=10)
        assert len(means) == 1
        assert means[0] == pytest.approx(20.0)

    def test_empty_gaps(self):
        assert compute_rolling_means([], window=5) == []

    def test_zero_window(self):
        assert compute_rolling_means([1, 2, 3], window=0) == []

    def test_window_equals_length(self):
        gaps = [10, 20, 30, 40]
        means = compute_rolling_means(gaps, window=4)
        assert len(means) == 1
        assert means[0] == pytest.approx(25.0)

    def test_single_gap_window(self):
        gaps = [15, 15, 15]
        means = compute_rolling_means(gaps, window=1)
        assert means == [15.0, 15.0, 15.0]


# ---------------------------------------------------------------------------
# ols_slope
# ---------------------------------------------------------------------------

class TestOlsSlope:
    def test_flat_series(self):
        assert ols_slope([5.0, 5.0, 5.0, 5.0]) == pytest.approx(0.0)

    def test_positive_slope(self):
        # y = 2x + 1 → slope = 2
        values = [1.0, 3.0, 5.0, 7.0, 9.0]
        assert ols_slope(values) == pytest.approx(2.0)

    def test_negative_slope(self):
        values = [10.0, 8.0, 6.0, 4.0, 2.0]
        assert ols_slope(values) == pytest.approx(-2.0)

    def test_single_value(self):
        assert ols_slope([42.0]) == 0.0

    def test_empty(self):
        assert ols_slope([]) == 0.0

    def test_two_values(self):
        assert ols_slope([3.0, 7.0]) == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# classify_trend
# ---------------------------------------------------------------------------

class TestClassifyTrend:
    def test_stable_low_cv(self):
        assert classify_trend(0.05, 0.1) == "stable"

    def test_stable_zero_slope(self):
        assert classify_trend(0.0, 0.2) == "stable"

    def test_accelerating(self):
        assert classify_trend(-0.5, 0.1) == "accelerating"

    def test_decelerating(self):
        assert classify_trend(0.5, 0.1) == "decelerating"

    def test_oscillating(self):
        # Small slope but high CV → oscillating
        assert classify_trend(0.05, 0.5) == "oscillating"

    def test_boundary_slope_negative(self):
        assert classify_trend(-0.1, 0.1) == "accelerating"

    def test_boundary_slope_positive(self):
        assert classify_trend(0.1, 0.1) == "decelerating"

    def test_boundary_slope_zero_high_cv(self):
        assert classify_trend(0.0, 0.31) == "oscillating"


# ---------------------------------------------------------------------------
# classify_stability
# ---------------------------------------------------------------------------

class TestClassifyStability:
    def test_tight(self):
        assert classify_stability(0.05) == "tight"

    def test_loose(self):
        assert classify_stability(0.15) == "loose"

    def test_drifty(self):
        assert classify_stability(0.4) == "drifty"

    def test_erratic(self):
        assert classify_stability(0.7) == "erratic"

    def test_boundary_tight(self):
        assert classify_stability(0.0) == "tight"

    def test_boundary_loose(self):
        assert classify_stability(0.1) == "loose"

    def test_boundary_drifty(self):
        assert classify_stability(0.3) == "drifty"

    def test_boundary_erratic(self):
        assert classify_stability(0.6) == "erratic"


# ---------------------------------------------------------------------------
# max_consecutive_run
# ---------------------------------------------------------------------------

class TestMaxConsecutiveRun:
    def test_all_above(self):
        above, below = max_consecutive_run([20, 20, 20, 20], 15.0)
        assert above == 4
        assert below == 0

    def test_all_below(self):
        above, below = max_consecutive_run([10, 10, 10], 15.0)
        assert above == 0
        assert below == 3

    def test_alternating(self):
        above, below = max_consecutive_run([20, 10, 20, 10], 15.0)
        assert above == 1
        assert below == 1

    def test_mixed_run(self):
        above, below = max_consecutive_run([20, 20, 10, 10, 10, 20], 15.0)
        assert above == 2
        assert below == 3

    def test_exact_target_breaks(self):
        above, below = max_consecutive_run([20, 20, 15.0, 20, 20], 15.0)
        assert above == 2  # run broken by exact target

    def test_empty(self):
        above, below = max_consecutive_run([], 15.0)
        assert above == 0
        assert below == 0

    def test_single_above(self):
        above, below = max_consecutive_run([20], 15.0)
        assert above == 1
        assert below == 0


# ---------------------------------------------------------------------------
# analyze — integration
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_empty_strokes(self):
        report = analyze([])
        assert isinstance(report, CadenceDriftReport)
        assert report.total_gaps == 0
        assert report.mean_gap == 0.0

    def test_single_stroke(self):
        strokes = _make_strokes([0])
        report = analyze(strokes)
        assert report.total_gaps == 0

    def test_perfect_cadence(self):
        """Strokes exactly at 15 s intervals should show zero drift."""
        offsets = _uniform_offsets(50, gap=15.0)
        strokes = _make_strokes(offsets)
        report = analyze(strokes, target_cadence=15.0, window=10)

        assert report.total_gaps == 49
        assert report.mean_gap == pytest.approx(15.0)
        assert report.absolute_drift == pytest.approx(0.0, abs=1e-9)
        assert report.relative_drift == pytest.approx(0.0, abs=1e-9)
        assert report.drift_slope == pytest.approx(0.0, abs=1e-9)
        assert report.drift_trend == "stable"
        assert report.stability_cv == pytest.approx(0.0, abs=1e-9)
        assert report.stability_grade == "tight"

    def test_slow_writer(self):
        """Writer running at 20 s instead of 15 s shows positive drift."""
        offsets = _uniform_offsets(50, gap=20.0)
        strokes = _make_strokes(offsets)
        report = analyze(strokes, target_cadence=15.0, window=10)

        assert report.mean_gap == pytest.approx(20.0)
        assert report.absolute_drift == pytest.approx(5.0)
        assert report.relative_drift == pytest.approx(5.0 / 15.0)
        assert report.windows_above_target > 0
        assert report.windows_below_target == 0

    def test_fast_writer(self):
        """Writer running at 10 s shows negative drift."""
        offsets = _uniform_offsets(50, gap=10.0)
        strokes = _make_strokes(offsets)
        report = analyze(strokes, target_cadence=15.0, window=10)

        assert report.mean_gap == pytest.approx(10.0)
        assert report.absolute_drift == pytest.approx(-5.0)
        assert report.relative_drift == pytest.approx(-5.0 / 15.0)
        assert report.windows_below_target > 0
        assert report.windows_above_target == 0

    def test_decelerating_writer(self):
        """Writer gradually slowing from 10 s to 30 s."""
        n = 60
        offsets = []
        t = 0
        for i in range(n):
            offsets.append(t)
            gap = 10 + (i * 20 / n)  # 10 → 30
            t += gap
        strokes = _make_strokes(offsets)
        report = analyze(strokes, target_cadence=15.0, window=10)

        assert report.drift_slope > 0
        assert report.drift_trend == "decelerating"

    def test_accelerating_writer(self):
        """Writer gradually speeding up from 30 s to 5 s."""
        n = 60
        offsets = []
        t = 0
        for i in range(n):
            offsets.append(t)
            gap = 30 - (i * 25 / n)  # 30 → 5
            t += gap
        strokes = _make_strokes(offsets)
        report = analyze(strokes, target_cadence=15.0, window=10)

        assert report.drift_slope < 0
        assert report.drift_trend == "accelerating"

    def test_custom_target_cadence(self):
        offsets = _uniform_offsets(40, gap=30.0)
        strokes = _make_strokes(offsets)
        report = analyze(strokes, target_cadence=30.0, window=10)

        assert report.mean_gap == pytest.approx(30.0)
        assert report.absolute_drift == pytest.approx(0.0, abs=1e-9)

    def test_custom_window(self):
        offsets = _uniform_offsets(50, gap=15.0)
        strokes = _make_strokes(offsets)
        report = analyze(strokes, window=5)
        assert report.window_size == 5
        assert len(report.rolling_means) == 49 - 5 + 1

    def test_window_equals_gap_count(self):
        offsets = _uniform_offsets(11, gap=15.0)  # 10 gaps
        strokes = _make_strokes(offsets)
        report = analyze(strokes, window=10)
        assert len(report.rolling_means) == 1

    def test_few_strokes_small_window(self):
        offsets = [0, 15, 30]
        strokes = _make_strokes(offsets)
        report = analyze(strokes, window=2)
        assert report.total_gaps == 2
        assert len(report.rolling_means) == 1
        assert report.rolling_means[0] == pytest.approx(15.0)

    def test_report_fields_populated(self):
        offsets = _uniform_offsets(50, gap=15.0)
        strokes = _make_strokes(offsets)
        report = analyze(strokes, target_cadence=15.0, window=10)

        assert isinstance(report, CadenceDriftReport)
        assert report.target_cadence == 15.0
        assert report.total_gaps == 49
        assert isinstance(report.drift_trend, str)
        assert isinstance(report.stability_grade, str)
        assert report.drift_trend in ("stable", "accelerating", "decelerating", "oscillating")
        assert report.stability_grade in ("tight", "loose", "drifty", "erratic")

    def test_noisy_strokes(self):
        """Irregular gaps should produce loose/drifty stability."""
        import random
        random.seed(42)
        offsets = [0]
        for _ in range(80):
            offsets.append(offsets[-1] + random.uniform(5, 25))
        strokes = _make_strokes(offsets)
        report = analyze(strokes, target_cadence=15.0, window=10)

        assert report.stability_cv > 0.05
        assert report.stability_grade in ("loose", "drifty", "erratic")

    def test_oscillating_pattern(self):
        """Alternating fast/slow blocks produce oscillating trend."""
        offsets = [0]
        # 10 fast gaps (5s), then 10 slow gaps (25s), repeated
        pattern = [5.0] * 10 + [25.0] * 10
        for g in pattern * 3:
            offsets.append(offsets[-1] + g)
        strokes = _make_strokes(offsets)
        report = analyze(strokes, target_cadence=15.0, window=10)

        # Mean gap should be ~15 s overall, so drift is near zero
        assert report.mean_gap == pytest.approx(15.0, abs=2.0)
        # But rolling means will oscillate → high CV
        assert report.stability_cv > 0.1

    def test_unsorted_timestamps(self):
        """Analyzer should sort timestamps internally."""
        strokes = [
            {"seq": 2, "at": _ts(30), "kind": "thought", "text": "c"},
            {"seq": 0, "at": _ts(0), "kind": "thought", "text": "a"},
            {"seq": 1, "at": _ts(15), "kind": "thought", "text": "b"},
        ]
        report = analyze(strokes, target_cadence=15.0, window=2)
        assert report.mean_gap == pytest.approx(15.0)

    def test_consecutive_above_and_below(self):
        offsets = [0]
        # 15 gaps at 10s (below 15), then 15 gaps at 20s (above 15)
        for _ in range(15):
            offsets.append(offsets[-1] + 10)
        for _ in range(15):
            offsets.append(offsets[-1] + 20)
        strokes = _make_strokes(offsets)
        report = analyze(strokes, target_cadence=15.0, window=5)

        assert report.max_consecutive_above > 0
        assert report.max_consecutive_below > 0

    def test_zero_target_cadence(self):
        """Edge case: target_cadence=0 should not crash."""
        offsets = _uniform_offsets(10, gap=15.0)
        strokes = _make_strokes(offsets)
        report = analyze(strokes, target_cadence=0.0, window=5)
        assert report.absolute_drift == pytest.approx(15.0)
        assert report.relative_drift == 0.0  # division guarded


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------

class TestDataclass:
    def test_defaults(self):
        r = CadenceDriftReport()
        assert r.target_cadence == 15.0
        assert r.mean_gap == 0.0
        assert r.rolling_means == []
        assert r.drift_trend == "stable"
        assert r.stability_grade == "tight"
        assert r.total_gaps == 0
        assert r.window_size == 20

    def test_independent_lists(self):
        """Two reports should not share list references."""
        a = CadenceDriftReport()
        b = CadenceDriftReport()
        a.rolling_means.append(1.0)
        assert b.rolling_means == []
