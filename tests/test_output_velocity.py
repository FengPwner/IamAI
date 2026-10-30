"""Tests for iamai.output_velocity."""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.output_velocity import (
    VelocityReport,
    _load_timestamps,
    _parse_ts,
    _rate,
    compute_velocity,
    velocity_from_timestamps,
    velocity_report,
    velocity_summary,
    verdict_for,
)


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTs:
    def test_iso_with_z(self):
        dt = _parse_ts("2026-10-21T14:30:00Z")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 10
        assert dt.hour == 14

    def test_iso_with_offset(self):
        dt = _parse_ts("2026-10-21T14:30:00+00:00")
        assert dt is not None
        assert dt.hour == 14

    def test_iso_without_tz(self):
        dt = _parse_ts("2026-10-21T14:30:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_empty_string(self):
        assert _parse_ts("") is None

    def test_none(self):
        assert _parse_ts(None) is None

    def test_garbage(self):
        assert _parse_ts("not-a-date") is None

    def test_fractional_seconds(self):
        dt = _parse_ts("2026-10-21T14:30:00.123456+00:00")
        assert dt is not None


# ---------------------------------------------------------------------------
# _rate
# ---------------------------------------------------------------------------

class TestRate:
    def test_basic(self):
        # 10 strokes in 600 seconds = 1.0 strokes/min
        assert _rate(10, 600) == pytest.approx(1.0)

    def test_zero_seconds(self):
        assert _rate(5, 0) == 0.0

    def test_negative_seconds(self):
        assert _rate(5, -10) == 0.0

    def test_zero_count(self):
        assert _rate(0, 600) == 0.0

    def test_fast(self):
        # 20 strokes in 60 seconds = 20 strokes/min
        assert _rate(20, 60) == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# verdict_for
# ---------------------------------------------------------------------------

class TestVerdictFor:
    def test_stalled_zero_second_half(self):
        assert verdict_for(0.5, 0) == "stalled"

    def test_stalled_low_ratio(self):
        assert verdict_for(0.10, 3) == "stalled"

    def test_stalled_boundary(self):
        assert verdict_for(0.19, 5) == "stalled"

    def test_decelerating(self):
        assert verdict_for(0.50, 5) == "decelerating"

    def test_decelerating_boundary_low(self):
        assert verdict_for(0.20, 5) == "decelerating"

    def test_decelerating_boundary_high(self):
        assert verdict_for(0.76, 5) == "decelerating"

    def test_steady_low(self):
        assert verdict_for(0.77, 5) == "steady"

    def test_steady_one(self):
        assert verdict_for(1.00, 5) == "steady"

    def test_steady_high(self):
        assert verdict_for(1.30, 5) == "steady"

    def test_accelerating(self):
        assert verdict_for(1.31, 5) == "accelerating"

    def test_accelerating_high(self):
        assert verdict_for(5.00, 10) == "accelerating"


# ---------------------------------------------------------------------------
# compute_velocity — helper to build timestamps
# ---------------------------------------------------------------------------

def _make_timestamps(intervals_seconds: list[float]) -> list[datetime]:
    """Build a list of timestamps from a list of inter-stroke intervals.

    The first stroke is at t=0 (epoch), then each interval is added.
    Returns *len(intervals) + 1* timestamps.
    """
    base = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
    ts = [base]
    current = base
    for iv in intervals_seconds:
        current = current + timedelta(seconds=iv)
        ts.append(current)
    return ts


class TestComputeVelocity:
    def test_empty(self):
        report = compute_velocity([])
        assert report.total_strokes == 0
        assert report.verdict == "stalled"

    def test_single(self):
        ts = [datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)]
        report = compute_velocity(ts)
        assert report.total_strokes == 1
        assert report.verdict == "unknown"

    def test_steady_cadence(self):
        # 20 strokes, each exactly 180 s apart → perfectly steady
        intervals = [180] * 19
        ts = _make_timestamps(intervals)
        report = compute_velocity(ts)
        assert report.total_strokes == 20
        assert report.verdict == "steady"
        assert report.ratio == pytest.approx(1.0, abs=0.15)

    def test_accelerating(self):
        # First half: 300 s apart (slow), second half: 60 s apart (fast)
        intervals = [300] * 9 + [60] * 10
        ts = _make_timestamps(intervals)
        report = compute_velocity(ts)
        assert report.total_strokes == 20
        assert report.verdict == "accelerating"
        assert report.ratio > 1.3

    def test_decelerating(self):
        # First half: 60 s apart (fast), second half: 120 s apart (slower)
        intervals = [60] * 9 + [120] * 10
        ts = _make_timestamps(intervals)
        report = compute_velocity(ts)
        assert report.total_strokes == 20
        assert report.verdict == "decelerating"
        assert report.ratio < 0.77
        assert report.ratio >= 0.20

    def test_stalled_second_half_empty(self):
        # Only one stroke in the second half → gap is zero → rate is zero
        # We need a scenario where second_half_count > 0 but second_rate == 0
        # That happens when all second-half timestamps are identical.
        base = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
        ts = [base + timedelta(seconds=i * 180) for i in range(5)]
        # Add 5 more all at the same time
        same_time = ts[-1]
        ts.extend([same_time] * 5)
        report = compute_velocity(ts)
        assert report.second_half_rate == 0.0
        assert report.verdict == "stalled"

    def test_gap_seconds_positive(self):
        # Timestamps in the past → gap should be large
        base = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ts = [base + timedelta(seconds=i * 180) for i in range(10)]
        report = compute_velocity(ts)
        assert report.gap_seconds > 0
        # Gap should be at least 5 years in seconds
        assert report.gap_seconds > 5 * 365 * 86400 * 0.9

    def test_unsorted_input_gets_sorted(self):
        # Feed timestamps out of order — function should sort them
        base = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
        ts_shuffled = [
            base + timedelta(seconds=360),
            base,
            base + timedelta(seconds=180),
            base + timedelta(seconds=540),
        ]
        report = compute_velocity(ts_shuffled)
        assert report.total_strokes == 4
        # Should still compute correctly
        assert report.overall_rate > 0

    def test_window_size_preserved(self):
        intervals = [120] * 39
        ts = _make_timestamps(intervals)
        report = compute_velocity(ts)
        assert report.total_strokes == 40
        assert len(report.timestamps) == 40

    def test_two_strokes(self):
        # Minimal case: just two timestamps
        ts = _make_timestamps([300])
        report = compute_velocity(ts)
        assert report.total_strokes == 2
        # With only 2 strokes, mid=1, first_half=[t0], second_half=[t1]
        # first_span = 0, second_span = 0 → both rates are 0 → stalled
        assert report.verdict in ("stalled", "steady", "unknown")


# ---------------------------------------------------------------------------
# _load_timestamps (file I/O)
# ---------------------------------------------------------------------------

class TestLoadTimestamps:
    def test_valid_file(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        lines = [
            {"at": "2026-10-21T12:00:00Z", "kind": "note", "text": "hello"},
            {"at": "2026-10-21T12:03:00Z", "kind": "note", "text": "world"},
            {"at": "2026-10-21T12:06:00Z", "kind": "note", "text": "foo"},
        ]
        f.write_text("\n".join(json.dumps(l) for l in lines))
        ts = _load_timestamps(f, window=10)
        assert len(ts) == 3

    def test_window_truncation(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        lines = [
            {"at": f"2026-10-21T12:{i:02d}:00Z", "kind": "note", "text": "x"}
            for i in range(20)
        ]
        f.write_text("\n".join(json.dumps(l) for l in lines))
        ts = _load_timestamps(f, window=5)
        assert len(ts) == 5

    def test_missing_file(self, tmp_path):
        ts = _load_timestamps(tmp_path / "nonexistent.jsonl", window=10)
        assert ts == []

    def test_malformed_lines(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"at": "2026-10-21T12:00:00Z", "kind": "note", "text": "ok"}\n'
            'this is not json\n'
            '{"at": "2026-10-21T12:03:00Z", "kind": "note", "text": "ok"}\n'
            '{"no_at_field": true}\n'
        )
        ts = _load_timestamps(f, window=10)
        assert len(ts) == 2

    def test_empty_file(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text("")
        ts = _load_timestamps(f, window=10)
        assert ts == []


# ---------------------------------------------------------------------------
# velocity_report (end-to-end with file)
# ---------------------------------------------------------------------------

class TestVelocityReport:
    def test_steady_file(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        lines = []
        base = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(20):
            ts = base + timedelta(seconds=i * 180)
            lines.append(json.dumps({
                "at": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "kind": "note",
                "text": f"stroke {i}",
            }))
        f.write_text("\n".join(lines))
        report = velocity_report(f, window=20)
        assert report.total_strokes == 20
        assert report.verdict == "steady"

    def test_decelerating_file(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        lines = []
        base = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
        # First 10: 60s apart, next 10: 120s apart
        current = base
        for i in range(20):
            lines.append(json.dumps({
                "at": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "kind": "note",
                "text": f"stroke {i}",
            }))
            gap = 60 if i < 9 else 120
            current += timedelta(seconds=gap)
        f.write_text("\n".join(lines))
        report = velocity_report(f, window=20)
        assert report.total_strokes == 20
        assert report.verdict == "decelerating"


# ---------------------------------------------------------------------------
# velocity_from_timestamps
# ---------------------------------------------------------------------------

class TestVelocityFromTimestamps:
    def test_basic(self):
        ts = _make_timestamps([180] * 9)
        report = velocity_from_timestamps(ts)
        assert report.total_strokes == 10
        assert report.verdict == "steady"


# ---------------------------------------------------------------------------
# velocity_summary
# ---------------------------------------------------------------------------

class TestVelocitySummary:
    def test_insufficient_data_zero(self):
        report = VelocityReport(total_strokes=0, verdict="stalled")
        s = velocity_summary(report)
        assert "insufficient data" in s
        assert "0 stroke" in s

    def test_insufficient_data_one(self):
        report = VelocityReport(total_strokes=1, verdict="unknown")
        s = velocity_summary(report)
        assert "insufficient data" in s

    def test_steady_summary(self):
        intervals = [180] * 19
        ts = _make_timestamps(intervals)
        report = compute_velocity(ts)
        s = velocity_summary(report)
        assert "steady" in s
        assert "first half" in s
        assert "second half" in s
        assert "gap" in s

    def test_summary_contains_rate(self):
        intervals = [120] * 9
        ts = _make_timestamps(intervals)
        report = compute_velocity(ts)
        s = velocity_summary(report)
        assert "strokes/min" in s


# ---------------------------------------------------------------------------
# Integration: ratio boundary tests
# ---------------------------------------------------------------------------

class TestRatioBoundaries:
    def test_ratio_exactly_one(self):
        # Perfectly steady → ratio should be 1.0 → steady
        ts = _make_timestamps([180] * 19)
        report = compute_velocity(ts)
        assert report.ratio == pytest.approx(1.0, abs=0.05)

    def test_first_half_zero_rate(self):
        # All first-half timestamps identical → first_rate = 0
        # second half spread out → ratio = inf → capped to 999 → accelerating
        base = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
        ts = [base] * 5 + [base + timedelta(seconds=i * 180) for i in range(1, 6)]
        report = compute_velocity(ts)
        assert report.ratio == 999.0
        assert report.verdict == "accelerating"

    def test_both_halves_zero_rate(self):
        # All timestamps identical → both rates 0 → ratio 0 → stalled
        base = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
        ts = [base] * 10
        report = compute_velocity(ts)
        assert report.first_half_rate == 0.0
        assert report.second_half_rate == 0.0
        assert report.verdict == "stalled"
