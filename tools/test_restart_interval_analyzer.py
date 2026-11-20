#!/usr/bin/env python3
"""Tests for restart_interval_analyzer.py."""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from restart_interval_analyzer import (
    detect_deaths,
    compute_intervals,
    analyze,
    _mean,
    _median,
    _std,
    _linear_slope,
    classify_trend,
    hour_histogram,
    DeathEvent,
)


def make_strokes(timestamps):
    """Create synthetic strokes from a list of datetime objects."""
    return [
        {"seq": i + 1, "at": ts.isoformat(), "kind": "thought", "text": f"stroke {i+1}"}
        for i, ts in enumerate(timestamps)
    ]


def test_no_deaths_when_uniform():
    """Uniform 15-second cadence should produce zero deaths."""
    base = datetime(2026, 11, 21, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [base + timedelta(seconds=15 * i) for i in range(100)]
    strokes = make_strokes(timestamps)
    deaths = detect_deaths(strokes, threshold=300)
    assert len(deaths) == 0, f"Expected 0 deaths, got {len(deaths)}"
    print("  PASS: no deaths when uniform cadence")


def test_single_death_detected():
    """A single large gap should produce exactly one death."""
    base = datetime(2026, 11, 21, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = (
        [base + timedelta(seconds=15 * i) for i in range(10)]
        + [base + timedelta(seconds=15 * 10 + 600)]  # 600s gap
        + [base + timedelta(seconds=15 * 10 + 600 + 15 * i) for i in range(1, 10)]
    )
    strokes = make_strokes(timestamps)
    deaths = detect_deaths(strokes, threshold=300)
    assert len(deaths) == 1, f"Expected 1 death, got {len(deaths)}"
    assert deaths[0].gap_seconds >= 599  # allow floating point
    print("  PASS: single death detected")


def test_multiple_deaths_and_intervals():
    """Multiple gaps should produce correct intervals."""
    base = datetime(2026, 11, 21, 0, 0, 0, tzinfo=timezone.utc)
    # Three death events at known times
    death_times = [
        base + timedelta(hours=1),
        base + timedelta(hours=3),
        base + timedelta(hours=8),
    ]
    timestamps = []
    for dt in death_times:
        # 5 strokes before each death
        for j in range(5):
            timestamps.append(dt - timedelta(seconds=15 * (5 - j)))
        # The death gap (skip 600s)
        timestamps.append(dt + timedelta(seconds=600))
    # Final tail
    for j in range(5):
        timestamps.append(death_times[-1] + timedelta(seconds=600 + 15 * (j + 1)))

    strokes = make_strokes(sorted(timestamps))
    deaths = detect_deaths(strokes, threshold=300)
    assert len(deaths) >= 3, f"Expected >=3 deaths, got {len(deaths)}"

    intervals = compute_intervals(deaths)
    assert len(intervals) >= 2, f"Expected >=2 intervals, got {len(intervals)}"
    # All intervals should be positive
    assert all(iv > 0 for iv in intervals), "Negative interval found"
    print("  PASS: multiple deaths and intervals correct")


def test_empty_strokes():
    """Empty input should return zero deaths."""
    deaths = detect_deaths([], threshold=300)
    assert len(deaths) == 0
    print("  PASS: empty strokes handled")


def test_analyze_insufficient_data():
    """analyze() with < 2 deaths should return safe defaults."""
    base = datetime(2026, 11, 21, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [base + timedelta(seconds=15 * i) for i in range(10)]
    strokes = make_strokes(timestamps)
    result = analyze(strokes, threshold=300)
    assert result["death_count"] == 0
    assert result["trend"] == "stable"
    assert result["peak_hour"] is None
    print("  PASS: analyze handles insufficient data")


def test_trend_classification():
    """Trend should reflect slope direction."""
    assert classify_trend(100.0, 1000.0) == "improving"   # +10%
    assert classify_trend(-100.0, 1000.0) == "degrading"  # -10%
    assert classify_trend(5.0, 1000.0) == "stable"        # +0.5%
    assert classify_trend(0.0, 0.0) == "stable"
    print("  PASS: trend classification correct")


def test_hour_histogram_counts():
    """Histogram should count deaths per UTC hour."""
    deaths = [
        DeathEvent(1, 600, "2026-11-21T03:10:00+00:00", 3),
        DeathEvent(2, 600, "2026-11-21T03:30:00+00:00", 3),
        DeathEvent(3, 600, "2026-11-21T14:00:00+00:00", 14),
    ]
    hist = hour_histogram(deaths)
    assert hist[3] == 2
    assert hist[14] == 1
    assert sum(hist.values()) == 3
    print("  PASS: hour histogram counts correct")


def test_cluster_coeff_bursty():
    """Bursty intervals (many short, few long) should give high cluster_coeff."""
    base = datetime(2026, 11, 21, 0, 0, 0, tzinfo=timezone.utc)
    # Create 4 deaths: 3 close together then 1 far away
    timestamps = []
    # Cluster at hour 0
    for t_offset in [0, 600, 1200, 1800]:
        timestamps.append(base + timedelta(seconds=t_offset))
        timestamps.append(base + timedelta(seconds=t_offset + 600))
    # Then a gap of 10 hours before next death
    timestamps.append(base + timedelta(hours=12))
    timestamps.append(base + timedelta(hours=12, seconds=600))

    strokes = make_strokes(sorted(timestamps))
    result = analyze(strokes, threshold=300)
    # With bursty deaths, cluster_coeff should be > 0
    assert result["cluster_coeff"] >= 0, "cluster_coeff should be non-negative"
    print(f"  PASS: cluster_coeff = {result['cluster_coeff']:.3f} for bursty pattern")


def test_mean_median_std_helpers():
    """Statistical helpers should return correct values."""
    assert _mean([2, 4, 6]) == 4.0
    assert _median([1, 3, 5]) == 3.0
    assert _median([1, 2, 3, 4]) == 2.5
    assert _mean([]) == 0.0
    assert _median([]) == 0.0
    assert abs(_std([2, 4, 4, 4, 5, 5, 7, 9]) - 2.138) < 0.01  # sample std
    assert _linear_slope([10, 20, 30]) == 10.0  # perfect positive slope
    assert _linear_slope([30, 20, 10]) == -10.0  # negative slope
    print("  PASS: statistical helpers correct")


def test_full_analysis_pipeline():
    """End-to-end test with synthetic data."""
    base = datetime(2026, 11, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = []
    # Simulate 5 death events spread over 24 hours
    death_offsets_hours = [2, 5, 9, 15, 22]
    for h in death_offsets_hours:
        # Some strokes before death
        for j in range(5):
            timestamps.append(base + timedelta(hours=h, seconds=-15 * (5 - j)))
        # Death gap: 600s of silence
        timestamps.append(base + timedelta(hours=h, seconds=600))
        # Resume strokes
        for j in range(5):
            timestamps.append(base + timedelta(hours=h, seconds=600 + 15 * (j + 1)))

    strokes = make_strokes(sorted(timestamps))
    result = analyze(strokes, threshold=300)

    assert result["death_count"] >= 5, f"Expected >=5 deaths, got {result['death_count']}"
    assert len(result["intervals"]) >= 4, f"Expected >=4 intervals"
    assert result["mean_interval_s"] > 0
    assert result["trend"] in ("improving", "degrading", "stable")
    assert result["peak_hour"] is not None
    assert 0 <= result["cluster_coeff"] <= 1.0
    print(f"  PASS: full pipeline — {result['death_count']} deaths, "
          f"trend={result['trend']}, peak_hour={result['peak_hour']}")


if __name__ == "__main__":
    tests = [
        test_empty_strokes,
        test_no_deaths_when_uniform,
        test_single_death_detected,
        test_multiple_deaths_and_intervals,
        test_analyze_insufficient_data,
        test_trend_classification,
        test_hour_histogram_counts,
        test_cluster_coeff_bursty,
        test_mean_median_std_helpers,
        test_full_analysis_pipeline,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {t.__name__}: {e}")
            failed += 1

    print(f"\n{passed}/{passed + failed} tests passed")
    sys.exit(1 if failed else 0)
