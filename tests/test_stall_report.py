"""Tests for tools/stall_report.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from stall_report import find_stalls, summarize, format_text


class TestFindStalls:
    def test_no_stalls_below_threshold(self):
        history = [
            {"at": "2026-10-07T01:00:00+00:00", "seq": 1, "kind": "note", "path": "a.md"},
            {"at": "2026-10-07T01:01:00+00:00", "seq": 2, "kind": "note", "path": "a.md"},
            {"at": "2026-10-07T01:02:00+00:00", "seq": 3, "kind": "note", "path": "a.md"},
        ]
        stalls = find_stalls(history, threshold_seconds=300)
        assert stalls == []

    def test_detects_stall_above_threshold(self):
        history = [
            {"at": "2026-10-07T01:00:00+00:00", "seq": 1, "kind": "note", "path": "a.md"},
            {"at": "2026-10-07T01:10:00+00:00", "seq": 2, "kind": "note", "path": "a.md"},
        ]
        stalls = find_stalls(history, threshold_seconds=300)
        assert len(stalls) == 1
        assert stalls[0]["gap_seconds"] == 600
        assert stalls[0]["strokes_before"] == 1
        assert stalls[0]["strokes_after"] == 2

    def test_multiple_stalls(self):
        history = [
            {"at": "2026-10-07T01:00:00+00:00", "seq": 1, "kind": "note", "path": "a.md"},
            {"at": "2026-10-07T01:10:00+00:00", "seq": 2, "kind": "note", "path": "a.md"},
            {"at": "2026-10-07T01:11:00+00:00", "seq": 3, "kind": "note", "path": "a.md"},
            {"at": "2026-10-07T01:30:00+00:00", "seq": 4, "kind": "note", "path": "a.md"},
        ]
        stalls = find_stalls(history, threshold_seconds=300)
        assert len(stalls) == 2
        assert stalls[0]["gap_seconds"] == 600
        assert stalls[1]["gap_seconds"] == 1140

    def test_empty_history(self):
        assert find_stalls([], threshold_seconds=300) == []

    def test_single_stroke(self):
        history = [
            {"at": "2026-10-07T01:00:00+00:00", "seq": 1, "kind": "note", "path": "a.md"},
        ]
        assert find_stalls(history, threshold_seconds=300) == []

    def test_exact_threshold_not_stall(self):
        history = [
            {"at": "2026-10-07T01:00:00+00:00", "seq": 1, "kind": "note", "path": "a.md"},
            {"at": "2026-10-07T01:05:00+00:00", "seq": 2, "kind": "note", "path": "a.md"},
        ]
        stalls = find_stalls(history, threshold_seconds=300)
        assert stalls == []


class TestSummarize:
    def test_empty_history_summary(self):
        result = summarize([], [])
        assert result["total_strokes"] == 0
        assert result["total_stalls"] == 0
        assert result["longest_gap_seconds"] == 0

    def test_summary_with_stalls(self):
        history = [
            {"at": "2026-10-07T01:00:00+00:00", "seq": 1, "kind": "note", "path": "a.md"},
            {"at": "2026-10-07T01:10:00+00:00", "seq": 2, "kind": "note", "path": "a.md"},
        ]
        stalls = find_stalls(history, threshold_seconds=300)
        result = summarize(stalls, history)
        assert result["total_strokes"] == 2
        assert result["total_stalls"] == 1
        assert result["longest_gap_seconds"] == 600
        assert result["total_stall_seconds"] == 600
        assert result["first_stroke"] == "2026-10-07T01:00:00+00:00"
        assert result["last_stroke"] == "2026-10-07T01:10:00+00:00"

    def test_summary_no_stalls(self):
        history = [
            {"at": "2026-10-07T01:00:00+00:00", "seq": 1, "kind": "note", "path": "a.md"},
            {"at": "2026-10-07T01:01:00+00:00", "seq": 2, "kind": "note", "path": "a.md"},
        ]
        stalls = find_stalls(history, threshold_seconds=300)
        result = summarize(stalls, history)
        assert result["total_stalls"] == 0
        assert result["longest_gap_seconds"] == 0


class TestFormatText:
    def test_format_includes_stall_count(self):
        summary = {
            "total_strokes": 100,
            "total_stalls": 3,
            "longest_gap_seconds": 3600,
            "total_stall_seconds": 7200,
            "first_stroke": "2026-10-07T00:00:00+00:00",
            "last_stroke": "2026-10-07T12:00:00+00:00",
            "stalls": [],
        }
        text = format_text(summary)
        assert "strokes: 100" in text
        assert "stalls:  3" in text
        assert "longest: 3600s" in text

    def test_format_empty(self):
        summary = {
            "total_strokes": 0,
            "total_stalls": 0,
            "longest_gap_seconds": 0,
            "total_stall_seconds": 0,
            "stalls": [],
        }
        text = format_text(summary)
        assert "strokes: 0" in text
        assert "stalls:  0" in text
