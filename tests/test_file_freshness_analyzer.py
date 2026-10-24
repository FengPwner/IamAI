#!/usr/bin/env python3
"""tests for scripts/file_freshness_analyzer.py — file freshness analyzer."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from file_freshness_analyzer import (
    compute_median_age,
    compute_stale_ratio,
    compute_critical_freshness,
    compute_age_dispersion,
    score_median_age,
    score_stale_ratio,
    score_critical_freshness,
    score_dispersion,
    compute_freshness_score,
    format_bar,
    format_report,
)


# ── median age computation ───────────────────────────────────────────


class TestComputeMedianAge:
    def test_single_file(self):
        ages = {"file.py": 10}
        assert compute_median_age(ages) == 10.0

    def test_two_files(self):
        ages = {"a.py": 5, "b.py": 15}
        assert compute_median_age(ages) == 10.0

    def test_odd_count(self):
        ages = {"a.py": 3, "b.py": 7, "c.py": 20}
        assert compute_median_age(ages) == 7.0

    def test_even_count(self):
        ages = {"a.py": 2, "b.py": 4, "c.py": 8, "d.py": 16}
        assert compute_median_age(ages) == 6.0

    def test_empty_dict(self):
        assert compute_median_age({}) == 0.0

    def test_all_same_age(self):
        ages = {"a.py": 10, "b.py": 10, "c.py": 10}
        assert compute_median_age(ages) == 10.0


# ── stale ratio computation ──────────────────────────────────────────


class TestComputeStaleRatio:
    def test_no_stale_files(self):
        ages = {"a.py": 5, "b.py": 10, "c.py": 15}
        assert compute_stale_ratio(ages, stale_days=30) == 0.0

    def test_all_stale(self):
        ages = {"a.py": 35, "b.py": 40, "c.py": 50}
        assert compute_stale_ratio(ages, stale_days=30) == 100.0

    def test_half_stale(self):
        ages = {"a.py": 10, "b.py": 20, "c.py": 35, "d.py": 40}
        assert compute_stale_ratio(ages, stale_days=30) == 50.0

    def test_custom_threshold(self):
        ages = {"a.py": 5, "b.py": 15, "c.py": 25}
        assert compute_stale_ratio(ages, stale_days=10) == 100.0 * (2 / 3)

    def test_empty_dict(self):
        assert compute_stale_ratio({}, stale_days=30) == 0.0

    def test_boundary_case(self):
        ages = {"a.py": 29, "b.py": 30, "c.py": 31}
        # 30 and 31 are stale (>= 30), so 2/3
        ratio = compute_stale_ratio(ages, stale_days=30)
        assert abs(ratio - 66.666) < 0.1


# ── critical freshness computation ───────────────────────────────────


class TestComputeCriticalFreshness:
    def test_all_critical_files(self):
        ages = {
            "tests/test_a.py": 2,
            "tools/tool_a.py": 4,
            "scripts/script_a.py": 6,
            "docs/readme.md": 8,
        }
        median = compute_critical_freshness(ages)
        assert median == 5.0  # median of [2, 4, 6, 8]

    def test_mixed_files(self):
        ages = {
            "src/main.py": 100,
            "tests/test_a.py": 5,
            "tools/tool_a.py": 10,
            "other.txt": 50,
        }
        median = compute_critical_freshness(ages)
        assert median == 7.5  # median of [5, 10]

    def test_no_critical_files(self):
        ages = {"src/a.py": 10, "src/b.py": 20}
        assert compute_critical_freshness(ages) == 0.0

    def test_empty_dict(self):
        assert compute_critical_freshness({}) == 0.0

    def test_only_tests(self):
        ages = {"tests/a.py": 3, "tests/b.py": 7}
        assert compute_critical_freshness(ages) == 5.0


# ── age dispersion computation ────────────────────────────────────────


class TestComputeAgeDispersion:
    def test_uniform_ages(self):
        ages = {"a.py": 10, "b.py": 10, "c.py": 10}
        assert compute_age_dispersion(ages) == 0.0

    def test_two_files_different(self):
        ages = {"a.py": 0, "b.py": 100}
        dispersion = compute_age_dispersion(ages)
        # gini = |0-100| / (2*2*50) = 100/200 = 0.5
        assert abs(dispersion - 0.5) < 0.01

    def test_spread_ages(self):
        ages = {"a.py": 10, "b.py": 20, "c.py": 30}
        dispersion = compute_age_dispersion(ages)
        # mean = 20, total diff = |10-20| + |10-30| + |20-30| = 10+20+10 = 40
        # gini = 40 / (9 * 20) = 40/180 ≈ 0.222
        assert 0.2 < dispersion < 0.3

    def test_single_file(self):
        ages = {"a.py": 10}
        assert compute_age_dispersion(ages) == 0.0

    def test_empty_dict(self):
        assert compute_age_dispersion({}) == 0.0

    def test_max_dispersion(self):
        ages = {"a.py": 0, "b.py": 0, "c.py": 1000}
        dispersion = compute_age_dispersion(ages)
        # highly skewed
        assert dispersion > 0.5


# ── scoring functions ────────────────────────────────────────────────


class TestScoring:
    def test_score_median_age_fresh(self):
        assert score_median_age(2) == 0
        assert score_median_age(5) == 5
        assert score_median_age(10) == 10

    def test_score_median_age_stale(self):
        assert score_median_age(25) == 15
        assert score_median_age(45) == 20
        assert score_median_age(100) == 25

    def test_score_stale_ratio_low(self):
        assert score_stale_ratio(5) == 0
        assert score_stale_ratio(20) == 5

    def test_score_stale_ratio_high(self):
        assert score_stale_ratio(50) == 15
        assert score_stale_ratio(90) == 25

    def test_score_critical_freshness_good(self):
        assert score_critical_freshness(1) == 0
        assert score_critical_freshness(4) == 5

    def test_score_critical_freshness_bad(self):
        assert score_critical_freshness(30) == 20
        assert score_critical_freshness(50) == 25

    def test_score_dispersion_uniform(self):
        assert score_dispersion(0.05) == 0
        assert score_dispersion(0.15) == 5

    def test_score_dispersion_skewed(self):
        assert score_dispersion(0.6) == 20
        assert score_dispersion(0.8) == 25


# ── full score computation ───────────────────────────────────────────


class TestComputeFreshnessScore:
    def test_fresh_repo(self):
        ages = {
            "tests/a.py": 1,
            "tools/b.py": 2,
            "scripts/c.py": 3,
            "docs/d.md": 4,
        }
        result = compute_freshness_score(ages, stale_days=30)
        assert result["grade"] == "FRESH"
        assert result["exit_code"] == 0
        assert result["total"] <= 20
        assert result["file_count"] == 4

    def test_healthy_repo(self):
        ages = {
            "tests/a.py": 5,
            "tools/b.py": 10,
            "src/c.py": 20,
            "docs/d.md": 15,
        }
        result = compute_freshness_score(ages, stale_days=30)
        assert result["grade"] in ["FRESH", "HEALTHY"]
        assert result["exit_code"] == 0

    def test_stale_repo(self):
        ages = {
            "tests/a.py": 40,
            "tools/b.py": 50,
            "src/c.py": 60,
            "docs/d.md": 70,
        }
        result = compute_freshness_score(ages, stale_days=30)
        # median=55 (20), stale=100% (25), critical=55 (25), dispersion≈0.10 (0)
        # total ≈ 70-80, ANCIENT grade
        assert result["grade"] in ["STALE", "ANCIENT"]
        assert result["exit_code"] in [1, 2]

    def test_ancient_repo(self):
        ages = {
            "a.py": 100,
            "b.py": 150,
            "c.py": 200,
            "d.py": 250,
        }
        result = compute_freshness_score(ages, stale_days=30)
        # no critical files, so critical_freshness=0; dispersion moderate
        # total around 60, STALE grade
        assert result["grade"] in ["STALE", "ANCIENT"]
        assert result["exit_code"] in [1, 2]

    def test_empty_ages(self):
        result = compute_freshness_score({}, stale_days=30)
        assert result["grade"] == "FRESH"
        assert result["total"] == 0
        assert result["file_count"] == 0

    def test_custom_stale_days(self):
        ages = {"a.py": 15, "b.py": 25}
        result = compute_freshness_score(ages, stale_days=20)
        assert "stale_ratio_pct" in result
        assert result["stale_ratio_pct"] == 50.0


# ── formatting ───────────────────────────────────────────────────────


class TestFormatting:
    def test_format_bar_zero(self):
        bar = format_bar(0, max_value=25, width=20)
        assert bar == "[" + "." * 20 + "]"

    def test_format_bar_full(self):
        bar = format_bar(25, max_value=25, width=20)
        assert bar == "[" + "#" * 20 + "]"

    def test_format_bar_half(self):
        bar = format_bar(12, max_value=25, width=20)
        assert "#" in bar
        assert "." in bar
        assert len(bar) == 22  # 20 + brackets

    def test_format_report_basic(self):
        result = {
            "file_count": 10,
            "stale_days": 30,
            "median_file_age": 5,
            "stale_file_ratio": 10,
            "critical_file_freshness": 5,
            "age_dispersion": 5,
            "total": 25,
            "grade": "HEALTHY",
            "median_days": 7.5,
            "stale_ratio_pct": 20.0,
            "critical_median_days": 5.0,
            "dispersion_gini": 0.15,
        }
        report = format_report(result)
        assert "file freshness analyzer" in report
        assert "files analyzed: 10" in report
        assert "HEALTHY" in report
        assert "25/100" in report


# ── edge cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    def test_very_large_ages(self):
        ages = {"a.py": 1000, "b.py": 2000}
        result = compute_freshness_score(ages, stale_days=30)
        # median=1500 (25), stale=100% (25), no critical (0), dispersion=0.33 (10)
        # total=60, STALE
        assert result["grade"] in ["STALE", "ANCIENT"]
        assert result["exit_code"] in [1, 2]

    def test_single_file_fresh(self):
        ages = {"a.py": 1}
        result = compute_freshness_score(ages, stale_days=30)
        assert result["grade"] == "FRESH"

    def test_zero_age_files(self):
        ages = {"a.py": 0, "b.py": 0, "c.py": 0}
        result = compute_freshness_score(ages, stale_days=30)
        assert result["median_days"] == 0.0
        assert result["stale_ratio_pct"] == 0.0
