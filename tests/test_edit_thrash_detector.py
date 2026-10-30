"""tests for edit_thrash_detector — catching when the writer loops in place.

covers:
  - severity classification boundaries (NONE/LOW/MODERATE/HIGH/SEVERE)
  - score computation from edit counts
  - hot file detection with varying thresholds
  - empty / missing strokes file handling
  - malformed JSON line tolerance
  - timestamp parsing edge cases
  - remediation_hint mapping
  - format_report output structure

no external services needed. all git / file I/O is mocked or uses tmp_path.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.edit_thrash_detector import (
    ThrashReport,
    ThrashSeverity,
    _load_strokes_in_window,
    _parse_ts,
    classify_severity,
    detect_thrash,
    format_report,
    remediation_hint,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _stroke(ts: datetime, path: str) -> str:
    """Build a JSONL stroke line."""
    return json.dumps({"ts": ts.isoformat(), "path": path, "kind": "note"})


def _write_strokes(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "strokes.jsonl"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# severity classification
# ---------------------------------------------------------------------------


class TestClassifySeverity:
    def test_zero_is_none(self):
        assert classify_severity(0) == ThrashSeverity.NONE

    def test_low(self):
        assert classify_severity(10) == ThrashSeverity.LOW

    def test_boundary_low(self):
        assert classify_severity(24.9) == ThrashSeverity.LOW

    def test_boundary_moderate(self):
        assert classify_severity(25) == ThrashSeverity.MODERATE

    def test_boundary_high(self):
        assert classify_severity(50) == ThrashSeverity.HIGH

    def test_boundary_severe(self):
        assert classify_severity(75) == ThrashSeverity.SEVERE

    def test_100_is_severe(self):
        assert classify_severity(100) == ThrashSeverity.SEVERE


# ---------------------------------------------------------------------------
# timestamp parsing
# ---------------------------------------------------------------------------


class TestParseTs:
    def test_utc_offset(self):
        dt = _parse_ts("2026-10-26T12:00:00+00:00")
        assert dt.year == 2026
        assert dt.hour == 12

    def test_z_suffix(self):
        dt = _parse_ts("2026-10-26T12:00:00Z")
        assert dt.tzinfo is not None

    def test_positive_offset(self):
        dt = _parse_ts("2026-10-26T21:00:00+08:00")
        assert dt.hour == 21

    def test_whitespace_stripped(self):
        dt = _parse_ts("  2026-10-26T12:00:00Z  ")
        assert dt.year == 2026


# ---------------------------------------------------------------------------
# _load_strokes_in_window
# ---------------------------------------------------------------------------


class TestLoadStrokesInWindow:
    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _load_strokes_in_window(p, cutoff) == []

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent.jsonl"
        cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _load_strokes_in_window(p, cutoff) == []

    def test_filters_old_strokes(self, tmp_path):
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=2)
        recent = now - timedelta(minutes=5)
        lines = [_stroke(old, "notes/old.md"), _stroke(recent, "notes/new.md")]
        p = _write_strokes(tmp_path, lines)
        cutoff = now - timedelta(minutes=30)
        result = _load_strokes_in_window(p, cutoff)
        assert result == ["notes/new.md"]

    def test_skips_malformed_json(self, tmp_path):
        now = datetime.now(timezone.utc)
        lines = [
            "not valid json {{{",
            _stroke(now - timedelta(minutes=1), "notes/good.md"),
        ]
        p = _write_strokes(tmp_path, lines)
        cutoff = now - timedelta(minutes=30)
        result = _load_strokes_in_window(p, cutoff)
        assert result == ["notes/good.md"]

    def test_handles_file_field_fallback(self, tmp_path):
        """Older strokes use 'file' instead of 'path'."""
        now = datetime.now(timezone.utc)
        obj = {"ts": (now - timedelta(minutes=1)).isoformat(), "file": "docs/old.md"}
        p = tmp_path / "strokes.jsonl"
        p.write_text(json.dumps(obj), encoding="utf-8")
        cutoff = now - timedelta(minutes=30)
        result = _load_strokes_in_window(p, cutoff)
        assert result == ["docs/old.md"]


# ---------------------------------------------------------------------------
# detect_thrash — score computation
# ---------------------------------------------------------------------------


class TestDetectThrash:
    def test_no_strokes_returns_none(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        report = detect_thrash(window_minutes=30, hot_threshold=3, strokes_path=p)
        assert report.score == 0.0
        assert report.severity == ThrashSeverity.NONE.value
        assert report.total_edits == 0

    def test_all_unique_files_is_low(self, tmp_path):
        now = datetime.now(timezone.utc)
        lines = [
            _stroke(now - timedelta(minutes=i), f"notes/file{i}.md")
            for i in range(10)
        ]
        p = _write_strokes(tmp_path, lines)
        report = detect_thrash(window_minutes=30, hot_threshold=3, strokes_path=p)
        # 10 edits, 10 unique files, none hot → score=0
        assert report.score == 0.0
        assert report.severity == ThrashSeverity.NONE.value
        assert report.total_edits == 10

    def test_concentrated_edits_flagged(self, tmp_path):
        now = datetime.now(timezone.utc)
        # 8 edits on one file, 2 on others
        lines = [_stroke(now - timedelta(minutes=i), "notes/hot.md") for i in range(8)]
        lines.append(_stroke(now - timedelta(minutes=9), "notes/a.md"))
        lines.append(_stroke(now - timedelta(minutes=10), "notes/b.md"))
        p = _write_strokes(tmp_path, lines)
        report = detect_thrash(window_minutes=30, hot_threshold=3, strokes_path=p)
        # hot_edits=8, total=10 → score=80 → SEVERE
        assert report.score == 80.0
        assert report.severity == ThrashSeverity.SEVERE.value
        assert "notes/hot.md" in report.hot_files
        assert report.top_file == "notes/hot.md"
        assert report.top_file_edits == 8

    def test_threshold_boundary(self, tmp_path):
        now = datetime.now(timezone.utc)
        # exactly 3 edits on one file (at threshold)
        lines = [_stroke(now - timedelta(minutes=i), "notes/x.md") for i in range(3)]
        p = _write_strokes(tmp_path, lines)
        report = detect_thrash(window_minutes=30, hot_threshold=3, strokes_path=p)
        # 3 hot edits / 3 total = 100 → SEVERE
        assert report.score == 100.0
        assert report.hot_files == ["notes/x.md"]

    def test_below_threshold_not_hot(self, tmp_path):
        now = datetime.now(timezone.utc)
        # 2 edits on one file, below threshold of 3
        lines = [_stroke(now - timedelta(minutes=i), "notes/y.md") for i in range(2)]
        p = _write_strokes(tmp_path, lines)
        report = detect_thrash(window_minutes=30, hot_threshold=3, strokes_path=p)
        assert report.hot_files == []
        assert report.score == 0.0
        assert report.severity == ThrashSeverity.NONE.value

    def test_multiple_hot_files(self, tmp_path):
        now = datetime.now(timezone.utc)
        lines = (
            [_stroke(now - timedelta(minutes=i), "notes/a.md") for i in range(4)]
            + [_stroke(now - timedelta(minutes=i + 4), "notes/b.md") for i in range(5)]
            + [_stroke(now - timedelta(minutes=9), "notes/c.md")]
        )
        p = _write_strokes(tmp_path, lines)
        report = detect_thrash(window_minutes=30, hot_threshold=3, strokes_path=p)
        # hot: a(4) + b(5) = 9, total = 10 → score=90
        assert report.score == 90.0
        assert len(report.hot_files) == 2
        # b has more edits, so it's first
        assert report.hot_files[0] == "notes/b.md"


# ---------------------------------------------------------------------------
# remediation_hint
# ---------------------------------------------------------------------------


class TestRemediationHint:
    def test_none_hint(self):
        assert "no action" in remediation_hint("NONE")

    def test_severe_hint(self):
        assert "stop" in remediation_hint("SEVERE")

    def test_unknown_hint(self):
        assert "unknown" in remediation_hint("BOGUS")


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def test_contains_key_fields(self, tmp_path):
        now = datetime.now(timezone.utc)
        lines = [_stroke(now - timedelta(minutes=1), "notes/z.md")]
        p = _write_strokes(tmp_path, lines)
        report = detect_thrash(window_minutes=30, hot_threshold=3, strokes_path=p)
        text = format_report(report)
        assert "thrash report" in text.lower()
        assert "score" in text.lower()
        assert "severity" in text.lower()
        assert "hint" in text.lower()

    def test_empty_report(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        report = detect_thrash(window_minutes=30, hot_threshold=3, strokes_path=p)
        text = format_report(report)
        assert "0.0" in text or "0 / 100" in text


# ---------------------------------------------------------------------------
# ThrashReport dataclass
# ---------------------------------------------------------------------------


class TestThrashReport:
    def test_str_with_no_edits(self):
        r = ThrashReport(
            timestamp="2026-10-26T23:00:00+00:00",
            window_minutes=30,
            hot_threshold=3,
            total_edits=0,
            hot_edits=0,
            score=0.0,
            severity="NONE",
        )
        assert "no edits" in str(r).lower()

    def test_str_with_edits(self):
        r = ThrashReport(
            timestamp="2026-10-26T23:00:00+00:00",
            window_minutes=30,
            hot_threshold=3,
            total_edits=10,
            hot_edits=8,
            score=80.0,
            severity="SEVERE",
            hot_files=["notes/x.md"],
            unique_files=3,
            top_file="notes/x.md",
            top_file_edits=8,
        )
        s = str(r)
        assert "80.0" in s
        assert "SEVERE" in s
        assert "notes/x.md" in s
