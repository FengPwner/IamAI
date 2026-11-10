#!/usr/bin/env python3
"""Tests for commit_viscosity.py — codebase flow resistance analysis."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_viscosity as cv

# ---------------------------------------------------------------------------
# Reference time
# ---------------------------------------------------------------------------
REF = datetime(2026, 11, 11, 0, 0, 0)  # Wed 2026-11-11 00:00 UTC


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _commit(sha, hours_after, files):
    """Create a CommitRecord at REF + hours_after with the given files."""
    return cv.CommitRecord(
        sha=sha,
        timestamp=REF + timedelta(hours=hours_after),
        files=frozenset(files),
    )


def _sequence(n, hours_step=1, files_fn=None):
    """Generate n commits spaced hours_step apart."""
    if files_fn is None:
        files_fn = lambda i: frozenset([f"iamai/mod_{i % 5}.py"])
    return [
        cv.CommitRecord(
            sha=f"c{i}",
            timestamp=REF + timedelta(hours=i * hours_step),
            files=files_fn(i),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# CommitRecord
# ---------------------------------------------------------------------------

class TestCommitRecord:
    def test_frozenset_conversion(self):
        c = cv.CommitRecord(sha="a", timestamp=REF, files=["x.py", "y.py"])
        assert isinstance(c.files, frozenset)
        assert c.files == frozenset({"x.py", "y.py"})

    def test_already_frozenset(self):
        fs = frozenset({"a.py"})
        c = cv.CommitRecord(sha="a", timestamp=REF, files=fs)
        assert c.files is fs

    def test_empty_files(self):
        c = cv.CommitRecord(sha="a", timestamp=REF, files=frozenset())
        assert len(c.files) == 0

    def test_immutable(self):
        c = _commit("a", 0, ["x.py"])
        with pytest.raises(AttributeError):
            c.sha = "b"


# ---------------------------------------------------------------------------
# classify_viscosity
# ---------------------------------------------------------------------------

class TestClassifyViscosity:
    def test_solid(self):
        assert cv.classify_viscosity(0.80) == "solid"
        assert cv.classify_viscosity(0.95) == "solid"
        assert cv.classify_viscosity(1.0) == "solid"

    def test_viscous(self):
        assert cv.classify_viscosity(0.60) == "viscous"
        assert cv.classify_viscosity(0.79) == "viscous"

    def test_thick(self):
        assert cv.classify_viscosity(0.40) == "thick"
        assert cv.classify_viscosity(0.59) == "thick"

    def test_thin(self):
        assert cv.classify_viscosity(0.20) == "thin"
        assert cv.classify_viscosity(0.39) == "thin"

    def test_flowing(self):
        assert cv.classify_viscosity(0.19) == "flowing"
        assert cv.classify_viscosity(0.0) == "flowing"

    def test_just_below_boundary(self):
        assert cv.classify_viscosity(0.7999) == "viscous"
        assert cv.classify_viscosity(0.5999) == "thick"
        assert cv.classify_viscosity(0.3999) == "thin"
        assert cv.classify_viscosity(0.1999) == "flowing"


# ---------------------------------------------------------------------------
# _top_area
# ---------------------------------------------------------------------------

class TestTopArea:
    def test_simple(self):
        assert cv._top_area("iamai/foo.py") == "iamai"

    def test_root_file(self):
        assert cv._top_area("README.md") == "."

    def test_deep(self):
        assert cv._top_area("src/core/utils/helpers.py") == "src"

    def test_backslash(self):
        assert cv._top_area("tests\\unit\\test_foo.py") == "tests"


# ---------------------------------------------------------------------------
# _area_set
# ---------------------------------------------------------------------------

class TestAreaSet:
    def test_mixed(self):
        fs = frozenset(["iamai/a.py", "tests/test_a.py", "README.md"])
        result = cv._area_set(fs)
        assert result == frozenset({"iamai", "tests", "."})

    def test_empty(self):
        assert cv._area_set(frozenset()) == frozenset()

    def test_single_area(self):
        fs = frozenset(["iamai/a.py", "iamai/b.py"])
        assert cv._area_set(fs) == frozenset({"iamai"})


# ---------------------------------------------------------------------------
# compute_viscosity — basic scenarios
# ---------------------------------------------------------------------------

class TestComputeViscosityBasic:
    def test_empty_commits(self):
        """No commits yields flowing with zero metrics."""
        r = cv.compute_viscosity([])
        assert r.window_commits == 0
        assert r.viscosity_class == "flowing"
        assert r.viscosity_score == 0.0

    def test_single_commit(self):
        """One commit — not enough data for meaningful metrics."""
        c = _commit("a", 0, ["iamai/foo.py"])
        r = cv.compute_viscosity([c])
        assert r.window_commits == 1
        assert r.viscosity_class == "flowing"

    def test_two_commits_same_area(self):
        """Two commits in the same area — minimal viscosity."""
        commits = [
            _commit("a", 0, ["iamai/foo.py"]),
            _commit("b", 1, ["iamai/bar.py"]),
        ]
        r = cv.compute_viscosity(commits)
        assert r.window_commits == 2
        assert r.shear_stress == 0.0  # no multi-area commits
        assert r.viscosity_score < 0.40


# ---------------------------------------------------------------------------
# compute_viscosity — flow rate
# ---------------------------------------------------------------------------

class TestFlowRate:
    def test_basic_flow_rate(self):
        """24 commits over 24 hours = 24 commits/day."""
        commits = _sequence(24, hours_step=1)
        r = cv.compute_viscosity(commits)
        assert r.flow_rate == pytest.approx(24.0, rel=0.1)

    def test_slow_flow(self):
        """10 commits over 100 hours = ~2.4 commits/day."""
        commits = _sequence(10, hours_step=10)
        r = cv.compute_viscosity(commits)
        # Span = 90 hours = 3.75 days → 10/3.75 ≈ 2.67
        assert r.flow_rate == pytest.approx(10 / (90 / 24), rel=0.01)

    def test_flow_rate_positive(self):
        commits = _sequence(5, hours_step=2)
        r = cv.compute_viscosity(commits)
        assert r.flow_rate > 0


# ---------------------------------------------------------------------------
# compute_viscosity — shear stress
# ---------------------------------------------------------------------------

class TestShearStress:
    def test_no_multi_area(self):
        """All commits touch one area — zero shear."""
        commits = _sequence(10, files_fn=lambda i: frozenset([f"iamai/m{i}.py"]))
        r = cv.compute_viscosity(commits)
        assert r.shear_stress == 0.0

    def test_all_multi_area(self):
        """Every commit crosses areas — maximum shear."""
        commits = _sequence(10, files_fn=lambda i: frozenset([
            f"iamai/m{i}.py", f"tests/test_m{i}.py",
        ]))
        r = cv.compute_viscosity(commits)
        assert r.shear_stress == 1.0

    def test_half_multi_area(self):
        """Half the commits cross areas."""
        def files_fn(i):
            if i % 2 == 0:
                return frozenset([f"iamai/m{i}.py"])
            return frozenset([f"iamai/m{i}.py", f"tests/test_m{i}.py"])
        commits = _sequence(10, files_fn=files_fn)
        r = cv.compute_viscosity(commits)
        assert r.shear_stress == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# compute_viscosity — layer coupling
# ---------------------------------------------------------------------------

class TestLayerCoupling:
    def test_no_multi_area_zero_coupling(self):
        commits = _sequence(10, files_fn=lambda i: frozenset([f"iamai/m{i}.py"]))
        r = cv.compute_viscosity(commits)
        assert r.layer_coupling == 0.0

    def test_two_areas_per_commit(self):
        commits = _sequence(10, files_fn=lambda i: frozenset([
            f"iamai/m{i}.py", f"tests/test_m{i}.py",
        ]))
        r = cv.compute_viscosity(commits)
        assert r.layer_coupling == pytest.approx(2.0)

    def test_three_areas_per_commit(self):
        commits = _sequence(10, files_fn=lambda i: frozenset([
            f"iamai/m{i}.py", f"tests/test_m{i}.py", f"docs/m{i}.md",
        ]))
        r = cv.compute_viscosity(commits)
        assert r.layer_coupling == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# compute_viscosity — yield point
# ---------------------------------------------------------------------------

class TestYieldPoint:
    def test_single_file_commits(self):
        commits = _sequence(10, files_fn=lambda i: frozenset([f"iamai/m{i}.py"]))
        r = cv.compute_viscosity(commits)
        assert r.yield_point == pytest.approx(1.0)

    def test_multi_file_commits(self):
        commits = _sequence(10, files_fn=lambda i: frozenset([
            f"iamai/a{i}.py", f"iamai/b{i}.py", f"iamai/c{i}.py",
        ]))
        r = cv.compute_viscosity(commits)
        assert r.yield_point == pytest.approx(3.0)

    def test_mixed_sizes(self):
        """Median of [1, 1, 1, 1, 1, 3, 3, 3, 3, 3] = 2.0."""
        def files_fn(i):
            if i < 5:
                return frozenset([f"iamai/m{i}.py"])
            return frozenset([f"iamai/a{i}.py", f"iamai/b{i}.py", f"iamai/c{i}.py"])
        commits = _sequence(10, files_fn=files_fn)
        r = cv.compute_viscosity(commits)
        assert r.yield_point == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# compute_viscosity — turbulence
# ---------------------------------------------------------------------------

class TestTurbulence:
    def test_uniform_sizes_zero_turbulence(self):
        """All commits touch exactly 1 file — CV = 0."""
        commits = _sequence(10, files_fn=lambda i: frozenset([f"iamai/m{i}.py"]))
        r = cv.compute_viscosity(commits)
        assert r.turbulence == pytest.approx(0.0)

    def test_variable_sizes_high_turbulence(self):
        """Mix of 1-file and 10-file commits → high CV."""
        def files_fn(i):
            if i % 2 == 0:
                return frozenset([f"iamai/m{i}.py"])
            return frozenset([f"iamai/f{j}.py" for j in range(10)])
        commits = _sequence(10, files_fn=files_fn)
        r = cv.compute_viscosity(commits)
        assert r.turbulence > 0.5

    def test_single_commit_zero_turbulence(self):
        """One commit — not enough for stdev."""
        c = _commit("a", 0, ["iamai/foo.py"])
        r = cv.compute_viscosity([c])
        assert r.turbulence == 0.0


# ---------------------------------------------------------------------------
# compute_viscosity — score composition
# ---------------------------------------------------------------------------

class TestComputeViscosityScore:
    def test_smooth_codebase_low_score(self):
        """Well-isolated, single-file commits → low viscosity."""
        commits = _sequence(30, hours_step=1,
                            files_fn=lambda i: frozenset([f"iamai/m{i % 10}.py"]))
        r = cv.compute_viscosity(commits)
        assert r.viscosity_score < 0.40
        assert r.viscosity_class in ("flowing", "thin")

    def test_coupled_codebase_higher_score(self):
        """Every commit crosses 3 areas with varying sizes → higher viscosity."""
        import random
        random.seed(42)

        def files_fn(i):
            n_extra = random.randint(0, 8)
            base = [f"iamai/m{i}.py", f"tests/test_m{i}.py", f"docs/d{i}.md"]
            extra = [f"scripts/s{j}.py" for j in range(n_extra)]
            return frozenset(base + extra)

        commits = _sequence(30, hours_step=1, files_fn=files_fn)
        r = cv.compute_viscosity(commits)
        assert r.viscosity_score >= 0.40
        assert r.viscosity_class in ("thick", "viscous", "solid")

    def test_score_clamped(self):
        """Score is always in [0, 1]."""
        commits = _sequence(50)
        r = cv.compute_viscosity(commits)
        assert 0.0 <= r.viscosity_score <= 1.0

    def test_zero_commits(self):
        r = cv.compute_viscosity([])
        assert r.viscosity_score == 0.0


# ---------------------------------------------------------------------------
# compute_viscosity — edge cases
# ---------------------------------------------------------------------------

class TestComputeViscosityEdgeCases:
    def test_all_empty_file_sets(self):
        """Commits with no files — no crash, minimal metrics."""
        commits = [
            cv.CommitRecord(sha=f"c{i}", timestamp=REF + timedelta(hours=i),
                            files=frozenset())
            for i in range(5)
        ]
        r = cv.compute_viscosity(commits)
        assert r.window_commits == 5
        assert r.shear_stress == 0.0
        assert r.yield_point == 0.0

    def test_identical_timestamps(self):
        """All commits at the same time — span clamped to 1 second."""
        commits = [
            cv.CommitRecord(sha=f"c{i}", timestamp=REF,
                            files=frozenset([f"iamai/m{i}.py"]))
            for i in range(5)
        ]
        r = cv.compute_viscosity(commits)
        assert r.flow_rate > 0  # doesn't crash

    def test_one_commit_multi_area(self):
        """Single commit touching 4 areas — not enough for full analysis."""
        c = cv.CommitRecord(
            sha="big", timestamp=REF,
            files=frozenset(["iamai/a.py", "tests/b.py", "docs/c.md", "scripts/d.sh"]),
        )
        r = cv.compute_viscosity([c])
        assert r.window_commits == 1
        assert r.viscosity_class == "flowing"


# ---------------------------------------------------------------------------
# viscosity_report
# ---------------------------------------------------------------------------

class TestViscosityReport:
    def test_contains_key_fields(self):
        commits = _sequence(10)
        r = cv.compute_viscosity(commits)
        report = cv.viscosity_report(r)
        assert "Viscosity analysis" in report
        assert "class:" in report
        assert "score:" in report
        assert "flow rate:" in report
        assert "shear stress:" in report
        assert "layer coupling:" in report
        assert "yield point:" in report
        assert "turbulence" in report

    def test_formatting(self):
        commits = _sequence(10)
        r = cv.compute_viscosity(commits)
        report = cv.viscosity_report(r)
        lines = report.strip().split("\n")
        assert len(lines) == 8  # header + 7 metrics


# ---------------------------------------------------------------------------
# viscosity_trend
# ---------------------------------------------------------------------------

class TestViscosityTrend:
    def test_empty(self):
        t = cv.viscosity_trend([])
        assert t.direction == "stable"
        assert t.sample_count == 0

    def test_single_result(self):
        r = cv.compute_viscosity(_sequence(10))
        t = cv.viscosity_trend([r])
        assert t.direction == "stable"
        assert t.sample_count == 1

    def test_increasing(self):
        r1 = cv.ViscosityResult(10, 24.0, 10.0, 0.1, 1.5, 1.0, 0.3, 0.20, "thin")
        r2 = cv.ViscosityResult(10, 24.0, 10.0, 0.5, 3.0, 4.0, 1.5, 0.70, "viscous")
        t = cv.viscosity_trend([r1, r2])
        assert t.direction == "increasing"
        assert t.score_delta == pytest.approx(0.50)

    def test_decreasing(self):
        r1 = cv.ViscosityResult(10, 24.0, 10.0, 0.5, 3.0, 4.0, 1.5, 0.70, "viscous")
        r2 = cv.ViscosityResult(10, 24.0, 10.0, 0.1, 1.5, 1.0, 0.3, 0.20, "thin")
        t = cv.viscosity_trend([r1, r2])
        assert t.direction == "decreasing"
        assert t.score_delta == pytest.approx(-0.50)

    def test_stable_small_delta(self):
        r1 = cv.ViscosityResult(10, 24.0, 10.0, 0.2, 2.0, 2.0, 0.5, 0.40, "thick")
        r2 = cv.ViscosityResult(10, 24.0, 10.0, 0.2, 2.0, 2.0, 0.5, 0.43, "thick")
        t = cv.viscosity_trend([r1, r2])
        assert t.direction == "stable"
        assert t.score_delta == pytest.approx(0.03)

    def test_multiple_results(self):
        results = [
            cv.ViscosityResult(10, 24.0, 10.0, 0.1, 1.5, 1.0, 0.3, 0.20 + i * 0.1, "thin")
            for i in range(5)
        ]
        t = cv.viscosity_trend(results)
        assert t.direction == "increasing"
        assert t.sample_count == 5
        assert t.earliest_score == pytest.approx(0.20)
        assert t.latest_score == pytest.approx(0.60)
