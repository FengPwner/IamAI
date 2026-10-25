"""Tests for iamai.milestone_tracker — detect when the repo crosses thresholds."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from iamai.milestone_tracker import (
    _load_state,
    _measure,
    _save_state,
    check_milestones,
    default_thresholds,
    milestone_summary,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _init_repo(tmp: Path) -> Path:
    """Create a tiny git repo with strokes.jsonl for testing."""
    repo = tmp / "milestone_test"
    repo.mkdir()
    (repo / "data").mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)

    # commit 1: create a few files
    (repo / "a.txt").write_text("line one\nline two\nline three\n")
    (repo / "b.txt").write_text("hello world\n")
    (repo / "data" / "strokes.jsonl").write_text(
        '{"seq": 1, "at": "2026-10-15T00:00:00+00:00", "kind": "thought", "text": "first"}\n'
        '{"seq": 2, "at": "2026-10-15T00:00:15+00:00", "kind": "note", "text": "second"}\n'
        '{"seq": 3, "at": "2026-10-15T00:00:30+00:00", "kind": "devlog", "text": "third"}\n'
    )
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

    # commit 2: add more strokes
    with open(repo / "data" / "strokes.jsonl", "a") as f:
        f.write('{"seq": 4, "at": "2026-10-15T00:00:45+00:00", "kind": "garden", "text": "fourth"}\n')
        f.write('{"seq": 5, "at": "2026-10-15T00:01:00+00:00", "kind": "metrics", "text": "fifth"}\n')
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "more strokes"], cwd=repo, capture_output=True)

    return repo


# ---------------------------------------------------------------------------
# default_thresholds
# ---------------------------------------------------------------------------

class TestDefaultThresholds:
    def test_returns_dict(self):
        t = default_thresholds()
        assert isinstance(t, dict)
        assert "strokes" in t
        assert "files" in t
        assert "commits" in t
        assert "lines" in t

    def test_returns_copy(self):
        t1 = default_thresholds()
        t2 = default_thresholds()
        t1["strokes"].append(99999)
        assert 99999 not in t2["strokes"], "modifying one copy must not affect the other"

    def test_thresholds_are_sorted(self):
        for metric, levels in default_thresholds().items():
            assert levels == sorted(levels), f"{metric} thresholds must be sorted"


# ---------------------------------------------------------------------------
# _measure
# ---------------------------------------------------------------------------

class TestMeasure:
    def test_strokes_count(self, tmp_path):
        repo = _init_repo(tmp_path)
        count = _measure("strokes", repo)
        assert count == 5, "5 strokes in the JSONL file"

    def test_strokes_missing_file(self, tmp_path):
        repo = tmp_path / "empty"
        repo.mkdir()
        (repo / "data").mkdir()
        count = _measure("strokes", repo)
        assert count == 0

    def test_files_count(self, tmp_path):
        repo = _init_repo(tmp_path)
        count = _measure("files", repo)
        assert count == 3, "a.txt, b.txt, data/strokes.jsonl"

    def test_commits_count(self, tmp_path):
        repo = _init_repo(tmp_path)
        count = _measure("commits", repo)
        assert count == 2, "init + more strokes"

    def test_lines_count(self, tmp_path):
        repo = _init_repo(tmp_path)
        count = _measure("lines", repo)
        # a.txt: 3 lines, b.txt: 1 line, strokes.jsonl: 5 lines = 9
        assert count == 9

    def test_unknown_metric(self, tmp_path):
        repo = _init_repo(tmp_path)
        count = _measure("nonexistent", repo)
        assert count == 0


# ---------------------------------------------------------------------------
# _load_state / _save_state
# ---------------------------------------------------------------------------

class TestState:
    def test_load_missing(self, tmp_path):
        state = _load_state(tmp_path)
        assert state == {}

    def test_save_and_load(self, tmp_path):
        (tmp_path / "data").mkdir(exist_ok=True)
        _save_state({"strokes": 100, "files": 50}, tmp_path)
        state = _load_state(tmp_path)
        assert state == {"strokes": 100, "files": 50}

    def test_load_corrupt_json(self, tmp_path):
        (tmp_path / "data").mkdir(exist_ok=True)
        (tmp_path / "data" / "milestone_state.json").write_text("{bad json")
        state = _load_state(tmp_path)
        assert state == {}, "corrupt state should return empty dict"


# ---------------------------------------------------------------------------
# check_milestones
# ---------------------------------------------------------------------------

class TestCheckMilestones:
    def test_crosses_threshold(self, tmp_path):
        repo = _init_repo(tmp_path)
        thresholds = {"strokes": [3, 5, 10]}
        crossed = check_milestones(repo, thresholds)
        # state starts empty (previous=0), current=5, so 3 and 5 are crossed
        stroke_crossed = [c for c in crossed if c["metric"] == "strokes"]
        assert len(stroke_crossed) == 2
        assert stroke_crossed[0]["threshold"] == 3
        assert stroke_crossed[1]["threshold"] == 5
        assert stroke_crossed[1]["value"] == 5
        assert stroke_crossed[1]["previous"] == 0

    def test_no_crossing_when_already_past(self, tmp_path):
        repo = _init_repo(tmp_path)
        thresholds = {"strokes": [3, 5, 10]}
        # First call: crosses 3 and 5
        check_milestones(repo, thresholds)
        # Second call: state saved at 5, nothing new crossed
        crossed2 = check_milestones(repo, thresholds)
        stroke_crossed = [c for c in crossed2 if c["metric"] == "strokes"]
        assert len(stroke_crossed) == 0, "no new crossings on second call"

    def test_exact_boundary(self, tmp_path):
        """When previous == threshold, it should NOT count as crossed."""
        repo = _init_repo(tmp_path)
        # Set state to exactly 5 (the current value)
        (repo / "data").mkdir(exist_ok=True)
        _save_state({"strokes": 5}, repo)
        thresholds = {"strokes": [5, 10]}
        crossed = check_milestones(repo, thresholds)
        stroke_crossed = [c for c in crossed if c["metric"] == "strokes"]
        assert len(stroke_crossed) == 0, "already at threshold, not crossed"

    def test_multiple_metrics(self, tmp_path):
        repo = _init_repo(tmp_path)
        thresholds = {"strokes": [3], "files": [2], "commits": [1]}
        crossed = check_milestones(repo, thresholds)
        metrics_crossed = {c["metric"] for c in crossed}
        assert "strokes" in metrics_crossed
        assert "files" in metrics_crossed
        assert "commits" in metrics_crossed

    def test_no_update_state(self, tmp_path):
        repo = _init_repo(tmp_path)
        thresholds = {"strokes": [3, 5]}
        crossed1 = check_milestones(repo, thresholds, update_state=False)
        # State not saved, so second call should find the same crossings
        crossed2 = check_milestones(repo, thresholds, update_state=False)
        assert len(crossed1) == len(crossed2)

    def test_custom_thresholds(self, tmp_path):
        repo = _init_repo(tmp_path)
        thresholds = {"files": [1, 2, 3, 100]}
        crossed = check_milestones(repo, thresholds)
        file_crossed = [c for c in crossed if c["metric"] == "files"]
        # 3 files, thresholds at 1, 2, 3 — all crossed
        assert len(file_crossed) == 3
        assert file_crossed[-1]["threshold"] == 3

    def test_empty_repo(self, tmp_path):
        repo = tmp_path / "empty"
        repo.mkdir()
        (repo / "data").mkdir()
        thresholds = {"strokes": [1], "files": [1]}
        crossed = check_milestones(repo, thresholds)
        # No strokes file, no git repo for files → values are 0
        assert len(crossed) == 0


# ---------------------------------------------------------------------------
# milestone_summary
# ---------------------------------------------------------------------------

class TestMilestoneSummary:
    def test_summary_with_crossings(self, tmp_path):
        repo = _init_repo(tmp_path)
        thresholds = {"strokes": [3, 5]}
        summary = milestone_summary(repo, thresholds)
        assert "milestones:" in summary
        assert "strokes" in summary
        assert "crossed" in summary

    def test_summary_no_crossings(self, tmp_path):
        repo = _init_repo(tmp_path)
        # Set state to current values so nothing crosses
        _save_state({"strokes": 5, "files": 3, "commits": 2, "lines": 9}, repo)
        thresholds = {"strokes": [10], "files": [10]}
        summary = milestone_summary(repo, thresholds)
        assert summary == "milestones: none crossed"

    def test_summary_format(self, tmp_path):
        repo = _init_repo(tmp_path)
        thresholds = {"strokes": [3]}
        summary = milestone_summary(repo, thresholds)
        # Should contain "strokes crossed 3 (now 5)"
        assert "strokes crossed 3" in summary
        assert "(now 5)" in summary
