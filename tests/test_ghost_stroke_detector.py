"""Tests for ghost_stroke_detector — comprehensive coverage.

Covers: WriterSession properties, Stroke parsing, GhostDetector scan
(in-window, out-of-window, tolerance edge cases, no sessions, multiple
sessions), GhostReport properties, reason classification, nearest-session
logic, _parse_ts formats, and load_strokes_from_jsonl.

Written by Qwen during caretaker visit 706, 2026-11-18.
"""

import json
import os
import tempfile
import pytest

from iamai.ghost_stroke_detector import (
    GhostDetector,
    GhostReport,
    GhostStroke,
    Stroke,
    WriterSession,
    _parse_ts,
    load_strokes_from_jsonl,
)


# ─── Fixtures ───────────────────────────────────────────────────────


def _session(name="qwen", start="2026-11-18T08:00:00+00:00",
             end="2026-11-18T12:00:00+00:00", cadence=15.0):
    return WriterSession(name=name, start=start, end=end,
                         expected_cadence_s=cadence)


def _stroke(seq=1, at="2026-11-18T10:00:00+00:00", kind="thought",
            text="hello"):
    return Stroke(seq=seq, at=at, kind=kind, text=text)


# ─── WriterSession ─────────────────────────────────────────────────


class TestWriterSession:

    def test_start_dt(self):
        s = _session()
        assert s.start_dt.hour == 8
        assert s.start_dt.tzinfo is not None

    def test_end_dt(self):
        s = _session()
        assert s.end_dt.hour == 12

    def test_duration_s(self):
        s = _session()
        assert s.duration_s == 4 * 3600  # 4 hours

    def test_frozen(self):
        s = _session()
        with pytest.raises(AttributeError):
            s.name = "doubao"

    def test_default_cadence(self):
        s = WriterSession(name="x", start="2026-01-01T00:00:00+00:00",
                          end="2026-01-01T01:00:00+00:00")
        assert s.expected_cadence_s == 15.0


# ─── Stroke ─────────────────────────────────────────────────────────


class TestStroke:

    def test_at_dt(self):
        s = _stroke()
        assert s.at_dt.hour == 10

    def test_defaults(self):
        s = Stroke(seq=0, at="2026-01-01T00:00:00+00:00")
        assert s.kind == ""
        assert s.text == ""

    def test_frozen(self):
        s = _stroke()
        with pytest.raises(AttributeError):
            s.seq = 99


# ─── GhostDetector: in-window strokes ───────────────────────────────


class TestInWindow:

    def test_stroke_inside_session(self):
        det = GhostDetector([_session()])
        report = det.scan([_stroke()])
        assert report.is_clean
        assert report.ghost_count == 0

    def test_stroke_at_session_start(self):
        det = GhostDetector([_session()])
        s = _stroke(at="2026-11-18T08:00:00+00:00")
        report = det.scan([s])
        assert report.is_clean

    def test_stroke_at_session_end(self):
        det = GhostDetector([_session()])
        s = _stroke(at="2026-11-18T12:00:00+00:00")
        report = det.scan([s])
        assert report.is_clean

    def test_stroke_within_tolerance_before_start(self):
        det = GhostDetector([_session()], tolerance_s=60)
        # 30 seconds before start — within 60s tolerance
        s = _stroke(at="2026-11-18T07:59:30+00:00")
        report = det.scan([s])
        assert report.is_clean

    def test_stroke_within_tolerance_after_end(self):
        det = GhostDetector([_session()], tolerance_s=60)
        # 30 seconds after end — within 60s tolerance
        s = _stroke(at="2026-11-18T12:00:30+00:00")
        report = det.scan([s])
        assert report.is_clean


# ─── GhostDetector: out-of-window strokes ───────────────────────────


class TestOutOfWindow:

    def test_stroke_before_session(self):
        det = GhostDetector([_session()], tolerance_s=30)
        s = _stroke(at="2026-11-18T06:00:00+00:00")
        report = det.scan([s])
        assert report.ghost_count == 1
        assert not report.is_clean

    def test_stroke_after_session(self):
        det = GhostDetector([_session()], tolerance_s=30)
        s = _stroke(at="2026-11-18T14:00:00+00:00")
        report = det.scan([s])
        assert report.ghost_count == 1

    def test_stroke_just_outside_tolerance(self):
        det = GhostDetector([_session()], tolerance_s=30)
        # 31 seconds before start — outside 30s tolerance
        s = _stroke(at="2026-11-18T07:59:29+00:00")
        report = det.scan([s])
        assert report.ghost_count == 1

    def test_multiple_strokes_mixed(self):
        det = GhostDetector([_session()], tolerance_s=30)
        strokes = [
            _stroke(seq=1, at="2026-11-18T10:00:00+00:00"),  # in
            _stroke(seq=2, at="2026-11-18T06:00:00+00:00"),  # out
            _stroke(seq=3, at="2026-11-18T11:00:00+00:00"),  # in
            _stroke(seq=4, at="2026-11-18T14:00:00+00:00"),  # out
        ]
        report = det.scan(strokes)
        assert report.total_strokes == 4
        assert report.ghost_count == 2
        assert report.ghosts[0].stroke.seq == 2
        assert report.ghosts[1].stroke.seq == 4


# ─── GhostDetector: no sessions ─────────────────────────────────────


class TestNoSessions:

    def test_no_sessions_all_ghosts(self):
        det = GhostDetector([])
        strokes = [_stroke(seq=i) for i in range(5)]
        report = det.scan(strokes)
        assert report.ghost_count == 5

    def test_no_sessions_reason(self):
        det = GhostDetector([])
        report = det.scan([_stroke()])
        assert report.ghosts[0].reason == "no_sessions_defined"
        assert report.ghosts[0].nearest_session is None

    def test_no_strokes(self):
        det = GhostDetector([_session()])
        report = det.scan([])
        assert report.total_strokes == 0
        assert report.ghost_count == 0
        assert report.is_clean


# ─── GhostDetector: multiple sessions ──────────────────────────────


class TestMultipleSessions:

    def test_stroke_in_second_session(self):
        sessions = [
            _session(name="qwen", start="2026-11-18T08:00:00+00:00",
                     end="2026-11-18T10:00:00+00:00"),
            _session(name="doubao", start="2026-11-18T12:00:00+00:00",
                     end="2026-11-18T14:00:00+00:00"),
        ]
        det = GhostDetector(sessions)
        s = _stroke(at="2026-11-18T13:00:00+00:00")
        report = det.scan([s])
        assert report.is_clean

    def test_stroke_between_sessions(self):
        sessions = [
            _session(name="qwen", start="2026-11-18T08:00:00+00:00",
                     end="2026-11-18T10:00:00+00:00"),
            _session(name="doubao", start="2026-11-18T12:00:00+00:00",
                     end="2026-11-18T14:00:00+00:00"),
        ]
        det = GhostDetector(sessions, tolerance_s=30)
        s = _stroke(at="2026-11-18T11:00:00+00:00")
        report = det.scan([s])
        assert report.ghost_count == 1

    def test_nearest_session_reported(self):
        sessions = [
            _session(name="qwen", start="2026-11-18T08:00:00+00:00",
                     end="2026-11-18T10:00:00+00:00"),
            _session(name="doubao", start="2026-11-18T12:00:00+00:00",
                     end="2026-11-18T14:00:00+00:00"),
        ]
        det = GhostDetector(sessions, tolerance_s=30)
        # 11:00 is 1h after qwen end, 1h before doubao start — equidistant
        s = _stroke(at="2026-11-18T11:00:00+00:00")
        report = det.scan([s])
        # Should pick one of them (either is fine)
        assert report.ghosts[0].nearest_session in ("qwen", "doubao")
        assert report.ghosts[0].gap_s == pytest.approx(3600, abs=1)


# ─── Reason classification ──────────────────────────────────────────


class TestReasonClassification:

    def test_just_outside_session(self):
        det = GhostDetector([_session()], tolerance_s=30)
        # 90 seconds before start — close but outside tolerance
        s = _stroke(at="2026-11-18T07:58:30+00:00")
        report = det.scan([s])
        assert "just_outside_session" in report.ghosts[0].reason

    def test_between_sessions(self):
        det = GhostDetector([_session()], tolerance_s=30)
        # 30 minutes before start
        s = _stroke(at="2026-11-18T07:30:00+00:00")
        report = det.scan([s])
        assert "between_sessions" in report.ghosts[0].reason

    def test_far_from_any_session(self):
        det = GhostDetector([_session()], tolerance_s=30)
        # 5 hours before start
        s = _stroke(at="2026-11-18T03:00:00+00:00")
        report = det.scan([s])
        assert "far_from_any_session" in report.ghosts[0].reason
        assert report.ghosts[0].gap_s > 3600


# ─── GhostReport ────────────────────────────────────────────────────


class TestGhostReport:

    def test_ghost_ratio_clean(self):
        r = GhostReport(total_strokes=100, ghost_count=0)
        assert r.ghost_ratio == 0.0
        assert r.is_clean

    def test_ghost_ratio_partial(self):
        r = GhostReport(total_strokes=100, ghost_count=25)
        assert r.ghost_ratio == 0.25
        assert not r.is_clean

    def test_ghost_ratio_empty(self):
        r = GhostReport(total_strokes=0, ghost_count=0)
        assert r.ghost_ratio == 0.0

    def test_ghost_ratio_all_ghosts(self):
        r = GhostReport(total_strokes=10, ghost_count=10)
        assert r.ghost_ratio == 1.0


# ─── _parse_ts ──────────────────────────────────────────────────────


class TestParseTs:

    def test_iso_with_offset(self):
        dt = _parse_ts("2026-11-18T10:00:00+00:00")
        assert dt.hour == 10
        assert dt.tzinfo is not None

    def test_iso_with_z(self):
        dt = _parse_ts("2026-11-18T10:00:00Z")
        assert dt.hour == 10

    def test_iso_no_tz(self):
        dt = _parse_ts("2026-11-18T10:00:00")
        assert dt.hour == 10
        # Should default to UTC
        assert dt.tzinfo is not None

    def test_iso_with_microseconds(self):
        dt = _parse_ts("2026-11-18T10:00:00.123456+00:00")
        assert dt.hour == 10

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_ts("not-a-date")

    def test_positive_offset(self):
        dt = _parse_ts("2026-11-18T18:00:00+08:00")
        assert dt.hour == 18
        assert dt.utcoffset().total_seconds() == 8 * 3600


# ─── load_strokes_from_jsonl ────────────────────────────────────────


class TestLoadStrokesFromJsonl:

    def test_load_valid(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 1, "at": "2026-11-18T10:00:00+00:00",
                        "kind": "thought", "text": "hello"}),
            json.dumps({"seq": 2, "at": "2026-11-18T10:00:15+00:00",
                        "kind": "note", "text": "world"}),
        ]
        p.write_text("\n".join(lines), encoding="utf-8")
        strokes = load_strokes_from_jsonl(str(p))
        assert len(strokes) == 2
        assert strokes[0].seq == 1
        assert strokes[1].kind == "note"

    def test_load_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        strokes = load_strokes_from_jsonl(str(p))
        assert strokes == []

    def test_load_skips_blank_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 1, "at": "2026-11-18T10:00:00+00:00"}),
            "",
            "  ",
            json.dumps({"seq": 2, "at": "2026-11-18T10:00:15+00:00"}),
        ]
        p.write_text("\n".join(lines), encoding="utf-8")
        strokes = load_strokes_from_jsonl(str(p))
        assert len(strokes) == 2

    def test_load_missing_fields(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(json.dumps({"seq": 1}), encoding="utf-8")
        strokes = load_strokes_from_jsonl(str(p))
        assert len(strokes) == 1
        assert strokes[0].at == ""
        assert strokes[0].kind == ""


# ─── Integration ────────────────────────────────────────────────────


class TestIntegration:

    def test_full_scan_with_realistic_data(self):
        """Simulate a realistic scenario with two writers and ghosts."""
        sessions = [
            WriterSession(
                name="qwen",
                start="2026-11-18T08:00:00+00:00",
                end="2026-11-18T10:00:00+00:00",
                expected_cadence_s=15,
            ),
            WriterSession(
                name="doubao",
                start="2026-11-18T10:30:00+00:00",
                end="2026-11-18T12:00:00+00:00",
                expected_cadence_s=20,
            ),
        ]
        det = GhostDetector(sessions, tolerance_s=30)

        strokes = [
            _stroke(seq=1, at="2026-11-18T08:30:00+00:00"),  # qwen ✓
            _stroke(seq=2, at="2026-11-18T09:00:00+00:00"),  # qwen ✓
            _stroke(seq=3, at="2026-11-18T09:45:00+00:00"),  # qwen ✓
            _stroke(seq=4, at="2026-11-18T10:15:00+00:00"),  # ghost!
            _stroke(seq=5, at="2026-11-18T10:45:00+00:00"),  # doubao ✓
            _stroke(seq=6, at="2026-11-18T11:30:00+00:00"),  # doubao ✓
            _stroke(seq=7, at="2026-11-18T15:00:00+00:00"),  # ghost!
        ]
        report = det.scan(strokes)

        assert report.total_strokes == 7
        assert report.ghost_count == 2
        assert report.ghosts[0].stroke.seq == 4
        assert report.ghosts[1].stroke.seq == 7
        assert report.ghost_ratio == pytest.approx(2 / 7, abs=0.01)
        assert not report.is_clean

    def test_empty_scan(self):
        """Empty input produces clean report."""
        det = GhostDetector([_session()])
        report = det.scan([])
        assert report.is_clean
        assert report.total_strokes == 0
        assert len(report.ghosts) == 0

    def test_all_in_window(self):
        """All strokes within a single session."""
        det = GhostDetector([_session()], tolerance_s=30)
        strokes = [
            _stroke(seq=i, at=f"2026-11-18T{9+i:02d}:00:00+00:00")
            for i in range(3)
        ]
        report = det.scan(strokes)
        assert report.is_clean
        assert report.ghost_count == 0

    def test_tolerance_boundary_exact(self):
        """Stroke exactly at tolerance boundary is attributed."""
        det = GhostDetector([_session()], tolerance_s=60)
        # Exactly 60s before start
        s = _stroke(at="2026-11-18T07:59:00+00:00")
        report = det.scan([s])
        assert report.is_clean

    def test_zero_tolerance(self):
        """Zero tolerance means exact window match only."""
        det = GhostDetector([_session()], tolerance_s=0)
        # 1 second before start
        s = _stroke(at="2026-11-18T07:59:59+00:00")
        report = det.scan([s])
        assert report.ghost_count == 1
