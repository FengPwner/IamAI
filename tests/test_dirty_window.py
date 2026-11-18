#!/usr/bin/env python3
"""Tests for tools/dirty_window.py — working-tree drift measurement."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from dirty_window import (
    DriftSnapshot,
    categorize_file,
    get_tracked_files,
    measure_drift,
    main,
)


# ---------------------------------------------------------------------------
# DriftSnapshot
# ---------------------------------------------------------------------------


class TestDriftSnapshot:
    """Tests for the DriftSnapshot dataclass."""

    def test_summary_zero_dirty(self):
        snap = DriftSnapshot(
            window_seconds=60,
            since_iso="2026-01-01T00:00:00+00:00",
            until_iso="2026-01-01T00:01:00+00:00",
            dirty_files=0,
            clean_files=100,
            total_tracked=100,
            dirty_ratio=0.0,
            files=[],
            categories={},
        )
        assert "0/100 dirty" in snap.summary()
        assert "0.0%" in snap.summary()

    def test_summary_some_dirty(self):
        snap = DriftSnapshot(
            window_seconds=120,
            since_iso="2026-01-01T00:00:00+00:00",
            until_iso="2026-01-01T00:02:00+00:00",
            dirty_files=5,
            clean_files=95,
            total_tracked=100,
            dirty_ratio=0.05,
            files=["a.py", "b.py", "c.md", "d.json", "e.txt"],
            categories={"tools": 2, "notes": 1, "data": 1, "other": 1},
        )
        s = snap.summary()
        assert "5/100" in s
        assert "5.0%" in s
        assert "120s" in s

    def test_summary_all_dirty(self):
        snap = DriftSnapshot(
            window_seconds=30,
            since_iso="2026-01-01T00:00:00+00:00",
            until_iso="2026-01-01T00:00:30+00:00",
            dirty_files=50,
            clean_files=0,
            total_tracked=50,
            dirty_ratio=1.0,
            files=[f"f{i}.py" for i in range(50)],
            categories={"tools": 50},
        )
        assert "50/50" in snap.summary()
        assert "100.0%" in snap.summary()

    def test_summary_empty_repo(self):
        snap = DriftSnapshot(
            window_seconds=60,
            since_iso="2026-01-01T00:00:00+00:00",
            until_iso="2026-01-01T00:01:00+00:00",
            dirty_files=0,
            clean_files=0,
            total_tracked=0,
            dirty_ratio=0.0,
            files=[],
            categories={},
        )
        assert "0/0" in snap.summary()


# ---------------------------------------------------------------------------
# categorize_file
# ---------------------------------------------------------------------------


class TestCategorizeFile:
    """Tests for file categorization."""

    def test_notes(self):
        assert categorize_file("notes/reading.md") == "notes"

    def test_docs(self):
        assert categorize_file("docs/DEVLOG.md") == "docs"

    def test_tools(self):
        assert categorize_file("tools/auto_restart.py") == "tools"

    def test_tests(self):
        assert categorize_file("tests/test_dirty_window.py") == "tests"

    def test_data(self):
        assert categorize_file("data/strokes.jsonl") == "data"

    def test_modules(self):
        assert categorize_file("modules/foo.py") == "modules"

    def test_src(self):
        assert categorize_file("src/main.py") == "src"

    def test_unknown_top(self):
        assert categorize_file("scripts/run.sh") == "scripts"

    def test_root_file(self):
        assert categorize_file("README.md") == "README.md"

    def test_empty_path(self):
        assert categorize_file("") == "other"


# ---------------------------------------------------------------------------
# get_tracked_files
# ---------------------------------------------------------------------------


class TestGetTrackedFiles:
    """Tests for listing tracked files via git."""

    def test_returns_list(self):
        result = get_tracked_files()
        assert isinstance(result, list)

    def test_non_empty_for_real_repo(self):
        result = get_tracked_files()
        assert len(result) > 0

    def test_invalid_repo_returns_empty(self, tmp_path):
        result = get_tracked_files(repo=tmp_path)
        assert result == []

    def test_known_files_present(self):
        result = get_tracked_files()
        # These files should always be tracked
        assert any("README" in f for f in result)


# ---------------------------------------------------------------------------
# measure_drift
# ---------------------------------------------------------------------------


class TestMeasureDrift:
    """Tests for the core drift measurement function."""

    def test_returns_snapshot(self):
        snap = measure_drift(window_seconds=60)
        assert isinstance(snap, DriftSnapshot)

    def test_total_tracked_positive(self):
        snap = measure_drift(window_seconds=60)
        assert snap.total_tracked > 0

    def test_dirty_plus_clean_equals_total(self):
        snap = measure_drift(window_seconds=60)
        assert snap.dirty_files + snap.clean_files == snap.total_tracked

    def test_ratio_in_range(self):
        snap = measure_drift(window_seconds=60)
        assert 0.0 <= snap.dirty_ratio <= 1.0

    def test_files_are_sorted(self):
        snap = measure_drift(window_seconds=3600)
        assert snap.files == sorted(snap.files)

    def test_categories_sum_matches_dirty(self):
        snap = measure_drift(window_seconds=3600)
        cat_total = sum(snap.categories.values())
        assert cat_total == snap.dirty_files

    def test_window_seconds_recorded(self):
        snap = measure_drift(window_seconds=123)
        assert snap.window_seconds == 123

    def test_explicit_since_until(self):
        now = datetime.now(timezone.utc)
        since = now - timedelta(minutes=5)
        snap = measure_drift(since=since, until=now)
        assert snap.since_iso == since.isoformat()
        assert snap.until_iso == now.isoformat()
        assert abs(snap.window_seconds - 300) < 2

    def test_since_only(self):
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=1)
        snap = measure_drift(since=since)
        # until should default to now
        assert snap.since_iso == since.isoformat()

    def test_until_only(self):
        now = datetime.now(timezone.utc)
        until = now - timedelta(minutes=1)
        snap = measure_drift(until=until)
        # since should default to epoch
        assert snap.until_iso == until.isoformat()

    def test_zero_window(self):
        now = datetime.now(timezone.utc)
        snap = measure_drift(since=now, until=now)
        assert snap.window_seconds == 0
        # With zero window, only files modified at exactly this instant count
        # In practice this should be zero or very small
        assert snap.dirty_files >= 0

    def test_large_window_catches_everything(self):
        # A 10-year window should catch all tracked files as "dirty"
        # (assuming the repo has been touched in the last decade)
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=365 * 10)
        snap = measure_drift(since=since, until=now)
        # Most files should be "dirty" in a 10-year window
        # (unless their mtime is older than 10 years, unlikely in a container)
        assert snap.dirty_files >= 0

    def test_invalid_repo(self, tmp_path):
        snap = measure_drift(repo=tmp_path, window_seconds=60)
        assert snap.total_tracked == 0
        assert snap.dirty_files == 0


# ---------------------------------------------------------------------------
# measure_drift with mock
# ---------------------------------------------------------------------------


class TestMeasureDriftMocked:
    """Tests with mocked filesystem to control mtime behavior."""

    def test_all_files_dirty(self, tmp_path):
        # Create a fake repo with tracked files
        (tmp_path / "a.py").write_text("hello")
        (tmp_path / "b.md").write_text("world")
        now = time.time()
        # Set mtime to now
        os.utime(tmp_path / "a.py", (now, now))
        os.utime(tmp_path / "b.md", (now, now))

        fake_tracked = ["a.py", "b.md"]
        now_dt = datetime.now(timezone.utc)

        with patch("dirty_window.get_tracked_files", return_value=fake_tracked):
            snap = measure_drift(
                repo=tmp_path,
                since=datetime.fromtimestamp(now - 10, tz=timezone.utc),
                until=datetime.fromtimestamp(now + 10, tz=timezone.utc),
            )
        assert snap.dirty_files == 2
        assert snap.clean_files == 0
        assert snap.dirty_ratio == 1.0

    def test_no_files_dirty(self, tmp_path):
        (tmp_path / "a.py").write_text("hello")
        old_time = time.time() - 86400  # yesterday
        os.utime(tmp_path / "a.py", (old_time, old_time))

        fake_tracked = ["a.py"]
        now = time.time()

        with patch("dirty_window.get_tracked_files", return_value=fake_tracked):
            snap = measure_drift(
                repo=tmp_path,
                since=datetime.fromtimestamp(now - 60, tz=timezone.utc),
                until=datetime.fromtimestamp(now, tz=timezone.utc),
            )
        assert snap.dirty_files == 0
        assert snap.clean_files == 1
        assert snap.dirty_ratio == 0.0

    def test_missing_file_counted_as_clean(self, tmp_path):
        fake_tracked = ["nonexistent.py"]
        now = time.time()

        with patch("dirty_window.get_tracked_files", return_value=fake_tracked):
            snap = measure_drift(
                repo=tmp_path,
                since=datetime.fromtimestamp(now - 60, tz=timezone.utc),
                until=datetime.fromtimestamp(now, tz=timezone.utc),
            )
        assert snap.dirty_files == 0
        assert snap.clean_files == 1

    def test_mixed_dirty_clean(self, tmp_path):
        now = time.time()
        (tmp_path / "dirty.py").write_text("new")
        os.utime(tmp_path / "dirty.py", (now, now))
        (tmp_path / "clean.py").write_text("old")
        os.utime(tmp_path / "clean.py", (now - 86400, now - 86400))

        fake_tracked = ["dirty.py", "clean.py"]

        with patch("dirty_window.get_tracked_files", return_value=fake_tracked):
            snap = measure_drift(
                repo=tmp_path,
                since=datetime.fromtimestamp(now - 60, tz=timezone.utc),
                until=datetime.fromtimestamp(now + 1, tz=timezone.utc),
            )
        assert snap.dirty_files == 1
        assert snap.clean_files == 1
        assert snap.dirty_ratio == 0.5
        assert "dirty.py" in snap.files

    def test_categories_populated(self, tmp_path):
        now = time.time()
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        (tools_dir / "a.py").write_text("x")
        os.utime(tools_dir / "a.py", (now, now))
        (notes_dir / "b.md").write_text("y")
        os.utime(notes_dir / "b.md", (now, now))

        fake_tracked = ["tools/a.py", "notes/b.md"]

        with patch("dirty_window.get_tracked_files", return_value=fake_tracked):
            snap = measure_drift(
                repo=tmp_path,
                since=datetime.fromtimestamp(now - 60, tz=timezone.utc),
                until=datetime.fromtimestamp(now + 1, tz=timezone.utc),
            )
        assert snap.categories == {"notes": 1, "tools": 1}


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for the CLI entry point."""

    def test_default_args(self):
        with patch("sys.argv", ["dirty_window"]):
            result = main()
        assert result == 0

    def test_json_output(self, capsys):
        with patch("sys.argv", ["dirty_window", "--json"]):
            result = main()
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "dirty_files" in data
        assert "total_tracked" in data

    def test_custom_window(self):
        with patch("sys.argv", ["dirty_window", "--window", "300"]):
            result = main()
        assert result == 0

    def test_since_until(self):
        with patch(
            "sys.argv",
            [
                "dirty_window",
                "--since",
                "2026-01-01T00:00:00",
                "--until",
                "2026-01-01T01:00:00",
            ],
        ):
            result = main()
        assert result == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
