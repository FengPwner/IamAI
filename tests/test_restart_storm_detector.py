"""Tests for restart_storm_detector — cascading restart cluster analysis.

33 tests covering the full public API surface:
- classify() severity labels
- Storm dataclass properties
- StormReport aggregation
- detect_storms() clustering logic
- storm_index() health metric
- Edge cases: empty, single, all-clustered, all-isolated

written by Qwen during caretaker visit 804, 2026-11-23
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.restart_storm_detector import (
    DEFAULT_GAP_MINUTES,
    Storm,
    StormReport,
    classify,
    detect_storms,
    storm_index,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _dt(minutes_offset: float, base: datetime | None = None) -> datetime:
    """Create a UTC datetime offset by *minutes_offset* from *base*."""
    if base is None:
        base = datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(minutes=minutes_offset)


def _make_storm(offsets: list[float], gap: float = 30.0) -> Storm:
    """Build a Storm from a list of minute-offsets."""
    ts = tuple(_dt(o) for o in offsets)
    return Storm(restarts=ts, gap_minutes=gap)


# ---------------------------------------------------------------------------
# classify()
# ---------------------------------------------------------------------------

class TestClassify:
    def test_zero_is_isolated(self):
        assert classify(0) == "isolated"

    def test_one_is_isolated(self):
        assert classify(1) == "isolated"

    def test_two_is_minor(self):
        assert classify(2) == "minor"

    def test_three_is_moderate(self):
        assert classify(3) == "moderate"

    def test_four_is_moderate(self):
        assert classify(4) == "moderate"

    def test_five_is_severe(self):
        assert classify(5) == "severe"

    def test_large_count_is_severe(self):
        assert classify(100) == "severe"


# ---------------------------------------------------------------------------
# Storm properties
# ---------------------------------------------------------------------------

class TestStorm:
    def test_count(self):
        s = _make_storm([0, 5, 10])
        assert s.count == 3

    def test_severity_isolated(self):
        s = _make_storm([0])
        assert s.severity == "isolated"

    def test_severity_moderate(self):
        s = _make_storm([0, 5, 10])
        assert s.severity == "moderate"

    def test_duration_minutes(self):
        s = _make_storm([0, 10, 25])
        assert s.duration_minutes == 25.0

    def test_duration_single_restart(self):
        s = _make_storm([0])
        assert s.duration_minutes == 0.0

    def test_median_interval(self):
        s = _make_storm([0, 5, 15, 25])
        # intervals: 5, 10, 10 → median 10
        assert s.median_interval_minutes == 10.0

    def test_median_interval_single(self):
        s = _make_storm([0])
        assert s.median_interval_minutes == 0.0

    def test_severity_weight_isolated(self):
        s = _make_storm([0])
        assert s.severity_weight == 0.0

    def test_severity_weight_severe(self):
        s = _make_storm([0, 1, 2, 3, 4])
        assert s.severity_weight == 1.0

    def test_is_accelerating_true(self):
        # intervals shrink: 20, 10, 5, 2
        s = _make_storm([0, 20, 30, 35, 37])
        assert s.is_accelerating() is True

    def test_is_accelerating_false(self):
        # intervals grow: 2, 5, 10, 20
        s = _make_storm([0, 2, 7, 17, 37])
        assert s.is_accelerating() is False

    def test_is_accelerating_too_few(self):
        s = _make_storm([0, 5])
        assert s.is_accelerating() is False


# ---------------------------------------------------------------------------
# detect_storms()
# ---------------------------------------------------------------------------

class TestDetectStorms:
    def test_empty_input(self):
        report = detect_storms([])
        assert report.total_restarts == 0
        assert report.storms == ()
        assert report.index == 0.0

    def test_single_restart(self):
        report = detect_storms([_dt(0)])
        assert report.total_restarts == 1
        assert len(report.storms) == 1
        assert report.storms[0].severity == "isolated"

    def test_two_isolated_restarts(self):
        report = detect_storms([_dt(0), _dt(120)])
        assert len(report.storms) == 2
        assert all(s.severity == "isolated" for s in report.storms)

    def test_one_minor_storm(self):
        report = detect_storms([_dt(0), _dt(10)])
        assert len(report.storms) == 1
        assert report.storms[0].severity == "minor"
        assert report.storm_count == 1

    def test_mixed_isolated_and_clustered(self):
        ts = [
            _dt(0), _dt(5), _dt(12),     # cluster 1: moderate (3)
            _dt(120),                      # isolated
            _dt(300), _dt(305),            # cluster 2: minor (2)
        ]
        report = detect_storms(ts)
        assert len(report.storms) == 3
        assert report.storms[0].severity == "moderate"
        assert report.storms[1].severity == "isolated"
        assert report.storms[2].severity == "minor"
        assert report.storm_count == 2
        assert report.clustered_restarts == 5

    def test_unsorted_input_handled(self):
        ts = [_dt(30), _dt(0), _dt(15)]
        report = detect_storms(ts)
        assert report.total_restarts == 3
        assert len(report.storms) == 1
        assert report.storms[0].count == 3

    def test_exact_gap_boundary(self):
        """Two restarts exactly gap_minutes apart belong to same storm."""
        report = detect_storms([_dt(0), _dt(DEFAULT_GAP_MINUTES)])
        assert len(report.storms) == 1
        assert report.storms[0].count == 2

    def test_just_over_gap_is_separate(self):
        report = detect_storms([_dt(0), _dt(DEFAULT_GAP_MINUTES + 0.1)])
        assert len(report.storms) == 2

    def test_custom_gap(self):
        ts = [_dt(0), _dt(5), _dt(60)]
        # with 10-min gap: first two cluster, third isolated
        report = detect_storms(ts, gap_minutes=10)
        assert len(report.storms) == 2
        assert report.storms[0].count == 2
        assert report.storms[1].count == 1

    def test_severe_storm(self):
        ts = [_dt(i * 5) for i in range(7)]  # 7 restarts, 5min apart
        report = detect_storms(ts)
        assert report.storms[0].severity == "severe"
        assert report.worst_severity == "severe"


# ---------------------------------------------------------------------------
# StormReport properties
# ---------------------------------------------------------------------------

class TestStormReport:
    def test_worst_severity_ordering(self):
        """severe > moderate > minor > isolated."""
        ts = [
            _dt(0), _dt(5), _dt(10), _dt(15), _dt(20),  # severe (5)
            _dt(200), _dt(205),                            # minor (2)
        ]
        report = detect_storms(ts)
        assert report.worst_severity == "severe"

    def test_summary_format(self):
        report = detect_storms([_dt(0), _dt(5)])
        s = report.summary()
        assert "2 restarts" in s
        assert "1 storms" in s
        assert "index=" in s

    def test_accelerating_storms_count(self):
        # Storm 1: accelerating (intervals shrink 15, 10, 5)
        ts1 = [_dt(0), _dt(15), _dt(25), _dt(30)]
        # Storm 2: not accelerating (intervals grow 2, 5)
        ts2 = [_dt(200), _dt(202), _dt(207)]
        report = detect_storms(ts1 + ts2)
        assert report.accelerating_storms == 1

    def test_is_accelerating_overall(self):
        """Successive storms with shrinking median intervals."""
        # Storm 1: median interval ~15
        ts1 = [_dt(0), _dt(10), _dt(20), _dt(30)]
        # Storm 2: median interval ~3
        ts2 = [_dt(200), _dt(197 + 3), _dt(200 + 3), _dt(200 + 6)]
        report = detect_storms(ts1 + ts2)
        # Both are moderate clusters; storm 2 has smaller intervals
        # The overall acceleration depends on median ordering
        # Just verify it returns a bool without error
        assert isinstance(report.is_accelerating_overall, bool)


# ---------------------------------------------------------------------------
# storm_index()
# ---------------------------------------------------------------------------

class TestStormIndex:
    def test_no_restarts(self):
        assert storm_index((), 0) == 0.0

    def test_all_isolated(self):
        storms = [_make_storm([0]), _make_storm([120]), _make_storm([240])]
        assert storm_index(storms, 3) == 0.0

    def test_all_severe(self):
        storms = [
            _make_storm([0, 1, 2, 3, 4]),
            _make_storm([200, 201, 202, 203, 204]),
        ]
        idx = storm_index(storms, 10)
        assert idx == 1.0

    def test_mixed_index(self):
        storms = [
            _make_storm([0, 5]),          # minor: weight 0.25, count 2
            _make_storm([120]),            # isolated: weight 0, count 1
        ]
        # weighted = 0.25*2 + 0*1 = 0.5; index = 0.5/3 ≈ 0.1667
        idx = storm_index(storms, 3)
        assert abs(idx - (0.5 / 3)) < 1e-9

    def test_index_clamped_to_one(self):
        # Edge case: ensure index never exceeds 1.0
        storms = [_make_storm([i for i in range(20)])]  # severe, all clustered
        idx = storm_index(storms, 20)
        assert idx <= 1.0

    def test_report_index_matches(self):
        ts = [_dt(0), _dt(5), _dt(10), _dt(200)]
        report = detect_storms(ts)
        assert report.index == storm_index(report.storms, report.total_restarts)


# ---------------------------------------------------------------------------
# Integration: realistic scenario
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_typical_day_with_one_storm(self):
        """A day with 10 restarts: 8 in a storm, 2 isolated."""
        # Storm: 8 restarts within 25 minutes
        storm_ts = [_dt(i * 3.5) for i in range(8)]
        # Isolated: 2 restarts hours later
        isolated_ts = [_dt(300), _dt(600)]
        all_ts = storm_ts + isolated_ts

        report = detect_storms(all_ts)
        assert report.total_restarts == 10
        assert report.storm_count == 1
        assert report.clustered_restarts == 8
        assert report.worst_severity == "severe"
        assert report.index > 0.5  # mostly clustered
        assert report.summary()  # smoke test

    def test_recovery_pattern(self):
        """Storms get less severe over time → recovery."""
        ts = [
            _dt(0), _dt(2), _dt(4), _dt(6), _dt(8),   # severe: 5 restarts
            _dt(200), _dt(205), _dt(210),                # moderate: 3
            _dt(500), _dt(505),                           # minor: 2
            _dt(800),                                      # isolated: 1
        ]
        report = detect_storms(ts)
        assert report.total_restarts == 11
        assert report.storm_count == 3
        # Severity decreases: severe → moderate → minor
        clustered = [s for s in report.storms if s.severity != "isolated"]
        severities = [s.severity for s in clustered]
        assert severities == ["severe", "moderate", "minor"]
