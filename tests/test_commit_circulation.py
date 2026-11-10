#!/usr/bin/env python3
"""Tests for commit_circulation.py — codebase circulation measurement."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_circulation as cc


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _c(sha="x", files=None):
    """Shorthand factory for CirculationCommit."""
    return cc.CirculationCommit(
        sha=sha,
        files=set(files or []),
    )


# ---------------------------------------------------------------------------
# classify_circulation
# ---------------------------------------------------------------------------

class TestClassifyCirculation:
    def test_interconnected_at_boundary(self):
        assert cc.classify_circulation(0.80) == "interconnected"

    def test_interconnected_high(self):
        assert cc.classify_circulation(0.95) == "interconnected"

    def test_interconnected_at_one(self):
        assert cc.classify_circulation(1.0) == "interconnected"

    def test_flowing_lower(self):
        assert cc.classify_circulation(0.60) == "flowing"

    def test_flowing_upper(self):
        assert cc.classify_circulation(0.79) == "flowing"

    def test_adequate_lower(self):
        assert cc.classify_circulation(0.40) == "adequate"

    def test_adequate_upper(self):
        assert cc.classify_circulation(0.55) == "adequate"

    def test_siloed_lower(self):
        assert cc.classify_circulation(0.20) == "siloed"

    def test_siloed_upper(self):
        assert cc.classify_circulation(0.35) == "siloed"

    def test_isolated_at_zero(self):
        assert cc.classify_circulation(0.0) == "isolated"

    def test_isolated_low(self):
        assert cc.classify_circulation(0.10) == "isolated"

    def test_isolated_below_boundary(self):
        assert cc.classify_circulation(0.19) == "isolated"


# ---------------------------------------------------------------------------
# _extract_area
# ---------------------------------------------------------------------------

class TestExtractArea:
    def test_root_file(self):
        assert cc._extract_area("README.md") == "."

    def test_single_dir(self):
        assert cc._extract_area("iamai/foo.py") == "iamai"

    def test_nested_dir(self):
        assert cc._extract_area("tests/unit/test_foo.py") == "tests"

    def test_deep_path(self):
        assert cc._extract_area("a/b/c/d.py") == "a"


# ---------------------------------------------------------------------------
# _commit_areas
# ---------------------------------------------------------------------------

class TestCommitAreas:
    def test_single_area(self):
        c = _c(files={"iamai/foo.py", "iamai/bar.py"})
        assert cc._commit_areas(c) == frozenset({"iamai"})

    def test_multi_area(self):
        c = _c(files={"iamai/foo.py", "tests/test_foo.py"})
        assert cc._commit_areas(c) == frozenset({"iamai", "tests"})

    def test_root_and_dir(self):
        c = _c(files={"README.md", "iamai/foo.py"})
        assert cc._commit_areas(c) == frozenset({".", "iamai"})

    def test_empty(self):
        c = _c(files=set())
        assert cc._commit_areas(c) == frozenset()


# ---------------------------------------------------------------------------
# _compute_cross_area_ratio
# ---------------------------------------------------------------------------

class TestCrossAreaRatio:
    def test_all_single_area(self):
        """Every commit touches only one area."""
        commits = [
            _c(files={"iamai/a.py"}),
            _c(files={"iamai/b.py"}),
            _c(files={"tests/test_a.py"}),
        ]
        assert cc._compute_cross_area_ratio(commits) == 0.0

    def test_all_cross_area(self):
        """Every commit touches multiple areas."""
        commits = [
            _c(files={"iamai/a.py", "tests/test_a.py"}),
            _c(files={"iamai/b.py", "docs/B.md"}),
        ]
        assert cc._compute_cross_area_ratio(commits) == 1.0

    def test_mixed(self):
        commits = [
            _c(files={"iamai/a.py", "tests/test_a.py"}),  # cross
            _c(files={"iamai/b.py"}),                       # single
        ]
        assert cc._compute_cross_area_ratio(commits) == pytest.approx(0.5)

    def test_empty(self):
        assert cc._compute_cross_area_ratio([]) == 0.0

    def test_empty_commits(self):
        commits = [_c(files=set()), _c(files=set())]
        assert cc._compute_cross_area_ratio(commits) == 0.0


# ---------------------------------------------------------------------------
# _jaccard
# ---------------------------------------------------------------------------

class TestJaccard:
    def test_identical(self):
        assert cc._jaccard(frozenset({"a", "b"}), frozenset({"a", "b"})) == 1.0

    def test_disjoint(self):
        assert cc._jaccard(frozenset({"a"}), frozenset({"b"})) == 0.0

    def test_partial(self):
        assert cc._jaccard(
            frozenset({"a", "b"}), frozenset({"b", "c"})
        ) == pytest.approx(1.0 / 3)

    def test_both_empty(self):
        assert cc._jaccard(frozenset(), frozenset()) == 0.0

    def test_one_empty(self):
        assert cc._jaccard(frozenset({"a"}), frozenset()) == 0.0


# ---------------------------------------------------------------------------
# _compute_area_coupling
# ---------------------------------------------------------------------------

class TestAreaCoupling:
    def test_single_commit(self):
        """Need ≥ 2 commits to measure coupling."""
        assert cc._compute_area_coupling([_c(files={"iamai/a.py"})]) == 0.0

    def test_identical_consecutive(self):
        """Each commit touches the same areas as the previous."""
        commits = [
            _c(files={"iamai/a.py", "tests/test_a.py"}),
            _c(files={"iamai/b.py", "tests/test_b.py"}),
            _c(files={"iamai/c.py", "tests/test_c.py"}),
        ]
        # Every consecutive pair: areas {iamai, tests} ∩ {iamai, tests}
        # Jaccard = 1.0 each time
        assert cc._compute_area_coupling(commits) == 1.0

    def test_disjoint_consecutive(self):
        """Each commit explores completely different areas."""
        commits = [
            _c(files={"iamai/a.py"}),
            _c(files={"tests/test_a.py"}),
            _c(files={"docs/A.md"}),
        ]
        # Every consecutive pair has Jaccard = 0.0
        assert cc._compute_area_coupling(commits) == 0.0

    def test_empty(self):
        assert cc._compute_area_coupling([]) == 0.0

    def test_partial_overlap(self):
        commits = [
            _c(files={"iamai/a.py", "tests/test_a.py"}),
            _c(files={"iamai/b.py"}),  # only iamai overlaps
        ]
        # prev={iamai,tests}, curr={iamai}, Jaccard = 1/2
        assert cc._compute_area_coupling(commits) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _compute_reach_breadth
# ---------------------------------------------------------------------------

class TestReachBreadth:
    def test_all_shared(self):
        """Every area is touched by multiple commits."""
        commits = [
            _c(files={"iamai/a.py"}),
            _c(files={"iamai/b.py"}),
        ]
        # area "iamai" touched by 2 commits → shared = 1/1 = 1.0
        assert cc._compute_reach_breadth(commits) == 1.0

    def test_all_one_off(self):
        """Every area is touched by exactly one commit."""
        commits = [
            _c(files={"iamai/a.py"}),
            _c(files={"tests/test_a.py"}),
            _c(files={"docs/A.md"}),
        ]
        # No area shared → 0/3 = 0.0
        assert cc._compute_reach_breadth(commits) == 0.0

    def test_mixed(self):
        commits = [
            _c(files={"iamai/a.py"}),
            _c(files={"iamai/b.py"}),
            _c(files={"tests/test_a.py"}),
        ]
        # iamai shared (2 commits), tests one-off → 1/2 = 0.5
        assert cc._compute_reach_breadth(commits) == pytest.approx(0.5)

    def test_empty(self):
        assert cc._compute_reach_breadth([]) == 0.0


# ---------------------------------------------------------------------------
# compute_reach_breadth_with_universe
# ---------------------------------------------------------------------------

class TestReachBreadthWithUniverse:
    def test_full_reach(self):
        commits = [
            _c(files={"iamai/a.py", "tests/test_a.py"}),
        ]
        universe = {"iamai", "tests"}
        assert cc.compute_reach_breadth_with_universe(commits, universe) == 1.0

    def test_partial_reach(self):
        commits = [_c(files={"iamai/a.py"})]
        universe = {"iamai", "tests", "docs"}
        assert cc.compute_reach_breadth_with_universe(
            commits, universe
        ) == pytest.approx(1.0 / 3)

    def test_empty_universe(self):
        assert cc.compute_reach_breadth_with_universe(
            [_c(files={"a.py"})], set()
        ) == 0.0

    def test_empty_commits(self):
        assert cc.compute_reach_breadth_with_universe(
            [], {"iamai"}
        ) == 0.0


# ---------------------------------------------------------------------------
# _compute_bridge_commit_ratio
# ---------------------------------------------------------------------------

class TestBridgeCommitRatio:
    def test_first_commit_is_bridge(self):
        """First commit with ≥ 2 areas always bridges new pairs."""
        commits = [
            _c(files={"iamai/a.py", "tests/test_a.py"}),
        ]
        assert cc._compute_bridge_commit_ratio(commits) == 1.0

    def test_no_new_bridges(self):
        """Subsequent commits only repeat known pairs."""
        commits = [
            _c(files={"iamai/a.py", "tests/test_a.py"}),
            _c(files={"iamai/b.py", "tests/test_b.py"}),  # same pair
        ]
        # second commit: pair (iamai, tests) already known → not a bridge
        # first commit: 1 bridge. total = 1/2 = 0.5
        assert cc._compute_bridge_commit_ratio(commits) == pytest.approx(0.5)

    def test_every_commit_bridges(self):
        """Each commit introduces a new area pair."""
        commits = [
            _c(files={"iamai/a.py", "tests/test_a.py"}),   # (iamai,tests)
            _c(files={"iamai/b.py", "docs/B.md"}),          # (iamai,docs)
            _c(files={"tests/t.py", "docs/D.md"}),          # (docs,tests)
        ]
        assert cc._compute_bridge_commit_ratio(commits) == 1.0

    def test_single_area_commits(self):
        """Single-area commits can never bridge."""
        commits = [
            _c(files={"iamai/a.py"}),
            _c(files={"iamai/b.py"}),
        ]
        assert cc._compute_bridge_commit_ratio(commits) == 0.0

    def test_empty(self):
        assert cc._compute_bridge_commit_ratio([]) == 0.0


# ---------------------------------------------------------------------------
# compute_circulation
# ---------------------------------------------------------------------------

class TestComputeCirculation:
    def test_empty(self):
        r = cc.compute_circulation([])
        assert r.circulation_score == 0.0
        assert r.circulation_class == "isolated"
        assert r.commit_count == 0

    def test_strong_circulation(self):
        """Commits that heavily cross area boundaries."""
        commits = [
            _c(files={"iamai/foo.py", "tests/test_foo.py"}),
            _c(files={"iamai/bar.py", "tests/test_bar.py", "docs/BAR.md"}),
            _c(files={"iamai/foo.py", "iamai/bar.py",
                      "tests/test_foo.py", "docs/FOO.md"}),
            _c(files={"iamai/baz.py", "tests/test_baz.py",
                      "docs/BAZ.md", "README.md"}),
        ]
        r = cc.compute_circulation(commits)
        assert r.circulation_class in ("interconnected", "flowing")
        assert r.circulation_score >= 0.55
        assert r.commit_count == 4

    def test_weak_circulation(self):
        """Every commit stays within its own area."""
        commits = [
            _c(files={"iamai/a.py"}),
            _c(files={"tests/test_a.py"}),
            _c(files={"docs/A.md"}),
            _c(files={"scripts/run.py"}),
        ]
        r = cc.compute_circulation(commits)
        assert r.circulation_class in ("isolated", "siloed")
        assert r.cross_area_ratio == 0.0

    def test_score_in_range(self):
        """Score is always in [0, 1]."""
        commits = [
            _c(files={"iamai/a.py", "tests/test_a.py"}),
            _c(files={"iamai/b.py"}),
            _c(files={"docs/A.md", "iamai/c.py"}),
        ]
        r = cc.compute_circulation(commits)
        assert 0.0 <= r.circulation_score <= 1.0

    def test_area_count(self):
        commits = [
            _c(files={"iamai/a.py", "tests/test_a.py"}),
            _c(files={"docs/A.md"}),
        ]
        r = cc.compute_circulation(commits)
        assert r.area_count == 3
        assert r.areas == {"iamai", "tests", "docs"}

    def test_single_commit_multi_area(self):
        commits = [_c(files={"iamai/a.py", "tests/test_a.py", "docs/A.md"})]
        r = cc.compute_circulation(commits)
        assert r.cross_area_ratio == 1.0
        assert r.bridge_commit_ratio == 1.0
        assert r.area_count == 3


# ---------------------------------------------------------------------------
# circulation_trend
# ---------------------------------------------------------------------------

class TestCirculationTrend:
    def test_empty(self):
        t = cc.circulation_trend([])
        assert t.scores == []
        assert t.trend == "stable"

    def test_improving(self):
        t = cc.circulation_trend([
            cc.CirculationResult(circulation_score=0.2),
            cc.CirculationResult(circulation_score=0.4),
            cc.CirculationResult(circulation_score=0.6),
            cc.CirculationResult(circulation_score=0.8),
        ])
        assert t.trend == "improving"
        assert t.slope > 0

    def test_fragmenting(self):
        t = cc.circulation_trend([
            cc.CirculationResult(circulation_score=0.8),
            cc.CirculationResult(circulation_score=0.6),
            cc.CirculationResult(circulation_score=0.4),
            cc.CirculationResult(circulation_score=0.2),
        ])
        assert t.trend == "fragmenting"
        assert t.slope < 0

    def test_stable(self):
        t = cc.circulation_trend([
            cc.CirculationResult(circulation_score=0.50),
            cc.CirculationResult(circulation_score=0.51),
            cc.CirculationResult(circulation_score=0.50),
        ])
        assert t.trend == "stable"
        assert abs(t.slope) < 0.02

    def test_single_result(self):
        t = cc.circulation_trend([
            cc.CirculationResult(circulation_score=0.6)
        ])
        assert len(t.scores) == 1
        assert t.slope == 0.0

    def test_stddev_zero_when_identical(self):
        t = cc.circulation_trend([
            cc.CirculationResult(circulation_score=0.5),
            cc.CirculationResult(circulation_score=0.5),
            cc.CirculationResult(circulation_score=0.5),
        ])
        assert t.stddev == 0.0


# ---------------------------------------------------------------------------
# circulation_report
# ---------------------------------------------------------------------------

class TestCirculationReport:
    def test_report_contains_key_info(self):
        r = cc.compute_circulation([
            _c(files={"iamai/a.py", "tests/test_a.py"}),
            _c(files={"iamai/b.py"}),
        ])
        report = cc.circulation_report(r)
        assert r.circulation_class in report
        assert f"{r.circulation_score:.2f}" in report
        assert "cross-area ratio" in report
        assert "area coupling" in report

    def test_report_non_empty(self):
        r = cc.compute_circulation([_c(files={"iamai/a.py"})])
        report = cc.circulation_report(r)
        assert len(report) > 50

    def test_report_lists_areas(self):
        r = cc.compute_circulation([
            _c(files={"iamai/a.py", "tests/test_a.py", "docs/A.md"}),
        ])
        report = cc.circulation_report(r)
        assert "docs" in report
        assert "iamai" in report
        assert "tests" in report


# ---------------------------------------------------------------------------
# trend_report
# ---------------------------------------------------------------------------

class TestTrendReport:
    def test_empty_trend(self):
        t = cc.CirculationTrend()
        report = cc.trend_report(t)
        assert "No circulation data" in report

    def test_report_contains_info(self):
        t = cc.circulation_trend([
            cc.CirculationResult(circulation_score=0.3),
            cc.CirculationResult(circulation_score=0.5),
            cc.CirculationResult(circulation_score=0.7),
        ])
        report = cc.trend_report(t)
        assert "improving" in report
        assert "windows analysed : 3" in report


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_commit_with_no_files(self):
        commits = [_c(files=set()), _c(files=set())]
        r = cc.compute_circulation(commits)
        assert r.area_count == 0
        assert r.cross_area_ratio == 0.0

    def test_mixed_empty_and_full(self):
        commits = [
            _c(files=set()),
            _c(files={"iamai/a.py", "tests/test_a.py"}),
        ]
        r = cc.compute_circulation(commits)
        assert r.area_count == 2
        assert r.commit_count == 2

    def test_many_commits_single_area(self):
        """All work in one area = isolated."""
        commits = [
            _c(files={f"iamai/module_{i}.py"}) for i in range(20)
        ]
        r = cc.compute_circulation(commits)
        assert r.area_count == 1
        assert r.cross_area_ratio == 0.0
        assert r.bridge_commit_ratio == 0.0

    def test_large_history(self):
        """Scale test with many commits and areas."""
        areas = ["iamai", "tests", "docs", "scripts", "tools"]
        commits = []
        for i in range(30):
            a1 = areas[i % len(areas)]
            a2 = areas[(i + 1) % len(areas)]
            files = {f"{a1}/file_{i}.py", f"{a2}/file_{i}.py"}
            commits.append(_c(sha=f"c{i}", files=files))
        r = cc.compute_circulation(commits)
        assert r.area_count == 5
        assert r.commit_count == 30
        assert 0.0 <= r.circulation_score <= 1.0

    def test_score_boundary_interconnected(self):
        assert cc.classify_circulation(0.80) == "interconnected"
        assert cc.classify_circulation(0.799) == "flowing"

    def test_score_boundary_isolated(self):
        assert cc.classify_circulation(0.199) == "isolated"
        assert cc.classify_circulation(0.20) == "siloed"

    def test_all_root_files(self):
        """Root-level files all map to area '.'."""
        commits = [
            _c(files={"README.md", "LICENSE", "Makefile"}),
        ]
        r = cc.compute_circulation(commits)
        assert r.area_count == 1
        assert r.areas == {"."}
