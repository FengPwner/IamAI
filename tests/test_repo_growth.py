"""Tests for iamai.repo_growth — repository size tracking and growth rates."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.repo_growth import (
    GrowthReport,
    GrowthSnapshot,
    _count_file,
    _is_binary,
    growth_rate,
    growth_summary,
    snapshot,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp: Path, files: dict[str, str] | None = None) -> Path:
    """Create a minimal git repo with the given files and commit them."""
    repo = tmp / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True, check=True,
    )
    if files:
        for name, content in files.items():
            p = repo / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo, capture_output=True, check=True,
        )
    return repo


# ---------------------------------------------------------------------------
# _is_binary
# ---------------------------------------------------------------------------

class TestIsBinary:
    def test_text_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world\n")
        assert _is_binary(f) is False

    def test_binary_file(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
        assert _is_binary(f) is True

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        assert _is_binary(f) is False

    def test_missing_file(self, tmp_path):
        f = tmp_path / "missing.txt"
        assert _is_binary(f) is True


# ---------------------------------------------------------------------------
# _count_file
# ---------------------------------------------------------------------------

class TestCountFile:
    def test_text_file(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("line1\nline2\nline3\n")
        lines, nbytes = _count_file(f)
        assert lines == 3
        assert nbytes > 0

    def test_binary_file(self, tmp_path):
        f = tmp_path / "img.png"
        f.write_bytes(b"\x89PNG\x00\x00\x00\x00")
        lines, nbytes = _count_file(f)
        assert lines == 0
        assert nbytes == 8

    def test_missing_file(self, tmp_path):
        f = tmp_path / "nope.txt"
        lines, nbytes = _count_file(f)
        assert lines == 0
        assert nbytes == 0

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.md"
        f.write_text("")
        lines, nbytes = _count_file(f)
        assert lines == 0
        assert nbytes == 0


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_basic_snapshot(self, tmp_path):
        repo = _make_repo(tmp_path, {
            "a.py": "print('hi')\n",
            "b.md": "# Hello\n\nWorld\n",
        })
        snap = snapshot(repo, at=1000.0)
        assert snap["files"] == 2
        assert snap["lines"] == 4  # 1 (a.py) + 3 (b.md: header, blank, text)
        assert snap["bytes"] > 0
        assert snap["at"] == 1000.0

    def test_empty_repo(self, tmp_path):
        repo = _make_repo(tmp_path)
        snap = snapshot(repo, at=500.0)
        assert snap["files"] == 0
        assert snap["lines"] == 0
        assert snap["bytes"] == 0
        assert snap["at"] == 500.0

    def test_nested_files(self, tmp_path):
        repo = _make_repo(tmp_path, {
            "src/main.py": "x = 1\n",
            "src/lib/utils.py": "def f():\n    pass\n",
            "README.md": "# project\n",
        })
        snap = snapshot(repo)
        assert snap["files"] == 3
        assert snap["lines"] == 4  # 1 + 2 + 1

    def test_default_timestamp(self, tmp_path):
        repo = _make_repo(tmp_path, {"f.txt": "hi\n"})
        snap = snapshot(repo)
        assert snap["at"] > 0
        assert isinstance(snap["at"], float)

    def test_invalid_repo(self, tmp_path):
        snap = snapshot(tmp_path / "nonexistent", at=123.0)
        assert snap["files"] == 0
        assert snap["lines"] == 0
        assert snap["at"] == 123.0


# ---------------------------------------------------------------------------
# growth_rate
# ---------------------------------------------------------------------------

class TestGrowthRate:
    def test_expanding(self):
        snaps: list[GrowthSnapshot] = [
            {"files": 100, "lines": 1000, "bytes": 50000, "at": 0.0},
            {"files": 110, "lines": 1500, "bytes": 75000, "at": 600.0},
        ]
        report = growth_rate(snaps)
        assert report.verdict == "expanding"
        assert report.files_per_min > 0
        assert report.lines_per_min > 0
        assert report.bytes_per_min > 0
        assert report.period_sec == 600.0

    def test_shrinking(self):
        snaps: list[GrowthSnapshot] = [
            {"files": 100, "lines": 1000, "bytes": 50000, "at": 0.0},
            {"files": 90, "lines": 400, "bytes": 20000, "at": 600.0},
        ]
        report = growth_rate(snaps)
        assert report.verdict == "shrinking"
        assert report.files_per_min < 0

    def test_steady(self):
        snaps: list[GrowthSnapshot] = [
            {"files": 100, "lines": 1000, "bytes": 50000, "at": 0.0},
            {"files": 100, "lines": 1001, "bytes": 50010, "at": 600.0},
        ]
        report = growth_rate(snaps)
        assert report.verdict == "steady"

    def test_insufficient_data_single(self):
        snaps: list[GrowthSnapshot] = [
            {"files": 100, "lines": 1000, "bytes": 50000, "at": 0.0},
        ]
        report = growth_rate(snaps)
        assert report.verdict == "insufficient_data"
        assert report.period_sec == 0.0

    def test_insufficient_data_empty(self):
        report = growth_rate([])
        assert report.verdict == "insufficient_data"

    def test_zero_elapsed(self):
        snaps: list[GrowthSnapshot] = [
            {"files": 100, "lines": 1000, "bytes": 50000, "at": 100.0},
            {"files": 110, "lines": 1500, "bytes": 75000, "at": 100.0},
        ]
        report = growth_rate(snaps)
        assert report.verdict == "insufficient_data"

    def test_uses_first_and_last(self):
        snaps: list[GrowthSnapshot] = [
            {"files": 100, "lines": 1000, "bytes": 50000, "at": 0.0},
            {"files": 105, "lines": 1100, "bytes": 55000, "at": 300.0},
            {"files": 120, "lines": 2000, "bytes": 100000, "at": 600.0},
        ]
        report = growth_rate(snaps)
        assert report.period_sec == 600.0
        # Uses first and last: (120-100)/10min = 2.0 fpm
        assert abs(report.files_per_min - 2.0) < 0.01


# ---------------------------------------------------------------------------
# growth_summary
# ---------------------------------------------------------------------------

class TestGrowthSummary:
    def test_expanding_summary(self, tmp_path):
        repo = _make_repo(tmp_path, {"f.txt": "hi\n"})
        snaps: list[GrowthSnapshot] = [
            {"files": 10, "lines": 100, "bytes": 5000, "at": 0.0},
            {"files": 20, "lines": 300, "bytes": 15000, "at": 600.0},
        ]
        result = growth_summary(repo, snaps)
        assert "expanding" in result
        assert "files/min" in result
        assert "lines/min" in result

    def test_insufficient_data_summary(self, tmp_path):
        repo = _make_repo(tmp_path, {"f.txt": "hi\n"})
        result = growth_summary(repo, [])
        assert "insufficient_data" in result

    def test_steady_summary(self, tmp_path):
        repo = _make_repo(tmp_path, {"f.txt": "hi\n"})
        snaps: list[GrowthSnapshot] = [
            {"files": 10, "lines": 100, "bytes": 5000, "at": 0.0},
            {"files": 10, "lines": 100, "bytes": 5000, "at": 600.0},
        ]
        result = growth_summary(repo, snaps)
        assert "steady" in result

    def test_shrinking_summary(self, tmp_path):
        repo = _make_repo(tmp_path, {"f.txt": "hi\n"})
        snaps: list[GrowthSnapshot] = [
            {"files": 50, "lines": 5000, "bytes": 250000, "at": 0.0},
            {"files": 40, "lines": 2000, "bytes": 100000, "at": 600.0},
        ]
        result = growth_summary(repo, snaps)
        assert "shrinking" in result


# ---------------------------------------------------------------------------
# integration: snapshot + growth_rate
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_snapshot_round_trip(self, tmp_path):
        repo = _make_repo(tmp_path, {
            "main.py": "import sys\nsys.exit(0)\n",
            "README.md": "# Test\n\nSome content here.\n",
        })
        s1 = snapshot(repo, at=0.0)
        assert s1["files"] == 2
        assert s1["lines"] >= 4

        # Add more files
        new_file = repo / "extra.py"
        new_file.write_text("x = 42\ny = 43\nz = x + y\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add extra"],
            cwd=repo, capture_output=True,
        )

        s2 = snapshot(repo, at=600.0)
        assert s2["files"] == 3
        assert s2["lines"] >= 7

        report = growth_rate([s1, s2])
        assert report.verdict == "expanding"
        assert report.files_per_min > 0
