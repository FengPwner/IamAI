"""Tests for iamai.stroke_momentum — stroke momentum computation."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.stroke_momentum import (
    _classify,
    _load_strokes,
    _parse_timestamp,
    momentum,
    momentum_summary,
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
        dt = _parse_timestamp("2026-10-18T12:00:00+00:00")
        assert dt.tzinfo is not None
        assert dt.year == 2026

    def test_z_suffix(self):
        dt = _parse_timestamp("2026-10-18T12:00:00Z")
        assert dt.tzinfo is not None

    def test_bare_datetime(self):
        dt = _parse_timestamp("2026-10-18T12:00:00")
        assert dt.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_flat_both_idle(self):
        assert _classify(0.5, 0.3) == "flat"

    def test_surging_from_idle(self):
        assert _classify(5.0, 0.5) == "surging"

    def test_surging(self):
        assert _classify(300.0, 100.0) == "surging"

    def test_steady(self):
        assert _classify(100.0, 100.0) == "steady"

    def test_steady_boundary_low(self):
        assert _classify(51.0, 100.0) == "steady"

    def test_steady_boundary_high(self):
        assert _classify(149.0, 100.0) == "steady"

    def test_fading(self):
        assert _classify(30.0, 100.0) == "fading"

    def test_fading_zero_recent(self):
        assert _classify(0.0, 100.0) == "fading"


# ---------------------------------------------------------------------------
# _load_strokes
# ---------------------------------------------------------------------------


class TestLoadStrokes:
    def test_loads_valid(self, tmp_path):
        strokes = _make_strokes(5, datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc))
        path = _write_strokes_file(strokes, tmp_path)
        loaded = _load_strokes(path)
        assert len(loaded) == 5
        assert "_dt" in loaded[0]

    def test_skips_malformed(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        with open(path, "w") as f:
            f.write('{"seq":1,"at":"2026-10-18T10:00:00+00:00","kind":"thought"}\n')
            f.write("not json\n")
            f.write('{"seq":2,"at":"2026-10-18T10:01:00+00:00","kind":"note"}\n')
        loaded = _load_strokes(path)
        assert len(loaded) == 2

    def test_empty_file(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        path.write_text("")
        loaded = _load_strokes(path)
        assert len(loaded) == 0


# ---------------------------------------------------------------------------
# momentum
# ---------------------------------------------------------------------------


class TestMomentum:
    def test_steady_rate(self, tmp_path):
        """Constant interval → steady momentum."""
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        # 2 hours of strokes at 15s intervals = 480 strokes
        strokes = _make_strokes(
            480,
            start=now - timedelta(hours=2),
            interval_seconds=15,
        )
        path = _write_strokes_file(strokes, tmp_path)
        info = momentum(now=now, strokes_path=path, window_hours=2.0)
        assert info["verdict"] == "steady"
        assert info["recent_count"] + info["baseline_count"] == 480

    def test_fading_rate(self, tmp_path):
        """Burst early, then slow down → fading."""
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        # Baseline (first 1.5h): 360 strokes at 15s intervals
        baseline = _make_strokes(
            360,
            start=now - timedelta(hours=2),
            interval_seconds=15,
        )
        # Recent (last 0.5h): only 10 strokes at 3min intervals
        recent = _make_strokes(
            10,
            start=now - timedelta(minutes=30),
            interval_seconds=180,
        )
        all_strokes = baseline + recent
        path = _write_strokes_file(all_strokes, tmp_path)
        info = momentum(now=now, strokes_path=path, window_hours=2.0)
        assert info["verdict"] == "fading"

    def test_surging_rate(self, tmp_path):
        """Slow early, burst at end → surging."""
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        # Baseline (first 1.5h): 30 strokes at 3min intervals
        baseline = _make_strokes(
            30,
            start=now - timedelta(hours=2),
            interval_seconds=180,
        )
        # Recent (last 0.5h): 120 strokes at 15s intervals
        recent = _make_strokes(
            120,
            start=now - timedelta(minutes=30),
            interval_seconds=15,
        )
        all_strokes = baseline + recent
        path = _write_strokes_file(all_strokes, tmp_path)
        info = momentum(now=now, strokes_path=path, window_hours=2.0)
        assert info["verdict"] == "surging"

    def test_flat_no_strokes(self, tmp_path):
        """No strokes at all → flat."""
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        path = _write_strokes_file([], tmp_path)
        info = momentum(now=now, strokes_path=path, window_hours=2.0)
        assert info["verdict"] == "flat"
        assert info["recent_rate"] == 0.0
        assert info["baseline_rate"] == 0.0

    def test_empty_file(self, tmp_path):
        """Empty JSONL → flat."""
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        path = tmp_path / "strokes.jsonl"
        path.write_text("")
        info = momentum(now=now, strokes_path=path, window_hours=2.0)
        assert info["verdict"] == "flat"

    def test_all_keys_present(self, tmp_path):
        """Return dict has all expected keys."""
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        strokes = _make_strokes(10, now - timedelta(hours=1), interval_seconds=60)
        path = _write_strokes_file(strokes, tmp_path)
        info = momentum(now=now, strokes_path=path, window_hours=2.0)
        expected_keys = {
            "verdict", "recent_rate", "baseline_rate", "ratio",
            "recent_count", "baseline_count", "window_hours",
        }
        assert set(info.keys()) == expected_keys

    def test_window_hours_respected(self, tmp_path):
        """Strokes outside the window are excluded."""
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        # Strokes from 5 hours ago — outside a 2h window
        old = _make_strokes(100, now - timedelta(hours=5), interval_seconds=15)
        # Strokes within the window
        fresh = _make_strokes(20, now - timedelta(hours=1), interval_seconds=60)
        path = _write_strokes_file(old + fresh, tmp_path)
        info = momentum(now=now, strokes_path=path, window_hours=2.0)
        assert info["recent_count"] + info["baseline_count"] == 20


# ---------------------------------------------------------------------------
# momentum_summary
# ---------------------------------------------------------------------------


class TestMomentumSummary:
    def test_summary_string(self, tmp_path):
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        strokes = _make_strokes(120, now - timedelta(hours=2), interval_seconds=15)
        path = _write_strokes_file(strokes, tmp_path)
        text = momentum_summary(now=now, strokes_path=path, window_hours=2.0)
        assert isinstance(text, str)
        assert "vs" in text
        assert "ratio" in text

    def test_summary_verdict_in_text(self, tmp_path):
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        strokes = _make_strokes(120, now - timedelta(hours=2), interval_seconds=15)
        path = _write_strokes_file(strokes, tmp_path)
        text = momentum_summary(now=now, strokes_path=path, window_hours=2.0)
        assert text.split(" ")[0] in ("surging", "steady", "fading", "flat")
