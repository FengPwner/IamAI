#!/usr/bin/env python3
"""Tests for commit_diffusivity.py — codebase change propagation analysis."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_diffusivity as cd

# ---------------------------------------------------------------------------
# Reference time
# ---------------------------------------------------------------------------
REF = datetime(2026, 11, 11, 0, 0, 0)  # Wed 2026-11-11 00:00 UTC


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _commit(sha, hours_after, files):
    """Create a CommitRecord at REF + hours_after with the given files."""
    return cd.CommitRecord(
        sha=sha,
        timestamp=REF + timedelta(hours=hours_after),
        files=frozenset(files),
    )


def _sequence(n, hours_step=1, files_fn=None):
    """Generate n commits spaced hours_step apart."""
    if files_fn is None:
        files_fn = lambda i: frozenset([f"iamai/mod_{i % 5}.py"])
    return [
        cd.CommitRecord(
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
        c = cd.CommitRecord(sha="a", timestamp=REF, files=["x.py", "y.py"])
        assert isinstance(c.files, frozenset)
        assert c.files == frozenset({"x.py", "y.py"})

    def test_already_frozenset(self):
        fs = frozenset({"a.py"})
        c = cd.CommitRecord(sha="a", timestamp=REF, files=fs)
        assert c.files is fs

    def test_frozen_dataclass(self):
        c = cd.CommitRecord(sha="a", timestamp=REF, files=["x.py"])
        with pytest.raises(AttributeError):
            c.sha = "b"

    def test_empty_files(self):
        c = cd.CommitRecord(sha="a", timestamp=REF, files=[])
        assert c.files == frozenset()

    def test_duplicate_files_deduplicated(self):
        c = cd.CommitRecord(sha="a", timestamp=REF, files=["x.py", "x.py", "y.py"])
        assert c.files == frozenset({"x.py", "y.py"})


# ---------------------------------------------------------------------------
# classify_diffusivity
# ---------------------------------------------------------------------------

class TestClassifyDiffusivity:
    @pytest.mark.parametrize("score,expected", [
        (0.0, "stagnant"),
        (0.10, "stagnant"),
        (0.19, "stagnant"),
        (0.20, "insulating"),
        (0.35, "insulating"),
        (0.39, "insulating"),
        (0.40, "diffusive"),
        (0.50, "diffusive"),
        (0.59, "diffusive"),
        (0.60, "conductive"),
        (0.70, "conductive"),
        (0.79, "conductive"),
        (0.80, "superconductor"),
        (0.90, "superconductor"),
        (1.0, "superconductor"),
    ])
    def test_boundaries(self, score, expected):
        assert cd.classify_diffusivity(score) == expected

    def test_clamps_above_one(self):
        assert cd.classify_diffusivity(1.5) == "superconductor"

    def test_clamps_below_zero(self):
        assert cd.classify_diffusivity(-0.5) == "stagnant"


# ---------------------------------------------------------------------------
# _gini helper
# ---------------------------------------------------------------------------

class TestGini:
    def test_empty(self):
        assert cd._gini([]) == 0.0

    def test_uniform(self):
        assert cd._gini([10, 10, 10, 10]) == pytest.approx(0.0, abs=0.01)

    def test_maximal_inequality(self):
        # One value has everything, rest are zero
        vals = [0, 0, 0, 100]
        g = cd._gini(vals)
        assert g > 0.7

    def test_moderate_inequality(self):
        vals = [1, 2, 3, 4, 5]
        g = cd._gini(vals)
        assert 0.2 < g < 0.5

    def test_all_zeros(self):
        assert cd._gini([0, 0, 0]) == 0.0

    def test_single_value(self):
        assert cd._gini([42]) == 0.0

    def test_two_values(self):
        g = cd._gini([1, 9])
        assert 0.3 < g < 0.6


# ---------------------------------------------------------------------------
# compute_diffusivity — empty / minimal
# ---------------------------------------------------------------------------

class TestComputeEdgeCases:
    def test_empty_commits(self):
        r = cd.compute_diffusivity([])
        assert r.n_commits == 0
        assert r.diffusivity_class == "stagnant"
        assert r.diffusivity_score == 0.0

    def test_single_commit(self):
        r = cd.compute_diffusivity([_commit("a", 0, ["x.py"])])
        assert r.n_commits == 1
        assert r.diffusivity_score >= 0.0
        assert r.diffusivity_score <= 1.0

    def test_single_empty_commit(self):
        r = cd.compute_diffusivity([_commit("a", 0, [])])
        assert r.n_commits == 1
        assert r.change_rate == 0.0

    def test_two_commits(self):
        commits = [
            _commit("a", 0, ["x.py"]),
            _commit("b", 1, ["y.py"]),
        ]
        r = cd.compute_diffusivity(commits)
        assert r.n_commits == 2
        assert r.change_rate == 1.0


# ---------------------------------------------------------------------------
# compute_diffusivity — uniform changes (high evenness)
# ---------------------------------------------------------------------------

class TestUniformChanges:
    def test_even_rotation(self):
        """Each commit touches one file in rotation — zero concentration."""
        commits = _sequence(50)  # 50 commits, rotating through 5 files
        r = cd.compute_diffusivity(commits)
        assert r.concentration_index == pytest.approx(0.0, abs=0.05)
        assert r.change_rate == 1.0
        assert r.n_files == 5

    def test_even_rotation_class(self):
        """Uniform rotation should produce a non-stagnant class."""
        commits = _sequence(50)
        r = cd.compute_diffusivity(commits)
        assert r.diffusivity_class != "stagnant"


# ---------------------------------------------------------------------------
# compute_diffusivity — concentrated changes (high Gini)
# ---------------------------------------------------------------------------

class TestConcentratedChanges:
    def test_one_file_dominates(self):
        """99% of commits touch the same file."""
        commits = []
        for i in range(100):
            if i % 100 == 0:
                files = [f"iamai/other_{i}.py"]
            else:
                files = ["iamai/hot.py"]
            commits.append(_commit(f"c{i}", i, files))
        r = cd.compute_diffusivity(commits)
        # Gini of [99, 1] with n=2: max achievable is (n-1)/n = 0.5
        assert r.concentration_index > 0.45

    def test_concentrated_has_higher_gini(self):
        """Uneven file frequencies should produce higher concentration than even."""
        # Even: 5 files each touched 10 times
        even = []
        for i in range(50):
            even.append(_commit(f"c{i}", i, [f"iamai/mod_{i % 5}.py"]))
        # Skewed: file_a touched 40 times, file_b 5 times, file_c 5 times
        skewed = []
        for i in range(40):
            skewed.append(_commit(f"c{i}", i, ["iamai/file_a.py"]))
        for i in range(5):
            skewed.append(_commit(f"d{i}", 40 + i, ["iamai/file_b.py"]))
        for i in range(5):
            skewed.append(_commit(f"e{i}", 45 + i, ["iamai/file_c.py"]))
        r_even = cd.compute_diffusivity(even)
        r_skewed = cd.compute_diffusivity(skewed)
        assert r_skewed.concentration_index > r_even.concentration_index


# ---------------------------------------------------------------------------
# compute_diffusivity — burst detection and propagation
# ---------------------------------------------------------------------------

class TestBurstPropagation:
    def _burst_sequence(self):
        """Create commits with a burst at index 5, then spreading changes."""
        commits = []
        # Normal: 5 commits touching 1 file each
        for i in range(5):
            commits.append(_commit(f"c{i}", i, [f"iamai/mod_{i}.py"]))
        # Burst: one commit touching 10 files
        burst_files = [f"iamai/burst_{j}.py" for j in range(10)]
        commits.append(_commit("c5_burst", 5, burst_files))
        # Propagation: next 10 commits touch new files
        for i in range(6, 16):
            commits.append(_commit(f"c{i}", i, [f"iamai/new_{i}.py"]))
        # Recovery: back to normal
        for i in range(16, 25):
            commits.append(_commit(f"c{i}", i, [f"iamai/mod_{i % 5}.py"]))
        return commits

    def test_burst_detected(self):
        commits = self._burst_sequence()
        r = cd.compute_diffusivity(commits)
        # The burst file (10 files) should be above burst threshold
        # (median ~ 1 * 3 = 3), so burst is detected
        assert r.penetration_depth > 0

    def test_spread_velocity_positive_after_burst(self):
        commits = self._burst_sequence()
        r = cd.compute_diffusivity(commits)
        assert r.spread_velocity > 0

    def test_diffusion_coefficient_positive(self):
        commits = self._burst_sequence()
        r = cd.compute_diffusivity(commits)
        assert r.diffusion_coefficient > 0

    def test_absorption_time_computed(self):
        commits = self._burst_sequence()
        r = cd.compute_diffusivity(commits)
        assert r.absorption_time > 0


# ---------------------------------------------------------------------------
# compute_diffusivity — absorption time
# ---------------------------------------------------------------------------

class TestAbsorptionTime:
    def test_immediate_absorption(self):
        """All related files updated in the very next commit."""
        commits = []
        # Burst then immediate full update
        commits.append(_commit("c0", 0, ["a.py"]))
        commits.append(_commit("c1", 1, ["a.py", "b.py", "c.py", "d.py", "e.py"]))
        # Then nothing changes for a while
        for i in range(2, 20):
            commits.append(_commit(f"c{i}", i, [f"mod_{i % 3}.py"]))
        r = cd.compute_diffusivity(commits)
        # Absorption should be fast
        assert r.absorption_time <= 5

    def test_slow_absorption(self):
        """Burst followed by gradual trickle of updates."""
        commits = []
        # Burst
        burst_files = [f"core_{j}.py" for j in range(8)]
        commits.append(_commit("c0", 0, burst_files))
        # Slow trickle: one new file every 3 commits
        for i in range(1, 30):
            if i % 3 == 0:
                commits.append(_commit(f"c{i}", i, [f"dep_{i}.py"]))
            else:
                commits.append(_commit(f"c{i}", i, ["stable.py"]))
        r = cd.compute_diffusivity(commits)
        # Absorption should be slow or not happen
        assert r.absorption_time >= 1


# ---------------------------------------------------------------------------
# compute_diffusivity — diffusion length
# ---------------------------------------------------------------------------

class TestDiffusionLength:
    def test_single_file_change_tracks_spread(self):
        """After a single-file commit, measure how many files are touched next."""
        commits = []
        commits.append(_commit("c0", 0, ["entry.py"]))
        # Next 5 commits each touch 2 files
        for i in range(1, 6):
            commits.append(_commit(f"c{i}", i, [f"layer_{i}.py", f"util_{i}.py"]))
        # Fill to have enough data
        for i in range(6, 20):
            commits.append(_commit(f"c{i}", i, [f"mod_{i % 4}.py"]))
        r = cd.compute_diffusivity(commits)
        assert r.diffusion_length > 0


# ---------------------------------------------------------------------------
# compute_diffusivity — sorting
# ---------------------------------------------------------------------------

class TestSorting:
    def test_out_of_order_commits_sorted(self):
        """Commits passed in wrong order should still produce correct results."""
        commits = [
            _commit("c2", 2, ["b.py"]),
            _commit("c0", 0, ["a.py"]),
            _commit("c1", 1, ["a.py"]),
        ]
        r = cd.compute_diffusivity(commits)
        assert r.n_commits == 3

    def test_same_timestamp(self):
        commits = [
            _commit("a", 0, ["x.py"]),
            _commit("b", 0, ["y.py"]),
        ]
        r = cd.compute_diffusivity(commits)
        assert r.n_commits == 2


# ---------------------------------------------------------------------------
# compute_diffusivity — score bounds
# ---------------------------------------------------------------------------

class TestScoreBounds:
    def test_score_between_0_and_1(self):
        for n in [1, 5, 20, 100]:
            commits = _sequence(n)
            r = cd.compute_diffusivity(commits)
            assert 0.0 <= r.diffusivity_score <= 1.0

    def test_high_activity_broader_spread(self):
        """A burst followed by broad propagation should increase penetration depth."""
        # Broad: burst of 15 files, then 10 commits each touching 2 new files
        broad = []
        for i in range(5):
            broad.append(_commit(f"c{i}", i, ["base.py"]))
        broad.append(_commit("burst_b", 5, [f"burst_{j}.py" for j in range(15)]))
        for i in range(6, 16):
            broad.append(_commit(f"c{i}", i, [f"new_{j}_{i}.py" for j in range(2)]))
        for i in range(16, 30):
            broad.append(_commit(f"c{i}", i, ["base.py"]))

        # Narrow: burst of 15 files, then 10 commits each touching 1 file
        narrow = []
        for i in range(5):
            narrow.append(_commit(f"c{i}", i, ["base.py"]))
        narrow.append(_commit("burst_n", 5, [f"burst_{j}.py" for j in range(15)]))
        for i in range(6, 16):
            narrow.append(_commit(f"c{i}", i, [f"follow_{i}.py"]))
        for i in range(16, 30):
            narrow.append(_commit(f"c{i}", i, ["base.py"]))

        r_broad = cd.compute_diffusivity(broad)
        r_narrow = cd.compute_diffusivity(narrow)
        assert r_broad.penetration_depth > r_narrow.penetration_depth


# ---------------------------------------------------------------------------
# DiffusivityResult properties
# ---------------------------------------------------------------------------

class TestDiffusivityResult:
    def test_is_healthy_true(self):
        r = cd.DiffusivityResult(diffusivity_class="conductive")
        assert r.is_healthy is True

    def test_is_healthy_true_superconductor(self):
        r = cd.DiffusivityResult(diffusivity_class="superconductor")
        assert r.is_healthy is True

    def test_is_healthy_false_diffusive(self):
        r = cd.DiffusivityResult(diffusivity_class="diffusive")
        assert r.is_healthy is False

    def test_is_healthy_false_stagnant(self):
        r = cd.DiffusivityResult(diffusivity_class="stagnant")
        assert r.is_healthy is False

    def test_frozen(self):
        r = cd.DiffusivityResult()
        with pytest.raises(AttributeError):
            r.diffusivity_score = 0.5


# ---------------------------------------------------------------------------
# diffusivity_report
# ---------------------------------------------------------------------------

class TestDiffusivityReport:
    def test_report_contains_class(self):
        r = cd.compute_diffusivity(_sequence(30))
        report = cd.diffusivity_report(r)
        assert r.diffusivity_class.upper() in report

    def test_report_contains_score(self):
        r = cd.compute_diffusivity(_sequence(30))
        report = cd.diffusivity_report(r)
        assert f"{r.diffusivity_score:.2f}" in report

    def test_report_contains_dimensions(self):
        r = cd.compute_diffusivity(_sequence(30))
        report = cd.diffusivity_report(r)
        assert "change_rate" in report
        assert "concentration_index" in report
        assert "spread_velocity" in report
        assert "diffusion_coefficient" in report
        assert "penetration_depth" in report
        assert "diffusion_length" in report
        assert "absorption_time" in report

    def test_report_health_indicator(self):
        r = cd.compute_diffusivity(_sequence(30))
        report = cd.diffusivity_report(r)
        assert "healthy" in report or "needs attention" in report

    def test_report_empty_result(self):
        r = cd.DiffusivityResult()
        report = cd.diffusivity_report(r)
        assert "STAGNANT" in report


# ---------------------------------------------------------------------------
# diffusivity_trend
# ---------------------------------------------------------------------------

class TestDiffusivityTrend:
    def test_insufficient_data(self):
        t = cd.diffusivity_trend([])
        assert t.n_windows == 0
        assert t.summary == "insufficient data"

    def test_single_window(self):
        r = cd.DiffusivityResult(diffusivity_score=0.5)
        t = cd.diffusivity_trend([r])
        assert t.n_windows == 1
        assert t.summary == "insufficient data"

    def test_increasing_trend(self):
        results = [
            cd.DiffusivityResult(diffusivity_score=0.2),
            cd.DiffusivityResult(diffusivity_score=0.3),
            cd.DiffusivityResult(diffusivity_score=0.6),
            cd.DiffusivityResult(diffusivity_score=0.7),
        ]
        t = cd.diffusivity_trend(results)
        assert t.direction == "increasing"
        assert t.delta > 0

    def test_decreasing_trend(self):
        results = [
            cd.DiffusivityResult(diffusivity_score=0.8),
            cd.DiffusivityResult(diffusivity_score=0.7),
            cd.DiffusivityResult(diffusivity_score=0.3),
            cd.DiffusivityResult(diffusivity_score=0.2),
        ]
        t = cd.diffusivity_trend(results)
        assert t.direction == "decreasing"
        assert t.delta < 0

    def test_stable_trend(self):
        results = [
            cd.DiffusivityResult(diffusivity_score=0.5),
            cd.DiffusivityResult(diffusivity_score=0.5),
            cd.DiffusivityResult(diffusivity_score=0.5),
            cd.DiffusivityResult(diffusivity_score=0.5),
        ]
        t = cd.diffusivity_trend(results)
        assert t.direction == "stable"
        assert t.delta == pytest.approx(0.0, abs=0.01)

    def test_trend_summary_increasing(self):
        results = [
            cd.DiffusivityResult(diffusivity_score=0.2),
            cd.DiffusivityResult(diffusivity_score=0.8),
        ]
        t = cd.diffusivity_trend(results)
        assert "improving" in t.summary

    def test_trend_summary_decreasing(self):
        results = [
            cd.DiffusivityResult(diffusivity_score=0.8),
            cd.DiffusivityResult(diffusivity_score=0.2),
        ]
        t = cd.diffusivity_trend(results)
        assert "degrading" in t.summary

    def test_trend_summary_stable(self):
        results = [
            cd.DiffusivityResult(diffusivity_score=0.5),
            cd.DiffusivityResult(diffusivity_score=0.5),
        ]
        t = cd.diffusivity_trend(results)
        assert "stable" in t.summary

    def test_scores_preserved(self):
        scores = [0.1, 0.3, 0.5, 0.7]
        results = [cd.DiffusivityResult(diffusivity_score=s) for s in scores]
        t = cd.diffusivity_trend(results)
        assert t.scores == scores


# ---------------------------------------------------------------------------
# Large-scale integration
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_large_uniform_dataset(self):
        """1000 commits rotating evenly across 20 files."""
        commits = _sequence(1000, files_fn=lambda i: frozenset([f"mod_{i % 20}.py"]))
        r = cd.compute_diffusivity(commits)
        assert r.n_commits == 1000
        assert r.n_files == 20
        assert r.concentration_index == pytest.approx(0.0, abs=0.05)
        assert 0.0 <= r.diffusivity_score <= 1.0

    def test_large_burst_dataset(self):
        """500 normal commits + 1 huge burst + 500 propagation commits."""
        commits = []
        for i in range(500):
            commits.append(_commit(f"c{i}", i, [f"mod_{i % 10}.py"]))
        burst = [f"burst_{j}.py" for j in range(50)]
        commits.append(_commit("burst", 500, burst))
        for i in range(501, 1001):
            commits.append(_commit(f"c{i}", i, [f"new_{i % 30}.py"]))
        r = cd.compute_diffusivity(commits)
        assert r.n_commits == 1001
        assert r.penetration_depth > 0

    def test_end_to_end_report_and_trend(self):
        """Full pipeline: compute, report, trend."""
        windows = []
        for w in range(4):
            commits = _sequence(
                30,
                files_fn=lambda i, w=w: frozenset([f"w{w}_mod_{i % (3 + w)}.py"]),
            )
            windows.append(cd.compute_diffusivity(commits))

        for r in windows:
            report = cd.diffusivity_report(r)
            assert len(report) > 50

        t = cd.diffusivity_trend(windows)
        assert t.n_windows == 4
        assert t.direction in ("increasing", "stable", "decreasing")
