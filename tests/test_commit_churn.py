#!/usr/bin/env python3
"""Tests for iamai/commit_churn.py — 30 tests.

The commit_churn module detects when the writer is rewriting the same
files instead of producing new content.  Tests cover:

1. _file_overlap — pure set overlap logic
2. _rewrite_ratio — insertion/deletion symmetry detection
3. _per_commit_churn — single-commit scoring
4. churn_index — end-to-end multi-commit analysis
5. Band classification — threshold boundaries
6. Edge cases — empty inputs, single commit, zero-change commits
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.commit_churn import (
    _file_overlap,
    _rewrite_ratio,
    _per_commit_churn,
    _band,
    churn_index,
)


class TestFileOverlap(unittest.TestCase):
    """Tests for _file_overlap(current, previous)."""

    def test_no_overlap(self):
        self.assertAlmostEqual(
            _file_overlap({"a.md", "b.md"}, {"c.md", "d.md"}), 0.0
        )

    def test_full_overlap(self):
        self.assertAlmostEqual(
            _file_overlap({"a.md", "b.md"}, {"a.md", "b.md"}), 1.0
        )

    def test_partial_overlap(self):
        # 1 of 2 current files overlap → 0.5
        self.assertAlmostEqual(
            _file_overlap({"a.md", "b.md"}, {"a.md", "c.md"}), 0.5
        )

    def test_current_empty(self):
        # empty current → 0.0 (no files to overlap)
        self.assertAlmostEqual(_file_overlap(set(), {"a.md"}), 0.0)

    def test_previous_empty(self):
        # empty previous → 0.0 (nothing to overlap with)
        self.assertAlmostEqual(_file_overlap({"a.md"}, set()), 0.0)

    def test_both_empty(self):
        self.assertAlmostEqual(_file_overlap(set(), set()), 0.0)

    def test_superset_previous(self):
        # overlap is measured against current, not previous
        self.assertAlmostEqual(
            _file_overlap({"a.md"}, {"a.md", "b.md", "c.md"}), 1.0
        )


class TestRewriteRatio(unittest.TestCase):
    """Tests for _rewrite_ratio(insertions, deletions)."""

    def test_pure_addition(self):
        self.assertAlmostEqual(_rewrite_ratio(100, 0), 0.0)

    def test_pure_deletion(self):
        self.assertAlmostEqual(_rewrite_ratio(0, 50), 0.0)

    def test_perfect_rewrite(self):
        self.assertAlmostEqual(_rewrite_ratio(50, 50), 1.0)

    def test_partial_rewrite(self):
        # min(30, 50) / max(30, 50) = 30/50 = 0.6
        self.assertAlmostEqual(_rewrite_ratio(30, 50), 0.6)

    def test_both_zero(self):
        # edge case: no changes at all → 0/1 = 0.0
        self.assertAlmostEqual(_rewrite_ratio(0, 0), 0.0)

    def test_one_each(self):
        self.assertAlmostEqual(_rewrite_ratio(1, 1), 1.0)

    def test_large_add_small_delete(self):
        # min(1, 1000) / max(1, 1000) ≈ 0.001
        ratio = _rewrite_ratio(1000, 1)
        self.assertAlmostEqual(ratio, 0.001)


class TestPerCommitChurn(unittest.TestCase):
    """Tests for _per_commit_churn(commit, prev_files)."""

    def test_no_overlap_pure_add(self):
        commit = {"files": {"new.md"}, "insertions": 20, "deletions": 0}
        score = _per_commit_churn(commit, {"old.md"})
        # 0.6 * 0.0 + 0.4 * 0.0 = 0.0
        self.assertAlmostEqual(score, 0.0)

    def test_full_overlap_pure_rewrite(self):
        commit = {"files": {"a.md"}, "insertions": 30, "deletions": 30}
        score = _per_commit_churn(commit, {"a.md"})
        # 0.6 * 1.0 + 0.4 * 1.0 = 1.0
        self.assertAlmostEqual(score, 1.0)

    def test_full_overlap_pure_add(self):
        # same files, but only adding lines → only overlap contributes
        commit = {"files": {"a.md"}, "insertions": 50, "deletions": 0}
        score = _per_commit_churn(commit, {"a.md"})
        # 0.6 * 1.0 + 0.4 * 0.0 = 0.6
        self.assertAlmostEqual(score, 0.6)

    def test_no_overlap_pure_rewrite(self):
        # different files, but heavy rewriting within them
        commit = {"files": {"new.md"}, "insertions": 10, "deletions": 10}
        score = _per_commit_churn(commit, {"old.md"})
        # 0.6 * 0.0 + 0.4 * 1.0 = 0.4
        self.assertAlmostEqual(score, 0.4)

    def test_missing_keys(self):
        # commit with no files key, no insertions/deletions
        score = _per_commit_churn({}, {"a.md"})
        self.assertAlmostEqual(score, 0.0)

    def test_score_range(self):
        commit = {"files": {"a.md", "b.md"}, "insertions": 5, "deletions": 3}
        score = _per_commit_churn(commit, {"a.md", "c.md"})
        # overlap = 1/2 = 0.5, rewrite = min(5,3)/max(5,3) = 3/5 = 0.6
        # 0.6 * 0.5 + 0.4 * 0.6 = 0.3 + 0.24 = 0.54
        self.assertAlmostEqual(score, 0.54)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestBand(unittest.TestCase):
    """Tests for _band(score)."""

    def test_healthy_low(self):
        self.assertEqual(_band(0), "healthy")

    def test_healthy_boundary(self):
        self.assertEqual(_band(29), "healthy")

    def test_churning_start(self):
        self.assertEqual(_band(30), "churning")

    def test_churning_boundary(self):
        self.assertEqual(_band(59), "churning")

    def test_stalled_start(self):
        self.assertEqual(_band(60), "stalled")

    def test_stalled_max(self):
        self.assertEqual(_band(100), "stalled")


class TestChurnIndex(unittest.TestCase):
    """Tests for churn_index(commits) — end-to-end analysis."""

    def test_empty_input(self):
        result = churn_index([])
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["band"], "healthy")
        self.assertEqual(result["per_commit"], [])
        self.assertIn("no commits", result["summary"])

    def test_single_commit(self):
        # single commit: first commit's score uses empty prev_files
        commits = [{"files": {"a.md"}, "insertions": 10, "deletions": 0}]
        result = churn_index(commits)
        # only one commit → effective = scores[0] (no skip since len ≤ 1)
        self.assertIn("score", result)
        self.assertIn("band", result)
        self.assertEqual(len(result["per_commit"]), 1)

    def test_two_commits_no_overlap(self):
        commits = [
            {"files": {"a.md"}, "insertions": 10, "deletions": 0},
            {"files": {"b.md"}, "insertions": 20, "deletions": 0},
        ]
        result = churn_index(commits)
        # commit 1 vs empty prev: overlap=0, rewrite=0 → 0.0
        # commit 2 vs {a.md}: overlap=0, rewrite=0 → 0.0
        # effective = [0.0] (skip first)
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["band"], "healthy")

    def test_two_commits_full_churn(self):
        commits = [
            {"files": {"a.md"}, "insertions": 10, "deletions": 0},
            {"files": {"a.md"}, "insertions": 10, "deletions": 10},
        ]
        result = churn_index(commits)
        # commit 2: overlap=1.0, rewrite=1.0 → 0.6+0.4 = 1.0
        # effective = [1.0]
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["band"], "stalled")

    def test_mixed_commits(self):
        commits = [
            {"files": {"a.md", "b.md"}, "insertions": 20, "deletions": 0},
            {"files": {"a.md", "c.md"}, "insertions": 15, "deletions": 5},
            {"files": {"d.md"}, "insertions": 30, "deletions": 0},
        ]
        result = churn_index(commits)
        # commit 1: overlap=0, rewrite=0 → 0.0
        # commit 2: overlap=0.5, rewrite=5/15=0.333 → 0.6*0.5+0.4*0.333=0.433
        # commit 3: overlap=0, rewrite=0 → 0.0
        # effective (skip first) = [0.433, 0.0] → mean ≈ 0.217 → score 22
        self.assertEqual(result["band"], "healthy")
        self.assertEqual(len(result["per_commit"]), 3)

    def test_churning_band(self):
        # engineer a sequence that yields ~0.4 mean churn
        commits = [
            {"files": {"a.md"}, "insertions": 10, "deletions": 0},
            {"files": {"a.md"}, "insertions": 5, "deletions": 5},   # 0.6+0.4=1.0
            {"files": {"b.md"}, "insertions": 10, "deletions": 0},   # 0.0+0.0=0.0
            {"files": {"b.md"}, "insertions": 8, "deletions": 2},    # 0.6+0.4*(2/8)=0.7
        ]
        result = churn_index(commits)
        # effective = [1.0, 0.0, 0.7] → mean ≈ 0.567 → score 57
        self.assertEqual(result["band"], "churning")

    def test_summary_high_churn_count(self):
        commits = [
            {"files": {"a.md"}, "insertions": 10, "deletions": 0},
            {"files": {"a.md"}, "insertions": 10, "deletions": 10},  # 1.0
            {"files": {"a.md"}, "insertions": 10, "deletions": 10},  # 1.0
        ]
        result = churn_index(commits)
        self.assertIn("2 high-churn commits", result["summary"])

    def test_score_clamped_to_100(self):
        # even with extreme values, score must not exceed 100
        commits = [
            {"files": {"a.md"}, "insertions": 1, "deletions": 0},
            {"files": {"a.md"}, "insertions": 9999, "deletions": 9999},
        ]
        result = churn_index(commits)
        self.assertLessEqual(result["score"], 100)

    def test_score_clamped_to_0(self):
        result = churn_index([])
        self.assertGreaterEqual(result["score"], 0)

    def test_per_commit_scores_preserved(self):
        commits = [
            {"files": {"x.md"}, "insertions": 5, "deletions": 0},
            {"files": {"y.md"}, "insertions": 10, "deletions": 0},
            {"files": {"z.md"}, "insertions": 8, "deletions": 0},
        ]
        result = churn_index(commits)
        self.assertEqual(len(result["per_commit"]), 3)
        # all are pure-add on new files → all scores should be 0
        for s in result["per_commit"]:
            self.assertAlmostEqual(s, 0.0)

    def test_result_keys(self):
        result = churn_index([{"files": {"a.md"}, "insertions": 1, "deletions": 0}])
        for key in ("score", "band", "per_commit", "summary"):
            self.assertIn(key, result)


class TestChurnIndexRealistic(unittest.TestCase):
    """Integration-style tests simulating real writer patterns."""

    def test_healthy_writer_pattern(self):
        """A healthy writer touches different files with additive changes."""
        commits = [
            {"files": {"docs/GARDEN.md"}, "insertions": 5, "deletions": 0},
            {"files": {"notes/a.md"}, "insertions": 20, "deletions": 1},
            {"files": {"iamai/new.py"}, "insertions": 80, "deletions": 0},
            {"files": {"tests/test_new.py"}, "insertions": 60, "deletions": 0},
            {"files": {"docs/DEVLOG.md", "snippets/x.py"}, "insertions": 10, "deletions": 2},
        ]
        result = churn_index(commits)
        self.assertEqual(result["band"], "healthy")
        self.assertLess(result["score"], 30)

    def test_stalled_writer_pattern(self):
        """A stalled writer rewrites the same files repeatedly."""
        commits = [
            {"files": {"data/strokes.jsonl", "docs/DEVLOG.md"}, "insertions": 3, "deletions": 3},
            {"files": {"data/strokes.jsonl", "docs/DEVLOG.md"}, "insertions": 2, "deletions": 2},
            {"files": {"data/strokes.jsonl", "docs/DEVLOG.md"}, "insertions": 3, "deletions": 3},
            {"files": {"data/strokes.jsonl", "docs/DEVLOG.md"}, "insertions": 2, "deletions": 2},
        ]
        result = churn_index(commits)
        self.assertEqual(result["band"], "stalled")
        self.assertGreater(result["score"], 59)


if __name__ == "__main__":
    unittest.main()
