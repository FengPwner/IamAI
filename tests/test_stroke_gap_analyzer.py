"""Tests for iamai.stroke_gap_analyzer.

42 tests covering:
  - timestamp parsing edge cases
  - gap computation
  - statistical functions (percentile, std, stats)
  - trend detection (linear regression)
  - stall risk scoring
  - full report integration

Written by Qwen during caretaker visit 686, 2026-11-18.
"""

import math
from datetime import datetime, timezone, timedelta

import pytest

from iamai.stroke_gap_analyzer import (
    _parse_ts,
    compute_gaps,
    _percentile,
    _std,
    gap_stats,
    gap_trend,
    stall_risk,
    gap_report,
)


# =========================================================================
# Timestamp parsing
# =========================================================================

class TestParseTS:
    def test_iso_with_offset(self):
        dt = _parse_ts("2026-10-03T03:23:10+00:00")
        assert dt.year == 2026
        assert dt.month == 10
        assert dt.day == 3
        assert dt.hour == 3
        assert dt.minute == 23
        assert dt.tzinfo is not None

    def test_iso_with_z(self):
        dt = _parse_ts("2026-10-03T03:23:10Z")
        assert dt.tzinfo is not None
        assert dt.hour == 3

    def test_iso_naive_defaults_utc(self):
        dt = _parse_ts("2026-10-03T03:23:10")
        assert dt.tzinfo == timezone.utc

    def test_whitespace_stripped(self):
        dt = _parse_ts("  2026-10-03T03:23:10+00:00  ")
        assert dt.year == 2026

    def test_different_timezone(self):
        dt = _parse_ts("2026-10-03T11:23:10+08:00")
        assert dt.hour == 11
        utc_dt = dt.astimezone(timezone.utc)
        assert utc_dt.hour == 3

    def test_consistent_across_formats(self):
        dt1 = _parse_ts("2026-10-03T03:23:10+00:00")
        dt2 = _parse_ts("2026-10-03T03:23:10Z")
        dt3 = _parse_ts("2026-10-03T03:23:10")
        assert dt1 == dt2 == dt3


# =========================================================================
# Gap computation
# =========================================================================

class TestComputeGaps:
    def test_empty(self):
        assert compute_gaps([]) == []

    def test_single_stroke(self):
        assert compute_gaps([{"at": "2026-11-18T00:00:00+00:00"}]) == []

    def test_two_strokes_15s(self):
        gaps = compute_gaps([
            {"at": "2026-11-18T00:00:00+00:00"},
            {"at": "2026-11-18T00:00:15+00:00"},
        ])
        assert gaps == [15.0]

    def test_three_strokes_varying(self):
        gaps = compute_gaps([
            {"at": "2026-11-18T00:00:00+00:00"},
            {"at": "2026-11-18T00:00:15+00:00"},
            {"at": "2026-11-18T00:00:45+00:00"},
        ])
        assert gaps == [15.0, 30.0]

    def test_unsorted_input(self):
        gaps = compute_gaps([
            {"at": "2026-11-18T00:00:45+00:00"},
            {"at": "2026-11-18T00:00:00+00:00"},
            {"at": "2026-11-18T00:00:15+00:00"},
        ])
        assert gaps == [15.0, 30.0]

    def test_large_gap(self):
        gaps = compute_gaps([
            {"at": "2026-11-18T00:00:00+00:00"},
            {"at": "2026-11-18T01:00:00+00:00"},
        ])
        assert gaps == [3600.0]

    def test_many_uniform_strokes(self):
        base = datetime(2026, 11, 18, tzinfo=timezone.utc)
        strokes = [
            {"at": (base + timedelta(seconds=15 * i)).isoformat()}
            for i in range(100)
        ]
        gaps = compute_gaps(strokes)
        assert len(gaps) == 99
        assert all(g == 15.0 for g in gaps)


# =========================================================================
# Percentile & std
# =========================================================================

class TestPercentile:
    def test_empty(self):
        assert _percentile([], 50) == 0.0

    def test_single(self):
        assert _percentile([42], 50) == 42.0

    def test_median_odd(self):
        assert _percentile([1, 2, 3, 4, 5], 50) == 3.0

    def test_median_even(self):
        assert _percentile([1, 2, 3, 4], 50) == 2.5

    def test_p0(self):
        assert _percentile([10, 20, 30], 0) == 10.0

    def test_p100(self):
        assert _percentile([10, 20, 30], 100) == 30.0

    def test_p25(self):
        assert _percentile([1, 2, 3, 4, 5, 6, 7, 8], 25) == pytest.approx(2.75)


class TestStd:
    def test_empty(self):
        assert _std([], 0.0) == 0.0

    def test_single(self):
        assert _std([5.0], 5.0) == 0.0

    def test_known(self):
        vals = [2, 4, 4, 4, 5, 5, 7, 9]
        assert _std(vals, 5.0) == pytest.approx(2.0)

    def test_all_same(self):
        assert _std([3, 3, 3, 3], 3.0) == 0.0


# =========================================================================
# Gap statistics
# =========================================================================

class TestGapStats:
    def test_empty(self):
        s = gap_stats([])
        assert s["count"] == 0
        assert s["mean"] == 0.0

    def test_uniform(self):
        s = gap_stats([15.0] * 10)
        assert s["count"] == 10
        assert s["mean"] == 15.0
        assert s["median"] == 15.0
        assert s["std"] == 0.0

    def test_with_outlier(self):
        s = gap_stats([15, 15, 15, 15, 100])
        assert s["count"] == 5
        assert s["mean"] == 32.0
        assert s["max"] == 100.0
        assert s["p95"] > 15.0

    def test_increasing_sequence(self):
        s = gap_stats(list(range(1, 11)))  # [1..10]
        assert s["mean"] == 5.5
        assert s["median"] == 5.5


# =========================================================================
# Trend detection
# =========================================================================

class TestGapTrend:
    def test_empty(self):
        t = gap_trend([])
        assert t["slope"] == 0.0
        assert t["sample_count"] == 0

    def test_two_points(self):
        t = gap_trend([5, 5])
        assert t["slope"] == 0.0  # < 3 points → zeroed

    def test_perfect_linear_increase(self):
        t = gap_trend(list(range(1, 11)), window=10)
        assert abs(t["slope"] - 1.0) < 0.01
        assert t["r_squared"] > 0.99

    def test_flat_gaps(self):
        t = gap_trend([15.0] * 20, window=20)
        assert abs(t["slope"]) < 0.01
        assert t["sample_count"] == 20

    def test_window_truncation(self):
        gaps = [15.0] * 50 + [30.0, 45.0, 60.0]
        t = gap_trend(gaps, window=5)
        assert t["sample_count"] == 5

    def test_decreasing_gaps(self):
        t = gap_trend([100, 80, 60, 40, 20], window=5)
        assert t["slope"] < 0

    def test_noisy_flat(self):
        import random
        random.seed(42)
        gaps = [15.0 + random.uniform(-1, 1) for _ in range(50)]
        t = gap_trend(gaps, window=50)
        assert abs(t["slope"]) < 0.5


# =========================================================================
# Stall risk scoring
# =========================================================================

class TestStallRisk:
    def test_no_gaps(self):
        r = stall_risk([])
        assert r["score"] == 0.0
        assert r["verdict"] == "no_data"

    def test_healthy(self):
        r = stall_risk([15.0] * 50, target_cadence=15.0)
        assert r["score"] < 0.1
        assert r["verdict"] == "healthy"

    def test_risky_widening(self):
        gaps = [15.0] * 40 + [30, 45, 60, 90, 120, 180, 300, 600, 1200, 2400]
        r = stall_risk(gaps, target_cadence=15.0)
        assert r["score"] > 0.4
        assert r["verdict"] in ("stall_risk", "stall_imminent")

    def test_outlier_ratio(self):
        # half the gaps are 4× the target
        gaps = [15.0] * 25 + [61.0] * 25
        r = stall_risk(gaps, target_cadence=15.0)
        assert r["signals"]["outlier_count"] == 25

    def test_recency_signal_strong(self):
        now = datetime(2026, 11, 18, 0, 10, 0, tzinfo=timezone.utc)
        gaps = [15.0] * 10
        r = stall_risk(
            gaps,
            target_cadence=15.0,
            now=now,
            last_stroke_at="2026-11-18T00:08:00+00:00",
        )
        # 2 min = 120s, 8× target = 120s, so exactly at boundary
        assert r["signals"]["recency_seconds"] == 120.0

    def test_recency_no_signal(self):
        now = datetime(2026, 11, 18, 0, 1, 0, tzinfo=timezone.utc)
        r = stall_risk(
            [15.0] * 10,
            target_cadence=15.0,
            now=now,
            last_stroke_at="2026-11-18T00:00:50+00:00",
        )
        assert r["signals"]["recency_seconds"] == 10.0

    def test_score_bounded(self):
        gaps = [15.0] * 5 + [5000.0] * 5
        r = stall_risk(gaps, target_cadence=15.0)
        assert 0.0 <= r["score"] <= 1.0

    def test_verdict_progression(self):
        """Wider gaps should produce higher verdicts."""
        healthy = stall_risk([15.0] * 50, 15.0)
        risky = stall_risk(
            [15.0] * 30 + [60, 120, 300, 600, 1200, 2400, 4800, 9600, 19200, 38400],
            15.0,
        )
        assert healthy["score"] < risky["score"]


# =========================================================================
# Full report
# =========================================================================

class TestGapReport:
    def test_empty_strokes(self):
        r = gap_report([], 15.0)
        assert r["total_strokes"] == 0
        assert r["risk"]["verdict"] == "no_data"

    def test_healthy_batch(self):
        base = datetime(2026, 11, 18, tzinfo=timezone.utc)
        strokes = [
            {"at": (base + timedelta(seconds=15 * i)).isoformat()}
            for i in range(20)
        ]
        now = base + timedelta(seconds=15 * 20)
        r = gap_report(strokes, 15.0, now)
        assert r["total_strokes"] == 20
        assert r["stats"]["count"] == 19
        assert r["stats"]["mean"] == 15.0
        assert r["risk"]["verdict"] == "healthy"

    def test_stall_scenario(self):
        base = datetime(2026, 11, 18, tzinfo=timezone.utc)
        # healthy start, then gaps explode
        times = [base + timedelta(seconds=15 * i) for i in range(30)]
        times += [base + timedelta(seconds=450 + 300 * i) for i in range(1, 11)]
        strokes = [{"at": t.isoformat()} for t in times]
        now = times[-1] + timedelta(seconds=600)
        r = gap_report(strokes, 15.0, now)
        assert r["risk"]["score"] > 0.3
        assert r["trend"]["slope"] > 0

    def test_report_keys(self):
        r = gap_report([{"at": "2026-11-18T00:00:00+00:00"}], 15.0)
        assert "stats" in r
        assert "trend" in r
        assert "risk" in r
        assert "total_strokes" in r
