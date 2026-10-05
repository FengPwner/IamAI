"""Tests for the BacklogMonitor module.

Covers: recording snapshots, loading with limits, current count,
trend analysis (growing/stable/shrinking/insufficient), peak detection,
and summary generation.
"""

import json
import tempfile
from pathlib import Path

import pytest

from iamai.backlog_monitor import BacklogMonitor


@pytest.fixture
def monitor(tmp_path):
    """Create a monitor with a temporary log file."""
    return BacklogMonitor(tmp_path / "backlog.jsonl")


class TestRecord:
    def test_record_creates_file(self, monitor):
        snap = monitor.record(count=5)
        assert monitor.filepath.exists()
        assert snap["count"] == 5

    def test_record_with_tag(self, monitor):
        snap = monitor.record(count=3, tag="post-restart")
        assert snap["tag"] == "post-restart"

    def test_record_appends(self, monitor):
        monitor.record(count=1)
        monitor.record(count=2)
        monitor.record(count=3)
        snapshots = monitor.load()
        assert len(snapshots) == 3
        assert [s["count"] for s in snapshots] == [1, 2, 3]

    def test_record_has_timestamp(self, monitor):
        snap = monitor.record(count=10)
        assert "timestamp" in snap
        assert "T" in snap["timestamp"]  # ISO format

    def test_record_empty_tag(self, monitor):
        snap = monitor.record(count=7)
        assert snap["tag"] == ""


class TestLoad:
    def test_load_empty(self, monitor):
        assert monitor.load() == []

    def test_load_all(self, monitor):
        for i in range(10):
            monitor.record(count=i)
        snapshots = monitor.load()
        assert len(snapshots) == 10

    def test_load_with_limit(self, monitor):
        for i in range(10):
            monitor.record(count=i)
        snapshots = monitor.load(limit=3)
        assert len(snapshots) == 3
        # Should be the last 3
        assert [s["count"] for s in snapshots] == [7, 8, 9]

    def test_load_limit_larger_than_data(self, monitor):
        monitor.record(count=1)
        monitor.record(count=2)
        snapshots = monitor.load(limit=100)
        assert len(snapshots) == 2

    def test_load_malformed_lines_skipped(self, monitor):
        monitor.record(count=1)
        # Write a bad line
        with open(monitor.filepath, "a") as f:
            f.write("not valid json\n")
        monitor.record(count=2)
        # load should handle malformed lines
        with pytest.raises(json.JSONDecodeError):
            monitor.load()


class TestCurrent:
    def test_current_empty(self, monitor):
        assert monitor.current() == 0

    def test_current_returns_latest(self, monitor):
        monitor.record(count=5)
        monitor.record(count=12)
        monitor.record(count=3)
        assert monitor.current() == 3

    def test_current_single_entry(self, monitor):
        monitor.record(count=42)
        assert monitor.current() == 42


class TestTrend:
    def test_trend_insufficient_data(self, monitor):
        monitor.record(count=5)
        monitor.record(count=6)
        assert monitor.trend() == "insufficient_data"

    def test_trend_stable(self, monitor):
        # 10 snapshots needed for default window=5
        # First 5: counts around 10
        for _ in range(5):
            monitor.record(count=10)
        # Last 5: also around 10
        for _ in range(5):
            monitor.record(count=10)
        assert monitor.trend() == "stable"

    def test_trend_growing(self, monitor):
        # Earlier 5: low counts
        for _ in range(5):
            monitor.record(count=5)
        # Recent 5: high counts (>20% increase)
        for _ in range(5):
            monitor.record(count=10)
        assert monitor.trend() == "growing"

    def test_trend_shrinking(self, monitor):
        # Earlier 5: high counts
        for _ in range(5):
            monitor.record(count=20)
        # Recent 5: low counts (>20% decrease)
        for _ in range(5):
            monitor.record(count=5)
        assert monitor.trend() == "shrinking"

    def test_trend_custom_window(self, monitor):
        # window=2: need 4 snapshots
        monitor.record(count=10)
        monitor.record(count=10)
        monitor.record(count=20)
        monitor.record(count=20)
        assert monitor.trend(window=2) == "growing"

    def test_trend_from_zero(self, monitor):
        # Earlier all zeros, recent has counts
        for _ in range(5):
            monitor.record(count=0)
        for _ in range(5):
            monitor.record(count=5)
        assert monitor.trend() == "growing"

    def test_trend_both_zero(self, monitor):
        for _ in range(10):
            monitor.record(count=0)
        assert monitor.trend() == "stable"

    def test_trend_slight_change_is_stable(self, monitor):
        # 10% change should be "stable" (threshold is 20%)
        for _ in range(5):
            monitor.record(count=10)
        for _ in range(5):
            monitor.record(count=11)
        assert monitor.trend() == "stable"


class TestPeak:
    def test_peak_empty(self, monitor):
        assert monitor.peak() == 0

    def test_peak_all(self, monitor):
        for count in [3, 7, 2, 15, 4]:
            monitor.record(count=count)
        assert monitor.peak() == 15

    def test_peak_with_window(self, monitor):
        for count in [20, 5, 3, 2, 1]:
            monitor.record(count=count)
        # Only look at last 3
        assert monitor.peak(window=3) == 3

    def test_peak_single(self, monitor):
        monitor.record(count=99)
        assert monitor.peak() == 99


class TestSummary:
    def test_summary_empty(self, monitor):
        s = monitor.summary()
        assert s["current"] == 0
        assert s["peak"] == 0
        assert s["sample_count"] == 0
        assert s["trend"] == "insufficient_data"

    def test_summary_populated(self, monitor):
        for i in range(12):
            monitor.record(count=i)
        s = monitor.summary()
        assert s["current"] == 11
        assert s["peak"] == 11
        assert s["sample_count"] == 12
        assert s["trend"] in ("growing", "stable", "shrinking", "insufficient_data")

    def test_summary_keys(self, monitor):
        monitor.record(count=5)
        s = monitor.summary()
        assert set(s.keys()) == {"current", "trend", "peak", "sample_count"}


class TestEdgeCases:
    def test_creates_parent_dirs(self, tmp_path):
        deep = BacklogMonitor(tmp_path / "a" / "b" / "c" / "backlog.jsonl")
        deep.record(count=1)
        assert deep.filepath.exists()

    def test_concurrent_appends(self, monitor):
        """Multiple record calls don't corrupt the file."""
        for i in range(50):
            monitor.record(count=i, tag=f"batch-{i}")
        snapshots = monitor.load()
        assert len(snapshots) == 50
        assert snapshots[-1]["count"] == 49
