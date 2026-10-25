#!/usr/bin/env python3
"""Tests for tools/commit_freshness.py — commit freshness monitor."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from commit_freshness import (
    FreshnessReport,
    _classify,
    _count_uncommitted,
    _human_duration,
    _run,
    as_markdown,
    measure,
)


# ── _classify ────────────────────────────────────────────────────────


class TestClassify:
    """Tests for the _classify helper."""

    def test_fresh_when_zero(self):
        assert _classify(0, 600) == "fresh"

    def test_fresh_when_equal(self):
        assert _classify(600, 600) == "fresh"

    def test_fresh_just_under(self):
        assert _classify(599, 600) == "fresh"

    def test_stale_just_over(self):
        assert _classify(601, 600) == "stale"

    def test_stale_at_double(self):
        assert _classify(1200, 600) == "stale"

    def test_stale_at_triple_boundary(self):
        assert _classify(1800, 600) == "stale"

    def test_dead_past_triple(self):
        assert _classify(1801, 600) == "dead"

    def test_dead_very_old(self):
        assert _classify(86400, 600) == "dead"

    def test_fresh_small_interval(self):
        assert _classify(30, 60) == "fresh"

    def test_dead_small_interval(self):
        assert _classify(200, 60) == "dead"

    def test_infinity_is_dead(self):
        assert _classify(float("inf"), 600) == "dead"


# ── _human_duration ─────────────────────────────────────────────────


class TestHumanDuration:
    """Tests for the _human_duration helper."""

    def test_seconds(self):
        assert _human_duration(0) == "0s"
        assert _human_duration(45) == "45s"

    def test_minutes(self):
        assert _human_duration(60) == "1.0m"
        assert _human_duration(150) == "2.5m"
        assert _human_duration(599) == "10.0m"

    def test_hours(self):
        assert _human_duration(3600) == "1.0h"
        assert _human_duration(7200) == "2.0h"
        assert _human_duration(86399) == "24.0h"

    def test_days(self):
        assert _human_duration(86400) == "1.0d"
        assert _human_duration(172800) == "2.0d"

    def test_fractional_seconds_rounds(self):
        assert _human_duration(0.5) == "0s"  # rounds to 0


# ── _run ─────────────────────────────────────────────────────────────


class TestRun:
    """Tests for the subprocess helper."""

    def test_successful_command(self, tmp_path):
        result = _run(["echo", "hello"], tmp_path)
        assert result == "hello"

    def test_missing_command_returns_empty(self, tmp_path):
        result = _run(["nonexistent_command_xyz_12345"], tmp_path)
        assert result == ""

    def test_output_is_stripped(self, tmp_path):
        result = _run(["echo", "  padded  "], tmp_path)
        assert result == "padded"


# ── _count_uncommitted ───────────────────────────────────────────────


class TestCountUncommitted:
    """Tests for counting uncommitted files via git status."""

    def test_clean_repo_via_measure(self, tmp_path):
        """A bare repo with no changes should report 0 uncommitted."""
        import subprocess
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        # create and commit a file
        (tmp_path / "a.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
        count = _count_uncommitted(tmp_path)
        assert count == 0

    def test_dirty_repo(self, tmp_path):
        """Modified files should be counted."""
        import subprocess
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "a.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
        # create dirty files
        (tmp_path / "a.txt").write_text("changed")
        (tmp_path / "b.txt").write_text("new")
        count = _count_uncommitted(tmp_path)
        assert count == 2


# ── measure (integration) ────────────────────────────────────────────


class TestMeasure:
    """Integration tests for the measure() function."""

    def _make_repo(self, tmp_path, commit_age=0):
        """Create a minimal git repo with one commit."""
        import subprocess
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "file.txt").write_text("content")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=tmp_path, capture_output=True)
        return tmp_path

    def test_fresh_commit(self, tmp_path):
        repo = self._make_repo(tmp_path)
        report = measure(interval=600, repo=repo)
        assert report.status == "fresh"
        assert report.commit_age_seconds < 5  # just committed
        assert report.latest_commit_message == "initial commit"
        assert report.uncommitted_files == 0

    def test_custom_interval(self, tmp_path):
        repo = self._make_repo(tmp_path)
        report = measure(interval=30, repo=repo)
        assert report.interval == 30
        assert report.stale_threshold == 30.0
        assert report.dead_threshold == 90.0

    def test_report_fields(self, tmp_path):
        repo = self._make_repo(tmp_path)
        report = measure(interval=600, repo=repo)
        assert isinstance(report, FreshnessReport)
        assert report.latest_commit_hash != "?"
        assert report.commit_age_human.endswith("s")  # just committed
        assert report.status in ("fresh", "stale", "dead")

    def test_no_repo_returns_dead_or_empty(self, tmp_path):
        """A directory with no git repo should still return a report."""
        report = measure(interval=600, repo=tmp_path)
        # No commits → age=inf → dead
        assert report.status == "dead"
        assert report.latest_commit_hash == "?"


# ── as_markdown ──────────────────────────────────────────────────────


class TestAsMarkdown:
    """Tests for the markdown rendering."""

    def _report(self, status="fresh", age=10.0, uncommitted=0):
        return FreshnessReport(
            commit_age_seconds=age,
            commit_age_human=_human_duration(age),
            latest_commit_hash="abc1234",
            latest_commit_message="test commit",
            interval=600,
            status=status,
            uncommitted_files=uncommitted,
            stale_threshold=600.0,
            dead_threshold=1800.0,
        )

    def test_fresh_has_green_icon(self):
        md = as_markdown(self._report("fresh"))
        assert "🟢" in md

    def test_stale_has_yellow_icon(self):
        md = as_markdown(self._report("stale", age=700))
        assert "🟡" in md

    def test_dead_has_red_icon(self):
        md = as_markdown(self._report("dead", age=2000))
        assert "🔴" in md

    def test_contains_hash(self):
        md = as_markdown(self._report())
        assert "abc1234" in md

    def test_contains_message(self):
        md = as_markdown(self._report())
        assert "test commit" in md

    def test_contains_uncommitted_count(self):
        md = as_markdown(self._report(uncommitted=3))
        assert "3 file(s)" in md

    def test_contains_thresholds(self):
        md = as_markdown(self._report())
        assert "600s" in md
        assert "1800s" in md


# ── Edge cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_zero_interval(self):
        """Zero interval means everything is stale."""
        assert _classify(1, 0) == "dead"

    def test_exact_stale_boundary(self):
        assert _classify(600, 600) == "fresh"
        assert _classify(600.01, 600) == "stale"

    def test_exact_dead_boundary(self):
        assert _classify(1800, 600) == "stale"
        assert _classify(1800.01, 600) == "dead"

    def test_large_interval(self):
        assert _classify(3599, 3600) == "fresh"
        assert _classify(3601, 3600) == "stale"

    def test_human_duration_boundary_values(self):
        assert "m" in _human_duration(60)
        assert "h" in _human_duration(3600)
        assert "d" in _human_duration(86400)
