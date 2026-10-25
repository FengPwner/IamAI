"""Tests for iamai.category_momentum — category attention shift measurement."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.category_momentum import (
    CATEGORIES,
    ALL_CATEGORIES,
    CategoryMomentum,
    MomentumReport,
    classify_file,
    classify_files,
    compute_momentum,
    momentum_report,
    momentum_summary,
    _compute_summary,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    """Verify category definitions are sane."""

    def test_root_is_in_all_categories(self):
        assert "root" in ALL_CATEGORIES

    def test_all_categories_has_ten_entries(self):
        assert len(ALL_CATEGORIES) == 10

    def test_all_category_names_are_lowercase(self):
        for name in ALL_CATEGORIES:
            assert name == name.lower()

    def test_no_duplicate_categories(self):
        assert len(ALL_CATEGORIES) == len(set(ALL_CATEGORIES))

    def test_categories_dict_matches_all_categories(self):
        for cat in CATEGORIES:
            assert cat in ALL_CATEGORIES

    def test_core_prefix_is_iamai(self):
        assert "iamai/" in CATEGORIES["core"]

    def test_tests_prefix_is_tests(self):
        assert "tests/" in CATEGORIES["tests"]


# ---------------------------------------------------------------------------
# classify_file
# ---------------------------------------------------------------------------

class TestClassifyFile:
    """Unit tests for file-to-category classification."""

    def test_core_file(self):
        assert classify_file("iamai/writer.py") == "core"

    def test_test_file(self):
        assert classify_file("tests/test_writer.py") == "tests"

    def test_tools_file(self):
        assert classify_file("tools/run_both.sh") == "tools"

    def test_docs_file(self):
        assert classify_file("docs/DEVLOG.md") == "docs"

    def test_notes_file(self):
        assert classify_file("notes/conventions.md") == "notes"

    def test_data_file(self):
        assert classify_file("data/strokes.jsonl") == "data"

    def test_snippets_file(self):
        assert classify_file("snippets/retry.py") == "snippets"

    def test_scripts_file(self):
        assert classify_file("scripts/deploy.sh") == "scripts"

    def test_infra_makefile(self):
        assert classify_file("Makefile") == "infra"

    def test_infra_pytest_ini(self):
        assert classify_file("pytest.ini") == "infra"

    def test_infra_github(self):
        assert classify_file(".github/workflows/ci.yml") == "infra"

    def test_infra_gitignore(self):
        assert classify_file(".gitignore") == "infra"

    def test_root_file(self):
        assert classify_file("README.md") == "root"

    def test_unknown_dir_is_root(self):
        assert classify_file("misc/something.txt") == "root"

    def test_deeply_nested_core(self):
        assert classify_file("iamai/sub/module.py") == "core"

    def test_deeply_nested_notes(self):
        assert classify_file("notes/visits/visit-1.md") == "notes"

    def test_requirements_is_infra(self):
        assert classify_file("requirements.txt") == "infra"

    def test_requirements_dev_is_infra(self):
        assert classify_file("requirements-dev.txt") == "infra"


# ---------------------------------------------------------------------------
# classify_files
# ---------------------------------------------------------------------------

class TestClassifyFiles:
    """Unit tests for batch file classification."""

    def test_empty_list(self):
        result = classify_files([])
        assert all(v == 0 for v in result.values())

    def test_mixed_files(self):
        result = classify_files([
            "iamai/writer.py",
            "tests/test_writer.py",
            "docs/DEVLOG.md",
            "README.md",
        ])
        assert result["core"] == 1
        assert result["tests"] == 1
        assert result["docs"] == 1
        assert result["root"] == 1

    def test_all_same_category(self):
        result = classify_files([
            "iamai/a.py",
            "iamai/b.py",
            "iamai/c.py",
        ])
        assert result["core"] == 3
        assert result["tests"] == 0

    def test_returns_all_categories(self):
        result = classify_files(["README.md"])
        assert len(result) == len(ALL_CATEGORIES)


# ---------------------------------------------------------------------------
# compute_momentum
# ---------------------------------------------------------------------------

class TestComputeMomentum:
    """Unit tests for the core momentum computation."""

    def test_no_change(self):
        """Equal distributions yield zero momentum."""
        old = {cat: 5 for cat in ALL_CATEGORIES}
        new = {cat: 5 for cat in ALL_CATEGORIES}
        old_total = sum(old.values())
        new_total = sum(new.values())
        result = compute_momentum(old, new, old_total, new_total)
        for cat in result:
            assert cat.momentum == 0.0
            assert cat.grade == "steady"

    def test_accelerating_category(self):
        """A category gaining attention has positive momentum."""
        old = {cat: 2 for cat in ALL_CATEGORIES}
        new = {cat: 2 for cat in ALL_CATEGORIES}
        new["core"] = 20  # big spike in core
        old_total = sum(old.values())
        new_total = sum(new.values())
        result = compute_momentum(old, new, old_total, new_total)
        core = next(c for c in result if c.name == "core")
        assert core.momentum > 10
        assert core.grade == "accelerating"

    def test_decelerating_category(self):
        """A category losing attention has negative momentum."""
        old = {cat: 5 for cat in ALL_CATEGORIES}
        old["notes"] = 50  # notes dominated old half
        new = {cat: 5 for cat in ALL_CATEGORIES}
        new["notes"] = 2  # barely present in new half
        old_total = sum(old.values())
        new_total = sum(new.values())
        result = compute_momentum(old, new, old_total, new_total)
        notes = next(c for c in result if c.name == "notes")
        assert notes.momentum < -10
        assert notes.grade == "decelerating"

    def test_zero_totals(self):
        """Empty inputs don't crash."""
        old = {cat: 0 for cat in ALL_CATEGORIES}
        new = {cat: 0 for cat in ALL_CATEGORIES}
        result = compute_momentum(old, new, 0, 0)
        for cat in result:
            assert cat.momentum == 0.0

    def test_sorted_by_momentum_descending(self):
        """Results should be sorted by momentum, highest first."""
        old = {cat: 1 for cat in ALL_CATEGORIES}
        new = {cat: 1 for cat in ALL_CATEGORIES}
        new["core"] = 20
        new["tests"] = 15
        new["notes"] = 0
        old_total = sum(old.values())
        new_total = sum(new.values())
        result = compute_momentum(old, new, old_total, new_total)
        momenta = [c.momentum for c in result]
        assert momenta == sorted(momenta, reverse=True)

    def test_all_categories_present(self):
        """Every category appears in the result."""
        old = {cat: 1 for cat in ALL_CATEGORIES}
        new = {cat: 1 for cat in ALL_CATEGORIES}
        result = compute_momentum(old, new, 10, 10)
        names = {c.name for c in result}
        assert names == set(ALL_CATEGORIES)

    def test_momentum_range(self):
        """Momentum values stay within reasonable bounds."""
        old = {cat: 0 for cat in ALL_CATEGORIES}
        old["root"] = 100
        new = {cat: 0 for cat in ALL_CATEGORIES}
        new["core"] = 100
        result = compute_momentum(old, new, 100, 100)
        for cat in result:
            assert -100 <= cat.momentum <= 100

    def test_steady_boundary(self):
        """Values within ±10 are steady."""
        old = {cat: 10 for cat in ALL_CATEGORIES}
        new = {cat: 10 for cat in ALL_CATEGORIES}
        new["core"] = 11  # tiny shift
        old_total = 100
        new_total = 101
        result = compute_momentum(old, new, old_total, new_total)
        core = next(c for c in result if c.name == "core")
        assert abs(core.momentum) < 10
        assert core.grade == "steady"


# ---------------------------------------------------------------------------
# _compute_summary
# ---------------------------------------------------------------------------

class TestComputeSummary:
    """Unit tests for the summary grade."""

    def test_balanced_when_all_steady(self):
        cats = [CategoryMomentum(name=c, momentum=0.0) for c in ALL_CATEGORIES]
        assert _compute_summary(cats, 100) == "balanced"

    def test_concentrating_when_one_dominates(self):
        cats = [CategoryMomentum(name=c, new_count=2, momentum=0.0)
                for c in ALL_CATEGORIES]
        cats[0] = CategoryMomentum(name="core", new_count=80, momentum=5.0)
        assert _compute_summary(cats, 100) == "concentrating"

    def test_shifting_when_large_momentum(self):
        cats = [CategoryMomentum(name=c, new_count=10, momentum=0.0)
                for c in ALL_CATEGORIES]
        cats[0] = CategoryMomentum(name="core", new_count=30, momentum=20.0)
        assert _compute_summary(cats, 100) == "shifting"

    def test_empty_categories(self):
        assert _compute_summary([], 0) == "balanced"

    def test_zero_new_total(self):
        cats = [CategoryMomentum(name=c) for c in ALL_CATEGORIES]
        assert _compute_summary(cats, 0) == "balanced"

    def test_concentrating_takes_priority_over_shifting(self):
        """If top-1 > 50% AND there's a shift, concentrating wins."""
        cats = [CategoryMomentum(name=c, new_count=5, momentum=0.0)
                for c in ALL_CATEGORIES]
        cats[0] = CategoryMomentum(name="core", new_count=80, momentum=25.0)
        assert _compute_summary(cats, 100) == "concentrating"


# ---------------------------------------------------------------------------
# CategoryMomentum.grade
# ---------------------------------------------------------------------------

class TestCategoryMomentumGrade:
    """Test the grade property."""

    def test_accelerating(self):
        cm = CategoryMomentum(name="core", momentum=15.0)
        assert cm.grade == "accelerating"

    def test_decelerating(self):
        cm = CategoryMomentum(name="core", momentum=-15.0)
        assert cm.grade == "decelerating"

    def test_steady_positive(self):
        cm = CategoryMomentum(name="core", momentum=5.0)
        assert cm.grade == "steady"

    def test_steady_negative(self):
        cm = CategoryMomentum(name="core", momentum=-5.0)
        assert cm.grade == "steady"

    def test_steady_zero(self):
        cm = CategoryMomentum(name="core", momentum=0.0)
        assert cm.grade == "steady"

    def test_boundary_accelerating(self):
        cm = CategoryMomentum(name="core", momentum=10.01)
        assert cm.grade == "accelerating"

    def test_boundary_decelerating(self):
        cm = CategoryMomentum(name="core", momentum=-10.01)
        assert cm.grade == "decelerating"

    def test_boundary_steady_high(self):
        cm = CategoryMomentum(name="core", momentum=10.0)
        assert cm.grade == "steady"

    def test_boundary_steady_low(self):
        cm = CategoryMomentum(name="core", momentum=-10.0)
        assert cm.grade == "steady"


# ---------------------------------------------------------------------------
# MomentumReport.to_dict
# ---------------------------------------------------------------------------

class TestMomentumReportToDict:
    """Test serialisation."""

    def test_empty_report(self):
        r = MomentumReport()
        d = r.to_dict()
        assert d["commits_analyzed"] == 0
        assert d["categories"] == []
        assert d["summary"] == "balanced"

    def test_with_data(self):
        r = MomentumReport(
            categories=[
                CategoryMomentum(name="core", old_count=5, new_count=10,
                                 momentum=8.33),
                CategoryMomentum(name="tests", old_count=3, new_count=2,
                                 momentum=-2.5),
            ],
            commits_analyzed=10,
            old_half_count=50,
            new_half_count=40,
            summary="shifting",
        )
        d = r.to_dict()
        assert d["commits_analyzed"] == 10
        assert len(d["categories"]) == 2
        assert d["categories"][0]["name"] == "core"
        assert d["summary"] == "shifting"

    def test_momentum_is_rounded(self):
        r = MomentumReport(
            categories=[
                CategoryMomentum(name="core", momentum=12.3456789),
            ],
        )
        d = r.to_dict()
        assert d["categories"][0]["momentum"] == 12.35


# ---------------------------------------------------------------------------
# Integration: momentum_report with mocked git
# ---------------------------------------------------------------------------

class TestMomentumReportIntegration:
    """Test the full report with mocked git calls."""

    @patch("iamai.category_momentum._get_recent_commits")
    @patch("iamai.category_momentum._get_commit_files")
    def test_basic_report(self, mock_files, mock_commits):
        mock_commits.return_value = [f"abc{i:03d}" for i in range(10)]
        # Old half (commits 5-9): mostly notes
        # New half (commits 0-4): mostly core
        def side_effect(cwd, h):
            idx = int(h[3:])
            if idx < 5:  # new half
                return ["iamai/mod.py", "tests/test_mod.py"]
            else:  # old half
                return ["notes/something.md", "docs/DEVLOG.md"]
        mock_files.side_effect = side_effect

        report = momentum_report(repo_path="/tmp/fake", commits=10)
        assert report.commits_analyzed == 10
        assert report.new_half_count > 0
        assert report.old_half_count > 0

        core = next(c for c in report.categories if c.name == "core")
        notes = next(c for c in report.categories if c.name == "notes")
        assert core.momentum > 0
        assert notes.momentum < 0

    @patch("iamai.category_momentum._get_recent_commits")
    def test_empty_repo(self, mock_commits):
        mock_commits.return_value = []
        report = momentum_report(repo_path="/tmp/fake")
        assert report.commits_analyzed == 0
        assert report.summary == "balanced"

    @patch("iamai.category_momentum._get_recent_commits")
    @patch("iamai.category_momentum._get_commit_files")
    def test_single_commit(self, mock_files, mock_commits):
        mock_commits.return_value = ["abc123"]
        mock_files.return_value = ["iamai/writer.py"]
        report = momentum_report(repo_path="/tmp/fake", commits=1)
        assert report.commits_analyzed == 1


# ---------------------------------------------------------------------------
# momentum_summary
# ---------------------------------------------------------------------------

class TestMomentumSummary:
    """Test the one-line summary function."""

    @patch("iamai.category_momentum.momentum_report")
    def test_no_commits(self, mock_report):
        mock_report.return_value = MomentumReport()
        result = momentum_summary("/tmp/fake")
        assert result == "no commits to analyse"

    @patch("iamai.category_momentum.momentum_report")
    def test_balanced_summary(self, mock_report):
        mock_report.return_value = MomentumReport(
            categories=[
                CategoryMomentum(name="core", momentum=2.0),
                CategoryMomentum(name="tests", momentum=-1.0),
            ],
            commits_analyzed=10,
        )
        result = momentum_summary("/tmp/fake")
        assert "balanced" in result

    @patch("iamai.category_momentum.momentum_report")
    def test_accelerating_mentioned(self, mock_report):
        mock_report.return_value = MomentumReport(
            categories=[
                CategoryMomentum(name="core", momentum=25.0),
                CategoryMomentum(name="tests", momentum=1.0),
            ],
            commits_analyzed=10,
        )
        result = momentum_summary("/tmp/fake")
        assert "gaining" in result
        assert "core" in result

    @patch("iamai.category_momentum.momentum_report")
    def test_decelerating_mentioned(self, mock_report):
        mock_report.return_value = MomentumReport(
            categories=[
                CategoryMomentum(name="notes", momentum=-20.0),
                CategoryMomentum(name="core", momentum=1.0),
            ],
            commits_analyzed=10,
        )
        result = momentum_summary("/tmp/fake")
        assert "losing" in result
        assert "notes" in result
