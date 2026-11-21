"""Tests for iamai.file_coupling — file co-change analysis."""

from __future__ import annotations

import pytest

from iamai.file_coupling import (
    CoChangeEvent,
    CouplingResult,
    _area,
    _normalize_edge,
    classify_coupling,
    compute_coupling,
    coupling_report,
)


# ---------------------------------------------------------------------------
# _area
# ---------------------------------------------------------------------------


class TestArea:
    def test_nested_file(self):
        assert _area("iamai/foo.py") == "iamai"

    def test_root_file(self):
        assert _area("README.md") == "."

    def test_deeply_nested(self):
        assert _area("iamai/sub/deep.py") == "iamai"

    def test_backslash_path(self):
        assert _area("iamai\\foo.py") == "iamai"


# ---------------------------------------------------------------------------
# _normalize_edge
# ---------------------------------------------------------------------------


class TestNormalizeEdge:
    def test_already_sorted(self):
        assert _normalize_edge("a", "b") == ("a", "b")

    def test_reverse_order(self):
        assert _normalize_edge("z", "a") == ("a", "z")

    def test_same_string(self):
        assert _normalize_edge("x", "x") == ("x", "x")


# ---------------------------------------------------------------------------
# CoChangeEvent
# ---------------------------------------------------------------------------


class TestCoChangeEvent:
    def test_auto_sort(self):
        ev = CoChangeEvent(file_a="z.py", file_b="a.py", commit_count=5)
        assert ev.file_a == "a.py"
        assert ev.file_b == "z.py"

    def test_already_sorted(self):
        ev = CoChangeEvent(file_a="a.py", file_b="b.py", commit_count=1)
        assert ev.file_a == "a.py"
        assert ev.file_b == "b.py"


# ---------------------------------------------------------------------------
# compute_coupling — basic cases
# ---------------------------------------------------------------------------


class TestComputeCouplingBasic:
    def test_empty_commits(self):
        result = compute_coupling([])
        assert result.total_commits == 0
        assert result.coupling_score == 0.0
        assert result.coupling_class == "modular"
        assert result.hot_edges == []

    def test_single_file_commits(self):
        commits = [
            {"files": ["iamai/a.py"]},
            {"files": ["tests/test_a.py"]},
        ]
        result = compute_coupling(commits)
        assert result.total_commits == 2
        assert result.coupling_score == 0.0
        assert result.cross_area_fraction == 0.0

    def test_same_area_pair(self):
        commits = [
            {"files": ["iamai/a.py", "iamai/b.py"]},
        ]
        result = compute_coupling(commits)
        assert result.total_commits == 1
        assert result.cross_area_fraction == 0.0
        assert len(result.hot_edges) == 1
        assert result.hot_edges[0].file_a == "iamai/a.py"
        assert result.hot_edges[0].file_b == "iamai/b.py"

    def test_cross_area_pair(self):
        commits = [
            {"files": ["iamai/a.py", "tests/test_a.py"]},
        ]
        result = compute_coupling(commits)
        assert result.total_commits == 1
        assert result.cross_area_fraction == 1.0
        assert result.coupling_class == "tight"


# ---------------------------------------------------------------------------
# compute_coupling — coupling score
# ---------------------------------------------------------------------------


class TestCouplingScore:
    def test_all_cross_area(self):
        commits = [
            {"files": ["iamai/a.py", "tests/test_a.py"]},
            {"files": ["iamai/b.py", "tests/test_b.py"]},
        ]
        result = compute_coupling(commits)
        assert result.coupling_score == 1.0
        assert result.coupling_class == "tight"

    def test_half_cross_area(self):
        commits = [
            {"files": ["iamai/a.py", "tests/test_a.py"]},
            {"files": ["iamai/b.py", "iamai/c.py"]},
        ]
        result = compute_coupling(commits)
        assert result.coupling_score == 0.5
        assert result.coupling_class == "moderate"

    def test_low_cross_area(self):
        commits = [
            {"files": ["iamai/a.py", "iamai/b.py"]},
            {"files": ["iamai/c.py", "iamai/d.py"]},
            {"files": ["iamai/e.py", "iamai/f.py"]},
            {"files": ["iamai/g.py", "iamai/h.py"]},
            {"files": ["iamai/i.py", "tests/test_i.py"]},
        ]
        result = compute_coupling(commits)
        assert result.coupling_score == 0.2
        assert result.coupling_class == "loose"


# ---------------------------------------------------------------------------
# compute_coupling — hot edges
# ---------------------------------------------------------------------------


class TestHotEdges:
    def test_edge_counting(self):
        commits = [
            {"files": ["iamai/a.py", "tests/test_a.py"]},
            {"files": ["iamai/a.py", "tests/test_a.py"]},
            {"files": ["iamai/b.py", "tests/test_b.py"]},
        ]
        result = compute_coupling(commits)
        assert result.hot_edges[0].commit_count == 2
        assert result.hot_edges[0].file_a == "iamai/a.py"

    def test_top_n_limit(self):
        # Create 15 unique edges
        commits = [
            {"files": [f"iamai/{i}.py", f"tests/test_{i}.py"]}
            for i in range(15)
        ]
        result = compute_coupling(commits, top_n=5)
        assert len(result.hot_edges) == 5

    def test_duplicate_files_in_commit(self):
        """Duplicate paths in a commit should be deduplicated."""
        commits = [
            {"files": ["iamai/a.py", "iamai/a.py", "tests/test_a.py"]},
        ]
        result = compute_coupling(commits)
        assert len(result.hot_edges) == 1


# ---------------------------------------------------------------------------
# compute_coupling — dispersion index
# ---------------------------------------------------------------------------


class TestDispersionIndex:
    def test_single_area_commits(self):
        commits = [
            {"files": ["iamai/a.py", "iamai/b.py"]},
            {"files": ["iamai/c.py"]},
        ]
        result = compute_coupling(commits)
        assert result.dispersion_index == 1.0

    def test_two_area_commits(self):
        commits = [
            {"files": ["iamai/a.py", "tests/test_a.py"]},
            {"files": ["iamai/b.py", "tests/test_b.py"]},
        ]
        result = compute_coupling(commits)
        assert result.dispersion_index == 2.0


# ---------------------------------------------------------------------------
# compute_coupling — area cohesion
# ---------------------------------------------------------------------------


class TestAreaCohesion:
    def test_pure_area(self):
        """An area that only changes with itself has cohesion 1.0."""
        commits = [
            {"files": ["iamai/a.py", "iamai/b.py"]},
            {"files": ["iamai/c.py", "iamai/d.py"]},
        ]
        result = compute_coupling(commits)
        assert result.area_cohesion["iamai"] == 1.0

    def test_mixed_area(self):
        """An area that sometimes crosses boundaries."""
        commits = [
            {"files": ["iamai/a.py", "iamai/b.py"]},
            {"files": ["iamai/a.py", "tests/test_a.py"]},
        ]
        result = compute_coupling(commits)
        # iamai touched in 2 commits: 1 intra, 1 inter → cohesion 0.5
        assert result.area_cohesion["iamai"] == 0.5

    def test_always_crossing(self):
        """An area that always appears in cross-area commits."""
        commits = [
            {"files": ["tests/test_a.py", "iamai/a.py"]},
            {"files": ["tests/test_b.py", "iamai/b.py"]},
        ]
        result = compute_coupling(commits)
        assert result.area_cohesion["tests"] == 0.0


# ---------------------------------------------------------------------------
# classify_coupling
# ---------------------------------------------------------------------------


class TestClassifyCoupling:
    def test_tight(self):
        assert classify_coupling(0.80) == "tight"
        assert classify_coupling(1.0) == "tight"

    def test_moderate(self):
        assert classify_coupling(0.50) == "moderate"
        assert classify_coupling(0.79) == "moderate"

    def test_loose(self):
        assert classify_coupling(0.20) == "loose"
        assert classify_coupling(0.49) == "loose"

    def test_modular(self):
        assert classify_coupling(0.0) == "modular"
        assert classify_coupling(0.19) == "modular"


# ---------------------------------------------------------------------------
# CouplingResult.is_modular
# ---------------------------------------------------------------------------


class TestCouplingResultIsModular:
    def test_modular_is_modular(self):
        commits = [{"files": ["iamai/a.py", "iamai/b.py"]}]
        result = compute_coupling(commits)
        assert result.is_modular is True

    def test_tight_is_not_modular(self):
        commits = [{"files": ["iamai/a.py", "tests/test_a.py"]}]
        result = compute_coupling(commits)
        assert result.is_modular is False


# ---------------------------------------------------------------------------
# coupling_report
# ---------------------------------------------------------------------------


class TestCouplingReport:
    def test_report_contains_key_fields(self):
        commits = [
            {"files": ["iamai/a.py", "tests/test_a.py"]},
            {"files": ["iamai/b.py", "iamai/c.py"]},
        ]
        result = compute_coupling(commits)
        report = coupling_report(result)
        assert "file coupling:" in report
        assert "moderate" in report
        assert "hot edges:" in report
        assert "area cohesion:" in report

    def test_empty_report(self):
        result = compute_coupling([])
        report = coupling_report(result)
        assert "modular" in report
        assert "commits analyzed: 0" in report


# ---------------------------------------------------------------------------
# Custom area function
# ---------------------------------------------------------------------------


class TestCustomAreaFn:
    def test_custom_area_extraction(self):
        """User can provide their own area function."""
        commits = [
            {"files": ["src/auth/login.py", "src/auth/logout.py"]},
            {"files": ["src/auth/login.py", "src/billing/invoice.py"]},
        ]
        result = compute_coupling(
            commits,
            area_fn=lambda p: "/".join(p.split("/")[:2]),
        )
        assert "src/auth" in result.area_cohesion
        assert "src/billing" in result.area_cohesion
        assert result.cross_area_fraction == 0.5
