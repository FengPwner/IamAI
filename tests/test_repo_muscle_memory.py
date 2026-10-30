#!/usr/bin/env python3
"""Tests for tools/repo_muscle_memory.py — muscle memory fitness analysis."""

from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from repo_muscle_memory import (
    ToolFitness,
    classify,
    discover_tools,
    fitness_score,
    format_text,
    analyze,
    parse_git_log_batch,
)


# ── classify ─────────────────────────────────────────────────────────────


class TestClassify:
    def test_well_practiced(self):
        assert classify(5, 3.0) == "WELL_PRACTICED"

    def test_well_practiced_boundary(self):
        assert classify(5, 7.0) == "WELL_PRACTICED"

    def test_well_practiced_high_commits_old_touch(self):
        """5 commits but last touch was 8 days ago → not WELL_PRACTICED."""
        assert classify(5, 8.0) == "EXERCISED"

    def test_exercised(self):
        assert classify(2, 10.0) == "EXERCISED"

    def test_exercised_boundary(self):
        assert classify(2, 14.0) == "EXERCISED"

    def test_exercised_few_commits(self):
        """Only 1 commit even if recent → not EXERCISED."""
        assert classify(1, 5.0) == "NEGLECTED"

    def test_neglected(self):
        assert classify(1, 20.0) == "NEGLECTED"

    def test_neglected_boundary(self):
        assert classify(1, 30.0) == "NEGLECTED"

    def test_atrophied_by_age(self):
        assert classify(1, 31.0) == "ATROPHIED"

    def test_atrophied_no_commits(self):
        assert classify(0, 5.0) == "ATROPHIED"

    def test_atrophied_infinite_age(self):
        assert classify(0, float("inf")) == "ATROPHIED"

    def test_many_commits_but_old(self):
        """10 commits but last touch was 60 days ago → ATROPHIED."""
        assert classify(10, 60.0) == "ATROPHIED"

    def test_few_commits_recent(self):
        """1 commit, 2 days ago → NEGLECTED (need ≥ 2 for EXERCISED)."""
        assert classify(1, 2.0) == "NEGLECTED"

    def test_well_practiced_just_over_7_days(self):
        """5 commits, 7.1 days → falls to EXERCISED."""
        assert classify(5, 7.1) == "EXERCISED"


# ── fitness_score ────────────────────────────────────────────────────────


class TestFitnessScore:
    def test_well_practiced(self):
        assert fitness_score("WELL_PRACTICED") == 100

    def test_exercised(self):
        assert fitness_score("EXERCISED") == 70

    def test_neglected(self):
        assert fitness_score("NEGLECTED") == 30

    def test_atrophied(self):
        assert fitness_score("ATROPHIED") == 0

    def test_unknown(self):
        assert fitness_score("UNKNOWN") == 0


# ── ToolFitness ──────────────────────────────────────────────────────────


class TestToolFitness:
    def test_default_values(self):
        tf = ToolFitness(name="foo.py", path="tools/foo.py")
        assert tf.commit_count == 0
        assert tf.days_since_touch == float("inf")
        assert tf.classification == "ATROPHIED"

    def test_consistency_no_intervals(self):
        tf = ToolFitness(name="foo.py", path="tools/foo.py")
        assert tf.consistency == float("inf")

    def test_consistency_one_interval(self):
        tf = ToolFitness(name="foo.py", path="tools/foo.py", intervals_days=[5.0])
        assert tf.consistency == float("inf")

    def test_consistency_perfect(self):
        """All intervals equal → stddev = 0."""
        tf = ToolFitness(name="foo.py", path="tools/foo.py", intervals_days=[5.0, 5.0, 5.0])
        assert tf.consistency == 0.0

    def test_consistency_variable(self):
        tf = ToolFitness(name="foo.py", path="tools/foo.py", intervals_days=[2.0, 8.0])
        # mean = 5, variance = (9 + 9)/2 = 9, stddev = 3
        assert abs(tf.consistency - 3.0) < 0.01

    def test_consistency_three_intervals(self):
        tf = ToolFitness(
            name="foo.py", path="tools/foo.py",
            intervals_days=[3.0, 5.0, 7.0],
        )
        # mean = 5, var = ((4+0+4)/3) = 2.667, stddev ≈ 1.633
        assert abs(tf.consistency - 1.633) < 0.01


# ── discover_tools ───────────────────────────────────────────────────────


class TestDiscoverTools:
    def test_finds_python_files(self, tmp_path):
        (tmp_path / "alpha.py").write_text("# alpha")
        (tmp_path / "beta.py").write_text("# beta")
        (tmp_path / "test_gamma.py").write_text("# test")
        (tmp_path / "notes.md").write_text("# notes")

        tools = discover_tools(tmp_path)
        assert "alpha.py" in tools
        assert "beta.py" in tools
        assert "test_gamma.py" not in tools  # test files excluded
        assert "notes.md" not in tools  # non-py excluded

    def test_empty_directory(self, tmp_path):
        assert discover_tools(tmp_path) == []

    def test_nonexistent_directory(self, tmp_path):
        fake = tmp_path / "nonexistent"
        assert discover_tools(fake) == []

    def test_sorted_output(self, tmp_path):
        (tmp_path / "zebra.py").write_text("")
        (tmp_path / "alpha.py").write_text("")
        (tmp_path / "middle.py").write_text("")

        tools = discover_tools(tmp_path)
        assert tools == sorted(tools)


# ── analyze (with mocked git) ────────────────────────────────────────────


class TestAnalyze:
    def test_empty_tools_dir(self, tmp_path):
        result = analyze(
            repo_path=tmp_path,
            tools_dir=tmp_path / "tools",
            days=90,
        )
        assert result["tool_count"] == 0
        assert result["muscle_score"] == 0

    def test_analyze_with_mocked_git(self, tmp_path):
        """Create tool files and mock git log to test full analysis."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "active.py").write_text("# active tool")
        (tools_dir / "dead.py").write_text("# dead tool")

        now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)

        # active.py: 10 commits over 30 days, last one 2 days ago
        active_commits = []
        for i in range(10):
            ts = now - timedelta(days=30 - i * 3)
            active_commits.append(ts)

        # dead.py: 1 commit 60 days ago
        dead_commits = [now - timedelta(days=60)]

        def mock_parse_git_log_batch(repo_path, filepaths, now_ts):
            result = {}
            for fp in filepaths:
                if "active.py" in fp:
                    result[fp] = list(active_commits)
                elif "dead.py" in fp:
                    result[fp] = list(dead_commits)
                else:
                    result[fp] = []
            return result

        with patch("repo_muscle_memory.parse_git_log_batch", side_effect=mock_parse_git_log_batch):
            result = analyze(
                repo_path=tmp_path,
                tools_dir=tools_dir,
                days=90,
                now=now,
            )

        assert result["tool_count"] == 2
        assert result["strongest"] == "active.py"
        assert result["atrophy_count"] >= 1  # dead.py should be atrophied

        # Check active.py classification
        active = next(t for t in result["tools"] if t["name"] == "active.py")
        assert active["commit_count"] == 10
        assert active["classification"] in ("WELL_PRACTICED", "EXERCISED")

        # Check dead.py classification
        dead = next(t for t in result["tools"] if t["name"] == "dead.py")
        assert dead["classification"] == "ATROPHIED"

    def test_muscle_score_range(self, tmp_path):
        """Score should be between 0 and 100."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "a.py").write_text("")
        (tools_dir / "b.py").write_text("")

        now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)

        # a.py: well-practiced; b.py: atrophied
        def mock_parse_batch(repo_path, filepaths, now_ts):
            result = {}
            for fp in filepaths:
                if "a.py" in fp:
                    result[fp] = [now - timedelta(days=i) for i in range(10)]
                else:
                    result[fp] = []
            return result

        with patch("repo_muscle_memory.parse_git_log_batch", side_effect=mock_parse_batch):
            result = analyze(repo_path=tmp_path, tools_dir=tools_dir, days=90, now=now)

        assert 0 <= result["muscle_score"] <= 100
        assert 0.0 <= result["practiced_ratio"] <= 1.0

    def test_practiced_ratio(self, tmp_path):
        """All well-practiced → ratio = 1.0; all atrophied → 0.0."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        for name in ["a.py", "b.py", "c.py", "d.py"]:
            (tools_dir / name).write_text("")

        now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)

        # 2 active, 2 dead
        def mock_parse_batch(repo_path, filepaths, now_ts):
            result = {}
            for fp in filepaths:
                if "a.py" in fp or "b.py" in fp:
                    result[fp] = [now - timedelta(days=i * 2) for i in range(6)]
                else:
                    result[fp] = []
            return result

        with patch("repo_muscle_memory.parse_git_log_batch", side_effect=mock_parse_batch):
            result = analyze(repo_path=tmp_path, tools_dir=tools_dir, days=90, now=now)

        assert result["practiced_ratio"] == 0.5

    def test_days_window_filtering(self, tmp_path):
        """Commits outside the window should be excluded."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "old.py").write_text("")

        now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)

        # All commits are 100+ days ago (outside 30-day window)
        old_commits = [now - timedelta(days=100 + i) for i in range(5)]

        def mock_parse_batch(repo_path, filepaths, now_ts):
            return {fp: list(old_commits) for fp in filepaths}

        with patch("repo_muscle_memory.parse_git_log_batch", side_effect=mock_parse_batch):
            result = analyze(
                repo_path=tmp_path, tools_dir=tools_dir, days=30, now=now,
            )

        tool = result["tools"][0]
        assert tool["commit_count"] == 0
        assert tool["classification"] == "ATROPHIED"


# ── format_text ──────────────────────────────────────────────────────────


class TestFormatText:
    def test_basic_formatting(self):
        result = {
            "tool_count": 2,
            "muscle_score": 50.0,
            "practiced_ratio": 0.5,
            "atrophy_count": 1,
            "strongest": "active.py",
            "weakest": "dead.py",
            "tools": [
                {
                    "name": "active.py",
                    "commit_count": 10,
                    "days_since_touch": 2.0,
                    "consistency": 3.5,
                    "classification": "WELL_PRACTICED",
                },
                {
                    "name": "dead.py",
                    "commit_count": 0,
                    "days_since_touch": float("inf"),
                    "consistency": None,
                    "classification": "ATROPHIED",
                },
            ],
        }
        text = format_text(result)
        assert "Repo Muscle Memory" in text
        assert "active.py" in text
        assert "dead.py" in text
        assert "50.0" in text
        assert "WELL_PRACTICED" in text
        assert "ATROPHIED" in text

    def test_infinite_days_display(self):
        result = {
            "tool_count": 1,
            "muscle_score": 0.0,
            "practiced_ratio": 0.0,
            "atrophy_count": 1,
            "strongest": "old.py",
            "weakest": "old.py",
            "tools": [
                {
                    "name": "old.py",
                    "commit_count": 0,
                    "days_since_touch": float("inf"),
                    "consistency": None,
                    "classification": "ATROPHIED",
                },
            ],
        }
        text = format_text(result)
        assert "never" in text

    def test_empty_tools(self):
        result = {
            "tool_count": 0,
            "muscle_score": 0,
            "practiced_ratio": 0.0,
            "atrophy_count": 0,
            "strongest": "",
            "weakest": "",
            "tools": [],
        }
        text = format_text(result)
        assert "tools analyzed:   0" in text
