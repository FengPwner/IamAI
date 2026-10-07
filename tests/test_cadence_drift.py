#!/usr/bin/env python3
"""Tests for cadence_drift.py — cadence drift measurement."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import cadence_drift as cd


def _make_history(timestamps: list[datetime]) -> list[dict]:
    """Build a minimal stroke history from a list of timestamps."""
    return [{"at": t.isoformat(), "seq": i, "kind": "thought", "text": "x"}
            for i, t in enumerate(timestamps)]


def _regular_history(n: int, interval_s: int, start: datetime = None) -> list[dict]:
    """Generate n strokes at a fixed interval."""
    if start is None:
        start = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
    times = [start + timedelta(seconds=i * interval_s) for i in range(n)]
    return _make_history(times)


# ---------------------------------------------------------------------------
# compute_intervals
# ---------------------------------------------------------------------------

class TestComputeIntervals:
    def test_empty_history(self):
        assert cd.compute_intervals([]) == []

    def test_single_entry(self):
        history = _make_history([datetime(2026, 1, 1, tzinfo=timezone.utc)])
        assert cd.compute_intervals(history) == []

    def test_regular_intervals(self):
        history = _regular_history(5, interval_s=15)
        intervals = cd.compute_intervals(history)
        assert len(intervals) == 4
        assert all(iv == 15.0 for iv in intervals)

    def test_variable_intervals(self):
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        times = [base, base + timedelta(seconds=10),
                 base + timedelta(seconds=30),
                 base + timedelta(seconds=35)]
        history = _make_history(times)
        intervals = cd.compute_intervals(history)
        assert intervals == [10.0, 20.0, 5.0]

    def test_skips_negative_intervals(self):
        """Clock skew producing a backwards timestamp is silently skipped."""
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        times = [base, base + timedelta(seconds=15),
                 base + timedelta(seconds=10),  # clock went backwards
                 base + timedelta(seconds=30)]
        history = _make_history(times)
        intervals = cd.compute_intervals(history)
        # The negative interval (10-15 = -5) is skipped; 30-10 = 20 is kept
        assert 20.0 in intervals
        assert all(iv >= 0 for iv in intervals)

    def test_malformed_entries_skipped(self):
        """Entries missing 'at' or with bad format are skipped.

        Only consecutive valid pairs produce intervals; bad entries break
        the chain rather than bridging over them.
        """
        history = [
            {"at": "2026-01-01T12:00:00+00:00", "seq": 0},
            {"at": "2026-01-01T12:00:15+00:00", "seq": 1},
            {"at": "not-a-date", "seq": 2},
            {"seq": 3},  # missing 'at'
            {"at": "2026-01-01T12:00:45+00:00", "seq": 4},
            {"at": "2026-01-01T12:01:00+00:00", "seq": 5},
        ]
        intervals = cd.compute_intervals(history)
        # Valid consecutive pairs: 0->1 (15s), 4->5 (15s)
        assert 15.0 in intervals
        assert len(intervals) == 2
        assert all(iv >= 0 for iv in intervals)


    def test_no_intervals_returns_error(self):
        report = cd.drift_report([], target=15)
        assert report["sample_size"] == 0
        assert "error" in report

    def test_tight_drift(self):
        """Intervals very close to target → tight."""
        intervals = [15.0, 15.5, 14.8, 15.2, 15.1]
        report = cd.drift_report(intervals, target=15, window=10)
        assert report["drift_class"] == "tight"
        assert abs(report["drift_pct"]) < 5

    def test_warm_drift(self):
        """Intervals moderately above target → warm."""
        intervals = [17.0, 17.5, 18.0, 17.2, 16.8]
        report = cd.drift_report(intervals, target=15, window=10)
        assert report["drift_class"] == "warm"
        assert 5 <= report["drift_pct"] < 20

    def test_hot_drift(self):
        """Intervals far from target → hot."""
        intervals = [25.0, 30.0, 28.0, 22.0, 26.0]
        report = cd.drift_report(intervals, target=15, window=10)
        assert report["drift_class"] == "hot"
        assert report["drift_pct"] > 20

    def test_faster_than_target(self):
        """Intervals below target produce negative drift."""
        intervals = [10.0, 11.0, 10.5, 10.2, 10.8]
        report = cd.drift_report(intervals, target=15, window=10)
        assert report["drift_pct"] < 0
        assert report["drift_class"] in ("tight", "warm", "hot")

    def test_window_truncation(self):
        """Only the most recent `window` intervals are used."""
        old = [100.0] * 50  # very slow
        recent = [15.0] * 10  # on target
        intervals = old + recent
        report = cd.drift_report(intervals, target=15, window=10)
        assert report["sample_size"] == 10
        assert report["drift_class"] == "tight"

    def test_median_calculation_even(self):
        intervals = [10.0, 20.0, 30.0, 40.0]
        report = cd.drift_report(intervals, target=15, window=10)
        assert report["median_interval_s"] == 25.0

    def test_median_calculation_odd(self):
        intervals = [10.0, 20.0, 30.0]
        report = cd.drift_report(intervals, target=15, window=10)
        assert report["median_interval_s"] == 20.0

    def test_min_max(self):
        intervals = [5.0, 15.0, 25.0, 10.0, 20.0]
        report = cd.drift_report(intervals, target=15, window=10)
        assert report["min_s"] == 5.0
        assert report["max_s"] == 25.0

    def test_zero_target_no_crash(self):
        """Target of 0 shouldn't cause division by zero."""
        intervals = [15.0, 15.0]
        report = cd.drift_report(intervals, target=0, window=10)
        assert report["drift_pct"] == 0.0


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------

class TestLoadStrokes:
    def test_missing_file(self, tmp_path):
        assert cd.load_strokes(tmp_path / "nonexistent.json") == []

    def test_valid_file(self, tmp_path):
        state = {"history": [{"at": "2026-01-01T00:00:00+00:00", "seq": 0}]}
        p = tmp_path / "state.json"
        p.write_text(json.dumps(state))
        result = cd.load_strokes(p)
        assert len(result) == 1

    def test_corrupt_json(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("{bad json")
        assert cd.load_strokes(p) == []


# ---------------------------------------------------------------------------
# integration: full pipeline
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_pipeline_regular(self):
        """Regular 15s intervals → tight drift."""
        history = _regular_history(100, interval_s=15)
        intervals = cd.compute_intervals(history)
        report = cd.drift_report(intervals, target=15, window=60)
        assert report["drift_class"] == "tight"
        assert report["sample_size"] == 60

    def test_full_pipeline_slow(self):
        """Regular 25s intervals with 15s target → hot drift."""
        history = _regular_history(100, interval_s=25)
        intervals = cd.compute_intervals(history)
        report = cd.drift_report(intervals, target=15, window=60)
        assert report["drift_class"] == "hot"
        assert report["drift_pct"] > 60

    def test_full_pipeline_accelerating(self):
        """Intervals that start fast and slow down.

        Window should capture only the slower tail.
        """
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        times = []
        gap = 10
        t = base
        for i in range(100):
            times.append(t)
            gap = min(gap + 0.5, 40)  # accelerate gap up to 40s
            t += timedelta(seconds=gap)
        history = _make_history(times)
        intervals = cd.compute_intervals(history)
        report = cd.drift_report(intervals, target=15, window=20)
        # Last 20 intervals should all be at 40s → very hot
        assert report["drift_class"] == "hot"
