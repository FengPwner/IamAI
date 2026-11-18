"""Tests for restart_cascade_detector module.

Covers: RestartEvent construction, RestartCascade properties,
RestartCascadeDetector lifecycle (record, clear, detect), cascade
grouping logic, severity classification, CascadeReport metrics,
edge cases (empty, single, all-isolated, all-cascade, identical
timestamps), and module-level convenience functions.
"""

import pytest

from iamai.restart_cascade_detector import (
    CascadeReport,
    RestartCascade,
    RestartCascadeDetector,
    RestartEvent,
    classify,
    clear,
    detect,
    record,
)


# ---------------------------------------------------------------------------
# RestartEvent
# ---------------------------------------------------------------------------

class TestRestartEvent:
    def test_basic_creation(self):
        e = RestartEvent(timestamp=10.0, process="writer")
        assert e.timestamp == 10.0
        assert e.process == "writer"
        assert e.pid is None

    def test_with_pid(self):
        e = RestartEvent(timestamp=5.0, process="batch", pid=1234)
        assert e.pid == 1234


# ---------------------------------------------------------------------------
# RestartCascade
# ---------------------------------------------------------------------------

class TestRestartCascade:
    def test_empty_cascade(self):
        c = RestartCascade()
        assert c.depth == 0
        assert c.duration == 0.0
        assert c.processes == []
        assert c.start_time == 0.0

    def test_single_event(self):
        e = RestartEvent(timestamp=100.0, process="writer")
        c = RestartCascade(events=[e])
        assert c.depth == 1
        assert c.duration == 0.0
        assert c.processes == ["writer"]
        assert c.start_time == 100.0

    def test_multiple_events(self):
        events = [
            RestartEvent(timestamp=0.0, process="writer"),
            RestartEvent(timestamp=5.0, process="batch"),
            RestartEvent(timestamp=10.0, process="supervisor"),
        ]
        c = RestartCascade(events=events)
        assert c.depth == 3
        assert c.duration == 10.0
        assert c.processes == ["writer", "batch", "supervisor"]
        assert c.start_time == 0.0


# ---------------------------------------------------------------------------
# Detector — lifecycle
# ---------------------------------------------------------------------------

class TestRestartCascadeDetector:
    def test_empty_detector(self):
        d = RestartCascadeDetector()
        report = d.detect()
        assert report.total_restarts == 0
        assert report.cascade_count == 0
        assert report.coordination_score == 100.0

    def test_invalid_window(self):
        with pytest.raises(ValueError):
            RestartCascadeDetector(window_seconds=0)
        with pytest.raises(ValueError):
            RestartCascadeDetector(window_seconds=-5)

    def test_record_returns_event(self):
        d = RestartCascadeDetector()
        e = d.record(1.0, "writer", pid=42)
        assert isinstance(e, RestartEvent)
        assert e.pid == 42

    def test_record_event_object(self):
        d = RestartCascadeDetector()
        original = RestartEvent(timestamp=1.0, process="writer")
        returned = d.record(original, "")  # ignored fields
        assert returned is original
        assert len(d.events) == 1

    def test_clear(self):
        d = RestartCascadeDetector()
        d.record(1.0, "writer")
        d.record(2.0, "batch")
        assert len(d.events) == 2
        d.clear()
        assert len(d.events) == 0

    def test_events_returns_copy(self):
        d = RestartCascadeDetector()
        d.record(1.0, "writer")
        copy = d.events
        copy.append(RestartEvent(99.0, "fake"))
        assert len(d.events) == 1  # original untouched


# ---------------------------------------------------------------------------
# Detector — cascade grouping
# ---------------------------------------------------------------------------

class TestCascadeGrouping:
    def test_two_events_within_window(self):
        d = RestartCascadeDetector(window_seconds=30.0)
        d.record(0.0, "writer")
        d.record(10.0, "batch")
        report = d.detect()
        assert report.cascade_count == 1
        assert report.max_cascade_depth == 2

    def test_two_events_outside_window(self):
        d = RestartCascadeDetector(window_seconds=10.0)
        d.record(0.0, "writer")
        d.record(100.0, "batch")
        report = d.detect()
        assert report.cascade_count == 0
        assert report.isolated_restarts == 2  # two depth-1 groups

    def test_three_events_spanning_window(self):
        d = RestartCascadeDetector(window_seconds=30.0)
        d.record(0.0, "writer")
        d.record(15.0, "batch")
        d.record(29.0, "supervisor")
        report = d.detect()
        assert report.cascade_count == 1
        assert report.max_cascade_depth == 3
        assert report.mean_cascade_depth == 3.0

    def test_mixed_cascades_and_isolated(self):
        d = RestartCascadeDetector(window_seconds=10.0)
        # cascade 1: depth 2
        d.record(0.0, "writer")
        d.record(5.0, "batch")
        # isolated
        d.record(100.0, "writer")
        # cascade 2: depth 2
        d.record(200.0, "writer")
        d.record(205.0, "batch")
        report = d.detect()
        assert report.cascade_count == 2
        assert report.isolated_restarts == 1  # one depth-1 group
        assert report.total_restarts == 5

    def test_unsorted_input(self):
        d = RestartCascadeDetector(window_seconds=30.0)
        d.record(10.0, "batch")
        d.record(0.0, "writer")
        d.record(5.0, "supervisor")
        report = d.detect()
        assert report.cascade_count == 1
        assert report.max_cascade_depth == 3


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------

class TestClassify:
    def test_clean(self):
        assert RestartCascadeDetector.classify(1) == "clean"
        assert RestartCascadeDetector.classify(0) == "clean"

    def test_minor(self):
        assert RestartCascadeDetector.classify(2) == "minor"
        assert RestartCascadeDetector.classify(3) == "minor"

    def test_major(self):
        assert RestartCascadeDetector.classify(4) == "major"
        assert RestartCascadeDetector.classify(5) == "major"

    def test_catastrophic(self):
        assert RestartCascadeDetector.classify(6) == "catastrophic"
        assert RestartCascadeDetector.classify(100) == "catastrophic"

    def test_custom_thresholds(self):
        assert RestartCascadeDetector.classify(3, minor=3, major=5, catastrophic=8) == "minor"
        assert RestartCascadeDetector.classify(5, minor=3, major=5, catastrophic=8) == "major"
        assert RestartCascadeDetector.classify(8, minor=3, major=5, catastrophic=8) == "catastrophic"
        assert RestartCascadeDetector.classify(2, minor=3, major=5, catastrophic=8) == "clean"

    def test_module_level_classify(self):
        assert classify(1) == "clean"
        assert classify(3) == "minor"
        assert classify(5) == "major"
        assert classify(7) == "catastrophic"


# ---------------------------------------------------------------------------
# CascadeReport metrics
# ---------------------------------------------------------------------------

class TestCascadeReport:
    def test_default_values(self):
        r = CascadeReport()
        assert r.total_restarts == 0
        assert r.coordination_score == 100.0
        assert r.cascade_fraction == 0.0
        assert r.largest_cascades == []

    def test_coordination_score_all_cascade(self):
        d = RestartCascadeDetector(window_seconds=30.0)
        # 6 events in one cascade
        for i in range(6):
            d.record(float(i), f"proc_{i}")
        report = d.detect()
        assert report.coordination_score == 0.0
        assert report.cascade_fraction == 1.0

    def test_coordination_score_half(self):
        d = RestartCascadeDetector(window_seconds=10.0)
        d.record(0.0, "writer")
        d.record(5.0, "batch")
        d.record(100.0, "writer")
        d.record(200.0, "writer")
        report = d.detect()
        assert report.cascade_fraction == 0.5
        assert report.coordination_score == 50.0

    def test_mean_time_between_cascades(self):
        d = RestartCascadeDetector(window_seconds=10.0)
        # cascade 1 at t=0
        d.record(0.0, "writer")
        d.record(5.0, "batch")
        # cascade 2 at t=100
        d.record(100.0, "writer")
        d.record(105.0, "batch")
        # cascade 3 at t=200
        d.record(200.0, "writer")
        d.record(205.0, "batch")
        report = d.detect()
        assert report.cascade_count == 3
        assert report.mean_time_between_cascades == 100.0

    def test_mean_cascade_duration(self):
        d = RestartCascadeDetector(window_seconds=30.0)
        d.record(0.0, "writer")
        d.record(10.0, "batch")
        d.record(100.0, "writer")
        d.record(120.0, "batch")
        report = d.detect()
        # Both cascades have duration 10 and 20 → mean = 15
        assert report.mean_cascade_duration == 15.0

    def test_largest_cascades_limited_to_three(self):
        d = RestartCascadeDetector(window_seconds=10.0, minor_threshold=2)
        for i in range(5):
            base = i * 100.0
            d.record(base, "writer")
            d.record(base + 1.0, "batch")
        report = d.detect()
        assert len(report.largest_cascades) == 3

    def test_largest_cascades_sorted_by_depth(self):
        d = RestartCascadeDetector(window_seconds=10.0, minor_threshold=2)
        # small cascade (depth 2)
        d.record(0.0, "a")
        d.record(1.0, "b")
        # medium cascade (depth 3)
        d.record(100.0, "a")
        d.record(101.0, "b")
        d.record(102.0, "c")
        report = d.detect()
        depths = [c.depth for c in report.largest_cascades]
        assert depths == sorted(depths, reverse=True)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_event_no_cascade(self):
        d = RestartCascadeDetector()
        d.record(0.0, "writer")
        report = d.detect()
        assert report.total_restarts == 1
        assert report.cascade_count == 0
        assert report.isolated_restarts == 1  # one group of depth 1
        assert report.coordination_score == 100.0

    def test_identical_timestamps(self):
        d = RestartCascadeDetector(window_seconds=10.0)
        d.record(5.0, "writer")
        d.record(5.0, "batch")
        d.record(5.0, "supervisor")
        report = d.detect()
        assert report.cascade_count == 1
        assert report.max_cascade_depth == 3
        assert report.mean_cascade_duration == 0.0

    def test_very_large_window(self):
        d = RestartCascadeDetector(window_seconds=1e9)
        d.record(0.0, "writer")
        d.record(1e6, "batch")
        d.record(2e6, "supervisor")
        report = d.detect()
        # All within one giant cascade
        assert report.cascade_count == 1
        assert report.max_cascade_depth == 3

    def test_very_small_window(self):
        d = RestartCascadeDetector(window_seconds=0.001)
        d.record(0.0, "writer")
        d.record(0.0001, "batch")
        d.record(1.0, "supervisor")
        d.record(2.0, "writer")
        report = d.detect()
        # First two in one cascade (depth 2); supervisor and writer each isolated
        assert report.cascade_count == 1
        assert report.isolated_restarts == 2  # two depth-1 groups

    def test_many_events_one_cascade(self):
        d = RestartCascadeDetector(window_seconds=100.0)
        for i in range(20):
            d.record(float(i), f"proc_{i % 3}")
        report = d.detect()
        assert report.cascade_count == 1
        assert report.max_cascade_depth == 20

    def test_alternating_isolated_pattern(self):
        d = RestartCascadeDetector(window_seconds=5.0)
        # Each event is 10s apart — all isolated
        for i in range(10):
            d.record(i * 10.0, "writer")
        report = d.detect()
        assert report.cascade_count == 0
        assert report.total_restarts == 10
        assert report.coordination_score == 100.0


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

class TestModuleLevelFunctions:
    def setup_method(self):
        clear()

    def test_record_and_detect(self):
        record(0.0, "writer")
        record(5.0, "batch")
        report = detect()
        assert report.total_restarts == 2

    def test_clear_resets(self):
        record(0.0, "writer")
        clear()
        report = detect()
        assert report.total_restarts == 0

    def teardown_method(self):
        clear()
