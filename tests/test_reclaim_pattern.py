"""Tests for iamai.reclaim_pattern — periodicity detection in process deaths."""

import pytest

from iamai.reclaim_pattern import (
    ReclaimAnalyzer,
    analyze_deaths,
    cycle_estimate,
    is_periodic,
)


# ---------------------------------------------------------------------------
# Data ingestion
# ---------------------------------------------------------------------------

class TestLoadEvents:
    def test_empty_load(self):
        a = ReclaimAnalyzer()
        a.load_events([])
        assert a.event_count == 0
        assert a.gap_count == 0

    def test_single_event(self):
        a = ReclaimAnalyzer()
        a.load_events([1000.0])
        assert a.event_count == 1
        assert a.gap_count == 0

    def test_two_events(self):
        a = ReclaimAnalyzer()
        a.load_events([1000.0, 2000.0])
        assert a.event_count == 2
        assert a.gap_count == 1
        assert a.gaps() == [1000.0]

    def test_unsorted_input(self):
        a = ReclaimAnalyzer()
        a.load_events([3000.0, 1000.0, 2000.0])
        assert a.timestamps == [1000.0, 2000.0, 3000.0]
        assert a.gaps() == [1000.0, 1000.0]

    def test_duplicate_removal(self):
        a = ReclaimAnalyzer()
        a.load_events([1000.0, 1000.0, 2000.0])
        assert a.event_count == 2
        assert a.gaps() == [1000.0]

    def test_add_event(self):
        a = ReclaimAnalyzer()
        a.load_events([1000.0, 2000.0])
        a.add_event(3000.0)
        assert a.event_count == 3
        assert a.gaps() == [1000.0, 1000.0]

    def test_add_duplicate_event(self):
        a = ReclaimAnalyzer()
        a.load_events([1000.0, 2000.0])
        a.add_event(2000.0)
        assert a.event_count == 2

    def test_add_event_unsorted(self):
        a = ReclaimAnalyzer()
        a.load_events([1000.0, 3000.0])
        a.add_event(2000.0)
        assert a.timestamps == [1000.0, 2000.0, 3000.0]
        assert a.gaps() == [1000.0, 1000.0]


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------

class TestCoreMetrics:
    def test_mean_gap_empty(self):
        a = ReclaimAnalyzer()
        assert a.mean_gap() == 0.0

    def test_mean_gap_single_gap(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 3600])
        assert a.mean_gap() == 3600.0

    def test_mean_gap_multiple(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 3600, 7200, 10800])
        assert a.mean_gap() == 3600.0

    def test_median_gap_even_count(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 1000, 3000, 6000])  # gaps: 1000, 2000, 3000
        assert a.median_gap() == 2000.0

    def test_median_gap_odd_count(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 1000, 2000, 4000, 8000])  # gaps: 1000, 1000, 2000, 4000
        assert a.median_gap() == 1500.0

    def test_stdev_gap_insufficient(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 3600])
        assert a.stdev_gap() == 0.0

    def test_stdev_gap_uniform(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 3600, 7200, 10800])  # all gaps 3600
        assert a.stdev_gap() == 0.0

    def test_stdev_gap_variable(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 1000, 3000, 6000])  # gaps: 1000, 2000, 3000
        # mean=2000, stdev=1000
        assert abs(a.stdev_gap() - 1000.0) < 1e-6

    def test_coefficient_of_variation_uniform(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 3600, 7200, 10800])
        assert a.coefficient_of_variation() == 0.0

    def test_coefficient_of_variation_variable(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 1000, 3000, 6000])  # mean=2000, stdev=1000
        assert abs(a.coefficient_of_variation() - 0.5) < 1e-6

    def test_gaps_minutes(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 3600, 7200])
        assert a.gaps_minutes() == [60.0, 60.0]


# ---------------------------------------------------------------------------
# Pattern classification
# ---------------------------------------------------------------------------

class TestPatternClassification:
    def test_insufficient_data_zero_gaps(self):
        a = ReclaimAnalyzer()
        a.load_events([1000])
        assert a.classify_pattern() == "insufficient_data"

    def test_insufficient_data_one_gap(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 3600])
        assert a.classify_pattern() == "insufficient_data"

    def test_periodic_perfect(self):
        """All gaps exactly 3600s — CV = 0."""
        a = ReclaimAnalyzer()
        a.load_events([0, 3600, 7200, 10800, 14400])
        assert a.classify_pattern() == "periodic"

    def test_periodic_near_perfect(self):
        """Gaps with <1% variation."""
        a = ReclaimAnalyzer()
        # gaps: 3600, 3610, 3590, 3605, 3595 → stdev ≈ 7.9, mean ≈ 3600
        a.load_events([0, 3600, 7210, 10800, 14405, 18000])
        assert a.classify_pattern() == "periodic"

    def test_quasi_periodic(self):
        """Gaps with moderate variation (~20-30% CV)."""
        a = ReclaimAnalyzer()
        # gaps: 3600, 2400, 4800, 3000, 4200 → mean=3600, stdev≈916, CV≈0.25
        a.load_events([0, 3600, 6000, 10800, 13800, 18000])
        result = a.classify_pattern()
        assert result in ("quasi-periodic", "irregular")

    def test_irregular(self):
        """Completely random gaps — high CV."""
        a = ReclaimAnalyzer()
        # gaps: 100, 9900, 50, 19950 → wildly variable
        a.load_events([0, 100, 10000, 10050, 30000])
        assert a.classify_pattern() == "irregular"

    def test_custom_thresholds(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 1000, 3000, 6000])  # CV = 0.5
        # With very generous thresholds, this could be "periodic"
        assert a.classify_pattern(periodic_threshold=0.6) == "periodic"
        # With strict thresholds, same data is "irregular"
        assert a.classify_pattern(periodic_threshold=0.01, quasi_threshold=0.05) == "irregular"


# ---------------------------------------------------------------------------
# Trend detection
# ---------------------------------------------------------------------------

class TestTrend:
    def test_insufficient_data(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 3600, 7200])  # 2 gaps, need 4
        assert a.trend(window=4) == "insufficient_data"

    def test_stable_trend(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 3600, 7200, 10800, 14400, 18000])
        assert a.trend() == "stable"

    def test_shortening_trend(self):
        """Recent gaps are much smaller than overall average."""
        a = ReclaimAnalyzer()
        # gaps: 7200, 7200, 7200, 1800, 1800, 1800, 1800
        # overall mean ≈ 4114, last 4 mean = 1800 → ratio ≈ 0.44
        a.load_events([0, 7200, 14400, 21600, 23400, 25200, 27000, 28800])
        assert a.trend(window=4) == "shortening"

    def test_lengthening_trend(self):
        """Recent gaps are much larger than overall average."""
        a = ReclaimAnalyzer()
        # gaps: 1800, 1800, 1800, 1800, 7200, 7200, 7200, 7200
        # overall mean = 4500, last 4 mean = 7200 → ratio = 1.6
        a.load_events([0, 1800, 3600, 5400, 7200, 14400, 21600, 28800, 36000])
        assert a.trend(window=4) == "lengthening"


# ---------------------------------------------------------------------------
# Cycle estimation
# ---------------------------------------------------------------------------

class TestCycleEstimation:
    def test_cycle_seconds_no_data(self):
        a = ReclaimAnalyzer()
        assert a.cycle_seconds() == 0.0

    def test_cycle_seconds_hourly(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 3600, 7200, 10800, 14400])
        assert a.cycle_seconds() == 3600.0

    def test_cycle_minutes(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 3600, 7200, 10800])
        assert a.cycle_minutes() == 60.0

    def test_cycle_with_outlier(self):
        """Median is robust to outliers."""
        a = ReclaimAnalyzer()
        # gaps: 3600, 3600, 3600, 36000 (one huge gap)
        a.load_events([0, 3600, 7200, 10800, 46800])
        assert a.cycle_seconds() == 3600.0  # median is 3600


# ---------------------------------------------------------------------------
# Outlier detection
# ---------------------------------------------------------------------------

class TestOutliers:
    def test_no_outliers_uniform(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 3600, 7200, 10800])
        assert a.outliers() == []

    def test_detects_large_gap(self):
        a = ReclaimAnalyzer()
        # gaps: 3600, 3600, 36000, 3600 → median=3600, threshold=7200
        a.load_events([0, 3600, 7200, 43200, 46800])
        assert a.outliers() == [2]  # index 2 is the 36000 gap

    def test_custom_factor(self):
        a = ReclaimAnalyzer()
        # gaps: 3600, 3600, 10800, 3600 → median=3600
        a.load_events([0, 3600, 7200, 18000, 21600])
        # factor=2 → threshold=7200; gap 10800 ≥ 7200 → outlier
        assert 2 in a.outliers(factor=2.0)
        # factor=5 → threshold=18000; gap 10800 < 18000 → not outlier
        assert a.outliers(factor=5.0) == []

    def test_empty_data(self):
        a = ReclaimAnalyzer()
        assert a.outliers() == []


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

class TestReport:
    def test_report_structure(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 3600, 7200, 10800, 14400])
        r = a.report()
        assert r["event_count"] == 5
        assert r["gap_count"] == 4
        assert r["mean_gap_s"] == 3600.0
        assert r["median_gap_s"] == 3600.0
        assert r["stdev_gap_s"] == 0.0
        assert r["cv"] == 0.0
        assert r["pattern"] == "periodic"
        assert r["cycle_seconds"] == 3600.0
        assert r["cycle_minutes"] == 60.0
        assert r["trend"] == "stable"
        assert r["outlier_indices"] == []

    def test_report_insufficient_data(self):
        a = ReclaimAnalyzer()
        a.load_events([100])
        r = a.report()
        assert r["pattern"] == "insufficient_data"
        assert r["trend"] == "insufficient_data"

    def test_report_with_variation(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 1000, 3000, 6000])  # gaps: 1000, 2000, 3000
        r = a.report()
        assert r["cv"] > 0
        assert r["pattern"] == "irregular"
        assert r["trend"] == "insufficient_data"  # only 3 gaps, window=4


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

class TestConvenienceFunctions:
    def test_analyze_deaths(self):
        r = analyze_deaths([0, 3600, 7200, 10800, 14400])
        assert r["pattern"] == "periodic"
        assert r["cycle_minutes"] == 60.0

    def test_analyze_deaths_empty(self):
        r = analyze_deaths([])
        assert r["event_count"] == 0
        assert r["pattern"] == "insufficient_data"

    def test_is_periodic_true(self):
        assert is_periodic([0, 3600, 7200, 10800, 14400]) is True

    def test_is_periodic_false(self):
        assert is_periodic([0, 100, 10000, 10050, 30000]) is False

    def test_is_periodic_insufficient(self):
        assert is_periodic([0, 3600]) is False

    def test_cycle_estimate(self):
        assert cycle_estimate([0, 3600, 7200, 10800]) == 3600.0

    def test_cycle_estimate_empty(self):
        assert cycle_estimate([]) == 0.0

    def test_cycle_estimate_single(self):
        assert cycle_estimate([42]) == 0.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_timestamps(self):
        a = ReclaimAnalyzer()
        a.load_events([0, 0, 0])  # all same → deduped to one
        assert a.event_count == 1
        assert a.gap_count == 0

    def test_negative_timestamps(self):
        """Negative timestamps are valid (relative to epoch)."""
        a = ReclaimAnalyzer()
        a.load_events([-7200, -3600, 0, 3600])
        assert a.gaps() == [3600.0, 3600.0, 3600.0]
        assert a.classify_pattern() == "periodic"

    def test_very_large_timestamps(self):
        a = ReclaimAnalyzer()
        base = 1728000000  # ~2024 epoch
        a.load_events([base, base + 3600, base + 7200, base + 10800])
        assert a.cycle_seconds() == 3600.0

    def test_fractional_timestamps(self):
        a = ReclaimAnalyzer()
        a.load_events([0.5, 1.5, 2.5, 3.5])
        assert a.gaps() == [1.0, 1.0, 1.0]
        assert a.mean_gap() == 1.0

    def test_two_identical_gaps(self):
        """Exactly two identical gaps — stdev should be 0."""
        a = ReclaimAnalyzer()
        a.load_events([0, 100, 200])
        assert a.stdev_gap() == 0.0
        assert a.coefficient_of_variation() == 0.0
        assert a.classify_pattern() == "periodic"
