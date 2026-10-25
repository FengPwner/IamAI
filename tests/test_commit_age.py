"""Tests for iamai.commit_age module."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

from iamai.commit_age import (
    commit_age_summary,
    file_age_seconds,
    uncommitted_ages,
)


class TestFileAgeSeconds:
    """Tests for file_age_seconds()."""

    def test_recently_modified_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        now = time.time()
        age = file_age_seconds(f, now=now)
        assert 0 <= age < 5  # just created, should be very young

    def test_old_file(self, tmp_path):
        f = tmp_path / "old.txt"
        f.write_text("old content")
        # set mtime to 100 seconds ago
        old_time = time.time() - 100
        os.utime(f, (old_time, old_time))
        age = file_age_seconds(f, now=time.time())
        assert 99 <= age <= 102

    def test_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            file_age_seconds(tmp_path / "nope.txt")

    def test_now_override(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("x")
        mtime = f.stat().st_mtime
        # set now to exactly 50 seconds after mtime
        age = file_age_seconds(f, now=mtime + 50)
        assert age == pytest.approx(50.0, abs=0.1)

    def test_string_path(self, tmp_path):
        f = tmp_path / "str.txt"
        f.write_text("content")
        age = file_age_seconds(str(f))
        assert age >= 0

    def test_zero_age(self, tmp_path):
        f = tmp_path / "zero.txt"
        f.write_text("z")
        mtime = f.stat().st_mtime
        age = file_age_seconds(f, now=mtime)
        assert age == pytest.approx(0.0, abs=0.01)


class TestUncommittedAges:
    """Tests for uncommitted_ages()."""

    def test_clean_repo_returns_empty(self, tmp_path):
        """A non-git directory returns empty dict."""
        result = uncommitted_ages(tmp_path)
        assert result == {}

    def test_with_modified_files(self, tmp_path):
        """Mock a repo with modified files."""
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("aaa")
        f2.write_text("bbb")
        now = time.time()
        # set different ages
        os.utime(f1, (now - 30, now - 30))
        os.utime(f2, (now - 120, now - 120))

        with mock.patch(
            "iamai.commit_age._get_modified_files",
            return_value=["a.txt", "b.txt"],
        ):
            ages = uncommitted_ages(tmp_path, now=now)
            assert "a.txt" in ages
            assert "b.txt" in ages
            assert ages["a.txt"] == pytest.approx(30, abs=1)
            assert ages["b.txt"] == pytest.approx(120, abs=1)

    def test_missing_file_skipped(self, tmp_path):
        """Files that disappeared between git status and stat are skipped."""
        with mock.patch(
            "iamai.commit_age._get_modified_files",
            return_value=["ghost.txt"],
        ):
            ages = uncommitted_ages(tmp_path)
            assert "ghost.txt" not in ages

    def test_default_repo_path(self):
        """Calling with no argument should not raise."""
        result = uncommitted_ages()
        assert isinstance(result, dict)

    def test_empty_modified_list(self, tmp_path):
        with mock.patch(
            "iamai.commit_age._get_modified_files",
            return_value=[],
        ):
            ages = uncommitted_ages(tmp_path)
            assert ages == {}


class TestCommitAgeSummary:
    """Tests for commit_age_summary()."""

    def test_empty_summary(self, tmp_path):
        with mock.patch(
            "iamai.commit_age.uncommitted_ages",
            return_value={},
        ):
            s = commit_age_summary(tmp_path)
            assert s["count"] == 0
            assert s["min_seconds"] == 0
            assert s["max_seconds"] == 0
            assert s["mean_seconds"] == 0
            assert s["median_seconds"] == 0
            assert s["files"] == []

    def test_single_file(self, tmp_path):
        with mock.patch(
            "iamai.commit_age.uncommitted_ages",
            return_value={"a.txt": 60.0},
        ):
            s = commit_age_summary(tmp_path)
            assert s["count"] == 1
            assert s["min_seconds"] == 60.0
            assert s["max_seconds"] == 60.0
            assert s["mean_seconds"] == 60.0
            assert s["median_seconds"] == 60.0
            assert len(s["files"]) == 1

    def test_multiple_files_stats(self, tmp_path):
        ages = {"a.txt": 10.0, "b.txt": 20.0, "c.txt": 30.0}
        with mock.patch(
            "iamai.commit_age.uncommitted_ages",
            return_value=ages,
        ):
            s = commit_age_summary(tmp_path)
            assert s["count"] == 3
            assert s["min_seconds"] == 10.0
            assert s["max_seconds"] == 30.0
            assert s["mean_seconds"] == 20.0
            assert s["median_seconds"] == 20.0

    def test_even_count_median(self, tmp_path):
        ages = {"a.txt": 10.0, "b.txt": 30.0}
        with mock.patch(
            "iamai.commit_age.uncommitted_ages",
            return_value=ages,
        ):
            s = commit_age_summary(tmp_path)
            assert s["median_seconds"] == 20.0

    def test_files_sorted_by_age_descending(self, tmp_path):
        ages = {"young.txt": 5.0, "old.txt": 500.0, "mid.txt": 50.0}
        with mock.patch(
            "iamai.commit_age.uncommitted_ages",
            return_value=ages,
        ):
            s = commit_age_summary(tmp_path)
            paths = [f[0] for f in s["files"]]
            assert paths == ["old.txt", "mid.txt", "young.txt"]

    def test_default_repo_path(self):
        """Calling with no argument should not raise."""
        result = commit_age_summary()
        assert isinstance(result, dict)
        assert "count" in result
