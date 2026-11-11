#!/usr/bin/env python3
"""Tests for commit_inertia — momentum persistence analysis for commit flow.

60 tests covering:
- CommitRecord construction and area extraction
- change_persistence (all survive, all overwritten, reverts, heavy deletions,
  empty commits, single commit, threshold boundary)
- follow_up_rate (all follow up, none follow up, empty files, single commit)
- amplification (full overlap, partial, none, single commit, empty current)
- decay_half_life (uniform gaps, varied gaps, no revisits, single commit)
- classify_inertia (all five classes + boundary values)
- compute_inertia (composite scoring, empty input, weight balance)
- inertia_report formatting
- inertia_trend (increasing, decreasing, stable, single, empty)
- full pipeline integration
"""

import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from iamai.commit_inertia import (
    CommitRecord,
    InertiaResult,
    InertiaTrend,
    _file_overlap,
    _is_revert,
    amplification,
    change_persistence,
    classify_inertia,
    compute_inertia,
    decay_half_life,
    follow_up_rate,
    inertia_report,
    inertia_trend,
)


def _mkcommit(
    hash: str,
    files: list,
    msg: str = "update",
    author: str = "qwen",
    ins: int = 10,
    dels: int = 2,
    ts_offset_minutes: int = 0,
) -> CommitRecord:
    """Helper to create a CommitRecord."""
    base = datetime(2025, 6, 1, 12, 0, 0)
    return CommitRecord(
        hash=hash,
        author=author,
        timestamp=base + timedelta(minutes=ts_offset_minutes),
        message=msg,
        files_changed=list(files),
        insertions=ins,
        deletions=dels,
    )


class TestCommitRecord(unittest.TestCase):
    """Tests for CommitRecord data class."""

    def test_areas_with_directories(self):
        c = _mkcommit("abc", ["src/foo.py", "tests/test_foo.py", "docs/readme.md"])
        self.assertEqual(c.areas(), {"src", "tests", "docs"})

    def test_areas_root_files(self):
        c = _mkcommit("abc", ["README.md", "setup.py"])
        self.assertEqual(c.areas(), {"__root__"})

    def test_areas_mixed(self):
        c = _mkcommit("abc", ["src/bar.py", "LICENSE"])
        self.assertEqual(c.areas(), {"src", "__root__"})

    def test_areas_empty(self):
        c = _mkcommit("abc", [])
        self.assertEqual(c.areas(), set())


class TestIsRevert(unittest.TestCase):
    """Tests for the revert detection helper."""

    def test_revert_prefix(self):
        self.assertTrue(_is_revert("Revert \"add feature X\""))

    def test_rollback(self):
        self.assertTrue(_is_revert("Rollback database migration"))

    def test_undo(self):
        self.assertTrue(_is_revert("Undo last deploy"))

    def test_rolls_back(self):
        self.assertTrue(_is_revert("This rolls back the auth change"))

    def test_normal_message(self):
        self.assertFalse(_is_revert("Add timeout parameter"))

    def test_partial_match(self):
        self.assertFalse(_is_revert("prevent accidental revert in parser"))


class TestFileOverlap(unittest.TestCase):
    """Tests for the _file_overlap helper."""

    def test_full_overlap(self):
        self.assertEqual(_file_overlap(["a", "b", "c"], ["a", "b", "c"]), 3)

    def test_partial_overlap(self):
        self.assertEqual(_file_overlap(["a", "b"], ["b", "c"]), 1)

    def test_no_overlap(self):
        self.assertEqual(_file_overlap(["a", "b"], ["c", "d"]), 0)

    def test_empty_lists(self):
        self.assertEqual(_file_overlap([], ["a"]), 0)
        self.assertEqual(_file_overlap(["a"], []), 0)


class TestChangePersistence(unittest.TestCase):
    """Tests for the change_persistence metric."""

    def test_all_survive(self):
        commits = [
            _mkcommit("a1", ["src/foo.py"], "add foo"),
            _mkcommit("a2", ["src/bar.py"], "add bar"),
            _mkcommit("a3", ["src/baz.py"], "add baz"),
        ]
        self.assertAlmostEqual(change_persistence(commits), 1.0)

    def test_revert_overwrites(self):
        commits = [
            _mkcommit("a1", ["src/foo.py", "src/bar.py"], "add feature"),
            _mkcommit("a2", ["src/foo.py", "src/bar.py"], "Revert add feature", ins=2, dels=20),
        ]
        # First commit gets overwritten by the revert
        # Second commit survives (nothing after it)
        result = change_persistence(commits)
        self.assertAlmostEqual(result, 0.5)

    def test_heavy_deletion_overwrites(self):
        commits = [
            _mkcommit("a1", ["src/foo.py", "src/bar.py", "src/baz.py"], "add stuff"),
            _mkcommit("a2", ["src/foo.py", "src/bar.py", "src/baz.py"], "cleanup",
                      ins=5, dels=50),
        ]
        # Second commit has del_ratio = 50/55 ≈ 0.91 > 0.60 and touches >50% files
        result = change_persistence(commits)
        self.assertAlmostEqual(result, 0.5)

    def test_small_overlap_no_overwrite(self):
        """Later commit touches fewer than threshold files → no overwrite."""
        commits = [
            _mkcommit("a1", ["a.py", "b.py", "c.py", "d.py"], "big change"),
            _mkcommit("a2", ["a.py"], "small fix", ins=2, dels=20),
        ]
        # a2 touches 1 of 4 files = 25% < 50% threshold → a1 survives
        result = change_persistence(commits)
        self.assertAlmostEqual(result, 1.0)

    def test_empty_commit_survives(self):
        commits = [
            _mkcommit("a1", [], "empty commit"),
            _mkcommit("a2", ["src/foo.py"], "add foo"),
        ]
        self.assertAlmostEqual(change_persistence(commits), 1.0)

    def test_single_commit(self):
        commits = [_mkcommit("a1", ["src/foo.py"], "init")]
        self.assertAlmostEqual(change_persistence(commits), 1.0)

    def test_empty_input(self):
        self.assertAlmostEqual(change_persistence([]), 0.0)

    def test_overwrite_window_respects_range(self):
        """Overwrite check should only look within the window."""
        commits = [
            _mkcommit("a1", ["src/foo.py", "src/bar.py"], "add feature"),
            _mkcommit("a2", ["other.py"], "other 1"),
            _mkcommit("a3", ["other.py"], "other 2"),
            _mkcommit("a4", ["other.py"], "other 3"),
            _mkcommit("a5", ["other.py"], "other 4"),
            _mkcommit("a6", ["other.py"], "other 5"),
            _mkcommit("a7", ["src/foo.py", "src/bar.py"], "Revert feature", ins=1, dels=30),
        ]
        # With overwrite_window=5, from a1 we check a2..a6; revert is at a7 (outside window)
        result = change_persistence(commits, overwrite_window=5)
        self.assertAlmostEqual(result, 1.0)

        # With overwrite_window=6, from a1 we check a2..a7; revert at a7 is in range
        result2 = change_persistence(commits, overwrite_window=6)
        self.assertLess(result2, 1.0)


class TestFollowUpRate(unittest.TestCase):
    """Tests for the follow_up_rate metric."""

    def test_all_follow_up(self):
        commits = [
            _mkcommit("a1", ["src/foo.py", "src/bar.py"]),
            _mkcommit("a2", ["src/foo.py", "tests/test_foo.py"]),
            _mkcommit("a3", ["src/bar.py", "docs/readme.md"]),
        ]
        # Pair (a1,a2): share src/foo.py → yes
        # Pair (a2,a3): share src/bar.py? No. a2 has src/foo.py, tests/test_foo.py; a3 has src/bar.py
        # Actually: a2 files = {src/foo.py, tests/test_foo.py}, a3 files = {src/bar.py, docs/readme.md}
        # No overlap → only 1 of 2 pairs
        result = follow_up_rate(commits)
        self.assertAlmostEqual(result, 0.5)

    def test_none_follow_up(self):
        commits = [
            _mkcommit("a1", ["src/foo.py"]),
            _mkcommit("a2", ["tests/bar.py"]),
            _mkcommit("a3", ["docs/baz.md"]),
        ]
        self.assertAlmostEqual(follow_up_rate(commits), 0.0)

    def test_all_follow_up_perfect(self):
        commits = [
            _mkcommit("a1", ["shared.py"]),
            _mkcommit("a2", ["shared.py", "extra.py"]),
            _mkcommit("a3", ["shared.py"]),
        ]
        self.assertAlmostEqual(follow_up_rate(commits), 1.0)

    def test_empty_files_skipped(self):
        commits = [
            _mkcommit("a1", []),
            _mkcommit("a2", ["src/foo.py"]),
        ]
        # a1 has no files → pair skipped
        self.assertAlmostEqual(follow_up_rate(commits), 0.0)

    def test_single_commit(self):
        commits = [_mkcommit("a1", ["src/foo.py"])]
        self.assertAlmostEqual(follow_up_rate(commits), 0.0)

    def test_empty_input(self):
        self.assertAlmostEqual(follow_up_rate([]), 0.0)


class TestAmplification(unittest.TestCase):
    """Tests for the amplification metric."""

    def test_full_overlap(self):
        commits = [
            _mkcommit("a1", ["a.py", "b.py"]),
            _mkcommit("a2", ["a.py", "b.py"]),
        ]
        # overlap = 2, current files = 2, ratio = 1.0
        self.assertAlmostEqual(amplification(commits), 1.0)

    def test_partial_overlap(self):
        commits = [
            _mkcommit("a1", ["a.py", "b.py"]),
            _mkcommit("a2", ["a.py", "c.py", "d.py", "e.py"]),
        ]
        # overlap = 1, current files = 4, ratio = 0.25
        self.assertAlmostEqual(amplification(commits), 0.25)

    def test_no_overlap(self):
        commits = [
            _mkcommit("a1", ["a.py"]),
            _mkcommit("a2", ["b.py", "c.py"]),
        ]
        # No overlap → skipped, empty ratios → 0.0
        self.assertAlmostEqual(amplification(commits), 0.0)

    def test_single_commit(self):
        commits = [_mkcommit("a1", ["a.py"])]
        self.assertAlmostEqual(amplification(commits), 0.0)

    def test_empty_current_skipped(self):
        commits = [
            _mkcommit("a1", ["a.py"]),
            _mkcommit("a2", []),
        ]
        self.assertAlmostEqual(amplification(commits), 0.0)

    def test_mixed_overlaps(self):
        commits = [
            _mkcommit("a1", ["a.py", "b.py"]),
            _mkcommit("a2", ["a.py", "b.py"]),  # overlap=2, total=2, ratio=1.0
            _mkcommit("a3", ["c.py", "d.py"]),  # overlap=0 → skipped
        ]
        self.assertAlmostEqual(amplification(commits), 1.0)


class TestDecayHalfLife(unittest.TestCase):
    """Tests for the decay_half_life metric."""

    def test_uniform_gap(self):
        """File touched every 2 commits."""
        commits = [
            _mkcommit("a1", ["a.py", "b.py"]),
            _mkcommit("a2", ["c.py"]),
            _mkcommit("a3", ["a.py", "b.py"]),
            _mkcommit("a4", ["c.py"]),
            _mkcommit("a5", ["a.py", "b.py"]),
        ]
        # a.py: gaps [2, 2], b.py: gaps [2, 2], c.py: gaps [2]
        # All gaps = [2, 2, 2, 2, 2], median = 2
        result = decay_half_life(commits)
        self.assertAlmostEqual(result, 2.0)

    def test_varied_gaps(self):
        commits = [
            _mkcommit("a1", ["a.py"]),
            _mkcommit("a2", ["b.py"]),
            _mkcommit("a3", ["a.py"]),
            _mkcommit("a4", ["b.py"]),
            _mkcommit("a5", ["a.py"]),
        ]
        # a.py gaps: [2, 2], b.py gaps: [2]
        # All gaps = [2, 2, 2], median = 2
        self.assertAlmostEqual(decay_half_life(commits), 2.0)

    def test_no_revisits(self):
        """Every commit touches unique files."""
        commits = [
            _mkcommit("a1", ["a.py"]),
            _mkcommit("a2", ["b.py"]),
            _mkcommit("a3", ["c.py"]),
        ]
        self.assertAlmostEqual(decay_half_life(commits), 0.0)

    def test_single_commit(self):
        commits = [_mkcommit("a1", ["a.py"])]
        self.assertAlmostEqual(decay_half_life(commits), 0.0)

    def test_empty_input(self):
        self.assertAlmostEqual(decay_half_life([]), 0.0)

    def test_large_gap(self):
        commits = [
            _mkcommit("a1", ["a.py"]),
            _mkcommit("a2", ["b.py"]),
            _mkcommit("a3", ["c.py"]),
            _mkcommit("a4", ["d.py"]),
            _mkcommit("a5", ["e.py"]),
            _mkcommit("a6", ["a.py"]),
        ]
        # a.py gap = 5, only one gap → median = 5
        self.assertAlmostEqual(decay_half_life(commits), 5.0)


class TestClassifyInertia(unittest.TestCase):
    """Tests for classify_inertia."""

    def test_ballistic(self):
        self.assertEqual(classify_inertia(0.85), "ballistic")

    def test_ballistic_boundary(self):
        self.assertEqual(classify_inertia(0.80), "ballistic")

    def test_driven(self):
        self.assertEqual(classify_inertia(0.70), "driven")

    def test_driven_lower_boundary(self):
        self.assertEqual(classify_inertia(0.60), "driven")

    def test_cruising(self):
        self.assertEqual(classify_inertia(0.50), "cruising")

    def test_cruising_lower_boundary(self):
        self.assertEqual(classify_inertia(0.40), "cruising")

    def test_drifting(self):
        self.assertEqual(classify_inertia(0.30), "drifting")

    def test_drifting_lower_boundary(self):
        self.assertEqual(classify_inertia(0.20), "drifting")

    def test_stalled(self):
        self.assertEqual(classify_inertia(0.10), "stalled")

    def test_stalled_zero(self):
        self.assertEqual(classify_inertia(0.0), "stalled")

    def test_one(self):
        self.assertEqual(classify_inertia(1.0), "ballistic")


class TestComputeInertia(unittest.TestCase):
    """Tests for the composite compute_inertia function."""

    def test_empty_input(self):
        result = compute_inertia([])
        self.assertEqual(result.window_commits, 0)
        self.assertEqual(result.momentum_score, 0.0)
        self.assertEqual(result.inertia_class, "stalled")

    def test_high_inertia(self):
        """Commits that persist, follow up, and settle."""
        commits = []
        for i in range(20):
            commits.append(
                _mkcommit(
                    f"c{i:02d}",
                    ["src/core.py", "src/utils.py"],
                    f"improve feature {i}",
                    ins=15,
                    dels=3,
                    ts_offset_minutes=i * 15,
                )
            )
        result = compute_inertia(commits, ideal_half_life=5)
        self.assertGreater(result.momentum_score, 0.5)
        self.assertIn(result.inertia_class, ("ballistic", "driven", "cruising"))

    def test_low_inertia(self):
        """Commits that don't build on each other."""
        commits = []
        for i in range(20):
            commits.append(
                _mkcommit(
                    f"c{i:02d}",
                    [f"unique_{i}.py"],
                    f"isolated change {i}",
                    ins=5,
                    dels=1,
                    ts_offset_minutes=i * 15,
                )
            )
        result = compute_inertia(commits)
        # persistence=1.0 (no reverts) but follow_up=0, amplification=0, half_life=0
        # score = 0.35*1.0 = 0.35 — low but not zero because changes do persist
        self.assertLess(result.momentum_score, 0.40)

    def test_result_fields(self):
        commits = [
            _mkcommit("a1", ["src/foo.py"], "init"),
            _mkcommit("a2", ["src/foo.py", "src/bar.py"], "extend"),
        ]
        result = compute_inertia(commits, window_hours=24.0)
        self.assertEqual(result.window_commits, 2)
        self.assertEqual(result.window_hours, 24.0)
        self.assertIsInstance(result.change_persistence, float)
        self.assertIsInstance(result.follow_up_rate, float)
        self.assertIsInstance(result.amplification, float)
        self.assertIsInstance(result.decay_half_life, float)
        self.assertIsInstance(result.momentum_score, float)
        self.assertIsInstance(result.inertia_class, str)

    def test_half_life_normalization(self):
        """Half-life at or above ideal → score component = 1.0."""
        # All files touched every 10 commits → half_life = 10
        commits = []
        for i in range(21):
            commits.append(
                _mkcommit(f"c{i:02d}", ["shared.py"], f"update {i}",
                          ts_offset_minutes=i * 15)
            )
        result = compute_inertia(commits, ideal_half_life=10)
        # Half-life is exactly 10 → normalized = 1.0 → contributes 0.20
        # Plus persistence and follow-up should be high
        self.assertGreaterEqual(result.momentum_score, 0.20)

    def test_weight_balance(self):
        """Verify composite uses correct weights."""
        # Construct a scenario where we can compute exact expected score
        # persistence=1.0, follow_up=0.0, amplification=0.0, half_life_score=0.0
        commits = [
            _mkcommit("a1", ["a.py"], "init", ins=10, dels=1),
            _mkcommit("a2", ["b.py"], "other", ins=10, dels=1),
        ]
        # persistence: both survive → 1.0
        # follow_up: a1→a2, no overlap → 0.0
        # amplification: no overlap → 0.0
        # half_life: no revisits → 0.0
        result = compute_inertia(commits)
        expected = round(0.35 * 1.0 + 0.25 * 0.0 + 0.20 * 0.0 + 0.20 * 0.0, 4)
        self.assertAlmostEqual(result.momentum_score, expected)


class TestInertiaReport(unittest.TestCase):
    """Tests for the human-readable report."""

    def test_report_contains_key_sections(self):
        result = InertiaResult(
            window_commits=50,
            window_hours=168.0,
            change_persistence=0.85,
            follow_up_rate=0.42,
            amplification=0.31,
            decay_half_life=8.5,
            momentum_score=0.6235,
            inertia_class="driven",
        )
        report = inertia_report(result)
        self.assertIn("Inertia analysis", report)
        self.assertIn("driven", report)
        self.assertIn("50 commits", report)
        self.assertIn("85.00%", report)
        self.assertIn("42.00%", report)
        self.assertIn("8.5 commits", report)

    def test_report_stalled(self):
        result = InertiaResult(
            window_commits=5,
            window_hours=2.0,
            change_persistence=0.1,
            follow_up_rate=0.0,
            amplification=0.0,
            decay_half_life=0.0,
            momentum_score=0.035,
            inertia_class="stalled",
        )
        report = inertia_report(result)
        self.assertIn("stalled", report)


class TestInertiaTrend(unittest.TestCase):
    """Tests for trend analysis across inertia measurements."""

    def test_increasing(self):
        results = [
            InertiaResult(10, 24, 0.3, 0.2, 0.1, 5.0, 0.30, "drifting"),
            InertiaResult(10, 24, 0.5, 0.4, 0.3, 8.0, 0.50, "cruising"),
            InertiaResult(10, 24, 0.7, 0.6, 0.5, 12.0, 0.70, "driven"),
        ]
        trend = inertia_trend(results)
        self.assertEqual(trend.direction, "increasing")
        self.assertAlmostEqual(trend.score_delta, 0.40)

    def test_decreasing(self):
        results = [
            InertiaResult(10, 24, 0.8, 0.7, 0.6, 15.0, 0.80, "ballistic"),
            InertiaResult(10, 24, 0.3, 0.2, 0.1, 3.0, 0.30, "drifting"),
        ]
        trend = inertia_trend(results)
        self.assertEqual(trend.direction, "decreasing")
        self.assertAlmostEqual(trend.score_delta, -0.50)

    def test_stable(self):
        results = [
            InertiaResult(10, 24, 0.5, 0.4, 0.3, 8.0, 0.50, "cruising"),
            InertiaResult(10, 24, 0.5, 0.4, 0.3, 8.0, 0.52, "cruising"),
        ]
        trend = inertia_trend(results)
        self.assertEqual(trend.direction, "stable")

    def test_single_result(self):
        results = [
            InertiaResult(10, 24, 0.5, 0.4, 0.3, 8.0, 0.50, "cruising"),
        ]
        trend = inertia_trend(results)
        self.assertEqual(trend.direction, "stable")
        self.assertEqual(trend.sample_count, 1)

    def test_empty(self):
        trend = inertia_trend([])
        self.assertEqual(trend.direction, "stable")
        self.assertEqual(trend.score_delta, 0.0)
        self.assertEqual(trend.sample_count, 0)

    def test_boundary_exactly_005(self):
        """Delta of exactly 0.05 should be 'stable' (not > 0.05)."""
        results = [
            InertiaResult(10, 24, 0.5, 0.4, 0.3, 8.0, 0.50, "cruising"),
            InertiaResult(10, 24, 0.5, 0.4, 0.3, 8.0, 0.55, "cruising"),
        ]
        trend = inertia_trend(results)
        # 0.55 - 0.50 = 0.05, which is NOT > 0.05 → stable
        self.assertEqual(trend.direction, "stable")


class TestFullPipeline(unittest.TestCase):
    """Integration tests exercising the full pipeline."""

    def test_realistic_workflow(self):
        """Simulate a realistic development session."""
        commits = [
            _mkcommit("c01", ["src/auth.py"], "add auth module", ts_offset_minutes=0),
            _mkcommit("c02", ["src/auth.py", "tests/test_auth.py"], "add auth tests",
                      ts_offset_minutes=15),
            _mkcommit("c03", ["src/auth.py", "src/db.py"], "connect auth to db",
                      ts_offset_minutes=30),
            _mkcommit("c04", ["src/db.py", "tests/test_db.py"], "add db tests",
                      ts_offset_minutes=45),
            _mkcommit("c05", ["src/auth.py", "src/db.py", "src/api.py"], "wire api",
                      ts_offset_minutes=60),
            _mkcommit("c06", ["src/api.py", "tests/test_api.py"], "add api tests",
                      ts_offset_minutes=75),
            _mkcommit("c07", ["docs/architecture.md"], "document architecture",
                      ts_offset_minutes=90),
            _mkcommit("c08", ["src/auth.py", "src/api.py"], "refactor auth api",
                      ts_offset_minutes=105),
        ]
        result = compute_inertia(commits, window_hours=2.0, ideal_half_life=4)
        report = inertia_report(result)

        # Should be non-trivial
        self.assertGreater(result.momentum_score, 0.0)
        self.assertIn("Inertia analysis", report)
        self.assertEqual(result.window_commits, 8)

    def test_chaotic_repo(self):
        """A repo with reverts, scattered files, no follow-up."""
        commits = [
            _mkcommit("c01", ["a.py", "b.py"], "try feature X", ts_offset_minutes=0),
            _mkcommit("c02", ["c.py", "d.py"], "unrelated fix", ts_offset_minutes=5),
            _mkcommit("c03", ["a.py", "b.py"], "Revert try feature X",
                      ins=1, dels=30, ts_offset_minutes=10),
            _mkcommit("c04", ["e.py"], "random change", ts_offset_minutes=15),
            _mkcommit("c05", ["f.py", "g.py"], "another unrelated", ts_offset_minutes=20),
        ]
        result = compute_inertia(commits)
        # Should be low: reverts, no follow-up, no overlap
        self.assertLess(result.momentum_score, 0.40)

    def test_trend_across_windows(self):
        """Compute inertia across multiple windows and check trend."""
        windows = []
        for start in range(3):
            commits = []
            base_offset = start * 1000
            # Each window has increasingly more follow-up
            for i in range(10):
                files = ["shared.py"] if i <= start * 3 else [f"unique_{start}_{i}.py"]
                commits.append(
                    _mkcommit(
                        f"w{start}_c{i:02d}",
                        files,
                        f"update {i}",
                        ts_offset_minutes=base_offset + i * 15,
                    )
                )
            windows.append(compute_inertia(commits, ideal_half_life=5))

        trend = inertia_trend(windows)
        self.assertIsInstance(trend.direction, str)
        self.assertGreaterEqual(trend.sample_count, 3)


if __name__ == "__main__":
    unittest.main()
