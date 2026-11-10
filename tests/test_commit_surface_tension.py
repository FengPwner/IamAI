#!/usr/bin/env python3
"""Tests for commit_surface_tension.py — codebase boundary coupling analysis."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_surface_tension as cst

# ---------------------------------------------------------------------------
# Reference time
# ---------------------------------------------------------------------------
REF = datetime(2026, 11, 11, 0, 0, 0)  # Wed 2026-11-11 00:00 UTC


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _commit(sha, hours_after, files, boundary=None, internal=None):
    """Create a CommitRecord at REF + hours_after."""
    return cst.CommitRecord(
        sha=sha,
        timestamp=REF + timedelta(hours=hours_after),
        files=frozenset(files),
        boundary_files=frozenset(boundary or []),
        internal_deps=frozenset(internal or []),
    )


def _sequence(n, hours_step=1, files_fn=None, boundary_fn=None, internal_fn=None):
    """Generate n commits spaced hours_step apart."""
    if files_fn is None:
        files_fn = lambda i: frozenset([f"iamai/mod_{i % 5}.py"])
    if boundary_fn is None:
        boundary_fn = lambda i: frozenset()
    if internal_fn is None:
        internal_fn = lambda i: frozenset()
    return [
        cst.CommitRecord(
            sha=f"c{i}",
            timestamp=REF + timedelta(hours=i * hours_step),
            files=files_fn(i),
            boundary_files=boundary_fn(i),
            internal_deps=internal_fn(i),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# CommitRecord
# ---------------------------------------------------------------------------

class TestCommitRecord:
    def test_frozenset_conversion(self):
        c = cst.CommitRecord(
            sha="a", timestamp=REF,
            files=["x.py", "y.py"],
            boundary_files=["api/v1.py"],
            internal_deps=["core/db.py"],
        )
        assert isinstance(c.files, frozenset)
        assert isinstance(c.boundary_files, frozenset)
        assert isinstance(c.internal_deps, frozenset)

    def test_already_frozenset(self):
        fs = frozenset({"a.py"})
        c = cst.CommitRecord(sha="a", timestamp=REF, files=fs, boundary_files=fs, internal_deps=fs)
        assert c.files is fs
        assert c.boundary_files is fs
        assert c.internal_deps is fs

    def test_frozen_dataclass(self):
        c = cst.CommitRecord(sha="a", timestamp=REF, files=["x.py"])
        with pytest.raises(AttributeError):
            c.sha = "b"

    def test_default_empty_sets(self):
        c = cst.CommitRecord(sha="a", timestamp=REF, files=["x.py"])
        assert c.boundary_files == frozenset()
        assert c.internal_deps == frozenset()


# ---------------------------------------------------------------------------
# classify_tension
# ---------------------------------------------------------------------------

class TestClassifyTension:
    @pytest.mark.parametrize("score,expected", [
        (0.0, "open"),
        (0.10, "open"),
        (0.19, "open"),
        (0.20, "porous"),
        (0.35, "porous"),
        (0.39, "porous"),
        (0.40, "cohesive"),
        (0.50, "cohesive"),
        (0.59, "cohesive"),
        (0.60, "tight"),
        (0.70, "tight"),
        (0.79, "tight"),
        (0.80, "sealed"),
        (0.90, "sealed"),
        (1.00, "sealed"),
    ])
    def test_boundaries(self, score, expected):
        assert cst.classify_tension(score) == expected

    def test_negative_clamps_to_open(self):
        assert cst.classify_tension(-0.5) == "open"

    def test_above_one_clamps_to_sealed(self):
        assert cst.classify_tension(1.5) == "sealed"


# ---------------------------------------------------------------------------
# _is_boundary (heuristic)
# ---------------------------------------------------------------------------

class TestIsBoundary:
    @pytest.mark.parametrize("filename,expected", [
        ("iamai/api/v1/handler.py", True),
        ("iamai/api/__init__.py", True),
        ("iamai/cli/main.py", True),
        ("iamai/cmd/runner.py", True),
        ("iamai/__init__.py", True),
        ("iamai/views/dashboard.py", True),
        ("iamai/routes/users.py", True),
        ("iamai/handler.py", True),
        ("iamai/endpoint.py", True),
        ("iamai/adapter.py", True),
        ("iamai/facade.py", True),
        ("iamai/internal/db.py", False),
        ("iamai/core/logic.py", False),
        ("iamai/utils.py", False),
        ("tests/test_foo.py", False),
        ("docs/README.md", False),
    ])
    def test_heuristic(self, filename, expected):
        assert cst._is_boundary(filename) == expected


# ---------------------------------------------------------------------------
# compute_surface_tension — edge cases
# ---------------------------------------------------------------------------

class TestComputeEdgeCases:
    def test_empty_commits(self):
        r = cst.compute_surface_tension([])
        assert r.window_commits == 0
        assert r.tension_class == "open"
        assert r.tension_score == 0.0

    def test_single_commit(self):
        c = _commit("a", 0, ["x.py"])
        r = cst.compute_surface_tension([c])
        assert r.window_commits == 1
        assert r.tension_class == "open"
        assert r.tension_score == 0.0

    def test_no_boundary_files(self):
        commits = _sequence(10, files_fn=lambda i: frozenset([f"iamai/internal_{i}.py"]))
        r = cst.compute_surface_tension(commits)
        assert r.boundary_ratio == 0.0
        assert r.surface_area == 0
        assert r.tension_score < 0.3


# ---------------------------------------------------------------------------
# compute_surface_tension — normal scenarios
# ---------------------------------------------------------------------------

class TestComputeNormal:
    def test_high_tension_scenario(self):
        """All commits touch boundary files with deep internal deps."""
        commits = [
            _commit(
                f"c{i}", i,
                files=[f"iamai/api/v{i % 3}.py", f"iamai/core/impl_{i}.py"],
                boundary=[f"iamai/api/v{i % 3}.py"],
                internal=[f"iamai/core/impl_{i}.py", f"iamai/core/util_{i}.py", f"iamai/db/q_{i}.py"],
            )
            for i in range(20)
        ]
        r = cst.compute_surface_tension(commits)
        assert r.boundary_ratio > 0
        assert r.coupling_depth > 1.0
        assert r.permeability < 0.5
        assert r.tension_class in ("tight", "sealed", "cohesive")

    def test_low_tension_scenario(self):
        """Commits touch only internal files, no boundary changes."""
        commits = [
            _commit(
                f"c{i}", i,
                files=[f"iamai/internal/mod_{i % 5}.py"],
            )
            for i in range(20)
        ]
        r = cst.compute_surface_tension(commits)
        assert r.boundary_ratio == 0.0
        assert r.permeability == 1.0
        assert r.tension_class == "open"

    def test_mixed_scenario(self):
        """Some commits touch boundary, some don't."""
        commits = []
        for i in range(20):
            if i % 3 == 0:
                commits.append(_commit(
                    f"c{i}", i,
                    files=[f"iamai/api/v{i % 2}.py", f"iamai/core/dep_{i}.py"],
                    boundary=[f"iamai/api/v{i % 2}.py"],
                    internal=[f"iamai/core/dep_{i}.py"],
                ))
            else:
                commits.append(_commit(
                    f"c{i}", i,
                    files=[f"iamai/internal/mod_{i % 4}.py"],
                ))
        r = cst.compute_surface_tension(commits)
        assert 0.0 < r.boundary_ratio < 1.0
        assert r.tension_class in ("porous", "cohesive", "tight")

    def test_permeability_with_no_internal_deps(self):
        """All commits have files but no internal deps — high permeability."""
        commits = [
            _commit(f"c{i}", i, files=[f"iamai/api/v{i % 2}.py"], boundary=[f"iamai/api/v{i % 2}.py"])
            for i in range(10)
        ]
        r = cst.compute_surface_tension(commits)
        assert r.permeability == 1.0

    def test_surface_stability_all_untouched(self):
        """Boundary files exist in override but no commit touches them."""
        override = frozenset(["iamai/api/stable.py", "iamai/api/legacy.py"])
        commits = _sequence(
            10,
            files_fn=lambda i: frozenset([f"iamai/internal/mod_{i}.py"]),
        )
        r = cst.compute_surface_tension(commits, boundary_files_override=override)
        # No boundary files detected in commits, so surface_area depends on override
        assert r.surface_stability == 1.0 or r.surface_area == 0


# ---------------------------------------------------------------------------
# compute_surface_tension — metric validation
# ---------------------------------------------------------------------------

class TestMetricValidation:
    def test_score_bounded(self):
        """Score is always in [0, 1]."""
        for seed in range(5):
            commits = [
                _commit(
                    f"c{i}", i * (seed + 1),
                    files=[f"mod_{(i * seed) % 7}.py", f"api/h_{(i + seed) % 3}.py"],
                    boundary=[f"api/h_{(i + seed) % 3}.py"] if i % 2 == 0 else [],
                    internal=[f"core/d_{i % 4}.py"] if i % 3 == 0 else [],
                )
                for i in range(30)
            ]
            r = cst.compute_surface_tension(commits)
            assert 0.0 <= r.tension_score <= 1.0

    def test_window_hours_positive(self):
        commits = _sequence(5, hours_step=2)
        r = cst.compute_surface_tension(commits)
        assert r.window_hours > 0

    def test_all_ratios_bounded(self):
        commits = [
            _commit(
                f"c{i}", i,
                files=[f"iamai/api/v{i % 3}.py", f"iamai/core/{i}.py"],
                boundary=[f"iamai/api/v{i % 3}.py"],
                internal=[f"iamai/core/{i}.py"],
            )
            for i in range(15)
        ]
        r = cst.compute_surface_tension(commits)
        assert 0.0 <= r.boundary_ratio <= 1.0
        assert 0.0 <= r.cohesion_index <= 1.0
        assert 0.0 <= r.permeability <= 1.0
        assert 0.0 <= r.surface_stability <= 1.0
        assert r.coupling_depth >= 0.0
        assert r.surface_area >= 0


# ---------------------------------------------------------------------------
# boundary_files_override
# ---------------------------------------------------------------------------

class TestBoundaryOverride:
    def test_override_restricts_boundary(self):
        """Only files in the override set are counted as boundary."""
        commits = [
            _commit(
                f"c{i}", i,
                files=[f"iamai/api/v{i % 2}.py", f"iamai/cli/main.py", f"iamai/core/{i}.py"],
                boundary=[f"iamai/api/v{i % 2}.py", f"iamai/cli/main.py"],
                internal=[f"iamai/core/{i}.py"],
            )
            for i in range(10)
        ]
        override = frozenset(["iamai/api/v0.py"])
        r = cst.compute_surface_tension(commits, boundary_files_override=override)
        # Only v0.py from boundary_files intersects with override
        assert r.surface_area <= 1

    def test_no_override_uses_heuristic(self):
        """Without override, heuristic detection kicks in."""
        commits = [
            _commit(
                f"c{i}", i,
                files=[f"iamai/api/v{i % 2}.py", f"iamai/core/{i}.py"],
            )
            for i in range(10)
        ]
        r = cst.compute_surface_tension(commits)
        # api/ files should be detected as boundary
        assert r.surface_area >= 1


# ---------------------------------------------------------------------------
# surface_tension_report
# ---------------------------------------------------------------------------

class TestReport:
    def test_report_contains_all_fields(self):
        commits = [
            _commit(
                f"c{i}", i,
                files=[f"iamai/api/v{i % 2}.py", f"iamai/core/{i}.py"],
                boundary=[f"iamai/api/v{i % 2}.py"],
                internal=[f"iamai/core/{i}.py"],
            )
            for i in range(10)
        ]
        r = cst.compute_surface_tension(commits)
        report = cst.surface_tension_report(r)
        assert "Surface tension analysis" in report
        assert "class:" in report
        assert "score:" in report
        assert "boundary ratio:" in report
        assert "coupling depth:" in report
        assert "cohesion index:" in report
        assert "permeability:" in report
        assert "surface area:" in report
        assert "surface stability:" in report

    def test_report_format(self):
        r = cst.SurfaceTensionResult(
            window_commits=10, window_hours=10.0,
            boundary_ratio=0.25, coupling_depth=2.5,
            cohesion_index=0.4, permeability=0.6,
            surface_area=5, surface_stability=0.8,
            tension_score=0.45, tension_class="cohesive",
        )
        report = cst.surface_tension_report(r)
        assert "10 commits" in report
        assert "cohesive" in report


# ---------------------------------------------------------------------------
# surface_tension_trend
# ---------------------------------------------------------------------------

class TestTrend:
    def test_empty_results(self):
        t = cst.surface_tension_trend([])
        assert t.direction == "stable"
        assert t.sample_count == 0

    def test_single_result(self):
        r = cst.SurfaceTensionResult(
            window_commits=10, window_hours=10.0,
            boundary_ratio=0.25, coupling_depth=2.5,
            cohesion_index=0.4, permeability=0.6,
            surface_area=5, surface_stability=0.8,
            tension_score=0.45, tension_class="cohesive",
        )
        t = cst.surface_tension_trend([r])
        assert t.direction == "stable"
        assert t.sample_count == 1

    def test_increasing_trend(self):
        results = [
            cst.SurfaceTensionResult(
                window_commits=10, window_hours=10.0,
                boundary_ratio=0.2, coupling_depth=1.0,
                cohesion_index=0.3, permeability=0.8,
                surface_area=3, surface_stability=0.9,
                tension_score=0.30, tension_class="porous",
            ),
            cst.SurfaceTensionResult(
                window_commits=10, window_hours=10.0,
                boundary_ratio=0.4, coupling_depth=3.0,
                cohesion_index=0.6, permeability=0.4,
                surface_area=8, surface_stability=0.5,
                tension_score=0.55, tension_class="cohesive",
            ),
        ]
        t = cst.surface_tension_trend(results)
        assert t.direction == "increasing"
        assert t.score_delta > 0

    def test_decreasing_trend(self):
        results = [
            cst.SurfaceTensionResult(
                window_commits=10, window_hours=10.0,
                boundary_ratio=0.4, coupling_depth=3.0,
                cohesion_index=0.6, permeability=0.4,
                surface_area=8, surface_stability=0.5,
                tension_score=0.65, tension_class="tight",
            ),
            cst.SurfaceTensionResult(
                window_commits=10, window_hours=10.0,
                boundary_ratio=0.1, coupling_depth=0.5,
                cohesion_index=0.1, permeability=0.9,
                surface_area=2, surface_stability=0.95,
                tension_score=0.15, tension_class="open",
            ),
        ]
        t = cst.surface_tension_trend(results)
        assert t.direction == "decreasing"
        assert t.score_delta < 0

    def test_stable_trend(self):
        r1 = cst.SurfaceTensionResult(
            window_commits=10, window_hours=10.0,
            boundary_ratio=0.25, coupling_depth=2.0,
            cohesion_index=0.4, permeability=0.6,
            surface_area=5, surface_stability=0.8,
            tension_score=0.45, tension_class="cohesive",
        )
        r2 = cst.SurfaceTensionResult(
            window_commits=10, window_hours=10.0,
            boundary_ratio=0.26, coupling_depth=2.1,
            cohesion_index=0.41, permeability=0.59,
            surface_area=5, surface_stability=0.79,
            tension_score=0.47, tension_class="cohesive",
        )
        t = cst.surface_tension_trend([r1, r2])
        assert t.direction == "stable"
        assert abs(t.score_delta) < 0.05


# ---------------------------------------------------------------------------
# Integration: round-trip scenario
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_pipeline(self):
        """End-to-end: generate commits, compute, report, trend."""
        # Phase 1: low tension
        phase1 = [
            _commit(
                f"p1c{i}", i,
                files=[f"iamai/internal/mod_{i % 4}.py"],
            )
            for i in range(10)
        ]
        r1 = cst.compute_surface_tension(phase1)
        assert r1.tension_class == "open"

        # Phase 2: increasing tension
        phase2 = [
            _commit(
                f"p2c{i}", 10 + i,
                files=[f"iamai/api/v{i % 3}.py", f"iamai/core/d_{i}.py", f"iamai/db/q_{i}.py"],
                boundary=[f"iamai/api/v{i % 3}.py"],
                internal=[f"iamai/core/d_{i}.py", f"iamai/db/q_{i}.py"],
            )
            for i in range(10)
        ]
        r2 = cst.compute_surface_tension(phase2)
        assert r2.tension_score > r1.tension_score

        # Trend across phases
        t = cst.surface_tension_trend([r1, r2])
        assert t.direction == "increasing"

        # Reports are valid strings
        rep1 = cst.surface_tension_report(r1)
        rep2 = cst.surface_tension_report(r2)
        assert "open" in rep1
        assert r2.tension_class in rep2
