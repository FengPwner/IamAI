"""Tests for iamai.session_memory — reconstruct session boundaries and summaries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from iamai.session_memory import (
    DEFAULT_SESSION_GAP,
    _build_session,
    _format_duration,
    _load_strokes_light,
    _parse_ts,
    detect_sessions,
    session_brief,
    session_pace,
    session_summary,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _stroke(seq: int, at: str, kind: str = "thought", path: str = "") -> dict:
    return {"seq": seq, "at": at, "kind": kind, "path": path}


def _write_strokes(tmp: Path, strokes: list[dict], filename: str = "strokes.jsonl") -> Path:
    p = tmp / filename
    p.write_text("\n".join(json.dumps(s) for s in strokes) + "\n", encoding="utf-8")
    return p


def _ts(iso: str) -> datetime:
    return _parse_ts(iso)


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    def test_utc_z_suffix(self):
        dt = _parse_ts("2026-10-15T12:00:00Z")
        assert dt.tzinfo is not None
        assert dt.hour == 12

    def test_offset_suffix(self):
        dt = _parse_ts("2026-10-15T12:00:00+08:00")
        assert dt.tzinfo is not None

    def test_naive_gets_utc(self):
        dt = _parse_ts("2026-10-15T12:00:00")
        assert dt.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# _format_duration
# ---------------------------------------------------------------------------

class TestFormatDuration:
    def test_seconds(self):
        assert _format_duration(45) == "45s"

    def test_minutes_only(self):
        assert _format_duration(300) == "5m"

    def test_minutes_and_seconds(self):
        assert _format_duration(325) == "5m25s"

    def test_hours(self):
        assert _format_duration(3661) == "1h01m"

    def test_zero(self):
        assert _format_duration(0) == "0s"


# ---------------------------------------------------------------------------
# _load_strokes_light
# ---------------------------------------------------------------------------

class TestLoadStrokesLight:
    def test_loads_basic_fields(self, tmp_path):
        p = _write_strokes(tmp_path, [
            _stroke(1, "2026-10-15T00:00:00Z", "thought", "notes/a.md"),
            _stroke(2, "2026-10-15T00:00:15Z", "note", "notes/b.md"),
        ])
        result = _load_strokes_light(p)
        assert len(result) == 2
        assert result[0]["seq"] == 1
        assert result[0]["kind"] == "thought"
        assert result[0]["path"] == "notes/a.md"
        assert isinstance(result[0]["at"], datetime)

    def test_missing_file_returns_empty(self, tmp_path):
        assert _load_strokes_light(tmp_path / "nonexistent.jsonl") == []

    def test_skips_malformed_lines(self, tmp_path):
        p = tmp_path / "bad.jsonl"
        p.write_text(
            '{"seq": 1, "at": "2026-10-15T00:00:00Z", "kind": "ok"}\n'
            'not json\n'
            '{"seq": 2, "at": "2026-10-15T00:00:15Z", "kind": "ok"}\n',
            encoding="utf-8",
        )
        result = _load_strokes_light(p)
        assert len(result) == 2

    def test_skips_lines_without_at(self, tmp_path):
        p = tmp_path / "no_at.jsonl"
        p.write_text(
            '{"seq": 1, "kind": "orphan"}\n'
            '{"seq": 2, "at": "2026-10-15T00:00:00Z", "kind": "ok"}\n',
            encoding="utf-8",
        )
        result = _load_strokes_light(p)
        assert len(result) == 1
        assert result[0]["seq"] == 2


# ---------------------------------------------------------------------------
# detect_sessions
# ---------------------------------------------------------------------------

class TestDetectSessions:
    def test_single_session(self, tmp_path):
        p = _write_strokes(tmp_path, [
            _stroke(i, f"2026-10-15T00:00:{i:02d}Z") for i in range(1, 6)
        ])
        sessions = detect_sessions(p, max_gap_seconds=60)
        assert len(sessions) == 1
        assert sessions[0]["stroke_count"] == 5
        assert sessions[0]["id"] == 1

    def test_two_sessions_with_gap(self, tmp_path):
        strokes = [
            _stroke(1, "2026-10-15T00:00:00Z"),
            _stroke(2, "2026-10-15T00:00:15Z"),
            _stroke(3, "2026-10-15T00:00:30Z"),
            # 40-minute gap
            _stroke(4, "2026-10-15T00:40:30Z"),
            _stroke(5, "2026-10-15T00:40:45Z"),
        ]
        p = _write_strokes(tmp_path, strokes)
        sessions = detect_sessions(p, max_gap_seconds=1800)
        assert len(sessions) == 2
        assert sessions[0]["stroke_count"] == 3
        assert sessions[1]["stroke_count"] == 2

    def test_empty_file(self, tmp_path):
        p = _write_strokes(tmp_path, [])
        sessions = detect_sessions(p)
        assert sessions == []

    def test_single_stroke(self, tmp_path):
        p = _write_strokes(tmp_path, [
            _stroke(1, "2026-10-15T00:00:00Z"),
        ])
        sessions = detect_sessions(p)
        assert len(sessions) == 1
        assert sessions[0]["stroke_count"] == 1
        assert sessions[0]["duration_seconds"] == 0.0

    def test_kind_breakdown(self, tmp_path):
        strokes = [
            _stroke(1, "2026-10-15T00:00:00Z", "thought"),
            _stroke(2, "2026-10-15T00:00:15Z", "note"),
            _stroke(3, "2026-10-15T00:00:30Z", "thought"),
            _stroke(4, "2026-10-15T00:00:45Z", "snippet"),
        ]
        p = _write_strokes(tmp_path, strokes)
        sessions = detect_sessions(p)
        bd = sessions[0]["kind_breakdown"]
        assert bd["thought"] == 2
        assert bd["note"] == 1
        assert bd["snippet"] == 1

    def test_files_touched(self, tmp_path):
        strokes = [
            _stroke(1, "2026-10-15T00:00:00Z", "thought", "notes/a.md"),
            _stroke(2, "2026-10-15T00:00:15Z", "note", "notes/b.md"),
            _stroke(3, "2026-10-15T00:00:30Z", "thought", "notes/a.md"),
        ]
        p = _write_strokes(tmp_path, strokes)
        sessions = detect_sessions(p)
        assert sessions[0]["files_touched"] == ["notes/a.md", "notes/b.md"]

    def test_seq_tracking(self, tmp_path):
        strokes = [
            _stroke(100, "2026-10-15T00:00:00Z"),
            _stroke(101, "2026-10-15T00:00:15Z"),
            _stroke(102, "2026-10-15T00:00:30Z"),
        ]
        p = _write_strokes(tmp_path, strokes)
        sessions = detect_sessions(p)
        assert sessions[0]["first_seq"] == 100
        assert sessions[0]["last_seq"] == 102

    def test_duration_calculation(self, tmp_path):
        strokes = [
            _stroke(1, "2026-10-15T00:00:00Z"),
            _stroke(2, "2026-10-15T00:05:00Z"),  # 5 min later
            _stroke(3, "2026-10-15T00:10:00Z"),  # 10 min from start
        ]
        p = _write_strokes(tmp_path, strokes)
        sessions = detect_sessions(p)
        assert sessions[0]["duration_seconds"] == 600.0

    def test_custom_gap_threshold(self, tmp_path):
        strokes = [
            _stroke(1, "2026-10-15T00:00:00Z"),
            _stroke(2, "2026-10-15T00:00:15Z"),
            # 120s gap — splits at 60s threshold, not at 300s
            _stroke(3, "2026-10-15T00:02:15Z"),
            _stroke(4, "2026-10-15T00:02:30Z"),
        ]
        p = _write_strokes(tmp_path, strokes)

        sessions_60 = detect_sessions(p, max_gap_seconds=60)
        assert len(sessions_60) == 2

        sessions_300 = detect_sessions(p, max_gap_seconds=300)
        assert len(sessions_300) == 1

    def test_many_sessions(self, tmp_path):
        # 10 sessions of 3 strokes each, separated by 1-hour gaps
        strokes = []
        seq = 1
        for s in range(10):
            base_hour = s * 2  # 2-hour spacing
            for i in range(3):
                strokes.append(_stroke(
                    seq,
                    f"2026-10-15T{base_hour:02d}:00:{i*15:02d}Z",
                ))
                seq += 1
        p = _write_strokes(tmp_path, strokes)
        sessions = detect_sessions(p, max_gap_seconds=1800)
        assert len(sessions) == 10
        for s in sessions:
            assert s["stroke_count"] == 3


# ---------------------------------------------------------------------------
# session_summary
# ---------------------------------------------------------------------------

class TestSessionSummary:
    def test_aggregate_stats(self, tmp_path):
        strokes = [
            _stroke(1, "2026-10-15T00:00:00Z", "thought"),
            _stroke(2, "2026-10-15T00:00:15Z", "note"),
            _stroke(3, "2026-10-15T00:00:30Z", "thought"),
            # gap
            _stroke(4, "2026-10-15T01:00:00Z", "snippet"),
            _stroke(5, "2026-10-15T01:00:15Z", "snippet"),
        ]
        p = _write_strokes(tmp_path, strokes)
        summary = session_summary(p, max_gap_seconds=1800)

        assert summary["total_sessions"] == 2
        assert summary["total_strokes"] == 5
        assert summary["longest_session_strokes"] == 3
        assert summary["longest_session_id"] == 1
        assert summary["kind_totals"]["thought"] == 2
        assert summary["kind_totals"]["note"] == 1
        assert summary["kind_totals"]["snippet"] == 2

    def test_empty_input(self, tmp_path):
        p = _write_strokes(tmp_path, [])
        summary = session_summary(p)
        assert summary["total_sessions"] == 0
        assert summary["total_strokes"] == 0
        assert summary["avg_strokes_per_session"] == 0.0

    def test_averages(self, tmp_path):
        strokes = [
            _stroke(1, "2026-10-15T00:00:00Z"),
            _stroke(2, "2026-10-15T00:00:15Z"),
            # gap
            _stroke(3, "2026-10-15T01:00:00Z"),
            _stroke(4, "2026-10-15T01:00:15Z"),
            _stroke(5, "2026-10-15T01:00:30Z"),
            _stroke(6, "2026-10-15T01:00:45Z"),
        ]
        p = _write_strokes(tmp_path, strokes)
        summary = session_summary(p, max_gap_seconds=1800)

        assert summary["avg_strokes_per_session"] == 3.0
        # Session 1: 15s, Session 2: 45s → avg 30s
        assert summary["avg_duration_seconds"] == 30.0


# ---------------------------------------------------------------------------
# session_brief
# ---------------------------------------------------------------------------

class TestSessionBrief:
    def test_brief_format(self, tmp_path):
        strokes = [
            _stroke(1, "2026-10-15T00:00:00Z", "thought"),
            _stroke(2, "2026-10-15T00:00:15Z", "note"),
            _stroke(3, "2026-10-15T00:00:30Z", "thought"),
            # gap
            _stroke(4, "2026-10-15T01:00:00Z", "snippet"),
            _stroke(5, "2026-10-15T01:00:15Z", "snippet"),
        ]
        p = _write_strokes(tmp_path, strokes)
        brief = session_brief(p, max_gap_seconds=1800, last_n=5)

        assert "session 1:" in brief
        assert "session 2:" in brief
        assert "---" in brief
        assert "2 sessions:" in brief

    def test_brief_last_n(self, tmp_path):
        strokes = []
        seq = 1
        for s in range(5):
            base = s * 2  # 2-hour spacing
            for i in range(3):
                strokes.append(_stroke(seq, f"2026-10-15T{base:02d}:00:{i*15:02d}Z"))
                seq += 1
        p = _write_strokes(tmp_path, strokes)
        brief = session_brief(p, max_gap_seconds=1800, last_n=2)

        # Should only mention the last 2 sessions
        assert "session 4:" in brief
        assert "session 5:" in brief
        assert "session 1:" not in brief
        assert "2 sessions:" in brief

    def test_brief_empty(self, tmp_path):
        p = _write_strokes(tmp_path, [])
        brief = session_brief(p)
        assert brief == "no sessions detected"

    def test_brief_single_stroke_session(self, tmp_path):
        p = _write_strokes(tmp_path, [
            _stroke(1, "2026-10-15T00:00:00Z", "thought"),
        ])
        brief = session_brief(p)
        assert "session 1:" in brief
        assert "1 strokes" in brief


# ---------------------------------------------------------------------------
# session_pace
# ---------------------------------------------------------------------------

class TestSessionPace:
    def test_per_session_cadence(self, tmp_path):
        # Session 1: strokes every 15s (on target)
        # Session 2: strokes every 60s (off target for 15s cadence)
        strokes = [
            _stroke(1, "2026-10-15T00:00:00Z"),
            _stroke(2, "2026-10-15T00:00:15Z"),
            _stroke(3, "2026-10-15T00:00:30Z"),
            # 2-hour gap
            _stroke(4, "2026-10-15T02:00:00Z"),
            _stroke(5, "2026-10-15T02:01:00Z"),
            _stroke(6, "2026-10-15T02:02:00Z"),
        ]
        p = _write_strokes(tmp_path, strokes)
        pace = session_pace(p, max_gap_seconds=1800, expected_cadence=15.0)

        assert len(pace["sessions"]) == 2
        assert pace["sessions"][0]["mean_gap"] == 15.0
        assert pace["sessions"][0]["on_target"] is True
        assert pace["sessions"][1]["mean_gap"] == 60.0
        assert pace["sessions"][1]["on_target"] is False

    def test_empty_input(self, tmp_path):
        p = _write_strokes(tmp_path, [])
        pace = session_pace(p)
        assert pace["sessions"] == []
        assert pace["overall_mean_gap"] == 0.0

    def test_single_stroke_session(self, tmp_path):
        p = _write_strokes(tmp_path, [
            _stroke(1, "2026-10-15T00:00:00Z"),
        ])
        pace = session_pace(p)
        assert len(pace["sessions"]) == 1
        assert pace["sessions"][0]["mean_gap"] == 0.0

    def test_overall_mean_gap(self, tmp_path):
        strokes = [
            _stroke(1, "2026-10-15T00:00:00Z"),
            _stroke(2, "2026-10-15T00:00:10Z"),
            _stroke(3, "2026-10-15T00:00:20Z"),
        ]
        p = _write_strokes(tmp_path, strokes)
        pace = session_pace(p, max_gap_seconds=1800)
        assert pace["overall_mean_gap"] == 10.0

    def test_sessions_on_target_pct(self, tmp_path):
        # 3 sessions: 2 on target, 1 off
        strokes = [
            _stroke(1, "2026-10-15T00:00:00Z"),
            _stroke(2, "2026-10-15T00:00:15Z"),
            # gap
            _stroke(3, "2026-10-15T02:00:00Z"),
            _stroke(4, "2026-10-15T02:00:15Z"),
            # gap
            _stroke(5, "2026-10-15T04:00:00Z"),
            _stroke(6, "2026-10-15T04:05:00Z"),  # 5 min gap — off target
        ]
        p = _write_strokes(tmp_path, strokes)
        pace = session_pace(p, max_gap_seconds=1800, expected_cadence=15.0)

        assert len(pace["sessions"]) == 3
        assert pace["sessions"][0]["on_target"] is True
        assert pace["sessions"][1]["on_target"] is True
        # Session 3 has mean_gap=300, ratio=20.0 → off target
        assert pace["sessions"][2]["on_target"] is False
        assert pace["sessions_on_target_pct"] == pytest.approx(66.7, abs=0.1)


# ---------------------------------------------------------------------------
# _build_session
# ---------------------------------------------------------------------------

class TestBuildSession:
    def test_basic(self):
        strokes = [
            {"seq": 10, "at": _ts("2026-10-15T00:00:00Z"), "kind": "thought", "path": "a.md"},
            {"seq": 11, "at": _ts("2026-10-15T00:00:15Z"), "kind": "note", "path": "b.md"},
            {"seq": 12, "at": _ts("2026-10-15T00:00:30Z"), "kind": "thought", "path": "a.md"},
        ]
        s = _build_session(7, strokes)
        assert s["id"] == 7
        assert s["stroke_count"] == 3
        assert s["duration_seconds"] == 30.0
        assert s["kind_breakdown"]["thought"] == 2
        assert s["kind_breakdown"]["note"] == 1
        assert s["files_touched"] == ["a.md", "b.md"]
        assert s["first_seq"] == 10
        assert s["last_seq"] == 12


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_z_suffix_timestamps(self, tmp_path):
        strokes = [
            {"seq": 1, "at": "2026-10-15T00:00:00Z", "kind": "x", "path": ""},
            {"seq": 2, "at": "2026-10-15T00:00:15Z", "kind": "x", "path": ""},
        ]
        p = _write_strokes(tmp_path, strokes)
        sessions = detect_sessions(p)
        assert len(sessions) == 1

    def test_mixed_kinds_ordering(self, tmp_path):
        strokes = [
            _stroke(1, "2026-10-15T00:00:00Z", "metrics"),
            _stroke(2, "2026-10-15T00:00:15Z", "thought"),
            _stroke(3, "2026-10-15T00:00:30Z", "metrics"),
            _stroke(4, "2026-10-15T00:00:45Z", "note"),
            _stroke(5, "2026-10-15T00:01:00Z", "metrics"),
        ]
        p = _write_strokes(tmp_path, strokes)
        sessions = detect_sessions(p)
        bd = sessions[0]["kind_breakdown"]
        assert bd["metrics"] == 3
        assert bd["thought"] == 1
        assert bd["note"] == 1
