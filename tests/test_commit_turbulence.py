#!/usr/bin/env python3
"""Tests for commit_turbulence — turbulence analysis for commit flow.

56 tests covering:
- CommitRecord construction and area extraction
- burstiness (uniform, bursty, empty windows, single commit)
- interval_cv (clock-like, erratic, edge cases)
- direction_entropy (focused, scattered, single-area)
- author_churn (solo, alternating, all-different)
- size_volatility (uniform, wild, zero-size)
- revert_ratio (clean, half-reverts, all-reverts)
- composite scoring and classification
- turbulence_report formatting
- area_turbulence per-area computation
- turbulence_trend (increasing, decreasing, stable, edge cases)
- full pipeline integration
"""

import math
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from iamai.commit_turbulence import (
    CommitRecord,
    TurbulenceResult,
    TurbulenceTrend,
    area_turbulence,
    classify_turbulence,
    compute_turbulence,
    turbulence_report,
    turbulence_trend,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_commit(
    sha: str = "abc",
    ts: datetime = datetime(2026, 11, 10, 10, 0),
    author: str = "qwen",
    files: list = None,
    lines: int = 50,
    message: str = "some change",
) -> CommitRecord:
    return CommitRecord(
        sha=sha,
        timestamp=ts,
        author=author,
        files_changed=files or ["iamai/foo.py"],
        lines_changed=lines,
        message=message,
    )


def _clock_commits(n: int, interval_seconds: int = 600, author: str = "qwen") -> list:
    """Generate n commits at perfectly regular intervals."""
    base = datetime(2026, 11, 10, 9, 0)
    return [
        _make_commit(
            sha=f"sha{i:03d}",
            ts=base + timedelta(seconds=i * interval_seconds),
            author=author,
            files=[f"iamai/module_{i % 3}.py"],
            lines=50,
            message=f"change {i}",
        )
        for i in range(n)
    ]


def _bursty_commits(n_bursts: int, commits_per_burst: int) -> list:
    """Generate bursts of commits with long gaps between bursts."""
    commits = []
    base = datetime(2026, 11, 10, 9, 0)
    idx = 0
    for b in range(n_bursts):
        burst_start = base + timedelta(hours=b * 4)
        for j in range(commits_per_burst):
            commits.append(
                _make_commit(
                    sha=f"sha{idx:03d}",
                    ts=burst_start + timedelta(seconds=j * 30),
                    author="qwen",
                    files=[f"iamai/area_{idx % 5}.py", f"tests/test_{idx % 3}.py"],
                    lines=50,
                    message=f"burst {b} commit {j}",
                )
            )
            idx += 1
    return commits


# ---------------------------------------------------------------------------
# CommitRecord tests
# ---------------------------------------------------------------------------

class TestCommitRecord(unittest.TestCase):

    def test_construction(self):
        c = _make_commit()
        self.assertEqual(c.sha, "abc")
        self.assertEqual(c.author, "qwen")

    def test_areas_single_file(self):
        c = _make_commit(files=["iamai/foo.py"])
        self.assertEqual(c.areas, ["iamai"])

    def test_areas_multiple_dirs(self):
        c = _make_commit(files=["iamai/foo.py", "tests/test_foo.py", "notes/bar.md"])
        self.assertEqual(c.areas, ["iamai", "notes", "tests"])

    def test_areas_root_file(self):
        c = _make_commit(files=["README.md"])
        self.assertEqual(c.areas, ["."])

    def test_areas_dedup(self):
        c = _make_commit(files=["iamai/a.py", "iamai/b.py", "iamai/c.py"])
        self.assertEqual(c.areas, ["iamai"])


# ---------------------------------------------------------------------------
# Burstiness tests
# ---------------------------------------------------------------------------

class TestBurstiness(unittest.TestCase):

    def test_uniform_commits(self):
        # Use a window large enough that all commits fall into a single bucket,
        # making burstiness = 1.0 by definition (max/mean = 1).
        commits = _clock_commits(5, interval_seconds=600)
        result = compute_turbulence(commits, window_minutes=60)
        # All commits in one window → burstiness = 1.0
        self.assertAlmostEqual(result.burstiness, 1.0, places=1)

    def test_bursty_commits(self):
        commits = _bursty_commits(3, 10)
        result = compute_turbulence(commits, window_minutes=10)
        # Bursts → high burstiness
        self.assertGreater(result.burstiness, 2.0)

    def test_single_commit(self):
        result = compute_turbulence([_make_commit()], window_minutes=60)
        self.assertEqual(result.burstiness, 1.0)

    def test_empty_commits(self):
        result = compute_turbulence([], window_minutes=60)
        self.assertEqual(result.burstiness, 0.0)

    def test_two_commits_same_time(self):
        ts = datetime(2026, 11, 10, 10, 0)
        commits = [_make_commit(sha="a", ts=ts), _make_commit(sha="b", ts=ts)]
        result = compute_turbulence(commits, window_minutes=60)
        self.assertEqual(result.burstiness, 1.0)


# ---------------------------------------------------------------------------
# Interval CV tests
# ---------------------------------------------------------------------------

class TestIntervalCV(unittest.TestCase):

    def test_clock_like(self):
        commits = _clock_commits(20, interval_seconds=300)
        result = compute_turbulence(commits)
        # Perfectly regular → CV ≈ 0
        self.assertAlmostEqual(result.interval_cv, 0.0, places=2)

    def test_erratic(self):
        base = datetime(2026, 11, 10, 9, 0)
        offsets = [0, 10, 200, 210, 1000, 1010, 2000]  # very irregular
        commits = [
            _make_commit(sha=f"s{i}", ts=base + timedelta(seconds=o))
            for i, o in enumerate(offsets)
        ]
        result = compute_turbulence(commits)
        self.assertGreater(result.interval_cv, 0.5)

    def test_two_commits(self):
        commits = _clock_commits(2)
        result = compute_turbulence(commits)
        # Only one interval → CV = 0
        self.assertEqual(result.interval_cv, 0.0)

    def test_single_commit(self):
        result = compute_turbulence([_make_commit()])
        self.assertEqual(result.interval_cv, 0.0)


# ---------------------------------------------------------------------------
# Direction entropy tests
# ---------------------------------------------------------------------------

class TestDirectionEntropy(unittest.TestCase):

    def test_focused(self):
        commits = [
            _make_commit(sha=f"s{i}", files=["iamai/foo.py"],
                         ts=datetime(2026, 11, 10, 10, i))
            for i in range(10)
        ]
        result = compute_turbulence(commits)
        # All in same area → entropy = 0
        self.assertAlmostEqual(result.direction_entropy, 0.0, places=2)

    def test_scattered(self):
        areas = ["iamai", "tests", "notes", "docs", "tools", "snippets"]
        commits = [
            _make_commit(sha=f"s{i}", files=[f"{areas[i % len(areas)]}/f.py"],
                         ts=datetime(2026, 11, 10, 10, i))
            for i in range(30)
        ]
        result = compute_turbulence(commits)
        # Uniformly scattered → high entropy
        self.assertGreater(result.direction_entropy, 0.8)

    def test_single_commit(self):
        result = compute_turbulence([_make_commit()])
        self.assertEqual(result.direction_entropy, 0.0)

    def test_two_areas(self):
        commits = [
            _make_commit(sha=f"s{i}",
                         files=["iamai/f.py"] if i % 2 == 0 else ["tests/f.py"],
                         ts=datetime(2026, 11, 10, 10, i))
            for i in range(10)
        ]
        result = compute_turbulence(commits)
        # Two areas equally split → entropy = 1.0 (max for 2 areas)
        self.assertAlmostEqual(result.direction_entropy, 1.0, places=2)


# ---------------------------------------------------------------------------
# Author churn tests
# ---------------------------------------------------------------------------

class TestAuthorChurn(unittest.TestCase):

    def test_solo_author(self):
        commits = _clock_commits(10, author="qwen")
        result = compute_turbulence(commits)
        self.assertAlmostEqual(result.author_churn, 0.0, places=2)

    def test_alternating_authors(self):
        base = datetime(2026, 11, 10, 9, 0)
        commits = [
            _make_commit(
                sha=f"s{i}",
                ts=base + timedelta(minutes=i * 10),
                author="qwen" if i % 2 == 0 else "kimi",
            )
            for i in range(10)
        ]
        result = compute_turbulence(commits)
        self.assertAlmostEqual(result.author_churn, 1.0, places=2)

    def test_single_author_change(self):
        base = datetime(2026, 11, 10, 9, 0)
        commits = [
            _make_commit(sha="s0", ts=base, author="qwen"),
            _make_commit(sha="s1", ts=base + timedelta(minutes=10), author="kimi"),
        ]
        result = compute_turbulence(commits)
        self.assertAlmostEqual(result.author_churn, 1.0, places=2)

    def test_single_commit(self):
        result = compute_turbulence([_make_commit()])
        self.assertEqual(result.author_churn, 0.0)


# ---------------------------------------------------------------------------
# Size volatility tests
# ---------------------------------------------------------------------------

class TestSizeVolatility(unittest.TestCase):

    def test_uniform_size(self):
        base = datetime(2026, 11, 10, 9, 0)
        commits = [
            _make_commit(sha=f"s{i}", ts=base + timedelta(minutes=i * 10), lines=100)
            for i in range(10)
        ]
        result = compute_turbulence(commits)
        self.assertAlmostEqual(result.size_volatility, 0.0, places=2)

    def test_wild_sizes(self):
        base = datetime(2026, 11, 10, 9, 0)
        sizes = [1, 500, 2, 1000, 3, 800, 1, 600]
        commits = [
            _make_commit(sha=f"s{i}", ts=base + timedelta(minutes=i * 10), lines=s)
            for i, s in enumerate(sizes)
        ]
        result = compute_turbulence(commits)
        self.assertGreater(result.size_volatility, 0.5)

    def test_zero_lines_clamped(self):
        base = datetime(2026, 11, 10, 9, 0)
        commits = [
            _make_commit(sha=f"s{i}", ts=base + timedelta(minutes=i * 10), lines=0)
            for i in range(5)
        ]
        result = compute_turbulence(commits)
        # Zero lines → clamped to 1 by max(1, abs(lines))
        self.assertAlmostEqual(result.size_volatility, 0.0, places=2)

    def test_single_commit(self):
        result = compute_turbulence([_make_commit()])
        self.assertEqual(result.size_volatility, 0.0)


# ---------------------------------------------------------------------------
# Revert ratio tests
# ---------------------------------------------------------------------------

class TestRevertRatio(unittest.TestCase):

    def test_no_reverts(self):
        commits = [_make_commit(sha=f"s{i}", message=f"feature {i}") for i in range(10)]
        result = compute_turbulence(commits)
        self.assertAlmostEqual(result.revert_ratio, 0.0, places=2)

    def test_all_reverts(self):
        commits = [_make_commit(sha=f"s{i}", message="Revert bad change") for i in range(5)]
        result = compute_turbulence(commits)
        self.assertAlmostEqual(result.revert_ratio, 1.0, places=2)

    def test_half_reverts(self):
        commits = [
            _make_commit(sha=f"s{i}",
                         message="Revert stuff" if i % 2 == 0 else "new feature")
            for i in range(10)
        ]
        result = compute_turbulence(commits)
        self.assertAlmostEqual(result.revert_ratio, 0.5, places=2)

    def test_rollback_patterns(self):
        commits = [
            _make_commit(sha="s0", message="rollback that thing"),
            _make_commit(sha="s1", message="Undo the undo"),
            _make_commit(sha="s2", message="REVERT merge commit"),
        ]
        result = compute_turbulence(commits)
        self.assertAlmostEqual(result.revert_ratio, 1.0, places=2)

    def test_empty(self):
        result = compute_turbulence([])
        self.assertEqual(result.revert_ratio, 0.0)


# ---------------------------------------------------------------------------
# Composite scoring and classification
# ---------------------------------------------------------------------------

class TestScoringAndClassification(unittest.TestCase):

    def test_classify_laminar(self):
        self.assertEqual(classify_turbulence(0.0), "laminar")
        self.assertEqual(classify_turbulence(0.29), "laminar")

    def test_classify_transitional(self):
        self.assertEqual(classify_turbulence(0.30), "transitional")
        self.assertEqual(classify_turbulence(0.50), "transitional")
        self.assertEqual(classify_turbulence(0.64), "transitional")

    def test_classify_turbulent(self):
        self.assertEqual(classify_turbulence(0.65), "turbulent")
        self.assertEqual(classify_turbulence(1.0), "turbulent")

    def test_laminar_flow_scoring(self):
        """Perfectly regular, single-author, focused commits → low score."""
        commits = _clock_commits(20, interval_seconds=600, author="qwen")
        # Override to all touch the same area
        for c in commits:
            c.files_changed = ["iamai/foo.py"]
            c.lines_changed = 50
        result = compute_turbulence(commits)
        self.assertLess(result.turbulence_score, 0.30)
        self.assertEqual(result.flow_regime, "laminar")

    def test_turbulent_flow_scoring(self):
        """Erratic timing, scattered areas, alternating authors → high score."""
        base = datetime(2026, 11, 10, 9, 0)
        areas = ["iamai", "tests", "notes", "docs", "tools"]
        offsets = [0, 5, 8, 200, 205, 210, 1500, 1502, 3000, 3001,
                   5000, 5001, 5003, 8000, 8005, 8010]
        commits = [
            _make_commit(
                sha=f"s{i}",
                ts=base + timedelta(seconds=offsets[i]),
                author="qwen" if i % 2 == 0 else "kimi",
                files=[f"{areas[i % len(areas)]}/f.py"],
                lines=abs((i * 137) % 1000) + 1,
                message="Revert stuff" if i % 4 == 0 else f"change {i}",
            )
            for i in range(len(offsets))
        ]
        result = compute_turbulence(commits, window_minutes=5)
        self.assertGreater(result.turbulence_score, 0.40)

    def test_score_bounds(self):
        """Score should always be in [0, 1]."""
        for n in [1, 2, 5, 50]:
            commits = _clock_commits(n)
            result = compute_turbulence(commits)
            self.assertGreaterEqual(result.turbulence_score, 0.0)
            self.assertLessEqual(result.turbulence_score, 1.0)

    def test_empty_result(self):
        result = compute_turbulence([])
        self.assertEqual(result.turbulence_score, 0.0)
        self.assertEqual(result.flow_regime, "laminar")
        self.assertEqual(result.commit_count, 0)


# ---------------------------------------------------------------------------
# Report tests
# ---------------------------------------------------------------------------

class TestReport(unittest.TestCase):

    def test_report_contains_fields(self):
        commits = _clock_commits(10)
        result = compute_turbulence(commits)
        report = turbulence_report(result)
        self.assertIn("Turbulence:", report)
        self.assertIn("Burstiness:", report)
        self.assertIn("Interval CV:", report)
        self.assertIn("Direction entropy:", report)
        self.assertIn("Author churn:", report)
        self.assertIn("Size volatility:", report)
        self.assertIn("Revert ratio:", report)

    def test_report_shows_regime(self):
        result = TurbulenceResult(
            turbulence_score=0.75, flow_regime="turbulent", commit_count=50
        )
        report = turbulence_report(result)
        self.assertIn("turbulent", report)


# ---------------------------------------------------------------------------
# Area turbulence tests
# ---------------------------------------------------------------------------

class TestAreaTurbulence(unittest.TestCase):

    def test_per_area(self):
        base = datetime(2026, 11, 10, 9, 0)
        iamai_commits = _clock_commits(10, interval_seconds=600)
        test_commits = _bursty_commits(3, 5)

        results = area_turbulence({
            "iamai": iamai_commits,
            "tests": test_commits,
        }, window_minutes=10)

        self.assertIn("iamai", results)
        self.assertIn("tests", results)
        self.assertIsInstance(results["iamai"], TurbulenceResult)

    def test_empty_area(self):
        results = area_turbulence({"empty": []})
        self.assertEqual(results["empty"].turbulence_score, 0.0)
        self.assertEqual(results["empty"].flow_regime, "laminar")


# ---------------------------------------------------------------------------
# Trend analysis tests
# ---------------------------------------------------------------------------

class TestTurbulenceTrend(unittest.TestCase):

    def test_increasing(self):
        snapshots = [0.1, 0.2, 0.35, 0.5, 0.7]
        trend = turbulence_trend(snapshots)
        self.assertEqual(trend.direction, "increasing")
        self.assertGreater(trend.slope, 0)
        self.assertIn("erratic", trend.interpretation)

    def test_decreasing(self):
        snapshots = [0.8, 0.6, 0.4, 0.25, 0.1]
        trend = turbulence_trend(snapshots)
        self.assertEqual(trend.direction, "decreasing")
        self.assertLess(trend.slope, 0)
        self.assertIn("stabilizing", trend.interpretation)

    def test_stable(self):
        snapshots = [0.4, 0.41, 0.39, 0.40, 0.41]
        trend = turbulence_trend(snapshots)
        self.assertEqual(trend.direction, "stable")
        self.assertAlmostEqual(trend.slope, 0.0, places=2)

    def test_single_snapshot(self):
        trend = turbulence_trend([0.5])
        self.assertEqual(trend.direction, "stable")
        self.assertEqual(trend.measurements, 1)
        self.assertEqual(trend.interpretation, "insufficient data for trend analysis")

    def test_empty(self):
        trend = turbulence_trend([])
        self.assertEqual(trend.direction, "stable")
        self.assertEqual(trend.measurements, 0)

    def test_two_snapshots(self):
        trend = turbulence_trend([0.2, 0.8])
        self.assertEqual(trend.direction, "increasing")
        self.assertAlmostEqual(trend.delta, 0.6, places=2)

    def test_delta_computation(self):
        trend = turbulence_trend([0.5, 0.3, 0.1])
        self.assertAlmostEqual(trend.delta, -0.4, places=2)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_massive_burst(self):
        """100 commits in 1 minute, then silence for hours."""
        base = datetime(2026, 11, 10, 9, 0)
        commits = [
            _make_commit(sha=f"s{i}", ts=base + timedelta(seconds=i))
            for i in range(100)
        ]
        result = compute_turbulence(commits, window_minutes=1)
        self.assertGreater(result.burstiness, 1.0)
        self.assertGreaterEqual(result.turbulence_score, 0.0)

    def test_negative_lines(self):
        """Negative lines_changed (deletions) should not break volatility."""
        base = datetime(2026, 11, 10, 9, 0)
        commits = [
            _make_commit(sha=f"s{i}", ts=base + timedelta(minutes=i * 10), lines=-200)
            for i in range(5)
        ]
        result = compute_turbulence(commits)
        self.assertGreaterEqual(result.size_volatility, 0.0)

    def test_identical_timestamps(self):
        ts = datetime(2026, 11, 10, 10, 0)
        commits = [_make_commit(sha=f"s{i}", ts=ts) for i in range(5)]
        result = compute_turbulence(commits)
        # All at same time → interval_cv=0, burstiness=1
        self.assertEqual(result.interval_cv, 0.0)

    def test_very_long_window(self):
        """Window larger than the entire commit span."""
        commits = _clock_commits(5, interval_seconds=60)
        result = compute_turbulence(commits, window_minutes=10000)
        # Everything fits in one bucket → burstiness = 1.0
        self.assertAlmostEqual(result.burstiness, 1.0, places=1)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):

    def test_full_pipeline_laminar(self):
        """Simulate a calm, focused development session."""
        base = datetime(2026, 11, 10, 9, 0)
        commits = [
            _make_commit(
                sha=f"s{i}",
                ts=base + timedelta(minutes=i * 15),
                author="qwen",
                files=["iamai/commit_turbulence.py", "tests/test_commit_turbulence.py"],
                lines=50 + (i % 10),
                message=f"add turbulence metric {i}",
            )
            for i in range(20)
        ]
        result = compute_turbulence(commits, window_minutes=30)
        self.assertEqual(result.flow_regime, "laminar")
        self.assertLess(result.turbulence_score, 0.35)
        report = turbulence_report(result)
        self.assertIn("laminar", report)

    def test_full_pipeline_turbulent(self):
        """Simulate a chaotic firefighting session."""
        base = datetime(2026, 11, 10, 2, 0)  # 2 AM firefight
        areas = ["iamai", "tests", "tools", "notes", "docs", "snippets"]
        offsets_seconds = [0, 20, 45, 300, 310, 320, 330, 2000, 2010, 5000]
        commits = [
            _make_commit(
                sha=f"s{i}",
                ts=base + timedelta(seconds=offsets_seconds[i]),
                author="oncall" if i % 2 == 0 else "founder",
                files=[f"{areas[i % len(areas)]}/emergency_{i}.py"],
                lines=abs((i * 271) % 2000) + 1,
                message="Revert the revert" if i % 3 == 0 else f"hotfix {i}",
            )
            for i in range(len(offsets_seconds))
        ]
        result = compute_turbulence(commits, window_minutes=5)
        self.assertGreater(result.turbulence_score, 0.30)

    def test_trend_after_stabilization(self):
        """Compute turbulence over multiple windows and check trend."""
        # Window 1: chaotic
        w1 = _bursty_commits(5, 8)
        r1 = compute_turbulence(w1, window_minutes=10)

        # Window 2: calmer
        w2 = _clock_commits(15, interval_seconds=600)
        r2 = compute_turbulence(w2, window_minutes=10)

        # Window 3: very calm
        w3 = _clock_commits(20, interval_seconds=900)
        r3 = compute_turbulence(w3, window_minutes=15)

        scores = [r1.turbulence_score, r2.turbulence_score, r3.turbulence_score]
        trend = turbulence_trend(scores)
        # Should be decreasing or stable
        self.assertIn(trend.direction, ["decreasing", "stable"])


if __name__ == "__main__":
    unittest.main()
