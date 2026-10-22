"""Tests for iamai.commit_breadth — commit category diversity measurement."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.commit_breadth import (
    CATEGORIES,
    TOTAL_CATEGORIES,
    CommitBreadth,
    BreadthReport,
    _classify_grade,
    _GRADE_THRESHOLDS,
    _GRADE_SINGLE,
    classify_file,
    classify_files,
    measure_commit,
    breadth_report,
    breadth_summary,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    """Verify the category definitions are sane."""

    def test_total_categories_includes_root(self):
        assert TOTAL_CATEGORIES == len(CATEGORIES) + 1

    def test_total_categories_value(self):
        # 9 named categories + root = 10
        assert TOTAL_CATEGORIES == 10

    def test_all_category_names_are_lowercase(self):
        for name in CATEGORIES:
            assert name == name.lower()

    def test_infra_category_exists(self):
        assert "infra" in CATEGORIES

    def test_core_category_exists(self):
        assert "core" in CATEGORIES

    def test_tests_category_exists(self):
        assert "tests" in CATEGORIES


# ---------------------------------------------------------------------------
# classify_file
# ---------------------------------------------------------------------------

class TestClassifyFile:
    """Unit tests for single-file classification."""

    def test_core_module(self):
        assert classify_file("iamai/commit_breadth.py") == "core"

    def test_core_submodule(self):
        assert classify_file("iamai/sub/dir/foo.py") == "core"

    def test_test_file(self):
        assert classify_file("tests/test_commit_breadth.py") == "tests"

    def test_tool_script(self):
        assert classify_file("tools/commit_breadth.py") == "tools"

    def test_doc_file(self):
        assert classify_file("docs/DEVLOG.md") == "docs"

    def test_note_file(self):
        assert classify_file("notes/conventions.md") == "notes"

    def test_data_file(self):
        assert classify_file("data/strokes.jsonl") == "data"

    def test_snippet_file(self):
        assert classify_file("snippets/atomic_counter.py") == "snippets"

    def test_script_file(self):
        assert classify_file("scripts/repo_pulse.py") == "scripts"

    def test_makefile_is_infra(self):
        assert classify_file("Makefile") == "infra"

    def test_pytest_ini_is_infra(self):
        assert classify_file("pytest.ini") == "infra"

    def test_requirements_is_infra(self):
        assert classify_file("requirements-dev.txt") == "infra"

    def test_github_dir_is_infra(self):
        assert classify_file(".github/workflows/ci.yml") == "infra"

    def test_gitignore_is_infra(self):
        assert classify_file(".gitignore") == "infra"

    def test_readme_is_root(self):
        assert classify_file("README.md") == "root"

    def test_license_is_root(self):
        assert classify_file("LICENSE") == "root"

    def test_unknown_top_level_is_root(self):
        assert classify_file("random_file.txt") == "root"

    def test_unknown_nested_is_root(self):
        assert classify_file("unknown_dir/file.py") == "root"

    def test_empty_string_is_root(self):
        assert classify_file("") == "root"

    def test_case_sensitive_prefix(self):
        # "Iamai/" should NOT match "iamai/"
        assert classify_file("Iamai/foo.py") == "root"


# ---------------------------------------------------------------------------
# classify_files
# ---------------------------------------------------------------------------

class TestClassifyFiles:
    """Unit tests for batch file classification."""

    def test_empty_list(self):
        assert classify_files([]) == set()

    def test_single_file(self):
        assert classify_files(["iamai/foo.py"]) == {"core"}

    def test_multiple_categories(self):
        files = [
            "iamai/commit_breadth.py",
            "tests/test_commit_breadth.py",
            "tools/commit_breadth.py",
        ]
        result = classify_files(files)
        assert result == {"core", "tests", "tools"}

    def test_deduplication(self):
        files = [
            "iamai/foo.py",
            "iamai/bar.py",
            "iamai/baz.py",
        ]
        result = classify_files(files)
        assert result == {"core"}

    def test_all_categories(self):
        files = [
            "iamai/a.py",
            "tests/test_a.py",
            "tools/a.py",
            "docs/A.md",
            "notes/a.md",
            "data/a.jsonl",
            "snippets/a.py",
            "scripts/a.py",
            "Makefile",
            "README.md",
        ]
        result = classify_files(files)
        assert len(result) == TOTAL_CATEGORIES

    def test_filters_empty_strings(self):
        result = classify_files(["", "iamai/foo.py", ""])
        assert result == {"core"}


# ---------------------------------------------------------------------------
# _classify_grade
# ---------------------------------------------------------------------------

class TestClassifyGrade:
    """Unit tests for the grade classification function."""

    def test_perfect_breadth(self):
        assert _classify_grade(100.0) == "excellent"

    def test_at_excellent_threshold(self):
        assert _classify_grade(80.0) == "excellent"

    def test_just_below_excellent(self):
        assert _classify_grade(79.9) == "good"

    def test_at_good_threshold(self):
        assert _classify_grade(60.0) == "good"

    def test_just_below_good(self):
        assert _classify_grade(59.9) == "fair"

    def test_at_fair_threshold(self):
        assert _classify_grade(40.0) == "fair"

    def test_just_below_fair(self):
        assert _classify_grade(39.9) == "narrow"

    def test_at_narrow_threshold(self):
        assert _classify_grade(20.0) == "narrow"

    def test_just_below_narrow(self):
        assert _classify_grade(19.9) == "single"

    def test_zero_breadth(self):
        assert _classify_grade(0.0) == "single"

    def test_boundary_values_are_inclusive(self):
        """Each threshold value maps to its own grade, not the one below."""
        for threshold, grade in _GRADE_THRESHOLDS:
            assert _classify_grade(threshold) == grade


# ---------------------------------------------------------------------------
# CommitBreadth data class
# ---------------------------------------------------------------------------

class TestCommitBreadth:
    """Unit tests for the CommitBreadth dataclass."""

    def test_frozen(self):
        cb = CommitBreadth(
            sha="abc123", files_changed=5,
            categories=("core", "tests"),
            breadth_score=20.0, grade="narrow",
        )
        with pytest.raises(AttributeError):
            cb.sha = "def456"

    def test_to_dict(self):
        cb = CommitBreadth(
            sha="abc123", files_changed=5,
            categories=("core", "tests"),
            breadth_score=20.0, grade="narrow",
        )
        d = cb.to_dict()
        assert d["sha"] == "abc123"
        assert d["files_changed"] == 5
        assert d["categories"] == ["core", "tests"]
        assert d["breadth_score"] == 20.0
        assert d["grade"] == "narrow"

    def test_to_dict_score_rounding(self):
        cb = CommitBreadth(
            sha="abc", files_changed=1,
            categories=("core",),
            breadth_score=10.123456, grade="single",
        )
        assert cb.to_dict()["breadth_score"] == 10.1


# ---------------------------------------------------------------------------
# BreadthReport data class
# ---------------------------------------------------------------------------

class TestBreadthReport:
    """Unit tests for the BreadthReport dataclass."""

    def test_empty_report_defaults(self):
        report = BreadthReport()
        assert report.commits == []
        assert report.avg_breadth == 0.0
        assert report.avg_grade == "single"
        assert report.total_commits == 0

    def test_to_dict_empty(self):
        report = BreadthReport()
        d = report.to_dict()
        assert d["total_commits"] == 0
        assert d["commits"] == []
        assert d["avg_breadth"] == 0.0

    def test_to_dict_with_commits(self):
        cb = CommitBreadth(
            sha="abc", files_changed=3,
            categories=("core", "tests", "tools"),
            breadth_score=30.0, grade="narrow",
        )
        report = BreadthReport(
            commits=[cb],
            avg_breadth=30.0,
            avg_grade="narrow",
            total_commits=1,
            broad_commits=0,
            narrow_commits=1,
        )
        d = report.to_dict()
        assert d["total_commits"] == 1
        assert len(d["commits"]) == 1
        assert d["commits"][0]["sha"] == "abc"


# ---------------------------------------------------------------------------
# measure_commit (with mocked git)
# ---------------------------------------------------------------------------

class TestMeasureCommit:
    """Unit tests for measure_commit using mocked git."""

    @patch("iamai.commit_breadth._get_commit_files")
    def test_single_category_commit(self, mock_files):
        mock_files.return_value = ["iamai/foo.py"]
        result = measure_commit(Path("/tmp/fake"), "abc123")
        assert result.categories == ("core",)
        assert result.breadth_score == pytest.approx(10.0, abs=0.1)
        assert result.grade == "single"

    @patch("iamai.commit_breadth._get_commit_files")
    def test_multi_category_commit(self, mock_files):
        mock_files.return_value = [
            "iamai/commit_breadth.py",
            "tests/test_commit_breadth.py",
            "tools/commit_breadth.py",
            "docs/METRICS.md",
            "notes/conventions.md",
        ]
        result = measure_commit(Path("/tmp/fake"), "abc123")
        assert len(result.categories) == 5
        assert result.breadth_score == pytest.approx(50.0, abs=0.1)
        assert result.grade == "fair"

    @patch("iamai.commit_breadth._get_commit_files")
    def test_empty_commit(self, mock_files):
        mock_files.return_value = []
        result = measure_commit(Path("/tmp/fake"), "abc123")
        assert result.breadth_score == 0.0
        assert result.grade == "single"
        assert result.categories == ()

    @patch("iamai.commit_breadth._get_commit_files")
    def test_broad_commit_all_categories(self, mock_files):
        mock_files.return_value = [
            "iamai/a.py",
            "tests/test_a.py",
            "tools/a.py",
            "docs/A.md",
            "notes/a.md",
            "data/a.jsonl",
            "snippets/a.py",
            "scripts/a.py",
            "Makefile",
            "README.md",
        ]
        result = measure_commit(Path("/tmp/fake"), "abc123")
        assert result.breadth_score == 100.0
        assert result.grade == "excellent"

    @patch("iamai.commit_breadth._get_commit_files")
    def test_files_changed_count(self, mock_files):
        mock_files.return_value = ["a.py", "b.py", "c.py"]
        result = measure_commit(Path("/tmp/fake"), "abc123")
        assert result.files_changed == 3

    @patch("iamai.commit_breadth._get_commit_files")
    def test_sha_preserved(self, mock_files):
        mock_files.return_value = ["iamai/x.py"]
        result = measure_commit(Path("/tmp/fake"), "deadbeef")
        assert result.sha == "deadbeef"


# ---------------------------------------------------------------------------
# breadth_report (with mocked git)
# ---------------------------------------------------------------------------

class TestBreadthReportFunction:
    """Integration tests for the breadth_report function."""

    @patch("iamai.commit_breadth._get_recent_shas")
    @patch("iamai.commit_breadth._get_commit_files")
    def test_basic_report(self, mock_files, mock_shas):
        mock_shas.return_value = ["sha1", "sha2", "sha3"]
        mock_files.side_effect = [
            ["iamai/a.py", "tests/test_a.py", "tools/a.py"],
            ["iamai/b.py"],
            ["iamai/c.py", "tests/test_c.py", "docs/C.md", "notes/c.md"],
        ]
        report = breadth_report(repo_path="/tmp/fake", last=3)
        assert report.total_commits == 3
        assert report.avg_breadth > 0

    @patch("iamai.commit_breadth._get_recent_shas")
    @patch("iamai.commit_breadth._get_commit_files")
    def test_broad_and_narrow_counts(self, mock_files, mock_shas):
        mock_shas.return_value = ["sha1", "sha2"]
        # sha1: 6 categories → score=60 → broad
        mock_files.side_effect = [
            ["iamai/a.py", "tests/test_a.py", "tools/a.py",
             "docs/A.md", "notes/a.md", "data/a.jsonl"],
            ["iamai/b.py"],  # 1 category → score=10 → narrow
        ]
        report = breadth_report(repo_path="/tmp/fake", last=2)
        assert report.broad_commits == 1
        assert report.narrow_commits == 1

    @patch("iamai.commit_breadth._get_recent_shas")
    def test_empty_shas_returns_empty_report(self, mock_shas):
        mock_shas.return_value = []
        report = breadth_report(repo_path="/tmp/fake")
        assert report.total_commits == 0
        assert report.commits == []

    @patch("iamai.commit_breadth._get_recent_shas")
    @patch("iamai.commit_breadth._get_commit_files")
    def test_git_error_skips_commit(self, mock_files, mock_shas):
        mock_shas.return_value = ["sha1", "sha2"]
        mock_files.side_effect = [
            subprocess.CalledProcessError(1, "git"),
            ["iamai/a.py"],
        ]
        report = breadth_report(repo_path="/tmp/fake", last=2)
        assert report.total_commits == 1

    @patch("iamai.commit_breadth._get_recent_shas")
    @patch("iamai.commit_breadth._get_commit_files")
    def test_avg_grade_computed(self, mock_files, mock_shas):
        mock_shas.return_value = ["sha1"]
        mock_files.return_value = [
            "iamai/a.py", "tests/test_a.py", "tools/a.py",
            "docs/A.md", "notes/a.md", "data/a.jsonl",
            "snippets/a.py", "scripts/a.py", "Makefile", "README.md",
        ]
        report = breadth_report(repo_path="/tmp/fake", last=1)
        assert report.avg_grade == "excellent"


# ---------------------------------------------------------------------------
# breadth_summary
# ---------------------------------------------------------------------------

class TestBreadthSummary:
    """Unit tests for the summary formatter."""

    def test_empty_report(self):
        report = BreadthReport()
        result = breadth_summary(report)
        assert "no commits" in result

    def test_normal_report(self):
        cb = CommitBreadth(
            sha="abc", files_changed=5,
            categories=("core", "tests", "tools", "docs", "notes"),
            breadth_score=50.0, grade="fair",
        )
        report = BreadthReport(
            commits=[cb],
            avg_breadth=50.0,
            avg_grade="fair",
            total_commits=1,
            broad_commits=0,
            narrow_commits=0,
        )
        result = breadth_summary(report)
        assert "50.0%" in result
        assert "fair" in result
        assert "1 commits" in result


# ---------------------------------------------------------------------------
# Integration test (real git, temp repo)
# ---------------------------------------------------------------------------

class TestIntegration:
    """End-to-end tests using a temporary git repository."""

    @pytest.fixture
    def temp_repo(self, tmp_path):
        """Create a minimal git repo with a few commits."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        # Init
        subprocess.run(
            ["git", "init", str(repo)],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test"],
            capture_output=True, check=True,
        )

        # Create directories
        for d in ["iamai", "tests", "tools", "docs", "notes", "data"]:
            (repo / d).mkdir()

        # Commit 1: narrow (only core)
        (repo / "iamai" / "foo.py").write_text("# foo")
        subprocess.run(
            ["git", "-C", str(repo), "add", "."],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "add foo"],
            capture_output=True, check=True,
        )

        # Commit 2: broader (core + tests + tools)
        (repo / "tests" / "test_foo.py").write_text("# test")
        (repo / "tools" / "foo.py").write_text("# tool")
        subprocess.run(
            ["git", "-C", str(repo), "add", "."],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "add test and tool"],
            capture_output=True, check=True,
        )

        # Commit 3: very broad (core + tests + docs + notes + data)
        (repo / "iamai" / "bar.py").write_text("# bar")
        (repo / "tests" / "test_bar.py").write_text("# test bar")
        (repo / "docs" / "DEVLOG.md").write_text("# devlog")
        (repo / "notes" / "read.md").write_text("# note")
        (repo / "data" / "s.jsonl").write_text("{}")
        subprocess.run(
            ["git", "-C", str(repo), "add", "."],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "add bar + docs"],
            capture_output=True, check=True,
        )

        return repo

    def test_real_repo_report(self, temp_repo):
        report = breadth_report(repo_path=temp_repo, last=10)
        assert report.total_commits == 3
        assert report.avg_breadth > 0

    def test_real_repo_has_broad_commit(self, temp_repo):
        report = breadth_report(repo_path=temp_repo, last=10)
        # Commit 3 touches 5 categories → 50% → fair
        scores = [c.breadth_score for c in report.commits]
        assert max(scores) >= 40.0

    def test_real_repo_narrow_commit(self, temp_repo):
        report = breadth_report(repo_path=temp_repo, last=10)
        scores = [c.breadth_score for c in report.commits]
        assert min(scores) <= 20.0  # commit 1 only touches core

    def test_real_repo_summary(self, temp_repo):
        report = breadth_report(repo_path=temp_repo, last=10)
        summary = breadth_summary(report)
        assert "commit_breadth" in summary
        assert "%" in summary
