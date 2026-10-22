"""Tests for iamai.stroke_yield — stroke preservation measurement."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.stroke_yield import (
    YieldReport,
    _classify_yield,
    _count_lines_in_file,
    _count_lines_at_head,
    _read_latest_seq,
    stroke_yield_report,
    yield_summary,
    _GRADE_THRESHOLDS,
    _GRADE_CRITICAL,
)


# ---------------------------------------------------------------------------
# _classify_yield
# ---------------------------------------------------------------------------

class TestClassifyYield:
    """Unit tests for the grade classification function."""

    def test_perfect_yield(self):
        assert _classify_yield(100.0) == "excellent"

    def test_at_excellent_threshold(self):
        assert _classify_yield(98.0) == "excellent"

    def test_just_below_excellent(self):
        assert _classify_yield(97.9) == "good"

    def test_at_good_threshold(self):
        assert _classify_yield(90.0) == "good"

    def test_just_below_good(self):
        assert _classify_yield(89.9) == "fair"

    def test_at_fair_threshold(self):
        assert _classify_yield(75.0) == "fair"

    def test_just_below_fair(self):
        assert _classify_yield(74.9) == "poor"

    def test_at_poor_threshold(self):
        assert _classify_yield(50.0) == "poor"

    def test_just_below_poor(self):
        assert _classify_yield(49.9) == "critical"

    def test_zero_yield(self):
        assert _classify_yield(0.0) == "critical"

    def test_boundary_values_are_inclusive(self):
        """Each threshold value maps to its own grade, not the one below."""
        for threshold, grade in _GRADE_THRESHOLDS:
            assert _classify_yield(threshold) == grade


# ---------------------------------------------------------------------------
# _count_lines_in_file
# ---------------------------------------------------------------------------

class TestCountLinesInFile:
    """Unit tests for line counting in a file."""

    def test_nonexistent_file_returns_zero(self, tmp_path):
        assert _count_lines_in_file(tmp_path / "nope.jsonl") == 0

    def test_empty_file_returns_zero(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        assert _count_lines_in_file(f) == 0

    def test_blank_lines_not_counted(self, tmp_path):
        f = tmp_path / "blanks.jsonl"
        f.write_text("\n\n\n")
        assert _count_lines_in_file(f) == 0

    def test_counts_non_empty_lines(self, tmp_path):
        f = tmp_path / "data.jsonl"
        f.write_text('{"a":1}\n{"b":2}\n\n{"c":3}\n')
        assert _count_lines_in_file(f) == 3

    def test_single_line_no_newline(self, tmp_path):
        f = tmp_path / "one.jsonl"
        f.write_text('{"a":1}')
        assert _count_lines_in_file(f) == 1


# ---------------------------------------------------------------------------
# _count_lines_at_head
# ---------------------------------------------------------------------------

class TestCountLinesAtHead:
    """Unit tests for counting committed lines via git show."""

    def test_returns_zero_on_git_error(self, tmp_path):
        """Non-git directory should return 0, not raise."""
        result = _count_lines_at_head(tmp_path, "data/strokes.jsonl")
        assert result == 0

    def test_returns_zero_when_file_missing_at_head(self, tmp_path):
        """If the file doesn't exist at HEAD, returns 0."""
        # Use a real but empty git repo
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            capture_output=True,
            cwd=str(tmp_path),
        )
        result = _count_lines_at_head(tmp_path, "data/strokes.jsonl")
        assert result == 0

    def test_counts_committed_lines(self, tmp_path):
        """Committed file lines are counted correctly."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            capture_output=True, cwd=str(tmp_path),
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            capture_output=True, cwd=str(tmp_path),
        )
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes = data_dir / "strokes.jsonl"
        strokes.write_text('{"seq":1}\n{"seq":2}\n{"seq":3}\n')
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(tmp_path))
        subprocess.run(
            ["git", "commit", "-m", "init"],
            capture_output=True, cwd=str(tmp_path),
        )
        result = _count_lines_at_head(tmp_path, "data/strokes.jsonl")
        assert result == 3


# ---------------------------------------------------------------------------
# _read_latest_seq
# ---------------------------------------------------------------------------

class TestReadLatestSeq:
    """Unit tests for reading the last seq number."""

    def test_missing_file_returns_none(self, tmp_path):
        assert _read_latest_seq(tmp_path / "nope.jsonl") is None

    def test_empty_file_returns_none(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        assert _read_latest_seq(f) is None

    def test_reads_last_seq(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"seq":10,"kind":"a"}\n'
            '{"seq":11,"kind":"b"}\n'
            '{"seq":12,"kind":"c"}\n'
        )
        assert _read_latest_seq(f) == 12

    def test_handles_blank_lines_between(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":5}\n\n{"seq":8}\n\n')
        assert _read_latest_seq(f) == 8

    def test_malformed_last_line_returns_none(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":1}\nnot json\n')
        assert _read_latest_seq(f) is None


# ---------------------------------------------------------------------------
# stroke_yield_report
# ---------------------------------------------------------------------------

class TestStrokeYieldReport:
    """Integration tests for the main report function."""

    def test_all_committed(self, tmp_path):
        """When working tree matches HEAD, yield is 100%."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            capture_output=True, cwd=str(tmp_path),
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            capture_output=True, cwd=str(tmp_path),
        )
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes = data_dir / "strokes.jsonl"
        strokes.write_text('{"seq":1}\n{"seq":2}\n{"seq":3}\n')
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(tmp_path))
        subprocess.run(
            ["git", "commit", "-m", "init"],
            capture_output=True, cwd=str(tmp_path),
        )
        report = stroke_yield_report(repo_path=tmp_path)
        assert report.total_strokes == 3
        assert report.committed_strokes == 3
        assert report.uncommitted_strokes == 0
        assert report.yield_pct == 100.0
        assert report.grade == "excellent"

    def test_some_uncommitted(self, tmp_path):
        """Extra lines in working tree lower the yield."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            capture_output=True, cwd=str(tmp_path),
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            capture_output=True, cwd=str(tmp_path),
        )
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes = data_dir / "strokes.jsonl"
        strokes.write_text('{"seq":1}\n{"seq":2}\n')
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(tmp_path))
        subprocess.run(
            ["git", "commit", "-m", "init"],
            capture_output=True, cwd=str(tmp_path),
        )
        # Append 2 more uncommitted strokes
        strokes.write_text('{"seq":1}\n{"seq":2}\n{"seq":3}\n{"seq":4}\n')
        report = stroke_yield_report(repo_path=tmp_path)
        assert report.total_strokes == 4
        assert report.committed_strokes == 2
        assert report.uncommitted_strokes == 2
        assert report.yield_pct == 50.0
        assert report.grade == "poor"

    def test_empty_repo(self, tmp_path):
        """No strokes at all yields 100% (nothing to lose)."""
        report = stroke_yield_report(repo_path=tmp_path)
        assert report.total_strokes == 0
        assert report.yield_pct == 100.0
        assert report.grade == "excellent"

    def test_no_commits_yet(self, tmp_path):
        """Strokes exist but nothing committed yet."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes = data_dir / "strokes.jsonl"
        strokes.write_text('{"seq":1}\n{"seq":2}\n{"seq":3}\n')
        report = stroke_yield_report(repo_path=tmp_path)
        assert report.total_strokes == 3
        assert report.committed_strokes == 0
        assert report.yield_pct == 0.0
        assert report.grade == "critical"

    def test_to_dict(self, tmp_path):
        """to_dict returns a plain dict with expected keys."""
        report = YieldReport(
            total_strokes=100,
            committed_strokes=95,
            uncommitted_strokes=5,
            yield_pct=95.0,
            grade="good",
        )
        d = report.to_dict()
        assert d["total_strokes"] == 100
        assert d["committed_strokes"] == 95
        assert d["uncommitted_strokes"] == 5
        assert d["yield_pct"] == 95.0
        assert d["grade"] == "good"


# ---------------------------------------------------------------------------
# yield_summary
# ---------------------------------------------------------------------------

class TestYieldSummary:
    """Tests for the human-readable summary helper."""

    def test_summary_format(self):
        report = YieldReport(
            total_strokes=200,
            committed_strokes=190,
            uncommitted_strokes=10,
            yield_pct=95.0,
            grade="good",
        )
        s = yield_summary(report)
        assert "95.0%" in s
        assert "good" in s
        assert "190/200" in s
        assert "10 uncommitted" in s

    def test_summary_with_kwargs(self, tmp_path):
        """When no report passed, builds one from kwargs."""
        s = yield_summary(repo_path=tmp_path)
        assert "100.0%" in s
        assert "excellent" in s
