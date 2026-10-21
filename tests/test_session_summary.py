"""Tests for iamai.session_summary."""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from iamai.session_summary import (
    _parse_iso,
    _count_strokes_since,
    _count_commits_since,
    _elapsed_seconds,
    _classify,
    summarise,
    report_line,
)


# ---------------------------------------------------------------------------
# _parse_iso
# ---------------------------------------------------------------------------

class TestParseIso:
    def test_utc_offset(self):
        dt = _parse_iso("2026-10-21T12:00:00+00:00")
        assert dt.year == 2026
        assert dt.month == 10
        assert dt.hour == 12

    def test_z_suffix(self):
        dt = _parse_iso("2026-10-21T12:00:00Z")
        assert dt.tzinfo is not None

    def test_timezone_offset(self):
        dt = _parse_iso("2026-10-21T21:00:00+08:00")
        assert dt.hour == 21

    def test_whitespace_stripped(self):
        dt = _parse_iso("  2026-10-21T12:00:00Z  ")
        assert dt.year == 2026


# ---------------------------------------------------------------------------
# _count_strokes_since
# ---------------------------------------------------------------------------

class TestCountStrokesSince:
    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _count_strokes_since(p, since) == 0

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nope.jsonl"
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _count_strokes_since(p, since) == 0

    def test_counts_after_cutoff(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 1, "at": "2026-10-21T10:00:00+00:00"}),
            json.dumps({"seq": 2, "at": "2026-10-21T11:00:00+00:00"}),
            json.dumps({"seq": 3, "at": "2026-10-21T12:00:00+00:00"}),
            json.dumps({"seq": 4, "at": "2026-10-21T13:00:00+00:00"}),
        ]
        p.write_text("\n".join(lines))
        since = datetime(2026, 10, 21, 11, 30, tzinfo=timezone.utc)
        assert _count_strokes_since(p, since) == 2  # seq 3 and 4

    def test_counts_all_if_old_cutoff(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 1, "at": "2026-10-21T10:00:00+00:00"}),
            json.dumps({"seq": 2, "at": "2026-10-21T11:00:00+00:00"}),
        ]
        p.write_text("\n".join(lines))
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _count_strokes_since(p, since) == 2

    def test_skips_malformed_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 1, "at": "2026-10-21T12:00:00+00:00"}),
            "not valid json",
            json.dumps({"seq": 2, "at": "2026-10-21T13:00:00+00:00"}),
        ]
        p.write_text("\n".join(lines))
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _count_strokes_since(p, since) == 2

    def test_handles_missing_at_field(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 1, "at": "2026-10-21T12:00:00+00:00"}),
            json.dumps({"seq": 2}),  # no "at" field
        ]
        p.write_text("\n".join(lines))
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _count_strokes_since(p, since) == 1


# ---------------------------------------------------------------------------
# _elapsed_seconds
# ---------------------------------------------------------------------------

class TestElapsedSeconds:
    def test_positive_elapsed(self):
        since = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
        now = datetime(2026, 10, 21, 12, 30, 0, tzinfo=timezone.utc)
        assert _elapsed_seconds(since, now) == 1800.0

    def test_zero_when_same(self):
        t = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
        assert _elapsed_seconds(t, t) == 0.0

    def test_negative_clamped(self):
        since = datetime(2026, 10, 21, 13, 0, 0, tzinfo=timezone.utc)
        now = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
        assert _elapsed_seconds(since, now) == 0.0


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_productive(self):
        assert _classify(5, 2) == "productive"

    def test_productive_exact_boundary(self):
        assert _classify(3, 1) == "productive"

    def test_quiet(self):
        assert _classify(2, 0) == "quiet"

    def test_quiet_one_stroke(self):
        assert _classify(1, 0) == "quiet"

    def test_idle(self):
        assert _classify(0, 0) == "idle"

    def test_strokes_but_no_commits_still_quiet(self):
        assert _classify(2, 0) == "quiet"


# ---------------------------------------------------------------------------
# report_line
# ---------------------------------------------------------------------------

class TestReportLine:
    def test_format(self):
        info = {
            "verdict": "productive",
            "strokes": 12,
            "commits": 3,
            "elapsed_seconds": 847.3,
        }
        line = report_line(info)
        assert "productive" in line
        assert "12 strokes" in line
        assert "3 commits" in line
        assert "847s" in line

    def test_idle_format(self):
        info = {
            "verdict": "idle",
            "strokes": 0,
            "commits": 0,
            "elapsed_seconds": 120.0,
        }
        line = report_line(info)
        assert "idle" in line
        assert "0 strokes" in line


# ---------------------------------------------------------------------------
# summarise (integration-style with tmp_path)
# ---------------------------------------------------------------------------

class TestSummarise:
    def test_idle_no_data(self, tmp_path):
        info = summarise(
            repo=tmp_path,
            visit_start_iso="2026-10-21T12:00:00+00:00",
            now=datetime(2026, 10, 21, 12, 30, 0, tzinfo=timezone.utc),
        )
        assert info["verdict"] == "idle"
        assert info["strokes"] == 0
        assert info["commits"] == 0

    def test_productive_with_strokes(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes = data_dir / "strokes.jsonl"
        lines = [
            json.dumps({"seq": i, "at": f"2026-10-21T12:{i:02d}:00+00:00"})
            for i in range(1, 6)
        ]
        strokes.write_text("\n".join(lines))

        info = summarise(
            repo=tmp_path,
            visit_start_iso="2026-10-21T11:59:00+00:00",
            now=datetime(2026, 10, 21, 12, 10, 0, tzinfo=timezone.utc),
        )
        assert info["strokes"] == 5
        assert info["verdict"] in ("productive", "quiet")  # depends on git

    def test_fallback_to_state_file(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        state = data_dir / "writer_state.qwen.json"
        state.write_text(json.dumps({
            "last_visit": "2026-10-21T12:00:00+00:00",
        }))

        info = summarise(
            repo=tmp_path,
            now=datetime(2026, 10, 21, 12, 15, 0, tzinfo=timezone.utc),
        )
        assert info["elapsed_seconds"] == pytest.approx(900.0, abs=1.0)

    def test_default_30min_fallback(self, tmp_path):
        now = datetime(2026, 10, 21, 13, 0, 0, tzinfo=timezone.utc)
        info = summarise(repo=tmp_path, now=now)
        assert info["elapsed_seconds"] == pytest.approx(1800.0, abs=1.0)

    def test_writer_field(self, tmp_path):
        info = summarise(repo=tmp_path, writer="testbot")
        assert info["writer"] == "testbot"

    def test_report_line_round_trip(self, tmp_path):
        info = summarise(
            repo=tmp_path,
            visit_start_iso="2026-10-21T12:00:00+00:00",
            now=datetime(2026, 10, 21, 12, 10, 0, tzinfo=timezone.utc),
        )
        line = report_line(info)
        assert isinstance(line, str)
        assert "elapsed" in line
