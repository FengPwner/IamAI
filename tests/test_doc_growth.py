"""Tests for iamai.doc_growth."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.doc_growth import (
    DEFAULT_THRESHOLD,
    TRACKED_FILES,
    _file_size,
    _git_file_size_at,
    growth_report,
    growth_summary,
    scan_growth,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    """Create a fake repo with given files."""
    if files:
        for relpath, content in files.items():
            p = tmp_path / relpath
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# _file_size
# ---------------------------------------------------------------------------

class TestFileSize:
    def test_existing_file(self, tmp_path):
        p = tmp_path / "test.txt"
        p.write_text("hello", encoding="utf-8")
        assert _file_size(tmp_path, "test.txt") == 5

    def test_missing_file(self, tmp_path):
        assert _file_size(tmp_path, "nonexistent.txt") == -1

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.txt"
        p.write_text("", encoding="utf-8")
        assert _file_size(tmp_path, "empty.txt") == 0

    def test_unicode_content(self, tmp_path):
        p = tmp_path / "uni.txt"
        content = "你好世界"  # 4 chars, 12 bytes in UTF-8
        p.write_text(content, encoding="utf-8")
        assert _file_size(tmp_path, "uni.txt") == len(content.encode("utf-8"))


# ---------------------------------------------------------------------------
# scan_growth
# ---------------------------------------------------------------------------

class TestScanGrowth:
    def test_basic_scan(self, tmp_path):
        """scan_growth returns one entry per tracked file."""
        _make_repo(
            tmp_path,
            {
                "docs/DEVLOG.md": "x" * 1000,
                "docs/GARDEN.md": "y" * 2000,
                "docs/METRICS.md": "z" * 500,
                "data/strokes.jsonl": '{"a":1}\n' * 100,
                "notes/conventions.md": "c" * 300,
                "notes/history.md": "h" * 400,
                "notes/limits.md": "l" * 200,
                "notes/reading.md": "r" * 150,
            },
        )
        results = scan_growth(
            tmp_path,
            threshold=5000,
            lookback_hours=1.0,
        )
        assert len(results) == len(TRACKED_FILES)

    def test_missing_files_reported(self, tmp_path):
        """Missing files get size_bytes = -1."""
        _make_repo(tmp_path, {})
        results = scan_growth(tmp_path, threshold=5000)
        for r in results:
            assert r["size_bytes"] == -1
            assert r["size_kb"] == -1

    def test_custom_file_list(self, tmp_path):
        """Custom file list overrides defaults."""
        _make_repo(tmp_path, {"custom.md": "hello"})
        results = scan_growth(tmp_path, files=["custom.md"])
        assert len(results) == 1
        assert results[0]["path"] == "custom.md"
        assert results[0]["size_bytes"] == 5

    def test_size_kb_calculation(self, tmp_path):
        _make_repo(tmp_path, {"docs/DEVLOG.md": "x" * 10240})
        results = scan_growth(tmp_path, files=["docs/DEVLOG.md"])
        assert results[0]["size_kb"] == 10.0

    def test_needs_compaction_flag(self, tmp_path):
        _make_repo(tmp_path, {"docs/DEVLOG.md": "x" * 2000})
        results = scan_growth(
            tmp_path,
            threshold=1000,
            files=["docs/DEVLOG.md"],
        )
        assert results[0]["needs_compaction"] is True
        assert results[0]["pct_of_threshold"] == 200.0

    def test_under_threshold(self, tmp_path):
        _make_repo(tmp_path, {"docs/DEVLOG.md": "x" * 500})
        results = scan_growth(
            tmp_path,
            threshold=1000,
            files=["docs/DEVLOG.md"],
        )
        assert results[0]["needs_compaction"] is False
        assert results[0]["pct_of_threshold"] == 50.0


# ---------------------------------------------------------------------------
# growth_summary
# ---------------------------------------------------------------------------

class TestGrowthSummary:
    def test_empty_results(self):
        summary = growth_summary([])
        assert summary["total_tracked_kb"] == 0
        assert summary["files_needing_compaction"] == []
        assert summary["fastest_growing"] is None

    def test_compaction_list(self):
        results = [
            {
                "path": "a.md",
                "size_bytes": 2000,
                "size_kb": 2.0,
                "bytes_per_hour": 100,
                "pct_of_threshold": 200,
                "hours_to_threshold": None,
                "needs_compaction": True,
            },
            {
                "path": "b.md",
                "size_bytes": 500,
                "size_kb": 0.5,
                "bytes_per_hour": 50,
                "pct_of_threshold": 50,
                "hours_to_threshold": 10.0,
                "needs_compaction": False,
            },
        ]
        summary = growth_summary(results)
        assert summary["files_needing_compaction"] == ["a.md"]
        assert summary["fastest_growing"] == "a.md"
        assert summary["fastest_rate_bph"] == 100

    def test_soonest_to_threshold(self):
        results = [
            {
                "path": "a.md",
                "size_bytes": 800,
                "size_kb": 0.8,
                "bytes_per_hour": 100,
                "pct_of_threshold": 80,
                "hours_to_threshold": 2.0,
                "needs_compaction": False,
            },
            {
                "path": "b.md",
                "size_bytes": 600,
                "size_kb": 0.6,
                "bytes_per_hour": 50,
                "pct_of_threshold": 60,
                "hours_to_threshold": 8.0,
                "needs_compaction": False,
            },
        ]
        summary = growth_summary(results)
        assert summary["soonest_to_threshold"] == "a.md"
        assert summary["soonest_hours"] == 2.0

    def test_total_kb_excludes_missing(self):
        results = [
            {"size_kb": 10.0},
            {"size_kb": -1},
            {"size_kb": 5.0},
        ]
        summary = growth_summary(results)
        assert summary["total_tracked_kb"] == 15.0


# ---------------------------------------------------------------------------
# growth_report
# ---------------------------------------------------------------------------

class TestGrowthReport:
    def test_report_contains_header(self, tmp_path):
        _make_repo(tmp_path, {"docs/DEVLOG.md": "x" * 100})
        report = growth_report(tmp_path, files=["docs/DEVLOG.md"])
        assert "doc growth report" in report
        assert "threshold" in report

    def test_report_shows_file(self, tmp_path):
        _make_repo(tmp_path, {"docs/DEVLOG.md": "x" * 1000})
        report = growth_report(
            tmp_path, threshold=5000, files=["docs/DEVLOG.md"]
        )
        assert "docs/DEVLOG.md" in report

    def test_report_shows_missing(self, tmp_path):
        _make_repo(tmp_path, {})
        report = growth_report(
            tmp_path, threshold=5000, files=["docs/DEVLOG.md"]
        )
        assert "MISSING" in report

    def test_report_shows_compaction_warning(self, tmp_path):
        _make_repo(tmp_path, {"docs/DEVLOG.md": "x" * 2000})
        report = growth_report(
            tmp_path, threshold=1000, files=["docs/DEVLOG.md"]
        )
        assert "NEEDS COMPACTION" in report
        assert "docs/DEVLOG.md" in report

    def test_report_no_compaction_clean(self, tmp_path):
        _make_repo(tmp_path, {"docs/DEVLOG.md": "x" * 100})
        report = growth_report(
            tmp_path, threshold=5000, files=["docs/DEVLOG.md"]
        )
        assert "NEEDS COMPACTION" not in report


# ---------------------------------------------------------------------------
# integration: hours_to_threshold calculation
# ---------------------------------------------------------------------------

class TestHoursToThreshold:
    def test_positive_growth(self, tmp_path):
        """Hours-to-threshold is computed when we have growth data."""
        # Create a file that's 50% of threshold
        content = "x" * 500
        _make_repo(tmp_path, {"docs/DEVLOG.md": content})

        # Mock the git functions to simulate growth
        with patch("iamai.doc_growth._find_ref_at", return_value="abc123"):
            with patch(
                "iamai.doc_growth._git_file_size_at", return_value=400
            ):
                results = scan_growth(
                    tmp_path,
                    threshold=1000,
                    lookback_hours=2.0,
                    files=["docs/DEVLOG.md"],
                )
        # growth = 500 - 400 = 100 bytes over 2 hours = 50 B/h
        # hours_to = (1000 - 500) / 50 = 10.0
        assert results[0]["growth_bytes"] == 100
        assert results[0]["bytes_per_hour"] == 50.0
        assert results[0]["hours_to_threshold"] == 10.0

    def test_zero_growth(self, tmp_path):
        """No growth means hours_to_threshold is None."""
        content = "x" * 500
        _make_repo(tmp_path, {"docs/DEVLOG.md": content})

        with patch("iamai.doc_growth._find_ref_at", return_value="abc123"):
            with patch(
                "iamai.doc_growth._git_file_size_at", return_value=500
            ):
                results = scan_growth(
                    tmp_path,
                    threshold=1000,
                    lookback_hours=2.0,
                    files=["docs/DEVLOG.md"],
                )
        assert results[0]["growth_bytes"] == 0
        assert results[0]["bytes_per_hour"] == 0.0
        assert results[0]["hours_to_threshold"] is None

    def test_shrinking_file(self, tmp_path):
        """File got smaller (compaction happened) — rate is -1."""
        content = "x" * 300
        _make_repo(tmp_path, {"docs/DEVLOG.md": content})

        with patch("iamai.doc_growth._find_ref_at", return_value="abc123"):
            with patch(
                "iamai.doc_growth._git_file_size_at", return_value=500
            ):
                results = scan_growth(
                    tmp_path,
                    threshold=1000,
                    lookback_hours=2.0,
                    files=["docs/DEVLOG.md"],
                )
        assert results[0]["growth_bytes"] == -200
        assert results[0]["bytes_per_hour"] == -1
        assert results[0]["hours_to_threshold"] is None
