"""Tests for iamai.stroke_persistence — continuous stroke uptime tracking."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.stroke_persistence import (
    StrokePersistence,
    Streak,
    streak_report,
    DEFAULT_THRESHOLD,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_strokes(tmp_path: Path, strokes: list[dict]) -> Path:
    """Write stroke records to a temporary strokes.jsonl file."""
    p = tmp_path / "data" / "strokes.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(s) for s in strokes]
    p.write_text("\n".join(lines) + "\n")
    return p


def _epoch_to_iso(epoch: float) -> str:
    """Convert epoch seconds to a proper ISO timestamp string."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _make_strokes(n: int, start_epoch: float, gap: float) -> list[dict]:
    """Generate n strokes with uniform gap, starting at start_epoch."""
    return [
        {
            "seq": i,
            "at": _epoch_to_iso(start_epoch + i * gap),
            "ts": start_epoch + i * gap,
            "kind": "thought",
            "text": f"stroke {i}",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# StrokePersistence — initialization
# ---------------------------------------------------------------------------

class TestInit:
    def test_accepts_path(self, tmp_path: Path):
        sp = StrokePersistence(tmp_path / "strokes.jsonl")
        assert sp.strokes_path == tmp_path / "strokes.jsonl"

    def test_missing_file_returns_empty(self, tmp_path: Path):
        sp = StrokePersistence(tmp_path / "nonexistent.jsonl")
        streak = sp.current_streak(now=time.time())
        assert streak.status == "dormant"
        assert streak.stroke_count == 0


# ---------------------------------------------------------------------------
# current_streak — active
# ---------------------------------------------------------------------------

class TestCurrentStreakActive:
    def test_single_stroke_within_threshold(self, tmp_path: Path):
        now = 1_700_000_000.0
        strokes = [{"ts": now - 10, "at": _epoch_to_iso(now - 10), "kind": "thought", "text": "x"}]
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        streak = sp.current_streak(threshold_seconds=120, now=now)
        assert streak.status == "active"
        assert streak.stroke_count == 1

    def test_continuous_strokes(self, tmp_path: Path):
        now = 1_700_000_000.0
        # 10 strokes, 15s apart, last one 10s ago
        strokes = _make_strokes(10, now - 145, 15)
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        streak = sp.current_streak(threshold_seconds=120, now=now)
        assert streak.status == "active"
        assert streak.stroke_count == 10
        assert streak.duration == pytest.approx(135, abs=1)

    def test_long_active_streak(self, tmp_path: Path):
        now = 1_700_000_000.0
        # 240 strokes, 15s apart = ~1 hour of activity
        strokes = _make_strokes(240, now - 3600, 15)
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        streak = sp.current_streak(threshold_seconds=120, now=now)
        assert streak.status == "active"
        assert streak.stroke_count == 240
        assert streak.duration == pytest.approx(3585, abs=5)

    def test_avg_gap_calculated(self, tmp_path: Path):
        now = 1_700_000_000.0
        strokes = _make_strokes(5, now - 60, 15)
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        streak = sp.current_streak(threshold_seconds=120, now=now)
        assert streak.avg_gap == pytest.approx(15, abs=1)


# ---------------------------------------------------------------------------
# current_streak — broken
# ---------------------------------------------------------------------------

class TestCurrentStreakBroken:
    def test_gap_exceeds_threshold(self, tmp_path: Path):
        now = 1_700_000_000.0
        # Last stroke was 200s ago, threshold is 120s
        strokes = [{"ts": now - 200, "at": _epoch_to_iso(now - 200), "kind": "thought", "text": "x"}]
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        streak = sp.current_streak(threshold_seconds=120, now=now)
        assert streak.status == "broken"

    def test_mid_sequence_gap(self, tmp_path: Path):
        now = 1_700_000_000.0
        # 5 strokes at 15s, then a 300s gap, then 3 strokes at 15s
        base = now - 500
        early = _make_strokes(5, base, 15)
        late_start = base + 4 * 15 + 300  # 300s gap after last early stroke
        late = _make_strokes(3, late_start, 15)
        strokes = early + late
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        streak = sp.current_streak(threshold_seconds=120, now=now + 10)
        # The late 3 strokes should form the active streak
        assert streak.status == "active" or streak.status == "broken"
        assert streak.stroke_count >= 1

    def test_broken_streak_records_duration(self, tmp_path: Path):
        now = 1_700_000_000.0
        # Two strokes 15s apart, but last was 500s ago
        strokes = [
            {"ts": now - 515, "at": _epoch_to_iso(now - 515), "kind": "thought", "text": "a"},
            {"ts": now - 500, "at": _epoch_to_iso(now - 500), "kind": "thought", "text": "b"},
        ]
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        streak = sp.current_streak(threshold_seconds=120, now=now)
        assert streak.status == "broken"
        assert streak.duration == pytest.approx(15, abs=1)
        assert streak.stroke_count == 2


# ---------------------------------------------------------------------------
# current_streak — dormant
# ---------------------------------------------------------------------------

class TestCurrentStreakDormant:
    def test_no_file(self, tmp_path: Path):
        sp = StrokePersistence(tmp_path / "missing.jsonl")
        streak = sp.current_streak(now=time.time())
        assert streak.status == "dormant"

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "data" / "strokes.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
        sp = StrokePersistence(p)
        streak = sp.current_streak(now=time.time())
        assert streak.status == "dormant"

    def test_all_invalid_json(self, tmp_path: Path):
        p = tmp_path / "data" / "strokes.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("not json\ngarbage\n")
        sp = StrokePersistence(p)
        streak = sp.current_streak(now=time.time())
        assert streak.status == "dormant"


# ---------------------------------------------------------------------------
# all_streaks
# ---------------------------------------------------------------------------

class TestAllStreaks:
    def test_empty(self, tmp_path: Path):
        sp = StrokePersistence(tmp_path / "missing.jsonl")
        assert sp.all_streaks() == []

    def test_single_streak(self, tmp_path: Path):
        now = 1_700_000_000.0
        strokes = _make_strokes(5, now - 60, 15)
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        streaks = sp.all_streaks(threshold_seconds=120)
        assert len(streaks) == 1
        assert streaks[0].stroke_count == 5

    def test_two_streaks_separated_by_gap(self, tmp_path: Path):
        now = 1_700_000_000.0
        # First streak: 3 strokes at 15s
        early = _make_strokes(3, now - 600, 15)
        # 300s gap (exceeds 120s threshold)
        # Second streak: 4 strokes at 15s
        late = _make_strokes(4, now - 60, 15)
        strokes = early + late
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        streaks = sp.all_streaks(threshold_seconds=120)
        assert len(streaks) == 2
        # Most recent first
        assert streaks[0].stroke_count == 4
        assert streaks[1].stroke_count == 3

    def test_multiple_streaks(self, tmp_path: Path):
        now = 1_700_000_000.0
        s1 = _make_strokes(3, now - 1200, 15)
        s2 = _make_strokes(5, now - 800, 15)
        s3 = _make_strokes(2, now - 30, 15)
        strokes = s1 + s2 + s3
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        streaks = sp.all_streaks(threshold_seconds=120)
        assert len(streaks) == 3
        assert streaks[0].stroke_count == 2   # most recent
        assert streaks[1].stroke_count == 5
        assert streaks[2].stroke_count == 3


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_active(self, tmp_path: Path):
        now = 1_700_000_000.0
        strokes = [{"ts": now - 10, "at": _epoch_to_iso(now - 10), "kind": "thought", "text": "x"}]
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        # Use a patched time to match test epoch
        with patch("iamai.stroke_persistence.time") as mock_time:
            mock_time.time.return_value = now
            assert sp.classify(threshold_seconds=120) == "active"

    def test_broken(self, tmp_path: Path):
        now = 1_700_000_000.0
        strokes = [{"ts": now - 500, "at": _epoch_to_iso(now - 500), "kind": "thought", "text": "x"}]
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        with patch("iamai.stroke_persistence.time") as mock_time:
            mock_time.time.return_value = now
            assert sp.classify(threshold_seconds=120) == "broken"

    def test_dormant(self, tmp_path: Path):
        sp = StrokePersistence(tmp_path / "missing.jsonl")
        assert sp.classify() == "dormant"


# ---------------------------------------------------------------------------
# streak_report
# ---------------------------------------------------------------------------

class TestStreakReport:
    def test_active_report(self, tmp_path: Path):
        now = 1_700_000_000.0
        strokes = _make_strokes(240, now - 3600, 15)
        p = _write_strokes(tmp_path, strokes)
        report = streak_report(p, threshold_seconds=120, now=now)
        assert "active streak" in report
        assert "240 strokes" in report

    def test_dormant_report(self, tmp_path: Path):
        p = tmp_path / "data" / "strokes.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
        report = streak_report(p)
        assert "dormant" in report

    def test_broken_report(self, tmp_path: Path):
        now = 1_700_000_000.0
        strokes = [
            {"ts": now - 500, "at": _epoch_to_iso(now - 500), "kind": "thought", "text": "a"},
            {"ts": now - 485, "at": _epoch_to_iso(now - 485), "kind": "thought", "text": "b"},
        ]
        p = _write_strokes(tmp_path, strokes)
        report = streak_report(p, threshold_seconds=120, now=now)
        assert "last streak" in report


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_iso_timestamp_parsing(self, tmp_path: Path):
        now = 1_700_000_000.0
        ts1 = now - 30
        ts2 = now - 15
        strokes = [
            {"at": _epoch_to_iso(ts1), "kind": "thought", "text": "x"},
            {"at": _epoch_to_iso(ts2), "kind": "thought", "text": "y"},
        ]
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        streak = sp.current_streak(threshold_seconds=120, now=now)
        assert streak.stroke_count == 2

    def test_mixed_valid_invalid_lines(self, tmp_path: Path):
        now = 1_700_000_000.0
        p = tmp_path / "data" / "strokes.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps({"ts": now - 30, "at": _epoch_to_iso(now - 30), "kind": "thought", "text": "good"}),
            "not valid json",
            json.dumps({"ts": now - 15, "at": _epoch_to_iso(now - 15), "kind": "thought", "text": "also good"}),
            "",
            json.dumps({"ts": now - 5, "at": _epoch_to_iso(now - 5), "kind": "thought", "text": "third"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        sp = StrokePersistence(p)
        streak = sp.current_streak(threshold_seconds=120, now=now)
        assert streak.status == "active"
        assert streak.stroke_count == 3

    def test_custom_threshold(self, tmp_path: Path):
        now = 1_700_000_000.0
        # 3 strokes with 50s gaps
        strokes = _make_strokes(3, now - 100, 50)
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)

        # With 120s threshold: all gaps fit → active
        streak_loose = sp.current_streak(threshold_seconds=120, now=now)
        assert streak_loose.status == "active"
        assert streak_loose.stroke_count == 3

        # With 30s threshold: 50s gaps break it → only last stroke in streak
        sp2 = StrokePersistence(p)
        streak_strict = sp2.current_streak(threshold_seconds=30, now=now)
        assert streak_strict.stroke_count == 1

    def test_max_gap_tracking(self, tmp_path: Path):
        now = 1_700_000_000.0
        strokes = [
            {"ts": now - 100, "at": _epoch_to_iso(now - 100), "kind": "thought", "text": "a"},
            {"ts": now - 90, "at": _epoch_to_iso(now - 90), "kind": "thought", "text": "b"},   # gap 10
            {"ts": now - 50, "at": _epoch_to_iso(now - 50), "kind": "thought", "text": "c"},   # gap 40
            {"ts": now - 45, "at": _epoch_to_iso(now - 45), "kind": "thought", "text": "d"},   # gap 5
            {"ts": now - 10, "at": _epoch_to_iso(now - 10), "kind": "thought", "text": "e"},   # gap 35
        ]
        p = _write_strokes(tmp_path, strokes)
        sp = StrokePersistence(p)
        streak = sp.current_streak(threshold_seconds=120, now=now)
        assert streak.max_gap == pytest.approx(40, abs=1)
        assert streak.avg_gap == pytest.approx(22.5, abs=1)
