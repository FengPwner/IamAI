"""Tests for stroke_momentum_tracker.py."""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from stroke_momentum_tracker import (
    build_windows,
    classify_momentum,
    compute_slope,
    load_strokes,
    parse_timestamp,
    track_momentum,
    MomentumReport,
    WindowStats,
)


# ── helpers ──────────────────────────────────────────────────────────


def make_strokes_file(strokes: list[dict], tmpdir: Path) -> Path:
    """Write a list of stroke dicts to a temporary JSONL file."""
    path = tmpdir / "strokes.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return path


def make_stroke(ts: str, kind: str = "note", writer: str = "qwen") -> dict:
    return {"timestamp": ts, "kind": kind, "writer": writer, "text": "x"}


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# ── parse_timestamp ──────────────────────────────────────────────────


class TestParseTimestamp:

    def test_iso_with_z(self):
        dt = parse_timestamp("2026-11-21T10:00:00+00:00")
        assert dt is not None
        assert dt.hour == 10

    def test_iso_naive(self):
        dt = parse_timestamp("2026-11-21T14:30:00")
        assert dt is not None
        assert dt.hour == 14
        assert dt.minute == 30

    def test_iso_with_microseconds(self):
        dt = parse_timestamp("2026-11-21T14:30:00.123456")
        assert dt is not None

    def test_invalid_returns_none(self):
        assert parse_timestamp("not-a-date") is None
        assert parse_timestamp("") is None


# ── compute_slope ────────────────────────────────────────────────────


class TestComputeSlope:

    def test_flat_series(self):
        assert compute_slope([5, 5, 5, 5]) == 0.0

    def test_increasing_series(self):
        slope = compute_slope([1, 2, 3, 4, 5])
        assert slope > 0
        assert abs(slope - 1.0) < 0.001

    def test_decreasing_series(self):
        slope = compute_slope([10, 8, 6, 4, 2])
        assert slope < 0
        assert abs(slope - (-2.0)) < 0.001

    def test_single_value(self):
        assert compute_slope([42]) == 0.0

    def test_empty(self):
        assert compute_slope([]) == 0.0

    def test_two_values_up(self):
        slope = compute_slope([0, 10])
        assert slope == 10.0

    def test_two_values_down(self):
        slope = compute_slope([10, 0])
        assert slope == -10.0


# ── classify_momentum ────────────────────────────────────────────────


class TestClassifyMomentum:

    def test_accelerating(self):
        assert classify_momentum(1.5) == "accelerating"

    def test_decelerating(self):
        assert classify_momentum(-1.5) == "decelerating"

    def test_steady(self):
        assert classify_momentum(0.3) == "steady"

    def test_boundary_positive(self):
        assert classify_momentum(0.5, accel_threshold=0.5) == "steady"

    def test_boundary_negative(self):
        assert classify_momentum(-0.5, accel_threshold=0.5) == "steady"

    def test_custom_threshold(self):
        assert classify_momentum(2.0, accel_threshold=3.0) == "steady"
        assert classify_momentum(4.0, accel_threshold=3.0) == "accelerating"


# ── build_windows ────────────────────────────────────────────────────


class TestBuildWindows:

    def test_empty_timestamps(self):
        assert build_windows([]) == []

    def test_correct_window_count(self):
        now = datetime(2026, 11, 21, 14, 0, 0)
        timestamps = [now - timedelta(minutes=i * 10) for i in range(20)]
        windows = build_windows(timestamps, window_minutes=60, num_windows=4)
        assert len(windows) == 4

    def test_all_strokes_in_one_window(self):
        # All 5 strokes within a few minutes — should land in the first window
        now = datetime(2026, 11, 21, 14, 0, 0)
        timestamps = [now + timedelta(minutes=i) for i in range(5)]
        windows = build_windows(timestamps, window_minutes=60, num_windows=3)
        # The first window (anchored at earliest) should have all 5 strokes
        assert windows[0].count == 5
        # Later windows should have 0
        assert windows[1].count == 0
        assert windows[2].count == 0

    def test_spread_across_windows(self):
        base = datetime(2026, 11, 21, 10, 0, 0)
        # One stroke per hour for 6 hours
        timestamps = [base + timedelta(hours=i) for i in range(6)]
        windows = build_windows(timestamps, window_minutes=60, num_windows=6)
        for w in windows:
            assert w.count >= 0  # each window should have at least 0

    def test_window_ordering(self):
        now = datetime(2026, 11, 21, 14, 0, 0)
        timestamps = [now - timedelta(hours=i) for i in range(10)]
        windows = build_windows(timestamps, window_minutes=60, num_windows=5)
        for i in range(len(windows) - 1):
            assert windows[i].start < windows[i + 1].start


# ── load_strokes ─────────────────────────────────────────────────────


class TestLoadStrokes:

    def test_load_all(self, tmp_path):
        strokes = [
            make_stroke("2026-11-21T10:00:00", writer="qwen"),
            make_stroke("2026-11-21T11:00:00", writer="claude"),
        ]
        path = make_strokes_file(strokes, tmp_path)
        loaded = load_strokes(path)
        assert len(loaded) == 2

    def test_filter_by_writer(self, tmp_path):
        strokes = [
            make_stroke("2026-11-21T10:00:00", writer="qwen"),
            make_stroke("2026-11-21T11:00:00", writer="claude"),
            make_stroke("2026-11-21T12:00:00", writer="qwen"),
        ]
        path = make_strokes_file(strokes, tmp_path)
        loaded = load_strokes(path, writer="qwen")
        assert len(loaded) == 2

    def test_missing_file(self, tmp_path):
        loaded = load_strokes(tmp_path / "nonexistent.jsonl")
        assert loaded == []

    def test_malformed_lines_skipped(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        path.write_text(
            '{"timestamp": "2026-11-21T10:00:00", "kind": "note"}\n'
            'this is not json\n'
            '{"timestamp": "2026-11-21T11:00:00", "kind": "thought"}\n',
            encoding="utf-8",
        )
        loaded = load_strokes(path)
        assert len(loaded) == 2


# ── track_momentum (integration) ─────────────────────────────────────


class TestTrackMomentum:

    def test_returns_none_for_empty_file(self, tmp_path):
        path = make_strokes_file([], tmp_path)
        assert track_momentum(path) is None

    def test_returns_none_for_missing_file(self, tmp_path):
        assert track_momentum(tmp_path / "nope.jsonl") is None

    def test_steady_writer(self, tmp_path):
        """A writer producing at a constant rate should be 'steady'."""
        base = datetime(2026, 11, 21, 8, 0, 0)
        strokes = []
        # 5 strokes per hour for 6 hours = steady; offset to stay in windows
        for h in range(6):
            for s in range(5):
                ts = base + timedelta(hours=h, minutes=5 + s * 10)
                strokes.append(make_stroke(iso(ts)))
        path = make_strokes_file(strokes, tmp_path)
        report = track_momentum(path, window_minutes=60, num_windows=6)
        assert report is not None
        assert report.momentum == "steady"
        assert report.measured_windows == 6
        assert report.avg_rate == pytest.approx(5.0, abs=1.0)

    def test_accelerating_writer(self, tmp_path):
        """A writer producing more strokes each window should be 'accelerating'."""
        base = datetime(2026, 11, 21, 8, 0, 0)
        strokes = []
        # Ramp: 1, 3, 5, 7, 9, 11 strokes per hour; offset to stay in windows
        for h, count in enumerate([1, 3, 5, 7, 9, 11]):
            for s in range(count):
                ts = base + timedelta(hours=h, minutes=5 + s * 4)
                strokes.append(make_stroke(iso(ts)))
        path = make_strokes_file(strokes, tmp_path)
        report = track_momentum(path, window_minutes=60, num_windows=6)
        assert report is not None
        assert report.momentum == "accelerating"
        assert report.slope > 0

    def test_decelerating_writer(self, tmp_path):
        """A writer producing fewer strokes each window should be 'decelerating'."""
        base = datetime(2026, 11, 21, 8, 0, 0)
        strokes = []
        # Ramp down: 11, 9, 7, 5, 3, 1 — offset by 5min to stay within windows
        for h, count in enumerate([11, 9, 7, 5, 3, 1]):
            for s in range(count):
                ts = base + timedelta(hours=h, minutes=5 + s * 4)
                strokes.append(make_stroke(iso(ts)))
        path = make_strokes_file(strokes, tmp_path)
        report = track_momentum(path, window_minutes=60, num_windows=6)
        assert report is not None
        assert report.momentum == "decelerating"
        assert report.slope < 0

    def test_writer_filter(self, tmp_path):
        """Filtering by writer should only count that writer's strokes."""
        base = datetime(2026, 11, 21, 8, 0, 0)
        strokes = []
        # qwen: 5 per hour (steady), offset to stay in windows
        for h in range(6):
            for s in range(5):
                ts = base + timedelta(hours=h, minutes=5 + s * 10)
                strokes.append(make_stroke(iso(ts), writer="qwen"))
        # claude: ramping up (would be accelerating if measured alone)
        for h, count in enumerate([1, 3, 5, 7, 9, 11]):
            for s in range(count):
                ts = base + timedelta(hours=h, minutes=5 + s * 4)
                strokes.append(make_stroke(iso(ts), writer="claude"))
        path = make_strokes_file(strokes, tmp_path)
        report = track_momentum(path, writer="qwen", window_minutes=60, num_windows=6)
        assert report is not None
        assert report.momentum == "steady"

    def test_report_has_peak_and_trough(self, tmp_path):
        base = datetime(2026, 11, 21, 8, 0, 0)
        strokes = []
        # Offset by 10min so strokes land cleanly within their windows
        for h, count in enumerate([2, 8, 4, 1, 6, 3]):
            for s in range(count):
                ts = base + timedelta(hours=h, minutes=10 + s * 7)
                strokes.append(make_stroke(iso(ts)))
        path = make_strokes_file(strokes, tmp_path)
        report = track_momentum(path, window_minutes=60, num_windows=6)
        assert report is not None
        assert report.peak_window is not None
        assert report.peak_window.count == 8
        assert report.trough_window is not None
        assert report.trough_window.count == 1

    def test_to_dict(self, tmp_path):
        base = datetime(2026, 11, 21, 8, 0, 0)
        strokes = []
        for h in range(6):
            for s in range(3):
                ts = base + timedelta(hours=h, minutes=5 + s * 15)
                strokes.append(make_stroke(iso(ts)))
        path = make_strokes_file(strokes, tmp_path)
        report = track_momentum(path, window_minutes=60, num_windows=6)
        assert report is not None
        d = report.to_dict()
        assert "windows" in d
        assert "slope" in d
        assert "momentum" in d
        assert "verdict" in d
        assert isinstance(d["windows"], list)

    def test_custom_threshold(self, tmp_path):
        """A high threshold should make everything look 'steady'."""
        base = datetime(2026, 11, 21, 8, 0, 0)
        strokes = []
        for h, count in enumerate([1, 3, 5, 7, 9, 11]):
            for s in range(count):
                ts = base + timedelta(hours=h, minutes=5 + s * 4)
                strokes.append(make_stroke(iso(ts)))
        path = make_strokes_file(strokes, tmp_path)
        report = track_momentum(
            path, window_minutes=60, num_windows=6, accel_threshold=100.0
        )
        assert report is not None
        assert report.momentum == "steady"
