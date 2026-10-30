"""Tests for iamai.test_coverage — module test coverage analysis."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.test_coverage import (
    _discover_modules,
    _discover_tests,
    module_test_coverage,
    coverage_report,
)


# ---------------------------------------------------------------------------
# _discover_modules
# ---------------------------------------------------------------------------


class TestDiscoverModules:
    def test_basic(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "foo.py").write_text("")
        (pkg / "bar.py").write_text("")
        (pkg / "baz.py").write_text("")
        modules = _discover_modules(tmp_path)
        assert modules == ["bar", "baz", "foo"]

    def test_empty_package(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        assert _discover_modules(tmp_path) == []

    def test_missing_package(self, tmp_path):
        assert _discover_modules(tmp_path) == []

    def test_excludes_init(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("# init")
        (pkg / "core.py").write_text("")
        modules = _discover_modules(tmp_path)
        assert "__init__" not in modules
        assert modules == ["core"]

    def test_excludes_pycache_dirs(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "foo.py").write_text("")
        (pkg / "__pycache__").mkdir()
        (pkg / "__pycache__" / "foo.cpython-312.pyc").write_text("")
        modules = _discover_modules(tmp_path)
        assert modules == ["foo"]


# ---------------------------------------------------------------------------
# _discover_tests
# ---------------------------------------------------------------------------


class TestDiscoverTests:
    def test_basic(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("")
        (tests_dir / "test_bar.py").write_text("")
        (tests_dir / "conftest.py").write_text("")
        covered = _discover_tests(tmp_path)
        assert covered == {"foo", "bar"}

    def test_empty(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        assert _discover_tests(tmp_path) == set()

    def test_missing_dir(self, tmp_path):
        assert _discover_tests(tmp_path) == set()

    def test_ignores_non_test_files(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_core.py").write_text("")
        (tests_dir / "helpers.py").write_text("")
        (tests_dir / "conftest.py").write_text("")
        covered = _discover_tests(tmp_path)
        assert covered == {"core"}


# ---------------------------------------------------------------------------
# test_coverage
# ---------------------------------------------------------------------------


class TestTestCoverage:
    def _make_repo(self, tmp_path, modules, tests):
        """Create a minimal repo structure."""
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        for m in modules:
            (pkg / f"{m}.py").write_text(f"# {m}")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        for t in tests:
            (tests_dir / f"test_{t}.py").write_text(f"# test {t}")

    def test_full_coverage(self, tmp_path):
        self._make_repo(tmp_path, ["foo", "bar"], ["foo", "bar"])
        info = module_test_coverage(tmp_path)
        assert info["total_modules"] == 2
        assert len(info["tested"]) == 2
        assert info["untested"] == []
        assert info["coverage_ratio"] == 1.0
        assert info["verdict"] == "solid"

    def test_partial_coverage(self, tmp_path):
        self._make_repo(tmp_path, ["a", "b", "c", "d"], ["a", "b"])
        info = module_test_coverage(tmp_path)
        assert info["total_modules"] == 4
        assert len(info["tested"]) == 2
        assert info["untested"] == ["c", "d"]
        assert info["coverage_ratio"] == 0.5
        assert info["verdict"] == "sparse"

    def test_fair_coverage(self, tmp_path):
        mods = [f"m{i}" for i in range(10)]
        tested = [f"m{i}" for i in range(7)]
        self._make_repo(tmp_path, mods, tested)
        info = module_test_coverage(tmp_path)
        assert info["coverage_ratio"] == 0.7
        assert info["verdict"] == "fair"

    def test_no_modules(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        info = module_test_coverage(tmp_path)
        assert info["total_modules"] == 0
        assert info["coverage_ratio"] == 0.0

    def test_no_repo(self, tmp_path):
        info = module_test_coverage(tmp_path)
        assert info["total_modules"] == 0
        assert info["untested"] == []

    def test_verdict_solid_at_90(self, tmp_path):
        mods = [f"m{i}" for i in range(10)]
        tested = [f"m{i}" for i in range(9)]
        self._make_repo(tmp_path, mods, tested)
        info = module_test_coverage(tmp_path)
        assert info["coverage_ratio"] == 0.9
        assert info["verdict"] == "solid"

    def test_verdict_fair_at_70(self, tmp_path):
        mods = [f"m{i}" for i in range(10)]
        tested = [f"m{i}" for i in range(7)]
        self._make_repo(tmp_path, mods, tested)
        info = module_test_coverage(tmp_path)
        assert info["verdict"] == "fair"

    def test_verdict_sparse_below_70(self, tmp_path):
        mods = [f"m{i}" for i in range(10)]
        tested = [f"m{i}" for i in range(6)]
        self._make_repo(tmp_path, mods, tested)
        info = module_test_coverage(tmp_path)
        assert info["verdict"] == "sparse"


# ---------------------------------------------------------------------------
# coverage_report
# ---------------------------------------------------------------------------


class TestCoverageReport:
    def _make_repo(self, tmp_path, modules, tests):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        for m in modules:
            (pkg / f"{m}.py").write_text(f"# {m}")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        for t in tests:
            (tests_dir / f"test_{t}.py").write_text(f"# test {t}")

    def test_full_report(self, tmp_path):
        self._make_repo(tmp_path, ["foo", "bar"], ["foo", "bar"])
        report = coverage_report(tmp_path)
        assert "solid" in report
        assert "2/2" in report
        assert "100.0%" in report

    def test_partial_report_lists_missing(self, tmp_path):
        self._make_repo(tmp_path, ["alpha", "beta", "gamma"], ["alpha"])
        report = coverage_report(tmp_path)
        assert "sparse" in report
        assert "beta" in report
        assert "gamma" in report

    def test_empty_repo(self, tmp_path):
        report = coverage_report(tmp_path)
        assert "sparse" in report
        assert "0/0" in report

    def test_many_untested_does_not_list_all(self, tmp_path):
        mods = [f"m{i}" for i in range(20)]
        self._make_repo(tmp_path, mods, [])
        report = coverage_report(tmp_path)
        assert "20 untested" in report
        # Should not list all 20 names
        assert "missing:" not in report


# ---------------------------------------------------------------------------
# Live repo smoke test (skipped if not running against the real repo)
# ---------------------------------------------------------------------------


class TestLiveRepo:
    def test_runs_against_real_repo(self):
        repo = Path(__file__).resolve().parent.parent
        if not (repo / "iamai" / "__init__.py").exists():
            pytest.skip("not in real repo")
        info = module_test_coverage(repo)
        assert info["total_modules"] > 50
        assert info["coverage_ratio"] > 0.0
        assert info["verdict"] in ("solid", "fair", "sparse")
