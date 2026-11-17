"""Tests for writer_loop_monitor module.

Covers:
- TickRecord construction and defaults
- LoopStats construction and summary formatting
- compute_intervals: normal, empty, single tick, clock skew
- compute_jitter: 0/1/2+ intervals, uniform, high variance
- compute_missed_ticks: no gaps, one big gap, multiple gaps, edge cases
- compute_drift: on-time, slow, fast, single tick
- classify_verdict: all quadrants, boundary values
- loop_health_report: end-to-end, empty, single tick, mixed
- compare_reports: improving, worsening, stable, unknown
"""

import pytest

from iamai.writer_loop_monitor import (
    LoopStats,
    TickRecord,
    classify_verdict,
    compare_reports,
    compute_drift,
    compute_intervals,
    compute_jitter,
    compute_missed_ticks,
    loop_health_report,
)


# ===========================================================================
# TickRecord
# ===========================================================================

class TestTickRecord:
    def test_minimal_construction(self):
        t = TickRecord(timestamp=1000.0)
        assert t.timestamp == 1000.0
        assert t.category == ""
        assert t.expected_at is None

    def test_full_construction(self):
        t = TickRecord(timestamp=1000.0, category="devlog", expected_at=999.5)
        assert t.category == "devlog"
        assert t.expected_at == 999.5


# ===========================================================================
# LoopStats
# ===========================================================================

class TestLoopStats:
    def test_defaults(self):
        s = LoopStats()
        assert s.tick_count == 0
        assert s.verdict == "unknown"

    def test_summary_contains_key_fields(self):
        s = LoopStats(
            tick_count=10,
            mean_interval=15.1,
            jitter_std=2.34,
            missed_ticks=1,
            drift_seconds=3.2,
            verdict="healthy",
        )
        text = s.summary()
        assert "healthy" in text
        assert "10" in text
        assert "2.34" in text
        assert "3.2" in text


# ===========================================================================
# compute_intervals
# ===========================================================================

class TestComputeIntervals:
    def test_empty(self):
        assert compute_intervals([]) == []

    def test_single_tick(self):
        assert compute_intervals([TickRecord(timestamp=100.0)]) == []

    def test_two_ticks(self):
        ticks = [TickRecord(timestamp=100.0), TickRecord(timestamp=115.0)]
        assert compute_intervals(ticks) == [15.0]

    def test_multiple_ticks_sorted(self):
        ticks = [
            TickRecord(timestamp=100.0),
            TickRecord(timestamp=115.0),
            TickRecord(timestamp=130.0),
        ]
        assert compute_intervals(ticks) == [15.0, 15.0]

    def test_unsorted_input(self):
        ticks = [
            TickRecord(timestamp=130.0),
            TickRecord(timestamp=100.0),
            TickRecord(timestamp=115.0),
        ]
        result = compute_intervals(ticks)
        assert result == [15.0, 15.0]

    def test_out_of_order_sorted_before_compute(self):
        # Unsorted input is sorted internally, so intervals are non-negative
        ticks = [
            TickRecord(timestamp=100.0),
            TickRecord(timestamp=99.0),  # out of order
        ]
        result = compute_intervals(ticks)
        assert result == [1.0]  # sorted: [99, 100] → interval 1.0

    def test_duplicate_timestamps(self):
        ticks = [
            TickRecord(timestamp=100.0),
            TickRecord(timestamp=100.0),
        ]
        assert compute_intervals(ticks) == [0.0]


# ===========================================================================
# compute_jitter
# ===========================================================================

class TestComputeJitter:
    def test_empty(self):
        assert compute_jitter([]) == 0.0

    def test_single_interval(self):
        assert compute_jitter([15.0]) == 0.0

    def test_uniform_intervals(self):
        assert compute_jitter([15.0, 15.0, 15.0, 15.0]) == 0.0

    def test_variable_intervals(self):
        intervals = [10.0, 20.0, 10.0, 20.0]
        j = compute_jitter(intervals)
        assert j > 0.0
        assert abs(j - 5.77) < 0.1  # stdev of [10,20,10,20] ≈ 5.77

    def test_two_intervals(self):
        j = compute_jitter([14.0, 16.0])
        assert abs(j - 1.414) < 0.01


# ===========================================================================
# compute_missed_ticks
# ===========================================================================

class TestComputeMissedTicks:
    def test_empty(self):
        assert compute_missed_ticks([], 15.0) == 0

    def test_single_tick(self):
        assert compute_missed_ticks([TickRecord(timestamp=100.0)], 15.0) == 0

    def test_no_gaps(self):
        ticks = [
            TickRecord(timestamp=100.0),
            TickRecord(timestamp=115.0),
            TickRecord(timestamp=130.0),
        ]
        assert compute_missed_ticks(ticks, 15.0) == 0

    def test_one_big_gap(self):
        # Gap of 60s with 15s target → expected 4 ticks, observed 1 → 3 missed
        ticks = [
            TickRecord(timestamp=100.0),
            TickRecord(timestamp=160.0),  # 60s gap
        ]
        missed = compute_missed_ticks(ticks, 15.0, tolerance=0.5)
        assert missed == 3

    def test_multiple_gaps(self):
        ticks = [
            TickRecord(timestamp=100.0),
            TickRecord(timestamp=115.0),  # normal
            TickRecord(timestamp=145.0),  # 30s gap → 1 missed
            TickRecord(timestamp=160.0),  # normal
            TickRecord(timestamp=220.0),  # 60s gap → 3 missed
        ]
        missed = compute_missed_ticks(ticks, 15.0, tolerance=0.5)
        assert missed == 4  # 1 + 3

    def test_zero_target_interval(self):
        ticks = [TickRecord(timestamp=100.0), TickRecord(timestamp=200.0)]
        assert compute_missed_ticks(ticks, 0.0) == 0

    def test_tolerance_boundary(self):
        # Exactly at tolerance: 15 * 1.5 = 22.5s → gap of 22.5 is NOT flagged
        ticks = [
            TickRecord(timestamp=100.0),
            TickRecord(timestamp=122.5),
        ]
        assert compute_missed_ticks(ticks, 15.0, tolerance=0.5) == 0

    def test_just_over_tolerance(self):
        ticks = [
            TickRecord(timestamp=100.0),
            TickRecord(timestamp=123.0),  # 23s > 22.5s threshold
        ]
        missed = compute_missed_ticks(ticks, 15.0, tolerance=0.5)
        assert missed == 0  # 23/15 = 1.53 → floor = 1, minus 1 = 0


# ===========================================================================
# compute_drift
# ===========================================================================

class TestComputeDrift:
    def test_empty(self):
        assert compute_drift([], 15.0) == 0.0

    def test_single_tick(self):
        assert compute_drift([TickRecord(timestamp=100.0)], 15.0) == 0.0

    def test_on_time(self):
        # 5 ticks, 15s apart → elapsed=60s, ideal=60s → drift=0
        ticks = [TickRecord(timestamp=100.0 + i * 15.0) for i in range(5)]
        assert abs(compute_drift(ticks, 15.0)) < 0.001

    def test_running_slow(self):
        # 5 ticks, 18s apart → elapsed=72s, ideal=60s → drift=+12
        ticks = [TickRecord(timestamp=100.0 + i * 18.0) for i in range(5)]
        assert abs(compute_drift(ticks, 15.0) - 12.0) < 0.001

    def test_running_fast(self):
        # 5 ticks, 12s apart → elapsed=48s, ideal=60s → drift=-12
        ticks = [TickRecord(timestamp=100.0 + i * 12.0) for i in range(5)]
        assert abs(compute_drift(ticks, 15.0) - (-12.0)) < 0.001

    def test_zero_target(self):
        ticks = [TickRecord(timestamp=100.0), TickRecord(timestamp=200.0)]
        assert compute_drift(ticks, 0.0) == 0.0


# ===========================================================================
# classify_verdict
# ===========================================================================

class TestClassifyVerdict:
    def test_healthy(self):
        assert classify_verdict(2.0, 1.0) == "healthy"

    def test_healthy_boundary(self):
        assert classify_verdict(4.9, 1.9) == "healthy"

    def test_degraded_by_jitter(self):
        assert classify_verdict(6.0, 0.5) == "degraded"

    def test_degraded_by_miss_pct(self):
        assert classify_verdict(1.0, 5.0) == "degraded"

    def test_critical_by_jitter(self):
        assert classify_verdict(16.0, 0.5) == "critical"

    def test_critical_by_miss_pct(self):
        assert classify_verdict(1.0, 11.0) == "critical"

    def test_unknown_on_negative(self):
        assert classify_verdict(-1.0, 0.0) == "unknown"
        assert classify_verdict(0.0, -1.0) == "unknown"

    def test_boundary_jitter_5(self):
        assert classify_verdict(5.0, 0.0) == "degraded"

    def test_boundary_jitter_15(self):
        assert classify_verdict(15.0, 0.0) == "critical"

    def test_boundary_missed_2(self):
        assert classify_verdict(0.0, 2.0) == "degraded"

    def test_boundary_missed_10(self):
        assert classify_verdict(0.0, 10.0) == "critical"


# ===========================================================================
# loop_health_report
# ===========================================================================

class TestLoopHealthReport:
    def test_empty(self):
        r = loop_health_report([])
        assert r.verdict == "unknown"
        assert r.tick_count == 0

    def test_single_tick(self):
        r = loop_health_report([TickRecord(timestamp=100.0)])
        assert r.verdict == "unknown"
        assert r.tick_count == 1

    def test_healthy_loop(self):
        # Perfect 15s cadence
        ticks = [TickRecord(timestamp=1000.0 + i * 15.0) for i in range(20)]
        r = loop_health_report(ticks, target_interval=15.0)
        assert r.verdict == "healthy"
        assert r.tick_count == 20
        assert r.missed_ticks == 0
        assert r.jitter_std == 0.0
        assert abs(r.drift_seconds) < 0.01

    def test_degraded_loop(self):
        # Slightly irregular: alternates 13s and 17s (mean 15, stdev ~2.8)
        base = 1000.0
        timestamps = [base]
        for i in range(19):
            timestamps.append(timestamps[-1] + (13.0 if i % 2 == 0 else 17.0))
        ticks = [TickRecord(timestamp=t) for t in timestamps]
        r = loop_health_report(ticks, target_interval=15.0)
        assert r.verdict in ("healthy", "degraded")
        assert r.missed_ticks == 0

    def test_critical_loop_with_missed(self):
        # Ticks every 30s (target 15s) → lots of missed ticks
        ticks = [TickRecord(timestamp=1000.0 + i * 30.0) for i in range(10)]
        r = loop_health_report(ticks, target_interval=15.0)
        assert r.missed_ticks > 0
        assert r.verdict == "critical"

    def test_with_categories(self):
        categories = ["devlog", "note", "snippet", "thought", "garden", "metrics"]
        ticks = [
            TickRecord(timestamp=1000.0 + i * 15.0, category=categories[i % len(categories)])
            for i in range(12)
        ]
        r = loop_health_report(ticks, target_interval=15.0)
        assert r.verdict == "healthy"
        assert r.tick_count == 12


# ===========================================================================
# compare_reports
# ===========================================================================

class TestCompareReports:
    def test_improving(self):
        before = LoopStats(verdict="critical", jitter_std=20.0)
        after = LoopStats(verdict="healthy", jitter_std=2.0)
        assert compare_reports(before, after) == "improving"

    def test_worsening(self):
        before = LoopStats(verdict="healthy", jitter_std=2.0)
        after = LoopStats(verdict="degraded", jitter_std=8.0)
        assert compare_reports(before, after) == "worsening"

    def test_stable(self):
        before = LoopStats(verdict="healthy", jitter_std=2.0)
        after = LoopStats(verdict="healthy", jitter_std=2.5)
        assert compare_reports(before, after) == "stable"

    def test_unknown_before(self):
        before = LoopStats(verdict="unknown")
        after = LoopStats(verdict="healthy")
        assert compare_reports(before, after) == "unknown"

    def test_unknown_after(self):
        before = LoopStats(verdict="healthy")
        after = LoopStats(verdict="unknown")
        assert compare_reports(before, after) == "unknown"

    def test_same_verdict_jitter_improving(self):
        before = LoopStats(verdict="degraded", jitter_std=12.0)
        after = LoopStats(verdict="degraded", jitter_std=8.0)
        assert compare_reports(before, after) == "improving"

    def test_same_verdict_jitter_worsening(self):
        before = LoopStats(verdict="degraded", jitter_std=8.0)
        after = LoopStats(verdict="degraded", jitter_std=12.0)
        assert compare_reports(before, after) == "worsening"
