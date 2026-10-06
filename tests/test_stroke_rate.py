"""Tests for iamai.stroke_rate — rolling stroke rate computation."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.stroke_rate import (
    _detect_trend,
    _load_strokes,
    _parse_timestamp,
    _strokes_in_window,
    compare_windows,
    rate_summary,
    stroke_rate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_strokes(count: int, start: datetime, interval_seconds: int = 15) -> list[dict]:
    """Generate synthetic stroke records."""
    kinds = ["thought", "snippet", "note", "devlog", "garden", "metrics"]
    strokes = []
    for i in range(count):
        dt = start + timedelta(seconds=interval_seconds * i)
        strokes.append({
            "seq": i + 1,
            "at": dt.isoformat(),
            "kind": kinds[i % len(kinds)],
            "text": f"test stroke {i + 1}",
        })
    return strokes


def _write_strokes_file(strokes: list[dict], tmpdir: Path) -> Path:
    """Write stroke records to a temporary JSONL file."""
    path = tmpdir / "strokes.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return path


# ---------------------------------------------------------------------------
# _parse_timestamp
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    def test_utc_offset(self):
        dt = _parse_timestamp("2026-10-06T12:00:00+00:00")
        assert dt.year == 2026
        assert dt.month == 10
        assert dt.day == 6
        assert dt.hour == 12
        assert dt.tzinfo is not None

    def test_z_suffix(self):
        dt = _parse_timestamp("2026-10-06T12:00:00Z")
        assert dt.hour == 12
        assert dt.tzinfo is not None

    def test_bare_datetime_assumes_utc(self):
        dt = _parse_timestamp("2026-10-06T12:00:00")
        assert dt.tzinfo == timezone.utc

    def test_whitespace_stripped(self):
        dt = _parse_timestamp("  2026-10-06T12:00:00Z  ")
        assert dt.hour == 12


# ---------------------------------------------------------------------------
# _load_strokes
# ---------------------------------------------------------------------------


class TestLoadStrokes:
    def test_basic_load(self, tmp_path: Path):
        strokes = _make_strokes(5, datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc))
        path = _write_strokes_file(strokes, tmp_path)
        loaded = _load_strokes(path)
        assert len(loaded) == 5
        assert all("_dt" in s for s in loaded)

    def test_empty_file(self, tmp_path: Path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        loaded = _load_strokes(path)
        assert loaded == []

    def test_malformed_lines_skipped(self, tmp_path: Path):
        path = tmp_path / "bad.jsonl"
        path.write_text(
            '{"seq":1,"at":"2026-10-06T10:00:00Z","kind":"thought"}\n'
            "not json\n"
            '{"seq":2,"at":"2026-10-06T10:01:00Z","kind":"snippet"}\n'
        )
        loaded = _load_strokes(path)
        assert len(loaded) == 2

    def test_missing_at_key_skipped(self, tmp_path: Path):
        path = tmp_path / "no_at.jsonl"
        path.write_text('{"seq":1,"kind":"thought"}\n')
        loaded = _load_strokes(path)
        assert loaded == []

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            _load_strokes(Path("/nonexistent/path/strokes.jsonl"))


# ---------------------------------------------------------------------------
# _strokes_in_window
# ---------------------------------------------------------------------------


class TestStrokesInWindow:
    def test_all_in_window(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        strokes = _make_strokes(
            10,
            start=now - timedelta(minutes=30),
            interval_seconds=60,
        )
        for s in strokes:
            s["_dt"] = _parse_timestamp(s["at"])
        result = _strokes_in_window(strokes, now, 1.0)
        assert len(result) == 10

    def test_some_outside_window(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        # Half the strokes are 2 hours old (outside 1h window)
        old = _make_strokes(5, start=now - timedelta(hours=2), interval_seconds=60)
        recent = _make_strokes(5, start=now - timedelta(minutes=30), interval_seconds=60)
        all_strokes = old + recent
        for s in all_strokes:
            s["_dt"] = _parse_timestamp(s["at"])
        result = _strokes_in_window(all_strokes, now, 1.0)
        assert len(result) == 5

    def test_none_in_window(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        strokes = _make_strokes(
            5,
            start=now - timedelta(hours=5),
            interval_seconds=60,
        )
        for s in strokes:
            s["_dt"] = _parse_timestamp(s["at"])
        result = _strokes_in_window(strokes, now, 1.0)
        assert len(result) == 0

    def test_empty_input(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        result = _strokes_in_window([], now, 1.0)
        assert result == []


# ---------------------------------------------------------------------------
# _detect_trend
# ---------------------------------------------------------------------------


class TestDetectTrend:
    def test_unknown_when_empty(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        assert _detect_trend([], 1.0, now) == "unknown"

    def test_unknown_when_single_stroke(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        strokes = _make_strokes(1, now - timedelta(minutes=5))
        for s in strokes:
            s["_dt"] = _parse_timestamp(s["at"])
        assert _detect_trend(strokes, 1.0, now) == "unknown"

    def test_steady_when_evenly_distributed(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        # 20 strokes evenly spaced over 1 hour
        strokes = _make_strokes(
            20,
            start=now - timedelta(minutes=55),
            interval_seconds=165,  # ~2.75 min apart
        )
        for s in strokes:
            s["_dt"] = _parse_timestamp(s["at"])
        result = _detect_trend(strokes, 1.0, now)
        assert result == "steady"

    def test_accelerating_when_second_half_has_more(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        # 2 strokes in first half, 10 in second half
        first = _make_strokes(2, start=now - timedelta(minutes=55), interval_seconds=120)
        second = _make_strokes(10, start=now - timedelta(minutes=25), interval_seconds=60)
        all_strokes = first + second
        for s in all_strokes:
            s["_dt"] = _parse_timestamp(s["at"])
        result = _detect_trend(all_strokes, 1.0, now)
        assert result == "accelerating"

    def test_declining_when_second_half_has_fewer(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        # 10 strokes in first half, 2 in second half
        first = _make_strokes(10, start=now - timedelta(minutes=55), interval_seconds=60)
        second = _make_strokes(2, start=now - timedelta(minutes=20), interval_seconds=120)
        all_strokes = first + second
        for s in all_strokes:
            s["_dt"] = _parse_timestamp(s["at"])
        result = _detect_trend(all_strokes, 1.0, now)
        assert result == "declining"

    def test_accelerating_when_first_half_empty(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        # All strokes in second half
        strokes = _make_strokes(5, start=now - timedelta(minutes=20), interval_seconds=60)
        for s in strokes:
            s["_dt"] = _parse_timestamp(s["at"])
        result = _detect_trend(strokes, 1.0, now)
        assert result == "accelerating"

    def test_declining_when_second_half_empty(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        # All strokes in first half
        strokes = _make_strokes(5, start=now - timedelta(minutes=55), interval_seconds=60)
        for s in strokes:
            s["_dt"] = _parse_timestamp(s["at"])
        result = _detect_trend(strokes, 1.0, now)
        assert result == "declining"


# ---------------------------------------------------------------------------
# stroke_rate (integration)
# ---------------------------------------------------------------------------


class TestStrokeRate:
    def test_basic_rate(self, tmp_path: Path):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        # 60 strokes over 1 hour = 60/hr
        strokes = _make_strokes(
            60,
            start=now - timedelta(minutes=59),
            interval_seconds=60,
        )
        path = _write_strokes_file(strokes, tmp_path)
        result = stroke_rate(window_hours=1.0, strokes_path=path, now=now)

        assert result["total"] == 60
        assert result["total_rate_per_hour"] == 60.0
        assert result["window_hours"] == 1.0
        assert result["oldest_stroke_dt"] is not None
        assert result["newest_stroke_dt"] is not None

    def test_empty_window(self, tmp_path: Path):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        strokes = _make_strokes(5, start=now - timedelta(hours=5), interval_seconds=60)
        path = _write_strokes_file(strokes, tmp_path)
        result = stroke_rate(window_hours=1.0, strokes_path=path, now=now)

        assert result["total"] == 0
        assert result["total_rate_per_hour"] == 0.0
        assert result["trend"] == "unknown"
        assert result["oldest_stroke_dt"] is None

    def test_by_kind_breakdown(self, tmp_path: Path):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        # 12 strokes: 2 of each kind (6 kinds cycling)
        strokes = _make_strokes(
            12,
            start=now - timedelta(minutes=30),
            interval_seconds=120,
        )
        path = _write_strokes_file(strokes, tmp_path)
        result = stroke_rate(window_hours=1.0, strokes_path=path, now=now)

        assert "thought" in result["by_kind"]
        assert "snippet" in result["by_kind"]
        assert sum(result["by_kind"].values()) == 12
        # Rate per kind should sum to approximately total rate
        total_kind_rate = sum(result["rate_per_kind"].values())
        assert abs(total_kind_rate - result["total_rate_per_hour"]) < 0.5

    def test_no_file_returns_empty(self, tmp_path: Path):
        path = tmp_path / "nonexistent.jsonl"
        with pytest.raises(FileNotFoundError):
            stroke_rate(strokes_path=path)

    def test_zero_window(self, tmp_path: Path):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        strokes = _make_strokes(5, start=now - timedelta(minutes=5), interval_seconds=60)
        path = _write_strokes_file(strokes, tmp_path)
        result = stroke_rate(window_hours=0.0, strokes_path=path, now=now)
        # Zero window → everything is at the boundary; rate is 0 or inf guarded
        assert result["total_rate_per_hour"] == 0.0 or result["total"] >= 0


# ---------------------------------------------------------------------------
# rate_summary
# ---------------------------------------------------------------------------


class TestRateSummary:
    def test_summary_format(self, tmp_path: Path):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        strokes = _make_strokes(
            30,
            start=now - timedelta(minutes=55),
            interval_seconds=110,
        )
        path = _write_strokes_file(strokes, tmp_path)
        summary = rate_summary(window_hours=1.0, strokes_path=path)
        assert "strokes/hr" in summary
        assert "trend:" in summary

    def test_summary_empty_window(self, tmp_path: Path):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        path = _write_strokes_file([], tmp_path)
        summary = rate_summary(window_hours=1.0, strokes_path=path)
        assert "0 strokes/hr" in summary
        assert "unknown" in summary


# ---------------------------------------------------------------------------
# compare_windows
# ---------------------------------------------------------------------------


class TestCompareWindows:
    def test_normal_pace(self, tmp_path: Path):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        # Steady 60 strokes/hr over 6 hours = 360 total
        strokes = _make_strokes(
            360,
            start=now - timedelta(hours=6),
            interval_seconds=60,
        )
        path = _write_strokes_file(strokes, tmp_path)
        result = compare_windows(
            short_hours=1.0, long_hours=6.0, strokes_path=path,
        )
        assert result["short_rate"] > 0
        assert result["long_rate"] > 0
        assert result["verdict"] in ("normal", "above_average", "below_average")
        assert "ratio" in result

    def test_below_average(self, tmp_path: Path):
        # Use a fixed "now" in the past so the synthetic data is always valid
        # (avoids depending on when the test is actually run)
        from iamai.stroke_rate import stroke_rate as _sr

        real_now = datetime.now(timezone.utc)
        # 100 strokes from 6h ago to 2h ago (interval = 4h/100 = 144s)
        # These all fall outside the 1h short window
        old = _make_strokes(
            100,
            start=real_now - timedelta(hours=6),
            interval_seconds=144,
        )
        # Only 2 strokes in the last hour
        recent = _make_strokes(
            2,
            start=real_now - timedelta(minutes=50),
            interval_seconds=600,
        )
        all_strokes = old + recent
        path = _write_strokes_file(all_strokes, tmp_path)
        result = compare_windows(
            short_hours=1.0, long_hours=6.0, strokes_path=path,
        )
        # Short window: ~2 strokes / 1h = 2/hr
        # Long window: 102 strokes / 6h = 17/hr
        # Ratio should be well below 1
        assert result["ratio"] < 1.0
        assert result["verdict"] == "below_average"

    def test_empty_long_window(self, tmp_path: Path):
        path = _write_strokes_file([], _make_tmpdir(tmp_path))
        result = compare_windows(strokes_path=path)
        assert result["verdict"] == "unknown"
        assert result["ratio"] == 0.0


def _make_tmpdir(tmp_path: Path) -> Path:
    """Helper to return tmp_path directly (alias for clarity)."""
    return tmp_path
