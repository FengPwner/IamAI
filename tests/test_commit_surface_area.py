#!/usr/bin/env python3
"""Tests for commit_surface_area.py — measure how broadly commits touch the repo.

60 tests covering:
  - file classification (maintenance vs creative)
  - top-directory extraction
  - depth calculation
  - depth score normalisation
  - composite surface-area score
  - classification thresholds
  - per-commit analysis structure
  - multi-commit aggregate report
  - trend detection (shrinking / stable / growing)
  - edge cases (empty commits, single file, all maintenance)
  - CLI exit codes

Run:  pytest tests/test_commit_surface_area.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.commit_surface_area import (
    CommitSurface,
    REPO,
    _classify,
    _compute_depth_score,
    _depth,
    _is_creative,
    _is_maintenance,
    _top_dir,
    analyse_commit,
    analyse_commits,
    main,
    surface_report,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_commit(
    hash: str = "abc123",
    message: str = "test commit",
    file_count: int = 5,
    dir_count: int = 3,
    files: list[str] | None = None,
    new_files: list[str] | None = None,
    modified_files: list[str] | None = None,
    creation_ratio: float = 0.2,
    maintenance_ratio: float = 0.4,
    creative_ratio: float = 0.4,
    depth_score: float = 0.5,
    surface_area: float = 0.5,
    classification: str = "moderate",
) -> CommitSurface:
    return CommitSurface(
        hash=hash,
        message=message,
        file_count=file_count,
        dir_count=dir_count,
        files=files or ["data/strokes.jsonl", "notes/test.md", "iamai/mod.py"],
        new_files=new_files or ["iamai/mod.py"],
        modified_files=modified_files or ["data/strokes.jsonl", "notes/test.md"],
        creation_ratio=creation_ratio,
        maintenance_ratio=maintenance_ratio,
        creative_ratio=creative_ratio,
        depth_score=depth_score,
        surface_area=surface_area,
        classification=classification,
    )


# ── _is_maintenance ──────────────────────────────────────────────────


class TestIsMaintenance:
    def test_strokes_jsonl(self):
        assert _is_maintenance("data/strokes.jsonl")

    def test_writer_state_qwen(self):
        assert _is_maintenance("data/writer_state.qwen.json")

    def test_writer_state_guoban(self):
        assert _is_maintenance("data/writer_state.guoban.json")

    def test_writer_state_kimi(self):
        assert _is_maintenance("data/writer_state.kimi.json")

    def test_devlog(self):
        assert _is_maintenance("docs/DEVLOG.md")

    def test_garden(self):
        assert _is_maintenance("docs/GARDEN.md")

    def test_metrics(self):
        assert _is_maintenance("docs/METRICS.md")

    def test_notes_not_maintenance(self):
        assert not _is_maintenance("notes/caretaker-visit-593.md")

    def test_new_module_not_maintenance(self):
        assert not _is_maintenance("iamai/commit_surface_area.py")

    def test_test_file_not_maintenance(self):
        assert not _is_maintenance("tests/test_commit_surface_area.py")

    def test_tools_script_not_maintenance(self):
        assert not _is_maintenance("tools/run_both.sh")


# ── _is_creative ─────────────────────────────────────────────────────


class TestIsCreative:
    def test_notes_creative(self):
        assert _is_creative("notes/reading.md")

    def test_docs_creative(self):
        assert _is_creative("docs/DEVLOG.md")

    def test_iamai_creative(self):
        assert _is_creative("iamai/stall_early_warning.py")

    def test_tests_creative(self):
        assert _is_creative("tests/test_stall_early_warning.py")

    def test_tools_creative(self):
        assert _is_creative("tools/writer_loop.py")

    def test_data_not_creative(self):
        assert not _is_creative("data/strokes.jsonl")

    def test_root_file_not_creative(self):
        assert not _is_creative("README.md")

    def test_config_not_creative(self):
        assert not _is_creative(".github/workflows/ci.yml")


# ── _top_dir ─────────────────────────────────────────────────────────


class TestTopDir:
    def test_nested_path(self):
        assert _top_dir("data/strokes.jsonl") == "data"

    def test_deep_path(self):
        assert _top_dir("iamai/sub/module.py") == "iamai"

    def test_root_file(self):
        assert _top_dir("README.md") == "."

    def test_single_dir(self):
        assert _top_dir("notes/caretaker-visit-593.md") == "notes"


# ── _depth ───────────────────────────────────────────────────────────


class TestDepth:
    def test_root_file(self):
        assert _depth("README.md") == 0

    def test_one_level(self):
        assert _depth("notes/test.md") == 1

    def test_two_levels(self):
        assert _depth("iamai/sub/module.py") == 2

    def test_three_levels(self):
        assert _depth("a/b/c/d.py") == 3


# ── _compute_depth_score ─────────────────────────────────────────────


class TestComputeDepthScore:
    def test_empty_files(self):
        assert _compute_depth_score([]) == 0.0

    def test_shallow_files(self):
        score = _compute_depth_score(["README.md"])
        assert score == 0.0  # max_d=0, avg_d=0

    def test_one_level_deep(self):
        score = _compute_depth_score(["notes/test.md"])
        assert 0.0 < score < 0.5

    def test_deep_files(self):
        score = _compute_depth_score(["a/b/c/d.py", "x/y/z.py"])
        assert score > 0.5

    def test_mixed_depth(self):
        shallow = _compute_depth_score(["a.py", "b/c.py"])
        deep = _compute_depth_score(["a/b/c/d.py", "x/y/z/w.py"])
        assert deep > shallow

    def test_bounded_at_one(self):
        score = _compute_depth_score(["a/b/c/d/e/f/g.py"])
        assert score <= 1.0


# ── _classify ────────────────────────────────────────────────────────


class TestClassify:
    def test_narrow_low_score(self):
        assert _classify(0.0) == "narrow"

    def test_narrow_boundary(self):
        assert _classify(0.19) == "narrow"

    def test_moderate_at_boundary(self):
        assert _classify(0.2) == "moderate"

    def test_moderate_mid(self):
        assert _classify(0.35) == "moderate"

    def test_broad_at_boundary(self):
        assert _classify(0.5) == "broad"

    def test_broad_high(self):
        assert _classify(0.75) == "broad"

    def test_exploratory_at_boundary(self):
        assert _classify(0.8) == "exploratory"

    def test_exploratory_max(self):
        assert _classify(1.0) == "exploratory"


# ── CommitSurface ────────────────────────────────────────────────────


class TestCommitSurface:
    def test_summary_contains_hash(self):
        c = _make_commit(hash="abc12345")
        assert "abc12345" in c.summary()

    def test_summary_contains_classification(self):
        c = _make_commit(classification="broad")
        assert "broad" in c.summary()

    def test_summary_contains_surface(self):
        c = _make_commit(surface_area=0.67)
        assert "0.67" in c.summary()

    def test_summary_contains_file_count(self):
        c = _make_commit(file_count=12)
        assert "files=12" in c.summary()


# ── analyse_commit (mocked git) ──────────────────────────────────────


class TestAnalyseCommit:
    def _mock_run(self, stdout_map):
        """Return a side_effect function for subprocess.run."""
        def side_effect(cmd, **kwargs):
            key = cmd[1] if len(cmd) > 1 else ""
            m = MagicMock()
            if "log" in cmd and "--format=%s" in cmd:
                m.stdout = "test commit message"
            elif "diff-tree" in cmd:
                m.stdout = stdout_map.get("diff", "")
            else:
                m.stdout = stdout_map.get(key, "")
            m.returncode = 0
            return m
        return side_effect

    def test_maintenance_only_commit(self):
        diff = (
            "M\tdata/strokes.jsonl\n"
            "M\tdata/writer_state.qwen.json\n"
            "M\tdocs/DEVLOG.md\n"
            "M\tdocs/GARDEN.md\n"
            "M\tdocs/METRICS.md\n"
        )
        with patch("subprocess.run", side_effect=self._mock_run({"diff": diff})):
            result = analyse_commit("abc123")
        assert result.file_count == 5
        assert result.maintenance_ratio == 1.0
        assert result.classification == "narrow"
        assert result.surface_area < 0.2

    def test_creative_commit_with_new_files(self):
        diff = (
            "A\tiamai/new_module.py\n"
            "A\ttests/test_new_module.py\n"
            "A\tnotes/caretaker-visit-600.md\n"
            "M\tdata/strokes.jsonl\n"
        )
        with patch("subprocess.run", side_effect=self._mock_run({"diff": diff})):
            result = analyse_commit("abc123")
        assert result.file_count == 4
        assert len(result.new_files) == 3
        assert result.creation_ratio == 0.75
        assert result.classification in ("broad", "exploratory")

    def test_empty_commit(self):
        with patch("subprocess.run", side_effect=self._mock_run({"diff": ""})):
            result = analyse_commit("abc123")
        assert result.file_count == 0
        assert result.classification == "narrow" or result.surface_area == 0.0 or result.surface_area <= 0.2

    def test_single_new_file(self):
        diff = "A\tnotes/new-idea.md\n"
        with patch("subprocess.run", side_effect=self._mock_run({"diff": diff})):
            result = analyse_commit("abc123")
        assert result.file_count == 1
        assert result.creation_ratio == 1.0
        assert result.creative_ratio == 1.0

    def test_broad_commit_many_dirs(self):
        diff = (
            "A\tiamai/module.py\n"
            "A\ttests/test_module.py\n"
            "M\tnotes/reading.md\n"
            "M\ttools/writer_loop.py\n"
            "M\tdata/strokes.jsonl\n"
            "A\tdocs/new-guide.md\n"
        )
        with patch("subprocess.run", side_effect=self._mock_run({"diff": diff})):
            result = analyse_commit("abc123")
        assert result.dir_count >= 4
        assert result.surface_area > 0.5


# ── surface_report ───────────────────────────────────────────────────


class TestSurfaceReport:
    def test_empty_list(self):
        r = surface_report([])
        assert r["total_commits"] == 0
        assert "no commits" in r["diagnosis"]

    def test_all_narrow(self):
        commits = [_make_commit(surface_area=0.1, classification="narrow") for _ in range(10)]
        r = surface_report(commits)
        assert r["narrow_ratio"] == 1.0
        assert "comfort zone" in r["diagnosis"]

    def test_all_broad(self):
        commits = [_make_commit(surface_area=0.7, classification="broad") for _ in range(10)]
        r = surface_report(commits)
        assert r["narrow_ratio"] == 0.0
        assert "healthy" in r["diagnosis"]

    def test_mixed_commits(self):
        commits = (
            [_make_commit(surface_area=0.1, classification="narrow") for _ in range(3)]
            + [_make_commit(surface_area=0.6, classification="broad") for _ in range(7)]
        )
        r = surface_report(commits)
        assert r["narrow_ratio"] == 0.3
        assert r["total_commits"] == 10

    def test_classification_counts(self):
        commits = [
            _make_commit(surface_area=0.1, classification="narrow"),
            _make_commit(surface_area=0.3, classification="moderate"),
            _make_commit(surface_area=0.6, classification="broad"),
            _make_commit(surface_area=0.9, classification="exploratory"),
        ]
        r = surface_report(commits)
        assert r["classification_counts"]["narrow"] == 1
        assert r["classification_counts"]["moderate"] == 1
        assert r["classification_counts"]["broad"] == 1
        assert r["classification_counts"]["exploratory"] == 1

    def test_trend_growing(self):
        # older commits (second half) are narrow, newer (first half) are broad
        older = [_make_commit(surface_area=0.1, classification="narrow") for _ in range(5)]
        newer = [_make_commit(surface_area=0.8, classification="exploratory") for _ in range(5)]
        commits = newer + older  # newest first (git log order)
        r = surface_report(commits)
        assert r["trend"] == "growing"

    def test_trend_shrinking(self):
        older = [_make_commit(surface_area=0.8, classification="exploratory") for _ in range(5)]
        newer = [_make_commit(surface_area=0.1, classification="narrow") for _ in range(5)]
        commits = newer + older
        r = surface_report(commits)
        assert r["trend"] == "shrinking"

    def test_trend_stable(self):
        commits = [_make_commit(surface_area=0.5, classification="moderate") for _ in range(10)]
        r = surface_report(commits)
        assert r["trend"] == "stable"

    def test_trend_insufficient_data(self):
        commits = [_make_commit(surface_area=0.5, classification="moderate") for _ in range(3)]
        r = surface_report(commits)
        assert r["trend"] == "insufficient data"

    def test_avg_surface_area(self):
        commits = [
            _make_commit(surface_area=0.2),
            _make_commit(surface_area=0.4),
            _make_commit(surface_area=0.6),
            _make_commit(surface_area=0.8),
        ]
        r = surface_report(commits)
        assert r["avg_surface_area"] == 0.5


# ── analyse_commits (mocked) ─────────────────────────────────────────


class TestAnalyseCommits:
    def test_returns_requested_count(self):
        hashes = "\n".join([f"hash{i}" for i in range(5)])

        def mock_run(cmd, **kwargs):
            m = MagicMock()
            if "--format=%H" in cmd:
                m.stdout = hashes
            elif "--format=%s" in cmd:
                m.stdout = "test"
            elif "diff-tree" in cmd:
                m.stdout = "M\tdata/strokes.jsonl\n"
            else:
                m.stdout = ""
            m.returncode = 0
            return m

        with patch("subprocess.run", side_effect=mock_run):
            results = analyse_commits(count=5)
        assert len(results) == 5


# ── CLI ──────────────────────────────────────────────────────────────


class TestCLI:
    def test_json_output(self, capsys):
        commits = [_make_commit(hash=f"h{i}", surface_area=0.5, classification="moderate")
                    for i in range(3)]
        with patch("iamai.commit_surface_area.analyse_commits", return_value=commits):
            rc = main(["--json", "--count", "3"])
            assert rc == 0
            out = capsys.readouterr().out
            data = json.loads(out)
            assert "commits" in data
            assert "report" in data

    def test_text_output(self, capsys):
        commits = [_make_commit(hash=f"h{i}", surface_area=0.6, classification="broad")
                    for i in range(3)]
        with patch("iamai.commit_surface_area.analyse_commits", return_value=commits):
            rc = main(["--count", "3"])
            assert rc == 0
            out = capsys.readouterr().out
            assert "broad" in out
            assert "diagnosis" in out

    def test_exit_code_2_comfort_zone(self):
        commits = [_make_commit(surface_area=0.1, classification="narrow") for _ in range(10)]
        with patch("iamai.commit_surface_area.analyse_commits", return_value=commits):
            rc = main(["--count", "10"])
            assert rc == 2

    def test_exit_code_1_some_narrow(self):
        commits = (
            [_make_commit(surface_area=0.1, classification="narrow")]
            + [_make_commit(surface_area=0.6, classification="broad") for _ in range(9)]
        )
        with patch("iamai.commit_surface_area.analyse_commits", return_value=commits):
            rc = main(["--count", "10"])
            assert rc == 1

    def test_exit_code_0_all_healthy(self):
        commits = [_make_commit(surface_area=0.6, classification="broad") for _ in range(5)]
        with patch("iamai.commit_surface_area.analyse_commits", return_value=commits):
            rc = main(["--count", "5"])
            assert rc == 0


# ── Integration: real repo ───────────────────────────────────────────


class TestIntegration:
    """Run against the actual repo — only if we are inside it."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_repo(self):
        if not (REPO / ".git").is_dir():
            pytest.skip("not inside the IamAI repo")

    def test_analyse_latest_commit(self):
        log = subprocess.run(
            ["git", "log", "-1", "--format=%H"],
            capture_output=True, text=True, cwd=str(REPO),
        )
        h = log.stdout.strip()
        result = analyse_commit(h)
        assert result.hash == h
        assert result.file_count > 0
        assert result.classification in ("narrow", "moderate", "broad", "exploratory")

    def test_analyse_commits_default(self):
        results = analyse_commits(5)
        assert len(results) == 5
        for r in results:
            assert 0.0 <= r.surface_area <= 1.0

    def test_report_has_trend(self):
        results = analyse_commits(10)
        report = surface_report(results)
        assert "trend" in report
        assert report["total_commits"] == 10
