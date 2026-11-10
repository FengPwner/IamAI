#!/usr/bin/env python3
"""Tests for commit_conductivity.py — codebase change transport efficiency analysis."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_conductivity as cc

# ---------------------------------------------------------------------------
# Reference time
# ---------------------------------------------------------------------------
REF = datetime(2026, 11, 11, 0, 0, 0)  # Wed 2026-11-11 00:00 UTC


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _commit(sha, hours_after, files, tests=None, dependents=None):
    """Create a CommitRecord at REF + hours_after."""
    return cc.CommitRecord(
        sha=sha,
        timestamp=REF + timedelta(hours=hours_after),
        files=frozenset(files),
        tests=frozenset(tests or []),
        dependents=frozenset(dependents or []),
    )


def _sequence(n, hours_step=1, files_fn=None, tests_fn=None, dependents_fn=None):
    """Generate n commits spaced hours_step apart."""
    if files_fn is None:
        files_fn = lambda i: frozenset([f"iamai/mod_{i % 5}.py"])
    if tests_fn is None:
        tests_fn = lambda i: frozenset()
    if dependents_fn is None:
        dependents_fn = lambda i: frozenset()
    return [
        cc.CommitRecord(
            sha=f"c{i}",
            timestamp=REF + timedelta(hours=i * hours_step),
            files=files_fn(i),
            tests=tests_fn(i),
            dependents=dependents_fn(i),
        )
        for i in range(n)
    ]


# ===========================================================================
# CommitRecord
# ===========================================================================

class TestCommitRecord:
    def test_basic_creation(self):
        c = cc.CommitRecord(
            sha="abc123",
            timestamp=REF,
            files=frozenset(["a.py"]),
            tests=frozenset(["tests/test_a.py"]),
            dependents=frozenset(["b.py"]),
        )
        assert c.sha == "abc123"
        assert c.files == frozenset(["a.py"])
        assert c.tests == frozenset(["tests/test_a.py"])
        assert c.dependents == frozenset(["b.py"])

    def test_default_empty_frozensets(self):
        c = cc.CommitRecord(sha="x", timestamp=REF)
        assert c.files == frozenset()
        assert c.tests == frozenset()
        assert c.dependents == frozenset()

    def test_auto_convert_list_to_frozenset(self):
        c = cc.CommitRecord(
            sha="x",
            timestamp=REF,
            files=["a.py", "b.py"],
            tests=["tests/test_a.py"],
            dependents=["c.py"],
        )
        assert isinstance(c.files, frozenset)
        assert isinstance(c.tests, frozenset)
        assert isinstance(c.dependents, frozenset)
        assert "a.py" in c.files
        assert "c.py" in c.dependents

    def test_frozen(self):
        c = cc.CommitRecord(sha="x", timestamp=REF)
        with pytest.raises(AttributeError):
            c.sha = "y"

    def test_auto_convert_set_to_frozenset(self):
        c = cc.CommitRecord(
            sha="x",
            timestamp=REF,
            files={"a.py"},
            tests={"tests/test_a.py"},
            dependents={"c.py"},
        )
        assert isinstance(c.files, frozenset)
        assert isinstance(c.tests, frozenset)
        assert isinstance(c.dependents, frozenset)


# ===========================================================================
# Classification
# ===========================================================================

class TestClassifyConductivity:
    def test_superconductor(self):
        assert cc.classify_conductivity(0.80) == "superconductor"
        assert cc.classify_conductivity(0.95) == "superconductor"
        assert cc.classify_conductivity(1.00) == "superconductor"

    def test_conductive(self):
        assert cc.classify_conductivity(0.60) == "conductive"
        assert cc.classify_conductivity(0.70) == "conductive"
        assert cc.classify_conductivity(0.79) == "conductive"

    def test_resistive(self):
        assert cc.classify_conductivity(0.40) == "resistive"
        assert cc.classify_conductivity(0.50) == "resistive"
        assert cc.classify_conductivity(0.59) == "resistive"

    def test_insulating(self):
        assert cc.classify_conductivity(0.20) == "insulating"
        assert cc.classify_conductivity(0.30) == "insulating"
        assert cc.classify_conductivity(0.39) == "insulating"

    def test_dielectric(self):
        assert cc.classify_conductivity(0.00) == "dielectric"
        assert cc.classify_conductivity(0.10) == "dielectric"
        assert cc.classify_conductivity(0.19) == "dielectric"

    def test_boundary_values(self):
        """Exact boundary values go to the higher class."""
        assert cc.classify_conductivity(0.80) == "superconductor"
        assert cc.classify_conductivity(0.60) == "conductive"
        assert cc.classify_conductivity(0.40) == "resistive"
        assert cc.classify_conductivity(0.20) == "insulating"


# ===========================================================================
# Helper functions
# ===========================================================================

class TestHelpers:
    def test_is_test_file_by_directory(self):
        assert cc._is_test_file("tests/test_foo.py") is True
        assert cc._is_test_file("test/test_bar.py") is True
        assert cc._is_test_file("iamai/foo.py") is False

    def test_is_test_file_by_name(self):
        assert cc._is_test_file("test_foo.py") is True
        assert cc._is_test_file("foo_test.py") is True
        assert cc._is_test_file("foo.py") is False

    def test_is_test_file_case_insensitive(self):
        assert cc._is_test_file("Tests/test_foo.py") is True
        assert cc._is_test_file("TEST/test_bar.py") is True

    def test_source_to_test_key(self):
        assert cc._source_to_test_key("iamai/module_a.py") == "module_a"
        assert cc._source_to_test_key("tools/foo_bar.py") == "foo_bar"
        assert cc._source_to_test_key("simple.py") == "simple"

    def test_test_to_source_key(self):
        assert cc._test_to_source_key("tests/test_module_a.py") == "module_a"
        assert cc._test_to_source_key("tests/test_foo_bar.py") == "foo_bar"
        assert cc._test_to_source_key("test_something.py") == "something"


# ===========================================================================
# Core computation — edge cases
# ===========================================================================

class TestComputeConductivityEdgeCases:
    def test_empty_commits(self):
        r = cc.compute_conductivity([])
        assert r.window_commits == 0
        assert r.conductivity_class == "dielectric"
        assert r.conductivity_score == 0.0

    def test_single_commit(self):
        r = cc.compute_conductivity([
            _commit("c0", 0, ["a.py"], ["tests/test_a.py"], ["b.py"])
        ])
        assert r.window_commits == 1
        assert r.conductivity_class == "dielectric"

    def test_two_commits_no_deps(self):
        """Two commits with no dependency relationships."""
        commits = [
            _commit("c0", 0, ["a.py"]),
            _commit("c1", 1, ["b.py"]),
        ]
        r = cc.compute_conductivity(commits)
        assert r.window_commits == 2
        assert r.pathway_efficiency == 1.0  # no deps = trivially efficient
        assert r.bottleneck_ratio == 0.0


# ===========================================================================
# Core computation — pathway efficiency
# ===========================================================================

class TestPathwayEfficiency:
    def test_perfect_pathway(self):
        """Every dependent is updated in the same or next commit."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"], dependents=["iamai/app.py"]),
            _commit("c1", 1, ["iamai/app.py"], dependents=[]),
            _commit("c2", 2, ["iamai/core.py"], dependents=["iamai/app.py"]),
            _commit("c3", 3, ["iamai/app.py"], dependents=[]),
        ]
        r = cc.compute_conductivity(commits)
        assert r.pathway_efficiency == 1.0

    def test_zero_pathway(self):
        """Dependents never get updated when their dependency changes."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"], dependents=["iamai/app.py"]),
            _commit("c1", 1, ["iamai/other.py"]),
            _commit("c2", 2, ["iamai/core.py"], dependents=["iamai/app.py"]),
            _commit("c3", 3, ["iamai/other.py"]),
        ]
        r = cc.compute_conductivity(commits)
        assert r.pathway_efficiency == 0.0

    def test_partial_pathway(self):
        """Some dependents update, some don't."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"],
                    dependents=["iamai/app.py", "iamai/cli.py"]),
            _commit("c1", 1, ["iamai/app.py"]),  # only one dep updated
            _commit("c2", 2, ["iamai/core.py"],
                    dependents=["iamai/app.py", "iamai/cli.py"]),
            _commit("c3", 3, ["iamai/app.py", "iamai/cli.py"]),  # both updated
        ]
        r = cc.compute_conductivity(commits)
        assert 0.0 < r.pathway_efficiency < 1.0


# ===========================================================================
# Core computation — coverage conductance
# ===========================================================================

class TestCoverageConductance:
    def test_perfect_coverage(self):
        """Tests always updated alongside source."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"], tests=["tests/test_core.py"]),
            _commit("c1", 1, ["iamai/core.py"], tests=["tests/test_core.py"]),
            _commit("c2", 2, ["iamai/core.py"], tests=["tests/test_core.py"]),
        ]
        r = cc.compute_conductivity(commits)
        assert r.coverage_conductance == 1.0

    def test_zero_coverage(self):
        """Source changes but tests never update in same or next commit."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"], tests=["tests/test_core.py"]),
            _commit("c1", 1, ["iamai/other.py"]),
            _commit("c2", 2, ["iamai/other.py"]),
            _commit("c3", 3, ["iamai/core.py"]),
            _commit("c4", 4, ["iamai/other.py"]),
            _commit("c5", 5, ["iamai/other.py"]),
            _commit("c6", 6, ["iamai/core.py"]),
            _commit("c7", 7, ["iamai/other.py"]),
            _commit("c8", 8, ["iamai/other.py"]),
        ]
        r = cc.compute_conductivity(commits)
        # c0 includes test_core.py (same-commit hit), but c3 and c6
        # don't have test updates in same or next commit → low conductance
        assert r.coverage_conductance < 0.5

    def test_next_commit_coverage(self):
        """Tests updated in the commit *after* the source change."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"], tests=["tests/test_core.py"]),
            _commit("c1", 1, [], tests=["tests/test_core.py"]),
            _commit("c2", 2, ["iamai/core.py"], tests=["tests/test_core.py"]),
            _commit("c3", 3, [], tests=["tests/test_core.py"]),
        ]
        r = cc.compute_conductivity(commits)
        assert r.coverage_conductance > 0.0

    def test_no_tests_at_all(self):
        """No test files mentioned — conductance defaults to 1.0."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"]),
            _commit("c1", 1, ["iamai/core.py"]),
        ]
        r = cc.compute_conductivity(commits)
        assert r.coverage_conductance == 1.0


# ===========================================================================
# Core computation — bottleneck ratio
# ===========================================================================

class TestBottleneckRatio:
    def test_no_bottlenecks(self):
        """Frequently changed files always have co-modified dependents."""
        commits = [
            _commit(f"c{i}", i, [f"iamai/core.py"],
                    dependents=["iamai/app.py"])
            if i % 2 == 0 else
            _commit(f"c{i}", i, ["iamai/app.py"])
            for i in range(10)
        ]
        r = cc.compute_conductivity(commits, frequent_change_threshold=3)
        assert r.bottleneck_ratio == 0.0

    def test_all_bottlenecks(self):
        """Frequently changed files whose dependents never co-modify."""
        commits = []
        for i in range(10):
            if i % 2 == 0:
                commits.append(_commit(
                    f"c{i}", i, ["iamai/core.py"],
                    dependents=["iamai/app.py"],
                ))
            else:
                commits.append(_commit(
                    f"c{i}", i, ["iamai/unrelated.py"],
                ))
        r = cc.compute_conductivity(commits, frequent_change_threshold=3)
        assert r.bottleneck_ratio > 0.0

    def test_no_frequent_files(self):
        """No file meets the frequency threshold — ratio is 0."""
        commits = [
            _commit(f"c{i}", i, [f"iamai/mod_{i}.py"])
            for i in range(5)
        ]
        r = cc.compute_conductivity(commits, frequent_change_threshold=100)
        assert r.bottleneck_ratio == 0.0


# ===========================================================================
# Core computation — signal fidelity
# ===========================================================================

class TestSignalFidelity:
    def test_perfect_fidelity(self):
        """All dependents reached within propagation window."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"],
                    dependents=["iamai/a.py", "iamai/b.py"]),
            _commit("c1", 1, ["iamai/a.py", "iamai/b.py"]),
            _commit("c2", 2, ["iamai/core.py"],
                    dependents=["iamai/a.py", "iamai/b.py"]),
            _commit("c3", 3, ["iamai/a.py", "iamai/b.py"]),
        ]
        r = cc.compute_conductivity(commits)
        assert r.signal_fidelity == 1.0

    def test_zero_fidelity(self):
        """No dependents ever reached."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"],
                    dependents=["iamai/a.py", "iamai/b.py"]),
            _commit("c1", 1, ["iamai/unrelated.py"]),
            _commit("c2", 2, ["iamai/unrelated.py"]),
            _commit("c3", 3, ["iamai/unrelated.py"]),
            _commit("c4", 4, ["iamai/unrelated.py"]),
        ]
        r = cc.compute_conductivity(commits)
        assert r.signal_fidelity == 0.0

    def test_partial_fidelity(self):
        """Some dependents reached, some not."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"],
                    dependents=["iamai/a.py", "iamai/b.py", "iamai/c.py"]),
            _commit("c1", 1, ["iamai/a.py"]),  # only 1 of 3
            _commit("c2", 2, ["iamai/unrelated.py"]),
            _commit("c3", 3, ["iamai/unrelated.py"]),
            _commit("c4", 4, ["iamai/unrelated.py"]),
        ]
        r = cc.compute_conductivity(commits)
        assert 0.0 < r.signal_fidelity < 1.0


# ===========================================================================
# Core computation — contact resistance
# ===========================================================================

class TestContactResistance:
    def test_low_resistance(self):
        """Dependents update quickly after source changes."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"], dependents=["iamai/app.py"]),
            _commit("c1", 1, ["iamai/app.py"]),  # 1 hour later
            _commit("c2", 2, ["iamai/core.py"], dependents=["iamai/app.py"]),
            _commit("c3", 3, ["iamai/app.py"]),  # 1 hour later
        ]
        r = cc.compute_conductivity(commits)
        assert r.contact_resistance <= 2.0

    def test_high_resistance(self):
        """Long delays before dependents update."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"], dependents=["iamai/app.py"]),
            _commit("c1", 1, ["iamai/other.py"]),
            _commit("c2", 2, ["iamai/other.py"]),
            _commit("c3", 3, ["iamai/other.py"]),
            _commit("c4", 24, ["iamai/app.py"]),  # 24h later
        ]
        r = cc.compute_conductivity(commits)
        assert r.contact_resistance > 10.0

    def test_no_dependents_zero_resistance(self):
        """No dependents → default 0 resistance."""
        commits = [
            _commit("c0", 0, ["a.py"]),
            _commit("c1", 1, ["b.py"]),
        ]
        r = cc.compute_conductivity(commits)
        assert r.contact_resistance == 0.0


# ===========================================================================
# Core computation — composite score
# ===========================================================================

class TestCompositeScore:
    def test_high_conductivity_scenario(self):
        """Everything propagates promptly → high score."""
        commits = []
        for i in range(10):
            if i % 2 == 0:
                commits.append(_commit(
                    f"c{i}", i,
                    ["iamai/core.py"],
                    tests=["tests/test_core.py"],
                    dependents=["iamai/app.py"],
                ))
            else:
                commits.append(_commit(
                    f"c{i}", i,
                    ["iamai/app.py"],
                    tests=["tests/test_core.py"],
                ))
        r = cc.compute_conductivity(commits)
        assert r.conductivity_score >= 0.60
        assert r.conductivity_class in ("superconductor", "conductive")

    def test_low_conductivity_scenario(self):
        """Nothing propagates → low score."""
        commits = []
        for i in range(10):
            commits.append(_commit(
                f"c{i}", i * 10,
                ["iamai/core.py"],
                tests=["tests/test_core.py"],
                dependents=["iamai/app.py", "iamai/cli.py"],
            ))
        # Dependents never appear in any commit
        r = cc.compute_conductivity(commits)
        assert r.conductivity_score < 0.60

    def test_score_bounds(self):
        """Score is always in [0, 1]."""
        for n in [2, 5, 10, 20]:
            commits = _sequence(n, hours_step=1)
            r = cc.compute_conductivity(commits)
            assert 0.0 <= r.conductivity_score <= 1.0

    def test_score_is_rounded(self):
        commits = _sequence(10)
        r = cc.compute_conductivity(commits)
        # Check that score has at most 4 decimal places
        assert r.conductivity_score == round(r.conductivity_score, 4)


# ===========================================================================
# Result dataclass
# ===========================================================================

class TestConductivityResult:
    def test_all_fields_present(self):
        r = cc.ConductivityResult(
            window_commits=10,
            window_hours=24.0,
            pathway_efficiency=0.8,
            coverage_conductance=0.7,
            bottleneck_ratio=0.1,
            signal_fidelity=0.9,
            contact_resistance=2.5,
            conductivity_score=0.75,
            conductivity_class="conductive",
        )
        assert r.window_commits == 10
        assert r.window_hours == 24.0
        assert r.pathway_efficiency == 0.8
        assert r.coverage_conductance == 0.7
        assert r.bottleneck_ratio == 0.1
        assert r.signal_fidelity == 0.9
        assert r.contact_resistance == 2.5
        assert r.conductivity_score == 0.75
        assert r.conductivity_class == "conductive"

    def test_frozen(self):
        r = cc.ConductivityResult(
            window_commits=1, window_hours=1.0,
            pathway_efficiency=0.0, coverage_conductance=0.0,
            bottleneck_ratio=0.0, signal_fidelity=0.0,
            contact_resistance=0.0, conductivity_score=0.0,
            conductivity_class="dielectric",
        )
        with pytest.raises(AttributeError):
            r.conductivity_score = 1.0


# ===========================================================================
# Report
# ===========================================================================

class TestConductivityReport:
    def test_report_contains_all_metrics(self):
        r = cc.ConductivityResult(
            window_commits=20,
            window_hours=48.0,
            pathway_efficiency=0.75,
            coverage_conductance=0.60,
            bottleneck_ratio=0.15,
            signal_fidelity=0.80,
            contact_resistance=3.5,
            conductivity_score=0.68,
            conductivity_class="conductive",
        )
        report = cc.conductivity_report(r)
        assert "Conductivity analysis" in report
        assert "20 commits" in report
        assert "48.0h" in report
        assert "conductive" in report
        assert "0.68" in report
        assert "75.00%" in report
        assert "60.00%" in report
        assert "15.00%" in report
        assert "80.00%" in report
        assert "3.50h" in report

    def test_report_format(self):
        r = cc.ConductivityResult(
            window_commits=5,
            window_hours=10.0,
            pathway_efficiency=0.5,
            coverage_conductance=0.5,
            bottleneck_ratio=0.5,
            signal_fidelity=0.5,
            contact_resistance=1.0,
            conductivity_score=0.5,
            conductivity_class="resistive",
        )
        report = cc.conductivity_report(r)
        lines = report.split("\n")
        assert len(lines) == 8  # header + 7 metrics


# ===========================================================================
# Trend analysis
# ===========================================================================

class TestConductivityTrend:
    def test_increasing_trend(self):
        results = [
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.5, coverage_conductance=0.5,
                bottleneck_ratio=0.5, signal_fidelity=0.5,
                contact_resistance=5.0, conductivity_score=0.40,
                conductivity_class="resistive",
            ),
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.7, coverage_conductance=0.7,
                bottleneck_ratio=0.3, signal_fidelity=0.7,
                contact_resistance=3.0, conductivity_score=0.60,
                conductivity_class="conductive",
            ),
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.9, coverage_conductance=0.9,
                bottleneck_ratio=0.1, signal_fidelity=0.9,
                contact_resistance=1.0, conductivity_score=0.85,
                conductivity_class="superconductor",
            ),
        ]
        t = cc.conductivity_trend(results)
        assert t.direction == "increasing"
        assert t.score_delta == pytest.approx(0.45, abs=0.01)
        assert t.earliest_score == 0.40
        assert t.latest_score == 0.85
        assert t.sample_count == 3

    def test_decreasing_trend(self):
        results = [
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.9, coverage_conductance=0.9,
                bottleneck_ratio=0.1, signal_fidelity=0.9,
                contact_resistance=1.0, conductivity_score=0.85,
                conductivity_class="superconductor",
            ),
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.5, coverage_conductance=0.5,
                bottleneck_ratio=0.5, signal_fidelity=0.5,
                contact_resistance=5.0, conductivity_score=0.50,
                conductivity_class="resistive",
            ),
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.3, coverage_conductance=0.3,
                bottleneck_ratio=0.7, signal_fidelity=0.3,
                contact_resistance=10.0, conductivity_score=0.30,
                conductivity_class="insulating",
            ),
        ]
        t = cc.conductivity_trend(results)
        assert t.direction == "decreasing"
        assert t.score_delta == pytest.approx(-0.55, abs=0.01)

    def test_stable_trend(self):
        results = [
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.6, coverage_conductance=0.6,
                bottleneck_ratio=0.4, signal_fidelity=0.6,
                contact_resistance=4.0, conductivity_score=0.55,
                conductivity_class="resistive",
            ),
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.6, coverage_conductance=0.6,
                bottleneck_ratio=0.4, signal_fidelity=0.6,
                contact_resistance=4.0, conductivity_score=0.57,
                conductivity_class="resistive",
            ),
        ]
        t = cc.conductivity_trend(results)
        assert t.direction == "stable"

    def test_single_result(self):
        results = [
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.6, coverage_conductance=0.6,
                bottleneck_ratio=0.4, signal_fidelity=0.6,
                contact_resistance=4.0, conductivity_score=0.55,
                conductivity_class="resistive",
            ),
        ]
        t = cc.conductivity_trend(results)
        assert t.direction == "stable"
        assert t.sample_count == 1

    def test_empty_results(self):
        t = cc.conductivity_trend([])
        assert t.direction == "stable"
        assert t.score_delta == 0.0
        assert t.sample_count == 0


# ===========================================================================
# Trend dataclass
# ===========================================================================

class TestConductivityTrendDataclass:
    def test_fields(self):
        t = cc.ConductivityTrend(
            direction="increasing",
            score_delta=0.25,
            earliest_score=0.40,
            latest_score=0.65,
            sample_count=5,
        )
        assert t.direction == "increasing"
        assert t.score_delta == 0.25
        assert t.earliest_score == 0.40
        assert t.latest_score == 0.65
        assert t.sample_count == 5

    def test_frozen(self):
        t = cc.ConductivityTrend(
            direction="stable",
            score_delta=0.0,
            earliest_score=0.5,
            latest_score=0.5,
            sample_count=1,
        )
        with pytest.raises(AttributeError):
            t.direction = "increasing"


# ===========================================================================
# Integration: realistic scenarios
# ===========================================================================

class TestIntegrationScenarios:
    def test_healthy_codebase(self):
        """Simulate a well-maintained repo with good change propagation."""
        commits = []
        for i in range(20):
            if i % 3 == 0:
                # Feature commit: change core + update tests
                commits.append(_commit(
                    f"c{i}", i,
                    ["iamai/core.py", "iamai/utils.py"],
                    tests=["tests/test_core.py", "tests/test_utils.py"],
                    dependents=["iamai/app.py", "iamai/cli.py"],
                ))
            elif i % 3 == 1:
                # Follow-up: update dependents
                commits.append(_commit(
                    f"c{i}", i,
                    ["iamai/app.py", "iamai/cli.py"],
                    tests=["tests/test_app.py"],
                ))
            else:
                # Cleanup
                commits.append(_commit(
                    f"c{i}", i,
                    ["docs/CHANGELOG.md"],
                ))
        r = cc.compute_conductivity(commits)
        assert r.conductivity_score >= 0.50
        assert r.window_commits == 20

    def test_neglected_codebase(self):
        """Simulate a repo where changes never propagate."""
        commits = []
        for i in range(20):
            commits.append(_commit(
                f"c{i}", i * 5,
                [f"iamai/module_{i % 3}.py"],
                tests=[f"tests/test_module_{i % 3}.py"],
                dependents=[f"iamai/caller_{i % 5}.py"],
            ))
        # Dependents never appear in any other commit
        r = cc.compute_conductivity(commits)
        # Low pathway efficiency and signal fidelity expected
        assert r.pathway_efficiency < 0.5
        assert r.window_hours > 0

    def test_window_hours_calculation(self):
        commits = [
            _commit("c0", 0, ["a.py"]),
            _commit("c1", 24, ["b.py"]),
        ]
        r = cc.compute_conductivity(commits)
        assert r.window_hours == 24.0

    def test_custom_propagation_window(self):
        """Wider propagation window captures more dependent updates."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"], dependents=["iamai/app.py"]),
            _commit("c1", 1, ["iamai/other.py"]),
            _commit("c2", 2, ["iamai/other.py"]),
            _commit("c3", 3, ["iamai/app.py"]),
            _commit("c4", 4, ["iamai/core.py"], dependents=["iamai/app.py"]),
            _commit("c5", 5, ["iamai/other.py"]),
            _commit("c6", 6, ["iamai/other.py"]),
            _commit("c7", 7, ["iamai/app.py"]),
        ]
        r_narrow = cc.compute_conductivity(commits, propagation_window=1)
        r_wide = cc.compute_conductivity(commits, propagation_window=5)
        # Wider window should capture more propagation
        assert r_wide.signal_fidelity >= r_narrow.signal_fidelity

    def test_report_matches_result(self):
        """Report output reflects the actual result values."""
        commits = _sequence(10, hours_step=2,
                            files_fn=lambda i: frozenset([f"iamai/mod_{i % 3}.py"]),
                            tests_fn=lambda i: frozenset([f"tests/test_mod_{i % 3}.py"]),
                            dependents_fn=lambda i: frozenset([f"iamai/caller_{i % 2}.py"]))
        r = cc.compute_conductivity(commits)
        report = cc.conductivity_report(r)
        assert r.conductivity_class in report
        assert f"{r.conductivity_score:.2f}" in report


# ===========================================================================
# ConductivityTrend edge cases
# ===========================================================================

class TestConductivityTrendEdgeCases:
    def test_exactly_005_delta_is_stable(self):
        """Boundary: delta == 0.05 should be 'stable' (not > 0.05)."""
        results = [
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.5, coverage_conductance=0.5,
                bottleneck_ratio=0.5, signal_fidelity=0.5,
                contact_resistance=5.0, conductivity_score=0.50,
                conductivity_class="resistive",
            ),
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.5, coverage_conductance=0.5,
                bottleneck_ratio=0.5, signal_fidelity=0.5,
                contact_resistance=5.0, conductivity_score=0.55,
                conductivity_class="resistive",
            ),
        ]
        t = cc.conductivity_trend(results)
        assert t.direction == "stable"

    def test_just_over_005_is_increasing(self):
        results = [
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.5, coverage_conductance=0.5,
                bottleneck_ratio=0.5, signal_fidelity=0.5,
                contact_resistance=5.0, conductivity_score=0.50,
                conductivity_class="resistive",
            ),
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.5, coverage_conductance=0.5,
                bottleneck_ratio=0.5, signal_fidelity=0.5,
                contact_resistance=5.0, conductivity_score=0.56,
                conductivity_class="resistive",
            ),
        ]
        t = cc.conductivity_trend(results)
        assert t.direction == "increasing"

    def test_just_under_neg_005_is_decreasing(self):
        results = [
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.5, coverage_conductance=0.5,
                bottleneck_ratio=0.5, signal_fidelity=0.5,
                contact_resistance=5.0, conductivity_score=0.50,
                conductivity_class="resistive",
            ),
            cc.ConductivityResult(
                window_commits=10, window_hours=24.0,
                pathway_efficiency=0.5, coverage_conductance=0.5,
                bottleneck_ratio=0.5, signal_fidelity=0.5,
                contact_resistance=5.0, conductivity_score=0.44,
                conductivity_class="resistive",
            ),
        ]
        t = cc.conductivity_trend(results)
        assert t.direction == "decreasing"
