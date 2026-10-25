"""Tests for iamai.doc_coverage."""

from pathlib import Path

import pytest

from iamai.doc_coverage import (
    _discover_documented,
    _discover_modules,
    _discover_tests,
    coverage_report,
    coverage_summary,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_repo(
    tmp_path: Path,
    modules: list[str] | None = None,
    tests: list[str] | None = None,
    notes: dict[str, str] | None = None,
) -> Path:
    """Create a minimal repo structure."""
    iamai_dir = tmp_path / "iamai"
    iamai_dir.mkdir(parents=True, exist_ok=True)
    (iamai_dir / "__init__.py").write_text("", encoding="utf-8")

    for name in (modules or []):
        (iamai_dir / f"{name}.py").write_text(f"# {name}", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    for name in (tests or []):
        (tests_dir / f"test_{name}.py").write_text(f"# test {name}", encoding="utf-8")

    if notes:
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        for fname, body in notes.items():
            (notes_dir / fname).write_text(body, encoding="utf-8")

    return tmp_path


# ---------------------------------------------------------------------------
# _discover_modules
# ---------------------------------------------------------------------------

class TestDiscoverModules:
    def test_empty(self, tmp_path):
        (tmp_path / "iamai").mkdir()
        assert _discover_modules(tmp_path / "iamai") == set()

    def test_finds_modules(self, tmp_path):
        repo = _build_repo(tmp_path, modules=["foo", "bar", "baz"])
        result = _discover_modules(repo / "iamai")
        assert result == {"foo", "bar", "baz"}

    def test_excludes_init(self, tmp_path):
        repo = _build_repo(tmp_path, modules=["foo"])
        (repo / "iamai" / "__init__.py").write_text("", encoding="utf-8")
        result = _discover_modules(repo / "iamai")
        assert "__init__" not in result
        assert result == {"foo"}


# ---------------------------------------------------------------------------
# _discover_tests
# ---------------------------------------------------------------------------

class TestDiscoverTests:
    def test_empty(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        assert _discover_tests(tests_dir) == set()

    def test_finds_tests(self, tmp_path):
        repo = _build_repo(tmp_path, tests=["foo", "bar"])
        result = _discover_tests(repo / "tests")
        assert result == {"foo", "bar"}

    def test_ignores_non_test(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "conftest.py").write_text("", encoding="utf-8")
        (tests_dir / "test_foo.py").write_text("", encoding="utf-8")
        result = _discover_tests(tests_dir)
        assert result == {"foo"}


# ---------------------------------------------------------------------------
# _discover_documented
# ---------------------------------------------------------------------------

class TestDiscoverDocumented:
    def test_no_notes_dir(self, tmp_path):
        assert _discover_documented(tmp_path / "notes") == set()

    def test_empty_notes(self, tmp_path):
        (tmp_path / "notes").mkdir()
        assert _discover_documented(tmp_path / "notes") == set()

    def test_finds_module_reference(self, tmp_path):
        notes = {
            "caretaker-visit-1-2026-10-16.md": "wrote iamai/foo.py module today",
        }
        repo = _build_repo(tmp_path, notes=notes)
        result = _discover_documented(repo / "notes")
        assert "foo" in result

    def test_backtick_format(self, tmp_path):
        notes = {
            "caretaker-visit-2-2026-10-16.md": "added `bar` module with 10 tests",
        }
        repo = _build_repo(tmp_path, notes=notes)
        result = _discover_documented(repo / "notes")
        assert "bar" in result

    def test_module_suffix_format(self, tmp_path):
        notes = {
            "caretaker-visit-3-2026-10-16.md": "new baz module for tracking drift",
        }
        repo = _build_repo(tmp_path, notes=notes)
        result = _discover_documented(repo / "notes")
        assert "baz" in result

    def test_ignores_non_visit_notes(self, tmp_path):
        notes = {
            "some-other-note.md": "iamai/foo.py is great",
        }
        repo = _build_repo(tmp_path, notes=notes)
        result = _discover_documented(repo / "notes")
        assert result == set()


# ---------------------------------------------------------------------------
# coverage_report
# ---------------------------------------------------------------------------

class TestCoverageReport:
    def test_full_coverage(self, tmp_path):
        repo = _build_repo(
            tmp_path,
            modules=["alpha", "beta"],
            tests=["alpha", "beta"],
            notes={
                "caretaker-visit-1-2026-10-16.md": "wrote iamai/alpha.py and `beta` module",
            },
        )
        r = coverage_report(repo)
        assert r["total_modules"] == 2
        assert r["tested_count"] == 2
        assert r["untested_count"] == 0
        assert r["test_coverage"] == 1.0
        assert r["doc_coverage"] == 1.0
        assert r["untested"] == []
        assert r["undocumented"] == []

    def test_partial_test_coverage(self, tmp_path):
        repo = _build_repo(
            tmp_path,
            modules=["alpha", "beta", "gamma"],
            tests=["alpha"],
        )
        r = coverage_report(repo)
        assert r["total_modules"] == 3
        assert r["tested_count"] == 1
        assert r["untested_count"] == 2
        assert r["test_coverage"] == pytest.approx(1 / 3, rel=1e-3)
        assert r["untested"] == ["beta", "gamma"]

    def test_no_modules(self, tmp_path):
        repo = _build_repo(tmp_path)
        r = coverage_report(repo)
        assert r["total_modules"] == 0
        assert r["test_coverage"] == 0.0
        assert r["doc_coverage"] == 0.0

    def test_test_not_matching_module(self, tmp_path):
        """Tests for non-existent modules are ignored."""
        repo = _build_repo(
            tmp_path,
            modules=["alpha"],
            tests=["alpha", "nonexistent"],
        )
        r = coverage_report(repo)
        assert r["tested_count"] == 1
        assert r["test_coverage"] == 1.0

    def test_sorted_output(self, tmp_path):
        repo = _build_repo(
            tmp_path,
            modules=["zebra", "apple", "mango"],
            tests=[],
        )
        r = coverage_report(repo)
        assert r["untested"] == ["apple", "mango", "zebra"]

    def test_doc_coverage_partial(self, tmp_path):
        repo = _build_repo(
            tmp_path,
            modules=["alpha", "beta"],
            notes={
                "caretaker-visit-1-2026-10-16.md": "wrote `alpha` module",
            },
        )
        r = coverage_report(repo)
        assert r["documented_count"] == 1
        assert r["undocumented_count"] == 1
        assert r["doc_coverage"] == 0.5
        assert r["undocumented"] == ["beta"]


# ---------------------------------------------------------------------------
# coverage_summary
# ---------------------------------------------------------------------------

class TestCoverageSummary:
    def test_format(self, tmp_path):
        repo = _build_repo(
            tmp_path,
            modules=["a", "b"],
            tests=["a", "b"],
            notes={
                "caretaker-visit-1-2026-10-16.md": "iamai/a.py and iamai/b.py",
            },
        )
        s = coverage_summary(repo)
        assert "2/2 tested" in s
        assert "100%" in s
        assert "2/2 documented" in s

    def test_zero_modules(self, tmp_path):
        repo = _build_repo(tmp_path)
        s = coverage_summary(repo)
        assert "0/0" in s
