"""Tests for drift_detector module."""

import pytest

from iamai.drift_detector import DriftState, assess, drift_report


class TestDriftStateRecording:
    """DriftState.record computes intervals correctly."""

    def test_first_record_no_interval(self):
        s = DriftState()
        s.record(100.0)
        assert s.intervals == []

    def test_two_records_one_interval(self):
        s = DriftState()
        s.record(0.0)
        s.record(15.0)
        assert s.intervals == [15.0]

    def test_multiple_records(self):
        s = DriftState()
        for t in [0, 10, 25, 40]:
            s.record(float(t))
        assert s.intervals == [10.0, 15.0, 15.0]

    def test_zero_interval_ignored(self):
        """Two identical timestamps should not add a zero interval."""
        s = DriftState()
        s.record(5.0)
        s.record(5.0)
        assert s.intervals == []

    def test_negative_interval_ignored(self):
        """Backwards timestamps are skipped (clock skew protection)."""
        s = DriftState()
        s.record(10.0)
        s.record(5.0)
        assert s.intervals == []

    def test_window_maxlen(self):
        """Window caps at 20 intervals; oldest drops off."""
        s = DriftState()
        for i in range(25):
            s.record(float(i * 10))
        assert len(s.intervals) == 20


class TestAssess:
    """assess() classifies drift correctly."""

    def test_steady_cadence(self):
        s = DriftState()
        for t in [0, 15, 30, 45, 60]:
            s.record(float(t))
        assert assess(s, cadence=15) == "steady"

    def test_faster_than_cadence(self):
        """Writer ticking faster than expected is still steady."""
        s = DriftState()
        for t in [0, 10, 20, 30, 40]:
            s.record(float(t))
        assert assess(s, cadence=15) == "steady"

    def test_drifting(self):
        """Average interval between steady and critical thresholds."""
        s = DriftState()
        # cadence=15, steady_threshold=22.5, critical_threshold=45
        # intervals: ~37.5 avg → drifting
        for t in [0, 35, 72, 108, 148]:
            s.record(float(t))
        result = assess(s, cadence=15)
        assert result == "drifting"

    def test_critical(self):
        """Average interval above critical threshold."""
        s = DriftState()
        # cadence=15, critical_threshold=45
        # intervals: 50 avg → critical
        for t in [0, 50, 100, 150, 200]:
            s.record(float(t))
        assert assess(s, cadence=15) == "critical"

    def test_too_few_samples_returns_steady(self):
        """Not enough data → default to steady (no false alarms)."""
        s = DriftState()
        s.record(0.0)
        s.record(120.0)  # one huge interval, but only 1 sample
        assert assess(s, cadence=15, min_samples=3) == "steady"

    def test_custom_factors(self):
        """Custom steady/critical factors shift thresholds."""
        s = DriftState()
        for t in [0, 20, 40, 60]:
            s.record(float(t))
        # avg=20, cadence=15: with steady_factor=1.2 → threshold=18 → drifting
        assert assess(s, cadence=15, steady_factor=1.2) == "drifting"
        # with steady_factor=2.0 → threshold=30 → steady
        assert assess(s, cadence=15, steady_factor=2.0) == "steady"

    def test_exactly_at_steady_boundary(self):
        """avg == steady_threshold → steady (≤)."""
        s = DriftState()
        # cadence=10, steady_factor=1.5 → threshold=15
        for t in [0, 15, 30, 45]:
            s.record(float(t))
        assert assess(s, cadence=10, steady_factor=1.5) == "steady"

    def test_exactly_at_critical_boundary(self):
        """avg == critical_threshold → critical (≥)."""
        s = DriftState()
        # cadence=10, critical_factor=3.0 → threshold=30
        for t in [0, 30, 60, 90]:
            s.record(float(t))
        assert assess(s, cadence=10, critical_factor=3.0) == "critical"


class TestDriftReport:
    """drift_report() returns well-formed diagnostic dicts."""

    def test_empty_state(self):
        r = drift_report(DriftState())
        assert r["status"] == "steady"
        assert r["sample_count"] == 0
        assert r["avg_interval"] == 0.0

    def test_healthy_report(self):
        s = DriftState()
        for t in [0, 15, 30, 45]:
            s.record(float(t))
        r = drift_report(s, cadence=15)
        assert r["status"] == "steady"
        assert r["avg_interval"] == 15.0
        assert r["max_interval"] == 15.0
        assert r["min_interval"] == 15.0
        assert r["sample_count"] == 3
        assert r["cadence"] == 15

    def test_drifting_report(self):
        s = DriftState()
        for t in [0, 30, 65, 105]:
            s.record(float(t))
        r = drift_report(s, cadence=15)
        assert r["status"] == "drifting"
        assert r["sample_count"] == 3

    def test_report_keys(self):
        """All expected keys present."""
        r = drift_report(DriftState())
        expected = {"status", "avg_interval", "max_interval",
                    "min_interval", "sample_count", "cadence"}
        assert set(r.keys()) == expected

    def test_intervals_are_rounded(self):
        """Report values are rounded to 2 decimal places."""
        s = DriftState()
        s.record(0.0)
        s.record(15.333333)
        s.record(30.666666)
        r = drift_report(s, cadence=15)
        assert r["avg_interval"] == 15.33
        assert r["max_interval"] == 15.33
        assert r["min_interval"] == 15.33
