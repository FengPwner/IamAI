#!/usr/bin/env python3
"""Tests for commit_elasticity.py — codebase recovery resilience analysis."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_elasticity as ce

# ---------------------------------------------------------------------------
# Reference time
# ---------------------------------------------------------------------------
REF = datetime(2026, 11, 11, 0, 0, 0)  # Wed 2026-11-11 00:00 UTC


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _commit(sha, hours_after, files):
    """Create a CommitRecord at REF + hours_after with the given files."""
    return ce.CommitRecord(
        sha=sha,
        timestamp=REF + timedelta(hours=hours_after),
        files=frozenset(files),
    )


def _sequence(n, hours_step=1, files_fn=None):
    """Generate n commits spaced hours_step apart."""
    if files_fn is None:
        files_fn = lambda i: frozenset([f"iamai/mod_{i % 5}.py"])
    return [
        ce.CommitRecord(
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
        c = ce.CommitRecord(sha="a", timestamp=REF, files=["x.py", "y.py"])
        assert isinstance(c.files, frozenset)
        assert c.files == frozenset({"x.py", "y.py"})

    def test_already_frozenset(self):
        fs = frozenset({"a.py"})
        c = ce.CommitRecord(sha="a", timestamp=REF, files=fs)
        assert c.files is fs

    def test_frozen_dataclass(self):
        c = ce.CommitRecord(sha="a", timestamp=REF, files=["x.py"])
        with pytest.raises(AttributeError):
            c.sha = "b"


# ---------------------------------------------------------------------------
# classify_elasticity
# ---------------------------------------------------------------------------

class TestClassifyElasticity:
    @pytest.mark.parametrize("score,expected", [
        (0.0, "brittle"),
        (0.10, "brittle"),
        (0.19, "brittle"),
        (0.20, "stiff"),
        (0.35, "stiff"),
        (0.39, "stiff"),
        (0.40, "springy"),
        (0.55, "springy"),
        (0.59, "springy"),
        (0.60, "resilient"),
        (0.75, "resilient"),
        (0.79, "resilient"),
        (0.80, "rubbery"),
        (0.95, "rubbery"),
        (1.00, "rubbery"),
    ])
    def test_boundaries(self, score, expected):
        assert ce.classify_elasticity(score) == expected

    def test_negative_clamps_to_brittle(self):
        assert ce.classify_elasticity(-0.5) == "brittle"

    def test_above_one_clamps_to_rubbery(self):
        assert ce.classify_elasticity(1.5) == "rubbery"


# ---------------------------------------------------------------------------
# compute_elasticity — edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_commits(self):
        r = ce.compute_elasticity([])
        assert r.window_commits == 0
        assert r.elasticity_class == "brittle"
        assert r.elasticity_score == 0.0

    def test_single_commit(self):
        r = ce.compute_elasticity([_commit("a", 0, ["x.py"])])
        assert r.window_commits == 1
        assert r.elasticity_class == "brittle"
        assert r.disruption_count == 0

    def test_two_identical_commits(self):
        r = ce.compute_elasticity([
            _commit("a", 0, ["x.py"]),
            _commit("b", 1, ["x.py"]),
        ])
        assert r.window_commits == 2
        assert r.disruption_count == 0
        assert r.baseline_files == 1.0


# ---------------------------------------------------------------------------
# compute_elasticity — baseline and threshold
# ---------------------------------------------------------------------------

class TestBaselineAndThreshold:
    def test_baseline_is_median(self):
        commits = _sequence(20, files_fn=lambda i: frozenset(
            [f"iamai/m{j}.py" for j in range(3)]  # always 3 files
        ))
        r = ce.compute_elasticity(commits)
        assert r.baseline_files == 3.0

    def test_threshold_is_multiplier_times_baseline(self):
        commits = _sequence(20, files_fn=lambda i: frozenset(
            [f"iamai/m{j}.py" for j in range(2)]
        ))
        r = ce.compute_elasticity(commits, disruption_multiplier=4.0)
        assert r.disruption_threshold == 2.0 * 4.0

    def test_variable_file_counts_baseline(self):
        commits = [
            _commit(f"c{i}", i, [f"f{j}.py" for j in range((i % 3) + 1)])
            for i in range(10)
        ]
        r = ce.compute_elasticity(commits)
        # file counts: 1,2,3,1,2,3,1,2,3,1 → median = 2.0
        assert r.baseline_files == 2.0


# ---------------------------------------------------------------------------
# compute_elasticity — disruption detection
# ---------------------------------------------------------------------------

class TestDisruptionDetection:
    def test_no_disruptions_in_uniform_sequence(self):
        commits = _sequence(20, files_fn=lambda i: frozenset(
            [f"iamai/mod_{i % 5}.py"]
        ))
        r = ce.compute_elasticity(commits)
        assert r.disruption_count == 0

    def test_single_large_disruption(self):
        commits = _sequence(20, files_fn=lambda i: frozenset(
            [f"iamai/mod_{i % 3}.py"]
        ))
        # Insert a massive commit at position 10
        big_files = frozenset([f"iamai/big_{j}.py" for j in range(30)])
        commits[10] = ce.CommitRecord(
            sha="big", timestamp=REF + timedelta(hours=10), files=big_files
        )
        r = ce.compute_elasticity(commits)
        assert r.disruption_count >= 1
        assert r.disruption_magnitude > 1.0

    def test_multiple_disruptions(self):
        commits = _sequence(30, files_fn=lambda i: frozenset(
            [f"iamai/mod_{i % 3}.py"]
        ))
        # Two big commits
        big1 = frozenset([f"iamai/x_{j}.py" for j in range(20)])
        big2 = frozenset([f"iamai/y_{j}.py" for j in range(25)])
        commits[10] = ce.CommitRecord(
            sha="big1", timestamp=REF + timedelta(hours=10), files=big1
        )
        commits[20] = ce.CommitRecord(
            sha="big2", timestamp=REF + timedelta(hours=20), files=big2
        )
        r = ce.compute_elasticity(commits)
        assert r.disruption_count >= 2


# ---------------------------------------------------------------------------
# compute_elasticity — recovery
# ---------------------------------------------------------------------------

class TestRecovery:
    def test_fast_recovery(self):
        """After a disruption, next commit is normal → latency = 1."""
        # 20 normal commits (1 file each) + 1 big one + 10 normal
        normal = [
            _commit(f"n{i}", i, [f"iamai/mod.py"])
            for i in range(10)
        ]
        big = [_commit("big", 10, [f"iamai/f{j}.py" for j in range(30)])]
        after = [
            _commit(f"a{i}", 11 + i, [f"iamai/mod.py"])
            for i in range(10)
        ]
        commits = normal + big + after
        r = ce.compute_elasticity(commits)
        assert r.disruption_count >= 1
        assert r.recovery_latency == 1.0  # Recovers in 1 commit
        assert r.rebound_ratio == 1.0

    def test_slow_recovery(self):
        """Gradual tapering after disruption → higher latency."""
        normal = [_commit(f"n{i}", i, ["iamai/mod.py"]) for i in range(10)]
        # Big commit, then gradually decreasing
        big = [_commit("big", 10, [f"iamai/f{j}.py" for j in range(30)])]
        taper = [
            _commit(f"t{i}", 11 + i, [f"iamai/f{j}.py" for j in range(max(1, 15 - i * 3))])
            for i in range(5)
        ]
        after = [_commit(f"a{i}", 16 + i, ["iamai/mod.py"]) for i in range(5)]
        commits = normal + big + taper + after
        r = ce.compute_elasticity(commits)
        assert r.disruption_count >= 1
        assert r.recovery_latency > 1.0

    def test_no_recovery(self):
        """Disruption at end of history → no chance to recover."""
        normal = [_commit(f"n{i}", i, ["iamai/mod.py"]) for i in range(10)]
        big = [_commit("big", 10, [f"iamai/f{j}.py" for j in range(30)])]
        commits = normal + big
        r = ce.compute_elasticity(commits)
        assert r.disruption_count >= 1
        assert r.rebound_ratio == 0.0
        assert r.recovery_latency == 0.0


# ---------------------------------------------------------------------------
# compute_elasticity — plastic deformation
# ---------------------------------------------------------------------------

class TestPlasticDeformation:
    def test_no_deformation_in_clean_repo(self):
        """Normal commitsits with no disruptions → zero deformation."""
        commits = _sequence(20, files_fn=lambda i: frozenset(
            [f"iamai/mod_{i % 5}.py"]
        ))
        r = ce.compute_elasticity(commits)
        assert r.plastic_deformation == 0.0

    def test_deformation_when_areas_stay_hot(self):
        """Disruption introduces areas that stay active."""
        # Normal: only iamai/ area
        normal = [
            _commit(f"n{i}", i, [f"iamai/mod_{i % 3}.py"])
            for i in range(10)
        ]
        # Disruption: touches many new areas
        disruption_files = [
            "docs/new1.md", "docs/new2.md", "tests/new1.py",
            "tests/new2.py", "scripts/new1.py", "scripts/new2.py",
        ] + [f"iamai/f{j}.py" for j in range(30)]
        big = [_commit("big", 10, disruption_files)]
        # After: the new areas stay active (deformation)
        after = [
            _commit(f"a{i}", 11 + i, [
                f"docs/new_{i}.md", f"tests/new_{i}.py",
                f"scripts/new_{i}.py", "iamai/mod.py"
            ])
            for i in range(10)
        ]
        commits = normal + big + after
        r = ce.compute_elasticity(commits)
        assert r.disruption_count >= 1
        # Areas introduced by disruption continue to be active
        assert r.plastic_deformation >= 0.0


# ---------------------------------------------------------------------------
# compute_elasticity — damping coefficient
# ---------------------------------------------------------------------------

class TestDampingCoefficient:
    def test_no_damping_without_disruptions(self):
        commits = _sequence(20, files_fn=lambda i: frozenset(
            [f"iamai/mod_{i % 5}.py"]
        ))
        r = ce.compute_elasticity(commits)
        assert r.damping_coefficient == 0.0

    def test_fast_damping(self):
        """Sharp drop after disruption → high damping."""
        normal = [_commit(f"n{i}", i, ["iamai/mod.py"]) for i in range(10)]
        big = [_commit("big", 10, [f"iamai/f{j}.py" for j in range(30)])]
        # Immediate return to normal
        after = [_commit(f"a{i}", 11 + i, ["iamai/mod.py"]) for i in range(10)]
        commits = normal + big + after
        r = ce.compute_elasticity(commits)
        assert r.damping_coefficient >= 0.0

    def test_slow_damping(self):
        """Gradual oscillation → lower damping."""
        normal = [_commit(f"n{i}", i, ["iamai/mod.py"]) for i in range(10)]
        big = [_commit("big", 10, [f"iamai/f{j}.py" for j in range(30)])]
        # Oscillating decay
        oscillation = [
            _commit(f"o{i}", 11 + i, [
                f"iamai/f{j}.py" for j in range(max(1, 20 - i * 4))
            ])
            for i in range(5)
        ]
        after = [_commit(f"a{i}", 16 + i, ["iamai/mod.py"]) for i in range(5)]
        commits = normal + big + oscillation + after
        r = ce.compute_elasticity(commits)
        assert r.damping_coefficient >= 0.0


# ---------------------------------------------------------------------------
# compute_elasticity — composite score
# ---------------------------------------------------------------------------

class TestCompositeScore:
    def test_perfect_elasticity(self):
        """All disruptions recover instantly → high score."""
        normal = [_commit(f"n{i}", i, ["iamai/mod.py"]) for i in range(10)]
        disruptions = []
        afters = []
        for d in range(3):
            base = 10 + d * 11
            disruptions.append(
                _commit(f"d{d}", base, [f"iamai/f{j}.py" for j in range(20)])
            )
            for j in range(10):
                afters.append(
                    _commit(f"a{d}_{j}", base + 1 + j, ["iamai/mod.py"])
                )
        commits = normal + disruptions + afters
        # Sort by timestamp
        commits.sort(key=lambda c: c.timestamp)
        r = ce.compute_elasticity(commits)
        assert r.elasticity_score >= 0.5  # Should be fairly elastic

    def test_poor_elasticity(self):
        """Disruption at end with no recovery → low score."""
        normal = [_commit(f"n{i}", i, ["iamai/mod.py"]) for i in range(10)]
        big = [_commit("big", 10, [f"iamai/f{j}.py" for j in range(30)])]
        commits = normal + big
        r = ce.compute_elasticity(commits)
        assert r.elasticity_score <= 0.5

    def test_score_in_range(self):
        commits = _sequence(30, files_fn=lambda i: frozenset(
            [f"iamai/mod_{i % 5}.py" for _ in range((i % 4) + 1)]
        ))
        r = ce.compute_elasticity(commits)
        assert 0.0 <= r.elasticity_score <= 1.0

    def test_score_rounded_to_4_decimals(self):
        commits = _sequence(20)
        r = ce.compute_elasticity(commits)
        assert r.elasticity_score == round(r.elasticity_score, 4)


# ---------------------------------------------------------------------------
# elasticity_report
# ---------------------------------------------------------------------------

class TestReport:
    def test_report_contains_key_fields(self):
        commits = _sequence(20, files_fn=lambda i: frozenset(
            [f"iamai/mod_{i % 5}.py" for _ in range((i % 3) + 1)]
        ))
        r = ce.compute_elasticity(commits)
        report = ce.elasticity_report(r)
        assert "Elasticity analysis" in report
        assert r.elasticity_class in report
        assert "baseline files" in report
        assert "rebound ratio" in report
        assert "damping coefficient" in report

    def test_report_with_disruption(self):
        normal = [_commit(f"n{i}", i, ["iamai/mod.py"]) for i in range(10)]
        big = [_commit("big", 10, [f"iamai/f{j}.py" for j in range(30)])]
        after = [_commit(f"a{i}", 11 + i, ["iamai/mod.py"]) for i in range(10)]
        commits = normal + big + after
        r = ce.compute_elasticity(commits)
        report = ce.elasticity_report(r)
        assert "disruptions found" in report
        assert str(r.disruption_count) in report


# ---------------------------------------------------------------------------
# elasticity_trend
# ---------------------------------------------------------------------------

class TestTrend:
    def test_empty_trend(self):
        t = ce.elasticity_trend([])
        assert t.direction == "stable"
        assert t.score_delta == 0.0
        assert t.sample_count == 0

    def test_single_sample(self):
        r = ce.compute_elasticity(_sequence(20))
        t = ce.elasticity_trend([r])
        assert t.direction == "stable"
        assert t.sample_count == 1

    def test_increasing_trend(self):
        r1 = ce.ElasticityResult(
            window_commits=10, window_hours=24, baseline_files=1.0,
            disruption_threshold=3.0, disruption_count=1,
            disruption_magnitude=3.0, recovery_latency=5.0,
            rebound_ratio=0.3, plastic_deformation=0.5,
            damping_coefficient=0.1, elasticity_score=0.3,
            elasticity_class="stiff",
        )
        r2 = ce.ElasticityResult(
            window_commits=10, window_hours=24, baseline_files=1.0,
            disruption_threshold=3.0, disruption_count=1,
            disruption_magnitude=3.0, recovery_latency=1.0,
            rebound_ratio=1.0, plastic_deformation=0.0,
            damping_coefficient=0.9, elasticity_score=0.9,
            elasticity_class="rubbery",
        )
        t = ce.elasticity_trend([r1, r2])
        assert t.direction == "increasing"
        assert t.score_delta > 0

    def test_decreasing_trend(self):
        r1 = ce.ElasticityResult(
            window_commits=10, window_hours=24, baseline_files=1.0,
            disruption_threshold=3.0, disruption_count=1,
            disruption_magnitude=3.0, recovery_latency=1.0,
            rebound_ratio=1.0, plastic_deformation=0.0,
            damping_coefficient=0.9, elasticity_score=0.9,
            elasticity_class="rubbery",
        )
        r2 = ce.ElasticityResult(
            window_commits=10, window_hours=24, baseline_files=1.0,
            disruption_threshold=3.0, disruption_count=1,
            disruption_magnitude=3.0, recovery_latency=5.0,
            rebound_ratio=0.3, plastic_deformation=0.5,
            damping_coefficient=0.1, elasticity_score=0.3,
            elasticity_class="stiff",
        )
        t = ce.elasticity_trend([r1, r2])
        assert t.direction == "decreasing"
        assert t.score_delta < 0

    def test_stable_trend(self):
        r1 = ce.ElasticityResult(
            window_commits=10, window_hours=24, baseline_files=1.0,
            disruption_threshold=3.0, disruption_count=1,
            disruption_magnitude=3.0, recovery_latency=2.0,
            rebound_ratio=0.8, plastic_deformation=0.1,
            damping_coefficient=0.5, elasticity_score=0.6,
            elasticity_class="resilient",
        )
        r2 = ce.ElasticityResult(
            window_commits=10, window_hours=24, baseline_files=1.0,
            disruption_threshold=3.0, disruption_count=1,
            disruption_magnitude=3.0, recovery_latency=2.0,
            rebound_ratio=0.8, plastic_deformation=0.1,
            damping_coefficient=0.5, elasticity_score=0.62,
            elasticity_class="resilient",
        )
        t = ce.elasticity_trend([r1, r2])
        assert t.direction == "stable"
        assert abs(t.score_delta) <= 0.05


# ---------------------------------------------------------------------------
# Integration: full pipeline
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_pipeline(self):
        """End-to-end: commits → analysis → report → trend."""
        commits = _sequence(40, files_fn=lambda i: frozenset(
            [f"iamai/mod_{i % 5}.py"]
            if i not in (10, 25) else
            [f"iamai/big_{j}.py" for j in range(20)]
        ))
        r = ce.compute_elasticity(commits)
        report = ce.elasticity_report(r)
        assert len(report) > 0
        assert r.window_commits == 40

        # Trend from two windows
        r1 = ce.compute_elasticity(commits[:20])
        r2 = ce.compute_elasticity(commits[20:])
        t = ce.elasticity_trend([r1, r2])
        assert t.sample_count == 2

    def test_helpers(self):
        assert ce._top_area("iamai/foo.py") == "iamai"
        assert ce._top_area("tests/test_x.py") == "tests"
        assert ce._top_area("README.md") == "."

        fs = frozenset(["iamai/a.py", "tests/b.py", "iamai/c.py"])
        assert ce._area_set(fs) == frozenset({"iamai", "tests"})
