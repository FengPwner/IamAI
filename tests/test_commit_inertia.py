#!/usr/bin/env python3
"""Tests for commit_inertia.py — codebase inertia / change-resistance analysis."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_inertia as ci

# ---------------------------------------------------------------------------
# Reference time
# ---------------------------------------------------------------------------
REF = datetime(2026, 11, 11, 2, 0, 0)  # Wed 2026-11-11 02:00 UTC


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _file(path="iamai/foo.py", lines=200, complexity=10, coupling=4,
          test_coverage=0.8, last_changed=None, area=""):
    if last_changed is None:
        last_changed = REF - timedelta(days=1)
    return ci.FileInfo(
        path=path, lines=lines, complexity=complexity,
        coupling=coupling, test_coverage=test_coverage,
        last_changed=last_changed, area=area,
    )


# ---------------------------------------------------------------------------
# FileInfo
# ---------------------------------------------------------------------------

class TestFileInfo:
    def test_area_from_path(self):
        f = ci.FileInfo(path="iamai/foo.py")
        assert f.area == "iamai"

    def test_area_explicit(self):
        f = ci.FileInfo(path="iamai/foo.py", area="custom")
        assert f.area == "custom"

    def test_area_no_slash(self):
        f = ci.FileInfo(path="README.md")
        assert f.area == ""

    def test_coverage_clamped_high(self):
        f = ci.FileInfo(path="x.py", test_coverage=1.5)
        assert f.test_coverage == 1.0

    def test_coverage_clamped_low(self):
        f = ci.FileInfo(path="x.py", test_coverage=-0.3)
        assert f.test_coverage == 0.0

    def test_default_values(self):
        f = ci.FileInfo(path="x.py")
        assert f.lines == 0
        assert f.complexity == 1
        assert f.coupling == 0
        assert f.test_coverage == 0.0
        assert f.last_changed is None


# ---------------------------------------------------------------------------
# compute_mass
# ---------------------------------------------------------------------------

class TestComputeMass:
    def test_zero_lines(self):
        assert ci.compute_mass(0, 10, 5) == 0.0

    def test_zero_complexity(self):
        # complexity=0 → norm=0 → mass=0
        assert ci.compute_mass(200, 0, 5) == 0.0

    def test_reference_file(self):
        # lines=500, complexity=20, coupling=10 → 1.0 * 1.0 * 2.0 = 2.0
        m = ci.compute_mass(500, 20, 10)
        assert abs(m - 2.0) < 1e-9

    def test_small_file(self):
        m = ci.compute_mass(50, 2, 0)
        assert 0 < m < 1.0

    def test_large_heavy_file(self):
        m = ci.compute_mass(2000, 50, 20)
        assert m > 10.0

    def test_coupling_amplifies(self):
        m_low = ci.compute_mass(200, 10, 0)
        m_high = ci.compute_mass(200, 10, 10)
        assert m_high > m_low

    def test_linear_in_lines(self):
        m1 = ci.compute_mass(100, 10, 5)
        m2 = ci.compute_mass(200, 10, 5)
        assert abs(m2 / m1 - 2.0) < 1e-9


# ---------------------------------------------------------------------------
# compute_friction
# ---------------------------------------------------------------------------

class TestComputeFriction:
    def test_zero_coupling(self):
        assert ci.compute_friction(0) == 0.0

    def test_negative_coupling(self):
        assert ci.compute_friction(-3) == 0.0

    def test_high_coupling_saturates(self):
        assert ci.compute_friction(8) == 1.0

    def test_very_high_coupling(self):
        assert ci.compute_friction(100) == 1.0

    def test_low_coupling(self):
        f = ci.compute_friction(1)
        assert 0 < f < 0.5

    def test_medium_coupling(self):
        f = ci.compute_friction(5)
        assert 0.4 < f < 0.8

    def test_monotonic(self):
        prev = 0.0
        for c in range(0, 12):
            curr = ci.compute_friction(c)
            assert curr >= prev
            prev = curr


# ---------------------------------------------------------------------------
# compute_velocity_score
# ---------------------------------------------------------------------------

class TestComputeVelocityScore:
    def test_zero(self):
        assert ci.compute_velocity_score(0) == 0.0

    def test_negative(self):
        assert ci.compute_velocity_score(-1) == 0.0

    def test_at_threshold(self):
        assert ci.compute_velocity_score(1.0) == 1.0

    def test_above_threshold(self):
        assert ci.compute_velocity_score(5.0) == 1.0

    def test_half(self):
        v = ci.compute_velocity_score(0.5)
        assert abs(v - 0.5) < 1e-9

    def test_monotonic(self):
        rates = [0, 0.1, 0.25, 0.5, 0.75, 1.0, 2.0]
        prev = -1.0
        for r in rates:
            curr = ci.compute_velocity_score(r)
            assert curr >= prev
            prev = curr


# ---------------------------------------------------------------------------
# compute_static_inertia
# ---------------------------------------------------------------------------

class TestComputeStaticInertia:
    def test_fresh_small_decoupled(self):
        si = ci.compute_static_inertia(0, 0, 0)
        assert si == 0.0

    def test_very_stale(self):
        si = ci.compute_static_inertia(365, 10.0, 1.0)
        assert si >= 0.7

    def test_bounded_01(self):
        si = ci.compute_static_inertia(1000, 100, 1.0)
        assert 0.0 <= si <= 1.0

    def test_mass_contributes(self):
        si_low = ci.compute_static_inertia(30, 0.1, 0.5)
        si_high = ci.compute_static_inertia(30, 10.0, 0.5)
        assert si_high > si_low

    def test_friction_contributes(self):
        si_low = ci.compute_static_inertia(30, 5.0, 0.1)
        si_high = ci.compute_static_inertia(30, 5.0, 0.9)
        assert si_high > si_low

    def test_staleness_logarithmic(self):
        si_10 = ci.compute_static_inertia(10, 5.0, 0.5)
        si_100 = ci.compute_static_inertia(100, 5.0, 0.5)
        si_1000 = ci.compute_static_inertia(1000, 5.0, 0.5)
        # Log scale: 10→100 gap similar to 100→1000 gap
        gap1 = si_100 - si_10
        gap2 = si_1000 - si_100
        assert abs(gap1 - gap2) < 0.25  # rough log behaviour


# ---------------------------------------------------------------------------
# compute_dynamic_inertia
# ---------------------------------------------------------------------------

class TestComputeDynamicInertia:
    def test_low_everything(self):
        di = ci.compute_dynamic_inertia(0.1, 0.0, 1.0, 0.0)
        assert di < 0.1

    def test_high_mass_high_friction_low_tests(self):
        di = ci.compute_dynamic_inertia(20.0, 1.0, 0.0, 0.0)
        assert di > 0.5

    def test_momentum_reduces(self):
        di_low = ci.compute_dynamic_inertia(5.0, 0.5, 0.5, 0.0)
        di_high = ci.compute_dynamic_inertia(5.0, 0.5, 0.5, 10.0)
        assert di_high < di_low

    def test_test_coverage_reduces(self):
        di_low = ci.compute_dynamic_inertia(5.0, 0.5, 0.9, 0.0)
        di_high = ci.compute_dynamic_inertia(5.0, 0.5, 0.1, 0.0)
        assert di_high > di_low

    def test_bounded_01(self):
        di = ci.compute_dynamic_inertia(100, 1.0, 0.0, 0.0)
        assert 0.0 <= di <= 1.0


# ---------------------------------------------------------------------------
# classify_inertia
# ---------------------------------------------------------------------------

class TestClassifyInertia:
    def test_frozen(self):
        assert ci.classify_inertia(0.85) == "frozen"

    def test_frozen_boundary(self):
        assert ci.classify_inertia(0.80) == "frozen"

    def test_rigid(self):
        assert ci.classify_inertia(0.65) == "rigid"

    def test_rigid_boundary(self):
        assert ci.classify_inertia(0.60) == "rigid"

    def test_stiff(self):
        assert ci.classify_inertia(0.50) == "stiff"

    def test_flexible(self):
        assert ci.classify_inertia(0.30) == "flexible"

    def test_fluid(self):
        assert ci.classify_inertia(0.10) == "fluid"

    def test_fluid_zero(self):
        assert ci.classify_inertia(0.0) == "fluid"

    def test_clamped_above(self):
        assert ci.classify_inertia(1.5) == "frozen"

    def test_clamped_below(self):
        assert ci.classify_inertia(-0.5) == "fluid"

    def test_all_classes_represented(self):
        scores = [0.9, 0.7, 0.5, 0.3, 0.1]
        classes = [ci.classify_inertia(s) for s in scores]
        assert classes == ["frozen", "rigid", "stiff", "flexible", "fluid"]


# ---------------------------------------------------------------------------
# compute_inertia (integration)
# ---------------------------------------------------------------------------

class TestComputeInertia:
    def test_active_small_file(self):
        """Small, well-tested, actively changing file → fluid/flexible."""
        f = _file(lines=50, complexity=3, coupling=1,
                  test_coverage=0.95, last_changed=REF - timedelta(hours=2))
        r = ci.compute_inertia(f, commits_per_day=3.0, now=REF)
        assert r.inertia_class in ("fluid", "flexible")
        assert r.inertia_score < 0.4

    def test_stale_heavy_file(self):
        """Large, complex, stale, coupled file → frozen/rigid."""
        f = _file(lines=1500, complexity=40, coupling=15,
                  test_coverage=0.2, last_changed=REF - timedelta(days=180))
        r = ci.compute_inertia(f, commits_per_day=0.0, now=REF)
        assert r.inertia_class in ("frozen", "rigid")
        assert r.inertia_score > 0.5

    def test_staleness_computed(self):
        f = _file(last_changed=REF - timedelta(days=7))
        r = ci.compute_inertia(f, now=REF)
        assert abs(r.staleness_days - 7.0) < 0.01

    def test_no_last_changed(self):
        f = ci.FileInfo(path="x.py", lines=100, complexity=5, coupling=2)
        r = ci.compute_inertia(f, commits_per_day=0.5, now=REF)
        assert r.staleness_days == 0.0
        assert r.static_inertia >= 0  # no staleness contribution

    def test_zero_velocity_uses_static(self):
        f = _file(last_changed=REF - timedelta(days=30))
        r = ci.compute_inertia(f, commits_per_day=0.0, now=REF)
        # With zero velocity, score == static_inertia
        assert abs(r.inertia_score - r.static_inertia) < 1e-6

    def test_result_fields(self):
        r = ci.compute_inertia(_file(), commits_per_day=1.0, now=REF)
        assert r.path == "iamai/foo.py"
        assert r.area == "iamai"
        assert isinstance(r.mass, float)
        assert isinstance(r.velocity, float)
        assert isinstance(r.friction_coefficient, float)
        assert isinstance(r.momentum, float)
        assert 0.0 <= r.inertia_score <= 1.0
        assert r.inertia_class in ci.INERTIA_CLASSES

    def test_details_populated(self):
        f = _file(lines=300, complexity=15, coupling=6)
        r = ci.compute_inertia(f, commits_per_day=2.0, now=REF)
        assert r.details["lines"] == 300
        assert r.details["complexity"] == 15
        assert r.details["coupling"] == 6
        assert r.details["commits_per_day"] == 2.0

    def test_momentum_is_mass_times_velocity(self):
        f = _file(lines=200, complexity=10, coupling=4)
        r = ci.compute_inertia(f, commits_per_day=0.5, now=REF)
        expected = r.mass * r.velocity
        assert abs(r.momentum - expected) < 1e-3


# ---------------------------------------------------------------------------
# area_inertia
# ---------------------------------------------------------------------------

class TestAreaInertia:
    def _make_results(self):
        files = [
            _file("iamai/a.py", lines=100, complexity=5, coupling=2,
                  test_coverage=0.9, last_changed=REF - timedelta(days=1)),
            _file("iamai/b.py", lines=500, complexity=20, coupling=8,
                  test_coverage=0.3, last_changed=REF - timedelta(days=60)),
            _file("iamai/c.py", lines=50, complexity=2, coupling=0,
                  test_coverage=1.0, last_changed=REF - timedelta(hours=6)),
        ]
        return [ci.compute_inertia(f, commits_per_day=1.0, now=REF) for f in files]

    def test_basic_aggregation(self):
        results = self._make_results()
        a = ci.area_inertia(results)
        assert a.area == "iamai"
        assert a.file_count == 3
        assert 0.0 <= a.mean_inertia <= 1.0
        assert a.area_class in ci.INERTIA_CLASSES

    def test_frozen_fluid_counts(self):
        results = self._make_results()
        a = ci.area_inertia(results)
        assert a.frozen_count + a.fluid_count <= a.file_count

    def test_heaviest_and_stillest(self):
        results = self._make_results()
        a = ci.area_inertia(results)
        assert "b.py" in a.heaviest_file  # 500 lines, complexity 20
        assert "b.py" in a.stillest_file  # 60 days stale

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            ci.area_inertia([])

    def test_custom_area(self):
        results = self._make_results()
        a = ci.area_inertia(results, area="custom_area")
        assert a.area == "custom_area"

    def test_details_populated(self):
        results = self._make_results()
        a = ci.area_inertia(results)
        assert "median_inertia" in a.details
        assert "frozen_fraction" in a.details
        assert "fluid_fraction" in a.details
        assert 0 <= a.details["frozen_fraction"] <= 1.0
        assert 0 <= a.details["fluid_fraction"] <= 1.0


# ---------------------------------------------------------------------------
# inertia_trend
# ---------------------------------------------------------------------------

class TestInertiaTrend:
    def test_increasing(self):
        snaps = [0.3, 0.4, 0.5, 0.6, 0.7]
        t = ci.inertia_trend(snaps)
        assert t.direction == "increasing"
        assert t.slope > 0

    def test_decreasing(self):
        snaps = [0.7, 0.6, 0.5, 0.4, 0.3]
        t = ci.inertia_trend(snaps)
        assert t.direction == "decreasing"
        assert t.slope < 0

    def test_stable(self):
        snaps = [0.5, 0.51, 0.50, 0.49, 0.50]
        t = ci.inertia_trend(snaps)
        assert t.direction == "stable"
        assert abs(t.slope) < 0.01

    def test_single_snapshot(self):
        t = ci.inertia_trend([0.5])
        assert t.direction == "stable"
        assert t.measurements == 1
        assert "insufficient" in t.interpretation.lower()

    def test_two_snapshots(self):
        t = ci.inertia_trend([0.3, 0.7])
        assert t.direction == "increasing"
        assert t.delta > 0

    def test_delta_computed(self):
        snaps = [0.2, 0.3, 0.4]
        t = ci.inertia_trend(snaps)
        assert abs(t.delta - 0.2) < 1e-6

    def test_interpretation_increasing(self):
        t = ci.inertia_trend([0.2, 0.4, 0.6])
        assert "resistant" in t.interpretation.lower() or "rigidity" in t.interpretation.lower()

    def test_interpretation_decreasing(self):
        t = ci.inertia_trend([0.6, 0.4, 0.2])
        assert "easier" in t.interpretation.lower() or "reduced" in t.interpretation.lower()

    def test_interpretation_stable(self):
        t = ci.inertia_trend([0.5, 0.5, 0.5])
        assert "steady" in t.interpretation.lower() or "stable" in t.interpretation.lower()


# ---------------------------------------------------------------------------
# inertia_report
# ---------------------------------------------------------------------------

class TestInertiaReport:
    def test_report_contains_key_fields(self):
        f = _file("iamai/widget.py", lines=300, complexity=12, coupling=5)
        r = ci.compute_inertia(f, commits_per_day=1.5, now=REF)
        report = ci.inertia_report(r)
        assert "widget.py" in report
        assert "iamai" in report
        assert r.inertia_class in report
        assert "Mass" in report
        assert "Velocity" in report
        assert "Friction" in report
        assert "Staleness" in report

    def test_report_not_empty(self):
        r = ci.compute_inertia(_file(), now=REF)
        assert len(ci.inertia_report(r)) > 50


# ---------------------------------------------------------------------------
# area_report
# ---------------------------------------------------------------------------

class TestAreaReport:
    def test_report_contains_key_fields(self):
        results = [
            ci.compute_inertia(_file("iamai/a.py"), now=REF),
            ci.compute_inertia(_file("iamai/b.py", lines=500), now=REF),
        ]
        a = ci.area_inertia(results)
        report = ci.area_report(a)
        assert "iamai" in report
        assert "Files: 2" in report
        assert a.area_class in report
        assert "Heaviest" in report
        assert "Stillest" in report


# ---------------------------------------------------------------------------
# Edge cases and integration
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_file(self):
        f = ci.FileInfo(path="empty.py", lines=0, complexity=0, coupling=0)
        r = ci.compute_inertia(f, now=REF)
        assert r.mass == 0.0
        assert r.inertia_class in ci.INERTIA_CLASSES

    def test_massive_file(self):
        f = ci.FileInfo(
            path="iamai/mega.py", lines=10000, complexity=100,
            coupling=50, test_coverage=0.1,
            last_changed=REF - timedelta(days=365),
        )
        r = ci.compute_inertia(f, commits_per_day=0.0, now=REF)
        assert r.inertia_score > 0.5
        assert r.inertia_class in ("frozen", "rigid")

    def test_very_active_file(self):
        f = ci.FileInfo(
            path="iamai/hot.py", lines=100, complexity=5,
            coupling=2, test_coverage=0.95,
            last_changed=REF - timedelta(minutes=30),
        )
        r = ci.compute_inertia(f, commits_per_day=10.0, now=REF)
        assert r.inertia_score < 0.3
        assert r.inertia_class in ("fluid", "flexible")

    def test_constants_consistency(self):
        """Verify threshold table matches classify_inertia."""
        for threshold, label in ci._THRESHOLDS:
            assert ci.classify_inertia(threshold) == label

    def test_inertia_classes_tuple(self):
        assert len(ci.INERTIA_CLASSES) == 5
        assert ci.INERTIA_CLASSES == ("frozen", "rigid", "stiff", "flexible", "fluid")

    def test_full_pipeline(self):
        """End-to-end: files → compute → aggregate → trend → report."""
        # Three files of varying inertia
        files = [
            ci.FileInfo("iamai/old.py", lines=800, complexity=30,
                        coupling=12, test_coverage=0.3,
                        last_changed=REF - timedelta(days=200)),
            ci.FileInfo("iamai/mid.py", lines=200, complexity=8,
                        coupling=3, test_coverage=0.7,
                        last_changed=REF - timedelta(days=14)),
            ci.FileInfo("iamai/new.py", lines=50, complexity=3,
                        coupling=1, test_coverage=0.95,
                        last_changed=REF - timedelta(hours=12)),
        ]
        results = [
            ci.compute_inertia(f, commits_per_day=0.5, now=REF)
            for f in files
        ]
        # Individual reports
        for r in results:
            assert ci.inertia_report(r)

        # Aggregation
        area = ci.area_inertia(results, area="iamai")
        assert ci.area_report(area)
        assert area.file_count == 3

        # Trend (simulate two snapshots)
        snap1 = area.mean_inertia
        snap2 = snap1 - 0.05  # slight improvement
        t = ci.inertia_trend([snap1, snap2])
        assert t.direction in ("stable", "decreasing")

    def test_area_inertia_single_file(self):
        f = _file("iamai/solo.py")
        r = ci.compute_inertia(f, now=REF)
        a = ci.area_inertia([r])
        assert a.file_count == 1
        assert a.mean_inertia == r.inertia_score

    def test_velocity_blending(self):
        """File with some velocity should use blended score."""
        f = _file(lines=300, complexity=10, coupling=4,
                  test_coverage=0.8, last_changed=REF - timedelta(days=5))
        r = ci.compute_inertia(f, commits_per_day=0.5, now=REF)
        # Score should be between static and dynamic
        assert min(r.static_inertia, r.dynamic_inertia) - 0.01 <= r.inertia_score
        assert r.inertia_score <= max(r.static_inertia, r.dynamic_inertia) + 0.01
