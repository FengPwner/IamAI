"""Tests for commit_velocity module.

Covers: timestamp parsing, gap computation, linear slope, velocity ratio,
burstiness, classification thresholds, edge cases (degenerate inputs,
identical timestamps, single commit), multi-window analysis, and the
VelocityReport.to_dict() serialisation.  28 test functions.

Written by Qwen during caretaker visit 723, 2026-11-19.
"""

import math
import pytest
from datetime import datetime, timezone, timedelta

from iamai.commit_velocity import (
    VelocityReport,
    _classify,
    _linear_slope,
    _to_epoch,
    _zero_report,
    analyse_velocity,
    analyse_velocity_windows,
)


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

class TestToEpoch:
    def test_epoch_int(self):
        assert _to_epoch(1000) == 1000.0

    def test_epoch_float(self):
        assert _to_epoch(1234.5) == 1234.5

    def test_datetime_naive(self):
        dt = datetime(2026, 1, 1, 0, 0, 0)
        # Naive datetimes are assumed UTC
        expected = dt.replace(tzinfo=timezone.utc).timestamp()
        assert _to_epoch(dt) == expected

    def test_datetime_aware(self):
        dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        assert _to_epoch(dt) == dt.timestamp()

    def test_iso_string_with_z(self):
        ts = "2026-01-01T00:00:00Z"
        result = _to_epoch(ts)
        expected = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
        assert result == expected

    def test_iso_string_with_offset(self):
        ts = "2026-07-01T12:00:00+08:00"
        result = _to_epoch(ts)
        expected = datetime(
            2026, 7, 1, 12, 0, 0,
            tzinfo=timezone(timedelta(hours=8))
        ).timestamp()
        assert result == expected

    def test_iso_string_naive(self):
        ts = "2026-03-15T10:30:00"
        result = _to_epoch(ts)
        # Naive → assumed UTC
        expected = datetime(2026, 3, 15, 10, 30, 0, tzinfo=timezone.utc).timestamp()
        assert result == expected

    def test_invalid_string(self):
        with pytest.raises(ValueError):
            _to_epoch("not-a-date")

    def test_unsupported_type(self):
        with pytest.raises(TypeError):
            _to_epoch([1, 2, 3])


# ---------------------------------------------------------------------------
# Linear slope
# ---------------------------------------------------------------------------

class TestLinearSlope:
    def test_constant(self):
        # All same values → slope = 0
        assert _linear_slope([5.0, 5.0, 5.0, 5.0]) == 0.0

    def test_increasing(self):
        # y = 2*i → slope should be 2
        values = [0.0, 2.0, 4.0, 6.0, 8.0]
        slope = _linear_slope(values)
        assert abs(slope - 2.0) < 1e-9

    def test_decreasing(self):
        # y = 10 - 3*i → slope should be -3
        values = [10.0, 7.0, 4.0, 1.0, -2.0]
        slope = _linear_slope(values)
        assert abs(slope - (-3.0)) < 1e-9

    def test_single_value(self):
        assert _linear_slope([42.0]) == 0.0

    def test_empty(self):
        assert _linear_slope([]) == 0.0

    def test_two_values(self):
        # slope = (1*5 - 0*8) / (1*1 - 0*0) ... let's compute manually
        # x=0,1  y=3,7  slope = (2*(0*3+1*7) - (0+1)*(3+7)) / (2*(0+1) - 1)
        # = (2*7 - 10) / (2 - 1) = 4
        slope = _linear_slope([3.0, 7.0])
        assert abs(slope - 4.0) < 1e-9


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassify:
    def test_accelerating(self):
        assert _classify(2.0) == "accelerating"
        assert _classify(1.5) == "accelerating"

    def test_steady(self):
        assert _classify(1.0) == "steady"
        assert _classify(1.49) == "steady"

    def test_slowing(self):
        assert _classify(0.67) == "slowing"
        assert _classify(0.99) == "slowing"

    def test_stalling(self):
        assert _classify(0.5) == "stalling"
        assert _classify(0.1) == "stalling"


# ---------------------------------------------------------------------------
# Zero report
# ---------------------------------------------------------------------------

class TestZeroReport:
    def test_defaults(self):
        r = _zero_report(0)
        assert r.n_commits == 0
        assert r.n_gaps == 0
        assert r.velocity_ratio == 1.0
        assert r.classification == "steady"

    def test_with_count(self):
        r = _zero_report(5)
        assert r.n_commits == 5
        assert r.burstiness == 0.0


# ---------------------------------------------------------------------------
# analyse_velocity — core functionality
# ---------------------------------------------------------------------------

class TestAnalyseVelocity:
    def test_empty(self):
        r = analyse_velocity([])
        assert r.n_commits == 0
        assert r.classification == "steady"

    def test_single_commit(self):
        r = analyse_velocity([1000])
        assert r.n_commits == 1
        assert r.n_gaps == 0
        assert r.classification == "steady"

    def test_two_commits(self):
        r = analyse_velocity([1000, 1600])
        assert r.n_commits == 2
        assert r.n_gaps == 1
        assert r.mean_gap_seconds == 600.0
        # Single gap → short window = 1 gap, long = same → ratio = 1.0
        assert r.velocity_ratio == 1.0
        assert r.classification == "steady"

    def test_accelerating_pattern(self):
        # Gaps shrink: 1000, 800, 600, 400, 200 → recent is faster
        base = 0
        gaps = [1000, 800, 600, 400, 200]
        ts = [base]
        for g in gaps:
            ts.append(ts[-1] + g)
        r = analyse_velocity(ts, short_fraction=0.4)
        # Long mean = 600, short (last 2) mean = 300 → ratio = 2.0
        assert r.velocity_ratio == 2.0
        assert r.classification == "accelerating"
        assert r.slope_seconds_per_commit < 0  # decreasing gaps

    def test_decelerating_pattern(self):
        # Gaps grow: 200, 400, 600, 800, 1000 → recent is slower
        base = 0
        gaps = [200, 400, 600, 800, 1000]
        ts = [base]
        for g in gaps:
            ts.append(ts[-1] + g)
        r = analyse_velocity(ts, short_fraction=0.4)
        # Long mean = 600, short (last 2) mean = 900 → ratio = 0.667
        assert abs(r.velocity_ratio - (600 / 900)) < 0.01
        assert r.classification == "stalling"
        assert r.slope_seconds_per_commit > 0

    def test_steady_pattern(self):
        # Constant gaps: 500, 500, 500, 500, 500
        ts = [i * 500 for i in range(6)]
        r = analyse_velocity(ts)
        assert r.velocity_ratio == 1.0
        assert r.classification == "steady"
        assert r.slope_seconds_per_commit == 0.0

    def test_burstiness_low(self):
        # Constant gaps → stdev = 0 → burstiness = 0
        ts = [i * 100 for i in range(10)]
        r = analyse_velocity(ts)
        assert r.burstiness == 0.0

    def test_burstiness_high(self):
        # Very irregular gaps: 10, 1000, 10, 1000, 10
        base = 0
        gaps = [10, 1000, 10, 1000, 10]
        ts = [base]
        for g in gaps:
            ts.append(ts[-1] + g)
        r = analyse_velocity(ts)
        # Mean ≈ 406, stdev ≈ 516 → CV ≈ 1.27
        assert r.burstiness > 1.0

    def test_identical_timestamps(self):
        r = analyse_velocity([500, 500, 500])
        assert r.classification == "stalling"
        assert r.mean_gap_seconds == 0.0
        assert r.velocity_ratio == 0.0

    def test_unsorted_input(self):
        # Should handle unsorted timestamps correctly
        ts = [300, 100, 500, 200, 400]
        r = analyse_velocity(ts)
        assert r.n_commits == 5
        # After sorting: 100, 200, 300, 400, 500 → gaps all 100
        assert r.mean_gap_seconds == 100.0
        assert r.classification == "steady"

    def test_iso_string_timestamps(self):
        ts = [
            "2026-11-19T10:00:00Z",
            "2026-11-19T10:10:00Z",
            "2026-11-19T10:20:00Z",
            "2026-11-19T10:30:00Z",
        ]
        r = analyse_velocity(ts)
        assert r.n_commits == 4
        assert r.mean_gap_seconds == 600.0

    def test_short_fraction_edge(self):
        # Only 2 gaps, short_fraction=0.5 → short_n = ceil(0.5*2) = 1
        r = analyse_velocity([0, 100, 300], short_fraction=0.5)
        assert r.n_gaps == 2
        # short window: last 1 gap = [200], mean = 200
        assert r.short_window_mean_seconds == 200.0
        # long: mean of [100, 200] = 150
        assert r.long_window_mean_seconds == 150.0


# ---------------------------------------------------------------------------
# VelocityReport serialisation
# ---------------------------------------------------------------------------

class TestVelocityReport:
    def test_to_dict(self):
        r = VelocityReport(
            n_commits=10,
            n_gaps=9,
            mean_gap_seconds=123.456,
            short_window_mean_seconds=100.123,
            long_window_mean_seconds=123.456,
            velocity_ratio=1.23456,
            slope_seconds_per_commit=-5.6789,
            burstiness=0.8901,
            classification="steady",
        )
        d = r.to_dict()
        assert d["n_commits"] == 10
        assert d["mean_gap_seconds"] == 123.46  # rounded to 2
        assert d["velocity_ratio"] == 1.2346  # rounded to 4
        assert d["slope_seconds_per_commit"] == -5.6789
        assert d["classification"] == "steady"


# ---------------------------------------------------------------------------
# Multi-window analysis
# ---------------------------------------------------------------------------

class TestAnalyseVelocityWindows:
    def test_default_windows(self):
        # 200 commits at constant 60s gaps
        ts = [i * 60 for i in range(200)]
        reports = analyse_velocity_windows(ts)
        assert len(reports) == 3  # default [20, 50, 100]
        for r in reports:
            assert r.classification == "steady"
            assert r.mean_gap_seconds == 60.0

    def test_custom_windows(self):
        ts = [i * 60 for i in range(50)]
        reports = analyse_velocity_windows(ts, window_sizes=[10, 25, 50])
        assert len(reports) == 3
        assert reports[0].n_commits == 10
        assert reports[1].n_commits == 25
        assert reports[2].n_commits == 50

    def test_window_larger_than_data(self):
        ts = [i * 60 for i in range(5)]
        reports = analyse_velocity_windows(ts, window_sizes=[10, 20])
        # Both windows clip to available data
        assert reports[0].n_commits == 5
        assert reports[1].n_commits == 5

    def test_empty_input(self):
        reports = analyse_velocity_windows([])
        assert len(reports) == 3
        for r in reports:
            assert r.n_commits == 0
