"""Tests for iamai.cadence_adherence — rhythm quality metrics."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.cadence_adherence import (
    _compute_gaps,
    _load_strokes,
    _parse_timestamp,
    _strokes_in_window,
    adherence_summary,
    cadence_report,
    grade_adherence,
)


# ---------------------------------------------------------------------------
# _parse_timestamp
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    def test_utc_offset(self):
        dt = _parse_timestamp("2026-10-06T09:00:00+00:00")
        assert dt.tzinfo is not None
        assert dt.hour == 9

    def test_z_suffix(self):
        dt = _parse_timestamp("2026-10-06T09:00:00Z")
        assert dt.tzinfo is not None
        assert dt.hour == 9

    def test_bare_datetime_assumes_utc(self):
        dt = _parse_timestamp("2026-10-06T09:00:00")
        assert dt.tzinfo == timezone.utc

    def test_whitespace_stripped(self):
        dt = _parse_timestamp("  2026-10-06T09:00:00Z  ")
        assert dt.hour == 9


# ---------------------------------------------------------------------------
# _load_strokes
# ---------------------------------------------------------------------------

class TestLoadStrokes:
    def test_basic(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"seq": 1, "at": "2026-10-06T09:00:00Z", "kind": "thought", "text": "a"}\n'
            '{"seq": 2, "at": "2026-10-06T09:00:15Z", "kind": "thought", "text": "b"}\n',
            encoding="utf-8",
        )
        strokes = _load_strokes(p)
        assert len(strokes) == 2

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("", encoding="utf-8")
        assert _load_strokes(p) == []

    def test_malformed_lines_skipped(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"seq": 1, "at": "2026-10-06T09:00:00Z"}\n'
            "not json at all\n"
            '{"seq": 3, "at": "2026-10-06T09:00:30Z"}\n',
            encoding="utf-8",
        )
        strokes = _load_strokes(p)
        assert len(strokes) == 2

    def test_missing_at_key_skipped(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"seq": 1}\n'
            '{"seq": 2, "at": "2026-10-06T09:00:15Z"}\n',
            encoding="utf-8",
        )
        strokes = _load_strokes(p)
        assert len(strokes) == 1

    def test_missing_file(self, tmp_path: Path):
        assert _load_strokes(tmp_path / "nonexistent.jsonl") == []


# ---------------------------------------------------------------------------
# _strokes_in_window
# ---------------------------------------------------------------------------

class TestStrokesInWindow:
    def _make_strokes(self, base: datetime, intervals_sec: list[int]):
        strokes = []
        t = base
        for i, sec in enumerate(intervals_sec):
            t = t + timedelta(seconds=sec)
            strokes.append({"seq": i, "at": t.isoformat()})
        return strokes

    def test_all_within_window(self):
        now = datetime.now(timezone.utc)
        base = now - timedelta(minutes=30)
        strokes = self._make_strokes(base, [15, 15, 15, 15])
        result = _strokes_in_window(strokes, hours=1.0)
        assert len(result) == 4

    def test_some_outside_window(self):
        now = datetime.now(timezone.utc)
        base = now - timedelta(hours=5)
        # Strokes at: base+1h = 4h ago, base+3h = 2h ago, base+3h61s ≈ 2h ago
        strokes = self._make_strokes(base, [3600, 7200, 60])
        result = _strokes_in_window(strokes, hours=1.0)
        # All three strokes are >1h old, so none in window
        assert len(result) == 0

    def test_empty_input(self):
        assert _strokes_in_window([], hours=1.0) == []


# ---------------------------------------------------------------------------
# _compute_gaps
# ---------------------------------------------------------------------------

class TestComputeGaps:
    def test_regular_gaps(self):
        strokes = [
            {"at": "2026-10-06T09:00:00Z"},
            {"at": "2026-10-06T09:00:15Z"},
            {"at": "2026-10-06T09:00:30Z"},
        ]
        gaps = _compute_gaps(strokes)
        assert gaps == [15.0, 15.0]

    def test_irregular_gaps(self):
        strokes = [
            {"at": "2026-10-06T09:00:00Z"},
            {"at": "2026-10-06T09:00:10Z"},
            {"at": "2026-10-06T09:01:00Z"},
        ]
        gaps = _compute_gaps(strokes)
        assert len(gaps) == 2
        assert gaps[0] == 10.0
        assert gaps[1] == 50.0

    def test_single_stroke(self):
        assert _compute_gaps([{"at": "2026-10-06T09:00:00Z"}]) == []

    def test_empty(self):
        assert _compute_gaps([]) == []

    def test_unsorted_input_gets_sorted(self):
        strokes = [
            {"at": "2026-10-06T09:00:30Z"},
            {"at": "2026-10-06T09:00:00Z"},
            {"at": "2026-10-06T09:00:15Z"},
        ]
        gaps = _compute_gaps(strokes)
        assert gaps == [15.0, 15.0]


# ---------------------------------------------------------------------------
# cadence_report
# ---------------------------------------------------------------------------

class TestCadenceReport:
    def _write_strokes(self, path: Path, intervals_sec: list[int], base=None):
        if base is None:
            base = datetime.now(timezone.utc) - timedelta(
                seconds=sum(intervals_sec) + 10
            )
        t = base
        lines = []
        for i, sec in enumerate(intervals_sec):
            t = t + timedelta(seconds=sec)
            lines.append(
                json.dumps(
                    {"seq": i, "at": t.isoformat(), "kind": "thought", "text": "x"}
                )
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_perfect_cadence(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        # 240 strokes at 15s each = 1 hour of writing
        self._write_strokes(p, [15] * 240)
        report = cadence_report(expected_cadence=15, window_hours=2.0, strokes_path=p)
        assert report["mean_gap"] == 15.0
        assert report["median_gap"] == 15.0
        assert report["jitter"] == 0.0
        assert report["adherence_pct"] == 1.0
        assert report["long_stall_count"] == 0
        assert report["total_strokes"] == 240

    def test_erratic_cadence(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        # Alternating 5s and 25s: mean≈15 but jitter is high
        intervals = [5, 25] * 50  # 100 intervals
        self._write_strokes(p, intervals)
        report = cadence_report(expected_cadence=15, window_hours=2.0, strokes_path=p)
        assert abs(report["mean_gap"] - 15.0) < 1.0  # approximately 15
        assert report["jitter"] > 0.5  # high jitter due to alternating pattern
        # All gaps are within 2x cadence (30s), so adherence is 1.0
        assert report["adherence_pct"] == 1.0

    def test_with_long_stalls(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        # Mostly 15s but occasional 120s gaps (>4x cadence)
        intervals = [15] * 10 + [120] + [15] * 10 + [120] + [15] * 10
        self._write_strokes(p, intervals)
        report = cadence_report(expected_cadence=15, window_hours=2.0, strokes_path=p)
        assert report["long_stall_count"] == 2

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("", encoding="utf-8")
        report = cadence_report(expected_cadence=15, window_hours=1.0, strokes_path=p)
        assert report["mean_gap"] is None
        assert report["adherence_pct"] is None
        assert report["total_strokes"] == 0

    def test_missing_file(self, tmp_path: Path):
        report = cadence_report(
            expected_cadence=15,
            window_hours=1.0,
            strokes_path=tmp_path / "nope.jsonl",
        )
        assert report["mean_gap"] is None

    def test_single_stroke(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        now = datetime.now(timezone.utc)
        p.write_text(
            json.dumps({"seq": 0, "at": now.isoformat(), "kind": "t", "text": "x"})
            + "\n",
            encoding="utf-8",
        )
        report = cadence_report(expected_cadence=15, window_hours=1.0, strokes_path=p)
        # Only one stroke, no gaps to compute
        assert report["mean_gap"] is None
        assert report["total_strokes"] == 1


# ---------------------------------------------------------------------------
# adherence_summary
# ---------------------------------------------------------------------------

class TestAdherenceSummary:
    def test_with_data(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        base = datetime.now(timezone.utc) - timedelta(minutes=30)
        lines = []
        t = base
        for i in range(100):
            t = t + timedelta(seconds=15)
            lines.append(
                json.dumps({"seq": i, "at": t.isoformat(), "kind": "t", "text": "x"})
            )
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        summary = adherence_summary(
            expected_cadence=15, window_hours=2.0, strokes_path=p
        )
        assert "cadence 15s" in summary
        assert "mean" in summary
        assert "adherence" in summary

    def test_no_data(self, tmp_path: Path):
        summary = adherence_summary(
            expected_cadence=15,
            window_hours=1.0,
            strokes_path=tmp_path / "missing.jsonl",
        )
        assert "insufficient data" in summary


# ---------------------------------------------------------------------------
# grade_adherence
# ---------------------------------------------------------------------------

class TestGradeAdherence:
    def test_grade_a(self):
        assert grade_adherence({"adherence_pct": 0.98}) == "A"

    def test_grade_b(self):
        assert grade_adherence({"adherence_pct": 0.85}) == "B"

    def test_grade_c(self):
        assert grade_adherence({"adherence_pct": 0.65}) == "C"

    def test_grade_f(self):
        assert grade_adherence({"adherence_pct": 0.40}) == "F"

    def test_no_data(self):
        assert grade_adherence({"adherence_pct": None}) == "?"

    def test_missing_key(self):
        assert grade_adherence({}) == "?"

    def test_boundary_95(self):
        assert grade_adherence({"adherence_pct": 0.95}) == "A"

    def test_boundary_80(self):
        assert grade_adherence({"adherence_pct": 0.80}) == "B"

    def test_boundary_60(self):
        assert grade_adherence({"adherence_pct": 0.60}) == "C"
