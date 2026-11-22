"""tests for iamai.event_interval — interval statistics from timestamps.

covers:
  1. _percentile edge cases (empty, single, known values)
  2. compute_intervals with < 2 timestamps (ValueError)
  3. compute_intervals with exact cadence (metronomic)
  4. compute_intervals with jittery cadence
  5. classify_rhythm at all boundary values
  6. IntervalStats.to_dict omits raw intervals
  7. integration: overnight stall pattern produces expected statistics
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from iamai.event_interval import (
    IntervalStats,
    _percentile,
    compute_intervals,
    classify_rhythm,
)


# ---------------------------------------------------------------------------
# _percentile
# ---------------------------------------------------------------------------

class TestPercentile:
    def test_empty_returns_zero(self):
        assert _percentile([], 50) == 0.0

    def test_single_element_any_percentile(self):
        assert _percentile([42.0], 0) == 42.0
        assert _percentile([42.0], 50) == 42.0
        assert _percentile([42.0], 100) == 42.0

    def test_two_elements_p50(self):
        # p50 of [10, 20] should be 15.0 (linear interpolation)
        assert _percentile([10.0, 20.0], 50) == 15.0

    def test_known_percentiles(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        # p0 = min, p100 = max
        assert _percentile(data, 0) == 1.0
        assert _percentile(data, 100) == 10.0
        # p50 = median area
        assert abs(_percentile(data, 50) - 5.5) < 0.01

    def test_p95_small_list(self):
        data = [10.0, 20.0, 30.0]
        # k = (3-1)*0.95 = 1.9 → interpolate between index 1 and 2
        # 20 + 0.9*(30-20) = 29.0
        assert abs(_percentile(data, 95) - 29.0) < 0.01

    def test_p99_small_list(self):
        data = [10.0, 20.0, 30.0]
        # k = (3-1)*0.99 = 1.98 → 20 + 0.98*10 = 29.8
        assert abs(_percentile(data, 99) - 29.8) < 0.01

    def test_percentile_at_boundary(self):
        # when c >= n, returns last element
        data = [5.0, 10.0]
        assert _percentile(data, 100) == 10.0


# ---------------------------------------------------------------------------
# compute_intervals — error cases
# ---------------------------------------------------------------------------

class TestComputeIntervalsErrors:
    def test_empty_raises_value_error(self):
        with pytest.raises(ValueError, match="need ≥ 2"):
            compute_intervals([])

    def test_single_timestamp_raises_value_error(self):
        with pytest.raises(ValueError, match="need ≥ 2"):
            compute_intervals([datetime(2026, 1, 1)])

    def test_error_message_includes_count(self):
        with pytest.raises(ValueError, match="got 1"):
            compute_intervals([datetime(2026, 1, 1)])


# ---------------------------------------------------------------------------
# compute_intervals — metronomic (perfect cadence)
# ---------------------------------------------------------------------------

class TestComputeIntervalsMetronomic:
    def test_perfect_15s_cadence(self):
        base = datetime(2026, 11, 22, 4, 0, 0)
        timestamps = [base + timedelta(seconds=15 * i) for i in range(10)]
        stats = compute_intervals(timestamps)

        assert stats.count == 10
        assert len(stats.intervals) == 9
        assert stats.min_s == 15.0
        assert stats.max_s == 15.0
        assert stats.mean_s == 15.0
        assert stats.median_s == 15.0
        assert stats.cv == 0.0  # no variation at all

    def test_perfect_600s_cadence(self):
        base = datetime(2026, 11, 22, 0, 0, 0)
        timestamps = [base + timedelta(seconds=600 * i) for i in range(5)]
        stats = compute_intervals(timestamps)

        assert stats.count == 5
        assert stats.mean_s == 600.0
        assert stats.cv == 0.0

    def test_two_timestamps_exact(self):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 1, 1, 0, 0, 30)
        stats = compute_intervals([t1, t2])

        assert stats.count == 2
        assert stats.intervals == [30.0]
        assert stats.mean_s == 30.0
        assert stats.cv == 0.0  # stdev of single value is 0.0


# ---------------------------------------------------------------------------
# compute_intervals — jittery cadence
# ---------------------------------------------------------------------------

class TestComputeIntervalsJitter:
    def test_mixed_intervals(self):
        base = datetime(2026, 11, 22, 0, 0, 0)
        # intervals: 10, 20, 30, 40 seconds
        offsets = [0, 10, 30, 60, 100]
        timestamps = [base + timedelta(seconds=o) for o in offsets]
        stats = compute_intervals(timestamps)

        assert stats.count == 5
        assert stats.min_s == 10.0
        assert stats.max_s == 40.0
        assert stats.mean_s == 25.0  # (10+20+30+40)/4
        assert stats.median_s == 25.0  # median of [10,20,30,40]

    def test_cv_positive_with_variation(self):
        base = datetime(2026, 1, 1)
        # very uneven: 1s, 1s, 1s, 100s
        offsets = [0, 1, 2, 3, 103]
        timestamps = [base + timedelta(seconds=o) for o in offsets]
        stats = compute_intervals(timestamps)

        assert stats.cv > 0.5  # high variation expected

    def test_unsorted_input_still_works(self):
        # compute_intervals sorts internally
        t1 = datetime(2026, 1, 1, 0, 0, 30)
        t2 = datetime(2026, 1, 1, 0, 0, 0)
        t3 = datetime(2026, 1, 1, 0, 0, 15)
        stats = compute_intervals([t1, t2, t3])

        # sorted: 0, 15, 30 → intervals [15, 15]
        assert stats.intervals == [15.0, 15.0]
        assert stats.cv == 0.0


# ---------------------------------------------------------------------------
# compute_intervals — rounding
# ---------------------------------------------------------------------------

class TestComputeIntervalsRounding:
    def test_mean_rounded_to_two_decimals(self):
        base = datetime(2026, 1, 1)
        # intervals: 10, 20, 30 → mean = 20.0 (exact)
        offsets = [0, 10, 30, 60]
        timestamps = [base + timedelta(seconds=o) for o in offsets]
        stats = compute_intervals(timestamps)

        # mean_s should be rounded to 2 decimals
        assert stats.mean_s == round(stats.mean_s, 2)
        assert stats.median_s == round(stats.median_s, 2)
        assert stats.p95_s == round(stats.p95_s, 2)
        assert stats.p99_s == round(stats.p99_s, 2)

    def test_cv_rounded_to_four_decimals(self):
        base = datetime(2026, 1, 1)
        offsets = [0, 10, 25, 35, 60]
        timestamps = [base + timedelta(seconds=o) for o in offsets]
        stats = compute_intervals(timestamps)

        assert stats.cv == round(stats.cv, 4)


# ---------------------------------------------------------------------------
# classify_rhythm
# ---------------------------------------------------------------------------

class TestClassifyRhythm:
    def test_metronomic_at_zero(self):
        assert classify_rhythm(0.0) == "metronomic"

    def test_metronomic_just_below_boundary(self):
        assert classify_rhythm(0.14) == "metronomic"
        assert classify_rhythm(0.149) == "metronomic"

    def test_metronomic_at_boundary(self):
        # 0.15 is NOT metronomic — the rule is cv < 0.15
        assert classify_rhythm(0.15) == "steady"

    def test_steady_mid_range(self):
        assert classify_rhythm(0.20) == "steady"
        assert classify_rhythm(0.30) == "steady"
        assert classify_rhythm(0.39) == "steady"

    def test_steady_at_boundary(self):
        # 0.40 is NOT steady — the rule is cv < 0.40
        assert classify_rhythm(0.40) == "uneven"

    def test_uneven_mid_range(self):
        assert classify_rhythm(0.50) == "uneven"
        assert classify_rhythm(0.70) == "uneven"
        assert classify_rhythm(0.79) == "uneven"

    def test_uneven_at_boundary(self):
        # 0.80 is NOT uneven — the rule is cv < 0.80
        assert classify_rhythm(0.80) == "erratic"

    def test_erratic_high_values(self):
        assert classify_rhythm(0.80) == "erratic"
        assert classify_rhythm(1.0) == "erratic"
        assert classify_rhythm(2.5) == "erratic"
        assert classify_rhythm(100.0) == "erratic"

    def test_all_boundary_values(self):
        # exact boundary sweep
        boundaries = [
            (0.00, "metronomic"),
            (0.14, "metronomic"),
            (0.15, "steady"),
            (0.39, "steady"),
            (0.40, "uneven"),
            (0.79, "uneven"),
            (0.80, "erratic"),
            (1.00, "erratic"),
        ]
        for cv, expected in boundaries:
            assert classify_rhythm(cv) == expected, f"cv={cv} should be {expected}"


# ---------------------------------------------------------------------------
# IntervalStats.to_dict
# ---------------------------------------------------------------------------

class TestIntervalStatsToDict:
    def test_omits_raw_intervals(self):
        base = datetime(2026, 1, 1)
        timestamps = [base + timedelta(seconds=15 * i) for i in range(5)]
        stats = compute_intervals(timestamps)
        d = stats.to_dict()

        assert "intervals" not in d
        assert "count" in d
        assert "mean_s" in d
        assert "cv" in d

    def test_dict_has_all_summary_fields(self):
        base = datetime(2026, 1, 1)
        timestamps = [base + timedelta(seconds=15 * i) for i in range(5)]
        stats = compute_intervals(timestamps)
        d = stats.to_dict()

        expected_keys = {"count", "min_s", "max_s", "mean_s", "median_s",
                         "p95_s", "p99_s", "cv"}
        assert set(d.keys()) == expected_keys


# ---------------------------------------------------------------------------
# integration: overnight stall scenario
# ---------------------------------------------------------------------------

class TestIntegrationOvernightStall:
    def test_overnight_stall_produces_high_cv(self):
        """simulate normal 15s cadence, then a 3000s stall, then resume."""
        base = datetime(2026, 11, 22, 0, 0, 0)
        timestamps = []

        # 20 normal strokes at 15s cadence
        for i in range(20):
            timestamps.append(base + timedelta(seconds=15 * i))

        # stall: jump 3000 seconds
        stall_end = timestamps[-1] + timedelta(seconds=3000)

        # 20 more normal strokes at 15s cadence after stall
        for i in range(20):
            timestamps.append(stall_end + timedelta(seconds=15 * i))

        stats = compute_intervals(timestamps)

        # the 3000s gap should dominate statistics
        assert stats.max_s >= 3000.0
        assert stats.min_s == 15.0
        assert stats.cv > 1.0  # extremely high variation
        assert classify_rhythm(stats.cv) == "erratic"

    def test_steady_writer_low_cv(self):
        """simulate a writer with small jitter (±1s) around 15s cadence."""
        base = datetime(2026, 11, 22, 0, 0, 0)
        jitter_pattern = [0, 15, 30, 46, 61, 76, 92, 107, 122, 138]
        timestamps = [base + timedelta(seconds=s) for s in jitter_pattern]
        stats = compute_intervals(timestamps)

        # intervals are 15, 15, 16, 15, 15, 16, 15, 15, 16 — very steady
        assert stats.cv < 0.15
        assert classify_rhythm(stats.cv) == "metronomic"

    def test_large_dataset_performance(self):
        """1000 timestamps should compute without issues."""
        base = datetime(2026, 1, 1)
        timestamps = [base + timedelta(seconds=15 * i) for i in range(1000)]
        stats = compute_intervals(timestamps)

        assert stats.count == 1000
        assert len(stats.intervals) == 999
        assert stats.mean_s == 15.0


# ---------------------------------------------------------------------------
# classify_rhythm integration with compute_intervals
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_metronomic_writer(self):
        base = datetime(2026, 1, 1)
        timestamps = [base + timedelta(seconds=15 * i) for i in range(50)]
        stats = compute_intervals(timestamps)
        assert classify_rhythm(stats.cv) == "metronomic"

    def test_uneven_writer(self):
        base = datetime(2026, 1, 1)
        # alternate between 5s and 25s gaps → mean=15, high variance
        timestamps = [base]
        for i in range(20):
            gap = 5 if i % 2 == 0 else 25
            timestamps.append(timestamps[-1] + timedelta(seconds=gap))
        stats = compute_intervals(timestamps)
        # cv should be significant due to alternating pattern
        assert stats.cv > 0.40
        rhythm = classify_rhythm(stats.cv)
        assert rhythm in ("uneven", "erratic")
