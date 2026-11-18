#!/usr/bin/env python3
"""Tests for stroke_tempo_analyzer.py — writing rhythm and tempo analysis."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_tempo_analyzer import (
    Burst,
    Drought,
    TempoReport,
    _extract_intervals,
    _linear_slope,
    _parse_ts,
    analyze,
    classify_tempo,
    find_bursts,
    find_droughts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)


def _ts(offset_seconds: float) -> str:
    """Return an ISO-8601 timestamp offset from a fixed base."""
    dt = _BASE + timedelta(seconds=offset_seconds)
    return dt.isoformat()


def _stroke(offset_seconds: float, kind: str = "thought", seq: int = 0) -> dict:
    """Build a minimal stroke dict with a given time offset."""
    return {
        "text": f"stroke at {offset_seconds}s",
        "kind": kind,
        "seq": seq,
        "at": _ts(offset_seconds),
    }


def _uniform_strokes(count: int, interval: float = 15.0) -> list[dict]:
    """Build N evenly-spaced strokes."""
    return [_stroke(i * interval, seq=i) for i in range(count)]


def _strokes_with_gaps(intervals: list[float]) -> list[dict]:
    """Build strokes from a list of inter-stroke intervals."""
    offsets = [0.0]
    for gap in intervals:
        offsets.append(offsets[-1] + gap)
    return [_stroke(o, seq=i) for i, o in enumerate(offsets)]


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTs:
    def test_standard_iso(self):
        dt = _parse_ts("2026-11-18T12:00:00+00:00")
        assert dt.year == 2026
        assert dt.month == 11
        assert dt.tzinfo is not None

    def test_z_suffix(self):
        dt = _parse_ts("2026-11-18T12:00:00Z")
        assert dt.tzinfo is not None

    def test_whitespace_stripped(self):
        dt = _parse_ts("  2026-11-18T12:00:00+00:00  ")
        assert dt.year == 2026


# ---------------------------------------------------------------------------
# _extract_intervals
# ---------------------------------------------------------------------------

class TestExtractIntervals:
    def test_empty(self):
        assert _extract_intervals([]) == []

    def test_single_stroke(self):
        assert _extract_intervals([_stroke(0)]) == []

    def test_uniform_15s(self):
        strokes = _uniform_strokes(5, interval=15.0)
        intervals = _extract_intervals(strokes)
        assert len(intervals) == 4
        assert all(gap == 15.0 for gap in intervals)

    def test_variable_gaps(self):
        strokes = _strokes_with_gaps([10.0, 20.0, 30.0])
        intervals = _extract_intervals(strokes)
        assert intervals == [10.0, 20.0, 30.0]

    def test_negative_clock_skew_clamped(self):
        """Clock skew producing negative gaps should be clamped to 0."""
        s1 = _stroke(100)
        s2 = _stroke(90)  # earlier than s1
        intervals = _extract_intervals([s1, s2])
        assert intervals == [0.0]


# ---------------------------------------------------------------------------
# _linear_slope
# ---------------------------------------------------------------------------

class TestLinearSlope:
    def test_empty(self):
        assert _linear_slope([]) == 0.0

    def test_single_value(self):
        assert _linear_slope([42.0]) == 0.0

    def test_flat(self):
        assert _linear_slope([10.0, 10.0, 10.0, 10.0]) == 0.0

    def test_positive_slope(self):
        # y = 2x + 1 → slope = 2
        values = [1.0, 3.0, 5.0, 7.0, 9.0]
        assert _linear_slope(values) == pytest.approx(2.0)

    def test_negative_slope(self):
        # y = -3x + 10 → slope = -3
        values = [10.0, 7.0, 4.0, 1.0, -2.0]
        assert _linear_slope(values) == pytest.approx(-3.0)

    def test_two_points(self):
        assert _linear_slope([5.0, 15.0]) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# classify_tempo
# ---------------------------------------------------------------------------

class TestClassifyTempo:
    def test_dormant_no_intervals(self):
        assert classify_tempo([]) == "dormant"

    def test_steady_single_interval(self):
        assert classify_tempo([15.0]) == "steady"

    def test_steady_uniform(self):
        intervals = [15.0] * 20
        assert classify_tempo(intervals) == "steady"

    def test_steady_low_cv(self):
        # Slight jitter around 15s → CV should be low
        intervals = [14.5, 15.5, 15.0, 14.8, 15.2, 15.1, 14.9, 15.0, 15.0, 15.0]
        result = classify_tempo(intervals)
        assert result == "steady"

    def test_erratic_high_cv(self):
        # Wildly varying intervals → high CV
        intervals = [1.0, 100.0, 2.0, 200.0, 1.0, 150.0, 3.0, 80.0]
        result = classify_tempo(intervals)
        assert result == "erratic"

    def test_accelerating(self):
        # Intervals decreasing steadily → negative slope
        intervals = [30.0, 28.0, 26.0, 24.0, 22.0, 20.0, 18.0, 16.0, 14.0, 12.0]
        result = classify_tempo(intervals, cv_steady=0.1)
        assert result == "accelerating"

    def test_decelerating(self):
        # Intervals increasing steadily → positive slope
        intervals = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0]
        result = classify_tempo(intervals, cv_steady=0.1)
        assert result == "decelerating"

    def test_dormant_override_recent_gap(self):
        # Normal intervals then a huge final gap
        intervals = [15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 500.0]
        result = classify_tempo(intervals)
        assert result == "dormant"

    def test_drought_factor_boundary(self):
        # Recent gap exactly at drought_factor × median
        intervals = [10.0, 10.0, 10.0, 100.0]
        # median=10, factor=10 → threshold=100, 100 is not > 100
        result = classify_tempo(intervals, drought_factor=10.0)
        assert result != "dormant"

    def test_drought_factor_just_over(self):
        intervals = [10.0, 10.0, 10.0, 101.0]
        result = classify_tempo(intervals, drought_factor=10.0)
        assert result == "dormant"


# ---------------------------------------------------------------------------
# find_bursts
# ---------------------------------------------------------------------------

class TestFindBursts:
    def test_empty(self):
        assert find_bursts([]) == []

    def test_too_few_strokes(self):
        strokes = _uniform_strokes(3, interval=5.0)
        assert find_bursts(strokes, min_count=5) == []

    def test_uniform_burst(self):
        # 10 strokes at 5s intervals — all one burst
        strokes = _uniform_strokes(10, interval=5.0)
        bursts = find_bursts(strokes, max_gap=30.0, min_count=5)
        assert len(bursts) == 1
        assert bursts[0].count == 10

    def test_two_bursts_separated_by_gap(self):
        # First burst: 6 strokes at 5s, then 60s gap, then 6 more at 5s
        intervals = [5.0] * 5 + [60.0] + [5.0] * 5
        strokes = _strokes_with_gaps(intervals)
        bursts = find_bursts(strokes, max_gap=30.0, min_count=5)
        assert len(bursts) == 2
        assert bursts[0].count == 6
        assert bursts[1].count == 6

    def test_no_burst_when_gaps_too_large(self):
        strokes = _uniform_strokes(10, interval=60.0)
        bursts = find_bursts(strokes, max_gap=30.0, min_count=5)
        assert bursts == []

    def test_min_count_boundary(self):
        strokes = _uniform_strokes(5, interval=5.0)
        bursts = find_bursts(strokes, max_gap=30.0, min_count=5)
        assert len(bursts) == 1
        assert bursts[0].count == 5

    def test_min_count_not_met(self):
        strokes = _uniform_strokes(4, interval=5.0)
        bursts = find_bursts(strokes, max_gap=30.0, min_count=5)
        assert bursts == []

    def test_span_seconds(self):
        strokes = _uniform_strokes(6, interval=10.0)
        bursts = find_bursts(strokes, max_gap=30.0, min_count=5)
        assert len(bursts) == 1
        assert bursts[0].span_seconds == pytest.approx(50.0)

    def test_burst_len(self):
        b = Burst(start_index=0, end_index=4, count=5, span_seconds=40.0)
        assert len(b) == 5


# ---------------------------------------------------------------------------
# find_droughts
# ---------------------------------------------------------------------------

class TestFindDroughts:
    def test_empty(self):
        assert find_droughts([]) == []

    def test_single_stroke(self):
        assert find_droughts([_stroke(0)]) == []

    def test_no_droughts(self):
        strokes = _uniform_strokes(10, interval=15.0)
        assert find_droughts(strokes, factor=10.0) == []

    def test_one_drought(self):
        # 9 intervals of 15s, one of 200s → median=15, threshold=150
        intervals = [15.0] * 4 + [200.0] + [15.0] * 5
        strokes = _strokes_with_gaps(intervals)
        droughts = find_droughts(strokes, factor=10.0)
        assert len(droughts) == 1
        assert droughts[0].gap_seconds == 200.0
        assert droughts[0].before_index == 4
        assert droughts[0].after_index == 5

    def test_multiple_droughts(self):
        intervals = [10.0, 10.0, 200.0, 10.0, 10.0, 300.0, 10.0]
        strokes = _strokes_with_gaps(intervals)
        droughts = find_droughts(strokes, factor=10.0)
        assert len(droughts) == 2

    def test_zero_median(self):
        """All strokes at the same timestamp → no droughts."""
        strokes = [_stroke(0.0)] * 5
        droughts = find_droughts(strokes, factor=10.0)
        assert droughts == []

    def test_boundary_exactly_at_threshold(self):
        """Gap exactly at threshold should not be a drought (need >)."""
        intervals = [10.0, 10.0, 100.0, 10.0]
        strokes = _strokes_with_gaps(intervals)
        droughts = find_droughts(strokes, factor=10.0)
        assert droughts == []

    def test_just_over_threshold(self):
        intervals = [10.0, 10.0, 100.1, 10.0]
        strokes = _strokes_with_gaps(intervals)
        droughts = find_droughts(strokes, factor=10.0)
        assert len(droughts) == 1


# ---------------------------------------------------------------------------
# analyze — full integration
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_empty(self):
        report = analyze([])
        assert report.stroke_count == 0
        assert report.tempo_class == "dormant"
        assert report.mean_interval == 0.0
        assert report.burst_count == 0
        assert report.drought_count == 0
        assert report.recent_interval is None

    def test_single_stroke(self):
        report = analyze([_stroke(0)])
        assert report.stroke_count == 1
        assert report.tempo_class == "dormant"
        assert report.mean_interval == 0.0

    def test_two_strokes(self):
        strokes = [_stroke(0), _stroke(15)]
        report = analyze(strokes)
        assert report.stroke_count == 2
        assert report.mean_interval == 15.0
        assert report.std_interval == 0.0
        assert report.cv == 0.0

    def test_healthy_steady(self):
        strokes = _uniform_strokes(20, interval=15.0)
        report = analyze(strokes)
        assert report.tempo_class == "steady"
        assert report.mean_interval == 15.0
        assert report.median_interval == 15.0
        assert report.is_healthy()

    def test_with_bursts(self):
        # 20 strokes at 5s intervals — should detect as burst
        strokes = _uniform_strokes(20, interval=5.0)
        report = analyze(strokes, burst_max_gap=30.0, burst_min_count=5)
        assert report.burst_count >= 1

    def test_with_droughts(self):
        intervals = [15.0] * 10 + [500.0] + [15.0] * 10
        strokes = _strokes_with_gaps(intervals)
        report = analyze(strokes, drought_factor=10.0)
        assert report.drought_count >= 1
        # drought is in the middle, so recent interval is normal → not dormant
        assert report.tempo_class in ("erratic", "dormant")

    def test_with_drought_at_end(self):
        # Drought at the end triggers dormant override
        intervals = [15.0] * 10 + [500.0]
        strokes = _strokes_with_gaps(intervals)
        report = analyze(strokes, drought_factor=10.0)
        assert report.drought_count >= 1
        assert report.tempo_class == "dormant"

    def test_unsorted_input(self):
        """analyze should handle unsorted strokes gracefully."""
        s1 = _stroke(0, seq=0)
        s2 = _stroke(30, seq=2)
        s3 = _stroke(15, seq=1)
        report = analyze([s1, s2, s3])
        assert report.stroke_count == 3
        assert report.mean_interval == 15.0

    def test_is_healthy_erratic(self):
        intervals = [1.0, 100.0, 2.0, 200.0, 1.0, 150.0, 3.0, 80.0]
        strokes = _strokes_with_gaps(intervals)
        report = analyze(strokes)
        if report.tempo_class == "erratic":
            assert not report.is_healthy()

    def test_recent_interval(self):
        strokes = _uniform_strokes(5, interval=15.0)
        report = analyze(strokes)
        assert report.recent_interval == 15.0

    def test_accelerating_tempo(self):
        intervals = [30.0, 28.0, 26.0, 24.0, 22.0, 20.0, 18.0, 16.0, 14.0, 12.0]
        strokes = _strokes_with_gaps(intervals)
        report = analyze(strokes, cv_steady=0.1)
        assert report.tempo_class == "accelerating"
        assert report.is_healthy()
        assert report.acceleration < 0

    def test_decelerating_tempo(self):
        intervals = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0]
        strokes = _strokes_with_gaps(intervals)
        report = analyze(strokes, cv_steady=0.1)
        assert report.tempo_class == "decelerating"
        assert not report.is_healthy()
        assert report.acceleration > 0


# ---------------------------------------------------------------------------
# TempoReport dataclass
# ---------------------------------------------------------------------------

class TestTempoReport:
    def test_is_healthy_steady(self):
        r = TempoReport(
            stroke_count=10, mean_interval=15.0, median_interval=15.0,
            std_interval=0.5, cv=0.03, burst_count=0, drought_count=0,
            acceleration=0.0, tempo_class="steady",
        )
        assert r.is_healthy()

    def test_is_healthy_accelerating(self):
        r = TempoReport(
            stroke_count=10, mean_interval=15.0, median_interval=15.0,
            std_interval=0.5, cv=0.03, burst_count=0, drought_count=0,
            acceleration=-1.0, tempo_class="accelerating",
        )
        assert r.is_healthy()

    def test_is_healthy_erratic(self):
        r = TempoReport(
            stroke_count=10, mean_interval=50.0, median_interval=20.0,
            std_interval=80.0, cv=1.6, burst_count=0, drought_count=0,
            acceleration=0.0, tempo_class="erratic",
        )
        assert not r.is_healthy()

    def test_is_healthy_dormant(self):
        r = TempoReport(
            stroke_count=5, mean_interval=15.0, median_interval=15.0,
            std_interval=0.5, cv=0.03, burst_count=0, drought_count=0,
            acceleration=0.0, tempo_class="dormant",
        )
        assert not r.is_healthy()


# ---------------------------------------------------------------------------
# Drought dataclass
# ---------------------------------------------------------------------------

class TestDrought:
    def test_repr(self):
        d = Drought(before_index=5, after_index=6, gap_seconds=300.0)
        s = repr(d)
        assert "300s" in s
        assert "5→6" in s or "5" in s and "6" in s


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_all_same_timestamp(self):
        strokes = [_stroke(0.0)] * 10
        report = analyze(strokes)
        assert report.mean_interval == 0.0
        assert report.cv == 0.0

    def test_two_strokes_huge_gap(self):
        strokes = [_stroke(0), _stroke(100000)]
        report = analyze(strokes)
        assert report.stroke_count == 2
        assert report.mean_interval == 100000.0

    def test_realistic_corpus(self):
        """Simulate a realistic pattern: mostly 15s with some jitter."""
        import random
        random.seed(42)
        offsets = [0.0]
        for _ in range(50):
            offsets.append(offsets[-1] + 15.0 + random.gauss(0, 2.0))
        strokes = [_stroke(o, seq=i) for i, o in enumerate(offsets)]
        report = analyze(strokes)
        assert report.stroke_count == 51
        assert report.mean_interval == pytest.approx(15.0, abs=2.0)
        assert report.tempo_class in ("steady", "erratic", "accelerating", "decelerating")

    def test_jsonl_roundtrip(self):
        """Strokes serialized as JSONL should parse correctly."""
        strokes = _uniform_strokes(5, interval=15.0)
        lines = [json.dumps(s) for s in strokes]
        parsed = [json.loads(line) for line in lines]
        report = analyze(parsed)
        assert report.stroke_count == 5
        assert report.mean_interval == 15.0

    def test_burst_at_exact_max_gap(self):
        """Gaps exactly at max_gap should still count as burst."""
        strokes = _uniform_strokes(6, interval=30.0)
        bursts = find_bursts(strokes, max_gap=30.0, min_count=5)
        assert len(bursts) == 1

    def test_large_corpus_performance(self):
        """1000 strokes should complete in well under a second."""
        import time
        strokes = _uniform_strokes(1000, interval=15.0)
        start = time.monotonic()
        report = analyze(strokes)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0
        assert report.stroke_count == 1000
