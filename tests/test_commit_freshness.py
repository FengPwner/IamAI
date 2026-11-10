#!/usr/bin/env python3
"""Tests for commit_freshness.py — codebase freshness measurement."""

import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_freshness as cf

# ---------------------------------------------------------------------------
# Reference time for all tests
# ---------------------------------------------------------------------------
REF = datetime(2026, 11, 10, 12, 0, 0)  # Mon 2026-11-10 12:00 UTC


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _f(path, hours_ago):
    """Create a FileAge touched *hours_ago* hours before REF."""
    from datetime import timedelta
    return cf.FileAge(path=path, last_touched=REF - timedelta(hours=hours_ago))


# ---------------------------------------------------------------------------
# FileAge.age_hours
# ---------------------------------------------------------------------------

class TestFileAgeAgeHours:
    def test_zero_hours(self):
        fa = _f("a.py", 0)
        assert fa.age_hours(REF) == 0.0

    def test_positive_hours(self):
        fa = _f("a.py", 48)
        assert fa.age_hours(REF) == 48.0

    def test_negative_clamped(self):
        """Future timestamps clamp to 0."""
        from datetime import timedelta
        fa = cf.FileAge(path="a.py", last_touched=REF + timedelta(hours=5))
        assert fa.age_hours(REF) == 0.0


# ---------------------------------------------------------------------------
# FileAge.area
# ---------------------------------------------------------------------------

class TestFileAgeArea:
    def test_nested(self):
        assert _f("iamai/foo.py", 1).area() == "iamai"

    def test_root_file(self):
        assert _f("README.md", 1).area() == "."

    def test_deep_nested(self):
        assert _f("src/core/utils.py", 1).area() == "src"

    def test_backslash_normalised(self):
        fa = cf.FileAge(path="iamai\\bar.py", last_touched=REF)
        assert fa.area() == "iamai"


# ---------------------------------------------------------------------------
# classify_freshness
# ---------------------------------------------------------------------------

class TestClassifyFreshness:
    def test_fresh_at_boundary(self):
        assert cf.classify_freshness(0.80) == "fresh"

    def test_fresh_high(self):
        assert cf.classify_freshness(1.0) == "fresh"

    def test_warm_at_boundary(self):
        assert cf.classify_freshness(0.60) == "warm"

    def test_warm_mid(self):
        assert cf.classify_freshness(0.70) == "warm"

    def test_tepid_at_boundary(self):
        assert cf.classify_freshness(0.40) == "tepid"

    def test_tepid_mid(self):
        assert cf.classify_freshness(0.50) == "tepid"

    def test_stale_at_boundary(self):
        assert cf.classify_freshness(0.20) == "stale"

    def test_stale_low(self):
        assert cf.classify_freshness(0.25) == "stale"

    def test_frozen_at_zero(self):
        assert cf.classify_freshness(0.0) == "frozen"

    def test_frozen_low(self):
        assert cf.classify_freshness(0.19) == "frozen"


# ---------------------------------------------------------------------------
# compute_freshness — empty input
# ---------------------------------------------------------------------------

class TestComputeFreshnessEmpty:
    def test_empty_returns_frozen(self):
        r = cf.compute_freshness([], reference_time=REF)
        assert r.freshness_class == "frozen"
        assert r.total_files == 0
        assert r.freshness_score == 0.0


# ---------------------------------------------------------------------------
# compute_freshness — all hot
# ---------------------------------------------------------------------------

class TestComputeFreshnessAllHot:
    def test_all_very_recent(self):
        files = [_f("iamai/a.py", 1), _f("iamai/b.py", 2), _f("tests/t.py", 3)]
        r = cf.compute_freshness(files, reference_time=REF)
        assert r.freshness_class == "fresh"
        assert r.freshness_score == 1.0
        assert r.hot_files == 3
        assert r.stale_files == 0

    def test_all_within_horizon(self):
        files = [_f("a.py", 10), _f("b.py", 20), _f("c.py", 50)]
        r = cf.compute_freshness(files, reference_time=REF, fresh_horizon_hours=72.0)
        assert r.freshness_score == 1.0
        assert r.freshness_class == "fresh"


# ---------------------------------------------------------------------------
# compute_freshness — all stale
# ---------------------------------------------------------------------------

class TestComputeFreshnessAllStale:
    def test_all_ancient(self):
        files = [_f("old/a.py", 500), _f("old/b.py", 600), _f("old/c.py", 700)]
        r = cf.compute_freshness(files, reference_time=REF)
        assert r.freshness_score == 0.0
        assert r.freshness_class == "frozen"
        assert r.stale_files == 3
        assert r.hot_files == 0
        assert r.stale_fraction == 1.0


# ---------------------------------------------------------------------------
# compute_freshness — mixed
# ---------------------------------------------------------------------------

class TestComputeFreshnessMixed:
    def test_mixed_ages(self):
        files = [
            _f("iamai/a.py", 1),     # hot
            _f("iamai/b.py", 48),    # within horizon
            _f("tests/t.py", 200),   # stale
            _f("docs/d.md", 500),    # very stale
        ]
        r = cf.compute_freshness(files, reference_time=REF)
        assert 0.0 < r.freshness_score < 1.0
        assert r.total_files == 4
        assert r.hot_files == 1  # only the 1-hour-old file
        assert r.stale_files == 2  # 200h and 500h

    def test_score_decay_is_linear(self):
        """A file at the midpoint between horizon and stale threshold
        should contribute ~0.5."""
        # horizon=72, stale=168 → midpoint = 120h
        files = [_f("a.py", 120)]
        r = cf.compute_freshness(files, reference_time=REF)
        assert 0.45 < r.freshness_score < 0.55

    def test_mean_age(self):
        files = [_f("a.py", 10), _f("b.py", 20), _f("c.py", 30)]
        r = cf.compute_freshness(files, reference_time=REF)
        assert r.mean_age_hours == 20.0

    def test_median_age_odd(self):
        files = [_f("a.py", 5), _f("b.py", 50), _f("c.py", 10)]
        r = cf.compute_freshness(files, reference_time=REF)
        assert r.median_age_hours == 10.0

    def test_median_age_even(self):
        files = [_f("a.py", 10), _f("b.py", 20)]
        r = cf.compute_freshness(files, reference_time=REF)
        assert r.median_age_hours == 15.0


# ---------------------------------------------------------------------------
# compute_freshness — coldest area
# ---------------------------------------------------------------------------

class TestColdestArea:
    def test_coldest_by_median(self):
        files = [
            _f("iamai/a.py", 1),
            _f("iamai/b.py", 2),
            _f("old/x.py", 400),
            _f("old/y.py", 500),
        ]
        r = cf.compute_freshness(files, reference_time=REF)
        assert r.coldest_area == "old"
        assert r.coldest_area_age_hours > r.area_ages["iamai"]

    def test_single_area(self):
        files = [_f("src/a.py", 5), _f("src/b.py", 10)]
        r = cf.compute_freshness(files, reference_time=REF)
        assert r.coldest_area == "src"

    def test_root_area(self):
        files = [_f("README.md", 2), _f("iamai/a.py", 100)]
        r = cf.compute_freshness(files, reference_time=REF)
        assert r.coldest_area == "iamai"


# ---------------------------------------------------------------------------
# compute_freshness — custom thresholds
# ---------------------------------------------------------------------------

class TestCustomThresholds:
    def test_custom_stale_threshold(self):
        """With stale_hours=48, a 50h-old file is stale."""
        files = [_f("a.py", 50)]
        r = cf.compute_freshness(files, reference_time=REF, stale_hours=48.0)
        assert r.stale_files == 1

    def test_custom_hot_threshold(self):
        """With hot_hours=48, a 47h-old file is hot."""
        files = [_f("a.py", 47)]
        r = cf.compute_freshness(files, reference_time=REF, hot_hours=48.0)
        assert r.hot_files == 1


# ---------------------------------------------------------------------------
# freshness_report
# ---------------------------------------------------------------------------

class TestFreshnessReport:
    def test_report_contains_class(self):
        files = [_f("a.py", 1)]
        r = cf.compute_freshness(files, reference_time=REF)
        report = cf.freshness_report(r)
        assert "fresh" in report

    def test_report_contains_score(self):
        files = [_f("a.py", 120)]
        r = cf.compute_freshness(files, reference_time=REF)
        report = cf.freshness_report(r)
        assert f"{r.freshness_score:.2f}" in report

    def test_report_contains_coldest(self):
        files = [_f("iamai/a.py", 1), _f("old/b.py", 300)]
        r = cf.compute_freshness(files, reference_time=REF)
        report = cf.freshness_report(r)
        assert "old" in report

    def test_report_is_single_line(self):
        files = [_f("a.py", 1)]
        r = cf.compute_freshness(files, reference_time=REF)
        report = cf.freshness_report(r)
        assert "\n" not in report


# ---------------------------------------------------------------------------
# freshness_trend
# ---------------------------------------------------------------------------

class TestFreshnessTrend:
    def test_improving(self):
        r1 = cf.FreshnessResult(
            mean_age_hours=100, median_age_hours=80,
            freshness_score=0.20, stale_fraction=0.80,
            hotspot_ratio=0.10, coldest_area="old",
            coldest_area_age_hours=200, freshness_class="stale",
            total_files=10, stale_files=8, hot_files=1,
        )
        r2 = cf.FreshnessResult(
            mean_age_hours=20, median_age_hours=10,
            freshness_score=0.85, stale_fraction=0.10,
            hotspot_ratio=0.70, coldest_area="old",
            coldest_area_age_hours=50, freshness_class="fresh",
            total_files=10, stale_files=1, hot_files=7,
        )
        t = cf.freshness_trend([r1, r2])
        assert t.direction == "improving"
        assert t.score_delta > 0

    def test_decaying(self):
        r1 = cf.FreshnessResult(
            mean_age_hours=10, median_age_hours=5,
            freshness_score=0.90, stale_fraction=0.05,
            hotspot_ratio=0.80, coldest_area="a",
            coldest_area_age_hours=20, freshness_class="fresh",
            total_files=10, stale_files=0, hot_files=8,
        )
        r2 = cf.FreshnessResult(
            mean_age_hours=200, median_age_hours=180,
            freshness_score=0.10, stale_fraction=0.90,
            hotspot_ratio=0.05, coldest_area="a",
            coldest_area_age_hours=300, freshness_class="frozen",
            total_files=10, stale_files=9, hot_files=0,
        )
        t = cf.freshness_trend([r1, r2])
        assert t.direction == "decaying"
        assert t.score_delta < 0

    def test_stable(self):
        r1 = cf.FreshnessResult(
            mean_age_hours=30, median_age_hours=25,
            freshness_score=0.65, stale_fraction=0.20,
            hotspot_ratio=0.40, coldest_area="x",
            coldest_area_age_hours=80, freshness_class="warm",
            total_files=10, stale_files=2, hot_files=4,
        )
        r2 = cf.FreshnessResult(
            mean_age_hours=28, median_age_hours=24,
            freshness_score=0.66, stale_fraction=0.20,
            hotspot_ratio=0.40, coldest_area="x",
            coldest_area_age_hours=75, freshness_class="warm",
            total_files=10, stale_files=2, hot_files=4,
        )
        t = cf.freshness_trend([r1, r2])
        assert t.direction == "stable"
        assert abs(t.score_delta) < 0.05

    def test_single_result(self):
        r = cf.FreshnessResult(
            mean_age_hours=30, median_age_hours=25,
            freshness_score=0.65, stale_fraction=0.20,
            hotspot_ratio=0.40, coldest_area="x",
            coldest_area_age_hours=80, freshness_class="warm",
            total_files=10, stale_files=2, hot_files=4,
        )
        t = cf.freshness_trend([r])
        assert t.direction == "stable"
        assert t.score_delta == 0.0
        assert t.latest_class == "warm"
        assert t.earliest_class == "warm"

    def test_empty_results(self):
        t = cf.freshness_trend([])
        assert t.direction == "stable"
        assert t.latest_class == "frozen"


# ---------------------------------------------------------------------------
# boundary / edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_file(self):
        files = [_f("lone.py", 5)]
        r = cf.compute_freshness(files, reference_time=REF)
        assert r.total_files == 1
        assert r.mean_age_hours == 5.0
        assert r.median_age_hours == 5.0

    def test_score_clamped_zero(self):
        """Score should not go below 0.0."""
        files = [_f("a.py", 10000)]
        r = cf.compute_freshness(files, reference_time=REF)
        assert r.freshness_score == 0.0

    def test_all_at_stale_boundary(self):
        """Files exactly at stale_hours threshold contribute 0.0."""
        files = [_f("a.py", 168)]
        r = cf.compute_freshness(files, reference_time=REF)
        assert r.freshness_score == 0.0
        # exactly at boundary (not strictly >) → not counted as stale
        assert r.stale_files == 0

    def test_just_past_stale_boundary(self):
        """Files just past stale_hours threshold are stale."""
        files = [_f("a.py", 169)]
        r = cf.compute_freshness(files, reference_time=REF)
        assert r.freshness_score == 0.0
        assert r.stale_files == 1

    def test_all_at_horizon_boundary(self):
        """Files exactly at fresh_horizon contribute 1.0."""
        files = [_f("a.py", 72)]
        r = cf.compute_freshness(files, reference_time=REF)
        assert r.freshness_score == 1.0

    def test_horizon_equals_stale(self):
        """Edge: horizon == stale → no linear zone, just step function."""
        files = [_f("a.py", 50)]
        r = cf.compute_freshness(
            files, reference_time=REF,
            stale_hours=100.0, fresh_horizon_hours=100.0,
        )
        assert r.freshness_score == 1.0  # 50 < 100 → full score
