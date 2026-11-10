#!/usr/bin/env python3
"""Tests for commit_ecology.py — commit ecosystem health measurement."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_ecology as ce


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _c(sha="x", msg="test", files=None, add=10, delete=0):
    """Shorthand factory for CommitInfo."""
    return ce.CommitInfo(
        sha=sha,
        message=msg,
        files=set(files or []),
        additions=add,
        deletions=delete,
    )


# ---------------------------------------------------------------------------
# classify_ecology
# ---------------------------------------------------------------------------

class TestClassifyEcology:
    def test_thriving_at_boundary(self):
        assert ce.classify_ecology(0.80) == "thriving"

    def test_thriving_high(self):
        assert ce.classify_ecology(0.95) == "thriving"

    def test_thriving_at_one(self):
        assert ce.classify_ecology(1.0) == "thriving"

    def test_healthy_lower_boundary(self):
        assert ce.classify_ecology(0.60) == "healthy"

    def test_healthy_upper(self):
        assert ce.classify_ecology(0.79) == "healthy"

    def test_fragile_lower(self):
        assert ce.classify_ecology(0.40) == "fragile"

    def test_fragile_upper(self):
        assert ce.classify_ecology(0.55) == "fragile"

    def test_barren_lower(self):
        assert ce.classify_ecology(0.20) == "barren"

    def test_barren_upper(self):
        assert ce.classify_ecology(0.35) == "barren"

    def test_monoculture_at_zero(self):
        assert ce.classify_ecology(0.0) == "monoculture"

    def test_monoculture_low(self):
        assert ce.classify_ecology(0.15) == "monoculture"

    def test_just_below_healthy(self):
        assert ce.classify_ecology(0.599) == "fragile"

    def test_just_below_barren(self):
        assert ce.classify_ecology(0.199) == "monoculture"

    def test_clamp_above_one(self):
        assert ce.classify_ecology(1.5) == "thriving"

    def test_clamp_below_zero(self):
        assert ce.classify_ecology(-0.5) == "monoculture"


# ---------------------------------------------------------------------------
# species_richness
# ---------------------------------------------------------------------------

class TestSpeciesRichness:
    def test_empty(self):
        assert ce.species_richness([]) == 0

    def test_single_commit_single_file(self):
        assert ce.species_richness([_c(files={"a.py"})]) == 1

    def test_single_commit_multiple_files(self):
        assert ce.species_richness([_c(files={"a.py", "b.py", "c.py"})]) == 3

    def test_multiple_commits_overlapping(self):
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"b.py", "c.py"}),
            _c(files={"c.py", "d.py"}),
        ]
        assert ce.species_richness(commits) == 4

    def test_multiple_commits_no_overlap(self):
        commits = [
            _c(files={"a.py"}),
            _c(files={"b.py"}),
            _c(files={"c.py"}),
        ]
        assert ce.species_richness(commits) == 3

    def test_large_set(self):
        files = {f"file_{i}.py" for i in range(100)}
        assert ce.species_richness([_c(files=files)]) == 100


# ---------------------------------------------------------------------------
# shannon_evenness
# ---------------------------------------------------------------------------

class TestShannonEvenness:
    def test_empty(self):
        assert ce.shannon_evenness([]) == 0.0

    def test_single_file(self):
        """Only one species → no evenness."""
        commits = [_c(files={"a.py"}), _c(files={"a.py"})]
        assert ce.shannon_evenness(commits) == 0.0

    def test_perfectly_even(self):
        """Each file touched equally → evenness near 1.0."""
        commits = [
            _c(files={"a.py", "b.py", "c.py"}),
        ]
        # Each file touched once, perfectly even
        result = ce.shannon_evenness(commits)
        assert result > 0.99

    def test_uneven(self):
        """One file dominates → lower evenness than perfectly even."""
        commits = [
            _c(files={"a.py"}),
            _c(files={"a.py"}),
            _c(files={"a.py"}),
            _c(files={"a.py", "b.py"}),
        ]
        result = ce.shannon_evenness(commits)
        # a: 5 touches, b: 1 → uneven but not zero
        assert result < 0.8
        assert result > 0.3

    def test_two_files_equal(self):
        commits = [
            _c(files={"a.py"}),
            _c(files={"b.py"}),
        ]
        result = ce.shannon_evenness(commits)
        assert result > 0.99

    def test_range(self):
        """Evenness is always in [0, 1]."""
        commits = [
            _c(files={"a.py", "b.py", "c.py"}),
            _c(files={"a.py"}),
            _c(files={"b.py", "c.py"}),
        ]
        result = ce.shannon_evenness(commits)
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# simpson_diversity
# ---------------------------------------------------------------------------

class TestSimpsonDiversity:
    def test_empty(self):
        assert ce.simpson_diversity([]) == 0.0

    def test_single_touch(self):
        """Only one file-touch total → 0."""
        commits = [_c(files={"a.py"})]
        assert ce.simpson_diversity(commits) == 0.0

    def test_two_equal_files(self):
        commits = [_c(files={"a.py", "b.py"})]
        # 2 touches, each p=0.5 → 1 - (0.25+0.25) = 0.5
        result = ce.simpson_diversity(commits)
        assert abs(result - 0.5) < 0.01

    def test_many_equal_files(self):
        files = {f"f{i}.py" for i in range(10)}
        commits = [_c(files=files)]
        # 10 equal touches → 1 - 10*(0.1^2) = 1 - 0.1 = 0.9
        result = ce.simpson_diversity(commits)
        assert abs(result - 0.9) < 0.01

    def test_heavily_skewed(self):
        commits = [
            _c(files={"a.py"}),
            _c(files={"a.py"}),
            _c(files={"a.py"}),
            _c(files={"a.py"}),
            _c(files={"a.py", "b.py"}),
        ]
        # a: 5, b: 1 → total 6 → 1 - (25/36 + 1/36) = 1 - 26/36 ≈ 0.278
        result = ce.simpson_diversity(commits)
        assert 0.2 < result < 0.35

    def test_range(self):
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"c.py"}),
        ]
        result = ce.simpson_diversity(commits)
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# keystone_fraction
# ---------------------------------------------------------------------------

class TestKeystoneFraction:
    def test_empty(self):
        assert ce.keystone_fraction([]) == 0.0

    def test_no_keystones(self):
        """All files touched only once or twice (below threshold 3)."""
        commits = [
            _c(files={"a.py"}),
            _c(files={"b.py"}),
        ]
        assert ce.keystone_fraction(commits) == 0.0

    def test_all_keystones(self):
        """All files touched ≥ 3 times."""
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"a.py", "b.py"}),
            _c(files={"a.py", "b.py"}),
        ]
        assert ce.keystone_fraction(commits) == 1.0

    def test_mixed(self):
        """Some keystone, some not."""
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"a.py", "c.py"}),
            _c(files={"a.py", "d.py"}),
        ]
        # a: 3 touches (keystone), b: 1, c: 1, d: 1 → 1/4 = 0.25
        assert ce.keystone_fraction(commits) == 0.25

    def test_custom_threshold(self):
        commits = [
            _c(files={"a.py"}),
            _c(files={"a.py"}),
            _c(files={"a.py", "b.py"}),
        ]
        # With min_touches=2: a=3 (yes), b=1 (no) → 1/2 = 0.5
        assert ce.keystone_fraction(commits, min_touches=2) == 0.5


# ---------------------------------------------------------------------------
# invasion_rate
# ---------------------------------------------------------------------------

class TestInvasionRate:
    def test_empty(self):
        assert ce.invasion_rate([]) == 0.0

    def test_single_commit(self):
        assert ce.invasion_rate([_c(files={"a.py"})]) == 0.0

    def test_no_invasion(self):
        """All files present from the start."""
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"a.py", "b.py"}),
        ]
        assert ce.invasion_rate(commits) == 0.0

    def test_full_invasion(self):
        """All files appear in the second half."""
        commits = [
            _c(files=set()),  # empty first commit
            _c(files={"a.py", "b.py"}),
        ]
        assert ce.invasion_rate(commits) == 1.0

    def test_partial_invasion(self):
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"a.py", "c.py"}),
        ]
        # early: {a, b}, all: {a, b, c}, new: {c} → 1/3
        result = ce.invasion_rate(commits)
        assert abs(result - 1 / 3) < 0.01

    def test_range(self):
        commits = [
            _c(files={"a.py"}),
            _c(files={"b.py"}),
            _c(files={"c.py"}),
            _c(files={"d.py"}),
        ]
        result = ce.invasion_rate(commits)
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# extinction_rate
# ---------------------------------------------------------------------------

class TestExtinctionRate:
    def test_empty(self):
        assert ce.extinction_rate([]) == 0.0

    def test_all_singletons(self):
        """Every file touched exactly once → 100% extinction."""
        commits = [
            _c(files={"a.py"}),
            _c(files={"b.py"}),
        ]
        assert ce.extinction_rate(commits) == 1.0

    def test_no_singletons(self):
        """Every file touched multiple times → 0% extinction."""
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"a.py", "b.py"}),
        ]
        assert ce.extinction_rate(commits) == 0.0

    def test_mixed(self):
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"a.py", "c.py"}),
        ]
        # a: 2, b: 1, c: 1 → singletons: 2/3
        result = ce.extinction_rate(commits)
        assert abs(result - 2 / 3) < 0.01


# ---------------------------------------------------------------------------
# connectance
# ---------------------------------------------------------------------------

class TestConnectance:
    def test_empty(self):
        assert ce.connectance([]) == 0.0

    def test_full_connectance(self):
        """Every commit touches every file."""
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"a.py", "b.py"}),
        ]
        # max_links = 2 * 2 = 4, realised = 2 + 2 = 4 → 1.0
        assert ce.connectance(commits) == 1.0

    def test_sparse_connectance(self):
        commits = [
            _c(files={"a.py"}),
            _c(files={"b.py"}),
        ]
        # max_links = 2 * 2 = 4, realised = 1 + 1 = 2 → 0.5
        assert ce.connectance(commits) == 0.5

    def test_moderate(self):
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"b.py", "c.py"}),
            _c(files={"c.py", "d.py"}),
        ]
        # files: {a, b, c, d} → max = 3*4 = 12
        # realised = 2+2+2 = 6 → 0.5
        assert ce.connectance(commits) == 0.5

    def test_range(self):
        commits = [
            _c(files={"a.py"}),
            _c(files={"a.py", "b.py"}),
        ]
        result = ce.connectance(commits)
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# compute_ecology
# ---------------------------------------------------------------------------

class TestComputeEcology:
    def test_empty(self):
        r = ce.compute_ecology([])
        assert r.ecology_score == 0.0
        assert r.ecology_class == "monoculture"
        assert r.commit_count == 0

    def test_thriving_ecosystem(self):
        """Diverse, well-connected commits should score above barren."""
        commits = [
            _c(sha="a", files={"iamai/foo.py", "tests/test_foo.py", "docs/FOO.md"}),
            _c(sha="b", files={"iamai/bar.py", "tests/test_bar.py", "docs/BAR.md"}),
            _c(sha="c", files={"iamai/foo.py", "iamai/baz.py", "tests/test_baz.py", "docs/BAZ.md"}),
            _c(sha="d", files={"iamai/bar.py", "tests/test_bar.py", "notes/history.md"}),
            _c(sha="e", files={"iamai/foo.py", "iamai/qux.py", "tests/test_qux.py"}),
        ]
        r = ce.compute_ecology(commits)
        assert r.ecology_class in ("thriving", "healthy", "fragile")
        assert r.ecology_score > 0.4
        assert r.commit_count == 5
        assert r.file_count > 5

    def test_monoculture(self):
        """All activity in one file → low diversity metrics."""
        commits = [
            _c(files={"a.py"}),
            _c(files={"a.py"}),
            _c(files={"a.py"}),
            _c(files={"a.py"}),
        ]
        r = ce.compute_ecology(commits)
        assert r.file_count == 1
        assert r.shannon_evenness == 0.0
        assert r.simpson_diversity == 0.0
        # keystone & connectance inflate the composite, but diversity is zero
        assert r.ecology_score < 0.5

    def test_score_in_range(self):
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"c.py"}),
            _c(files={"a.py", "d.py"}),
        ]
        r = ce.compute_ecology(commits)
        assert 0.0 <= r.ecology_score <= 1.0

    def test_result_fields_populated(self):
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"b.py", "c.py"}),
        ]
        r = ce.compute_ecology(commits)
        assert r.species_richness > 0
        assert 0.0 <= r.shannon_evenness <= 1.0
        assert 0.0 <= r.simpson_diversity <= 1.0
        assert 0.0 <= r.keystone_fraction <= 1.0
        assert 0.0 <= r.invasion_rate <= 1.0
        assert 0.0 <= r.extinction_rate <= 1.0
        assert 0.0 <= r.connectance <= 1.0

    def test_deterministic(self):
        """Same input → same output."""
        commits = [
            _c(sha="a", files={"x.py", "y.py"}),
            _c(sha="b", files={"y.py", "z.py"}),
        ]
        r1 = ce.compute_ecology(commits)
        r2 = ce.compute_ecology(commits)
        assert r1.ecology_score == r2.ecology_score
        assert r1.ecology_class == r2.ecology_class


# ---------------------------------------------------------------------------
# ecology_trend
# ---------------------------------------------------------------------------

class TestEcologyTrend:
    def test_empty(self):
        t = ce.ecology_trend([])
        assert t.scores == []
        assert t.trend == "stable"

    def test_improving(self):
        results = [
            ce.EcologyResult(ecology_score=0.2),
            ce.EcologyResult(ecology_score=0.4),
            ce.EcologyResult(ecology_score=0.6),
            ce.EcologyResult(ecology_score=0.8),
        ]
        t = ce.ecology_trend(results)
        assert t.trend == "improving"
        assert t.slope > 0

    def test_degrading(self):
        results = [
            ce.EcologyResult(ecology_score=0.9),
            ce.EcologyResult(ecology_score=0.7),
            ce.EcologyResult(ecology_score=0.5),
            ce.EcologyResult(ecology_score=0.3),
        ]
        t = ce.ecology_trend(results)
        assert t.trend == "degrading"
        assert t.slope < 0

    def test_stable(self):
        results = [
            ce.EcologyResult(ecology_score=0.65),
            ce.EcologyResult(ecology_score=0.66),
            ce.EcologyResult(ecology_score=0.64),
            ce.EcologyResult(ecology_score=0.65),
        ]
        t = ce.ecology_trend(results)
        assert t.trend == "stable"
        assert abs(t.slope) < 0.02

    def test_single_result(self):
        t = ce.ecology_trend([ce.EcologyResult(ecology_score=0.5)])
        assert t.trend == "stable"
        assert t.slope == 0.0
        assert t.mean == 0.5

    def test_stats(self):
        results = [
            ce.EcologyResult(ecology_score=0.5),
            ce.EcologyResult(ecology_score=0.7),
        ]
        t = ce.ecology_trend(results)
        assert len(t.scores) == 2
        assert t.mean == pytest.approx(0.6, abs=0.01)


# ---------------------------------------------------------------------------
# ecology_report
# ---------------------------------------------------------------------------

class TestEcologyReport:
    def test_report_contains_key_info(self):
        r = ce.compute_ecology([
            _c(files={"a.py", "b.py"}),
            _c(files={"b.py", "c.py"}),
        ])
        report = ce.ecology_report(r)
        assert r.ecology_class in report
        assert f"{r.ecology_score:.2f}" in report
        assert "shannon evenness" in report
        assert "simpson diversity" in report

    def test_report_non_empty(self):
        r = ce.compute_ecology([_c(files={"a.py"})])
        report = ce.ecology_report(r)
        assert len(report) > 50


# ---------------------------------------------------------------------------
# trend_report
# ---------------------------------------------------------------------------

class TestTrendReport:
    def test_empty_trend(self):
        t = ce.EcologyTrend()
        report = ce.trend_report(t)
        assert "No ecology data" in report

    def test_report_contains_info(self):
        t = ce.ecology_trend([
            ce.EcologyResult(ecology_score=0.5),
            ce.EcologyResult(ecology_score=0.6),
            ce.EcologyResult(ecology_score=0.7),
        ])
        report = ce.trend_report(t)
        assert "improving" in report
        assert "windows analysed: 3" in report


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_commit_with_no_files(self):
        commits = [_c(files=set()), _c(files=set())]
        r = ce.compute_ecology(commits)
        assert r.file_count == 0
        # extinction_rate=0 (no files to go extinct), so (1-0)*weight leaks in
        assert r.ecology_score <= 0.15

    def test_mixed_empty_and_full(self):
        commits = [
            _c(files=set()),
            _c(files={"a.py", "b.py", "c.py"}),
        ]
        r = ce.compute_ecology(commits)
        assert r.file_count == 3
        assert r.commit_count == 2

    def test_many_commits_single_file(self):
        commits = [_c(files={"solo.py"}) for _ in range(50)]
        r = ce.compute_ecology(commits)
        assert r.file_count == 1
        assert r.shannon_evenness == 0.0
        assert r.simpson_diversity == 0.0
        assert r.keystone_fraction == 1.0  # touched 50 times
        assert r.extinction_rate == 0.0

    def test_large_ecosystem(self):
        """Scale test with many files and commits."""
        commits = []
        for i in range(20):
            files = {f"file_{i * 3 + j}.py" for j in range(3)}
            commits.append(_c(sha=f"c{i}", files=files))
        r = ce.compute_ecology(commits)
        assert r.file_count == 60
        assert r.commit_count == 20
        assert 0.0 <= r.ecology_score <= 1.0
