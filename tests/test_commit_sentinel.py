#!/usr/bin/env python3
"""Tests for commit_sentinel — 44 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.commit_sentinel import (  # noqa: E402
    SentinelReport,
    _compute_score,
    _score_to_verdict,
    _signal_change_scope,
    _signal_file_count,
    _signal_length_variance,
    _signal_message_length,
    _signal_message_pattern,
    _signal_timing_regularity,
    automation_ratio,
    classify_commit,
    classify_history,
)


# ---------------------------------------------------------------------------
# Signal: message_pattern
# ---------------------------------------------------------------------------

class TestSignalMessagePattern(unittest.TestCase):
    """Message pattern detection."""

    def test_catchup_detected(self):
        self.assertEqual(_signal_message_pattern("catch-up: commit pending"), 1.0)

    def test_visit_detected(self):
        self.assertEqual(_signal_message_pattern("visit-123: add module"), 1.0)

    def test_stroke_detected(self):
        self.assertEqual(_signal_message_pattern("stroke 42 things"), 1.0)

    def test_auto_commit_detected(self):
        self.assertEqual(_signal_message_pattern("auto-commit batch"), 1.0)

    def test_bot_prefix_detected(self):
        self.assertEqual(_signal_message_pattern("bot: scheduled push"), 1.0)

    def test_feat_prefix_human(self):
        self.assertEqual(_signal_message_pattern("feat(auth): add login"), 0.0)

    def test_fix_prefix_human(self):
        self.assertEqual(_signal_message_pattern("fix: null pointer"), 0.0)

    def test_merge_human(self):
        self.assertEqual(_signal_message_pattern("Merge branch 'main'"), 0.0)

    def test_unknown_message_neutral(self):
        val = _signal_message_pattern("updated the thing")
        self.assertAlmostEqual(val, 0.3)


# ---------------------------------------------------------------------------
# Signal: message_length
# ---------------------------------------------------------------------------

class TestSignalMessageLength(unittest.TestCase):
    """Message length uniformity."""

    def test_same_as_average(self):
        # 20 chars, history avg ~20
        val = _signal_message_length("exactly twenty chars", [18, 20, 22, 19, 21])
        self.assertGreaterEqual(val, 0.5)

    def test_very_different_from_average(self):
        # 5 chars vs avg ~50
        val = _signal_message_length("tiny", [48, 50, 52, 49, 51])
        self.assertLessEqual(val, 0.3)

    def test_empty_history(self):
        val = _signal_message_length("hello", [])
        self.assertAlmostEqual(val, 0.3)

    def test_short_history(self):
        val = _signal_message_length("hello", [10, 12])
        self.assertAlmostEqual(val, 0.3)


# ---------------------------------------------------------------------------
# Signal: length_variance
# ---------------------------------------------------------------------------

class TestSignalLengthVariance(unittest.TestCase):
    """Message length variance."""

    def test_zero_variance(self):
        val = _signal_length_variance([20, 20, 20, 20, 20])
        self.assertGreaterEqual(val, 0.8)

    def test_high_variance(self):
        val = _signal_length_variance([5, 100, 10, 200, 3])
        self.assertLessEqual(val, 0.3)

    def test_moderate_variance(self):
        val = _signal_length_variance([30, 40, 35, 45, 38])
        self.assertGreaterEqual(val, 0.2)
        self.assertLessEqual(val, 0.7)

    def test_too_few_samples(self):
        val = _signal_length_variance([10, 20])
        self.assertAlmostEqual(val, 0.3)


# ---------------------------------------------------------------------------
# Signal: file_count
# ---------------------------------------------------------------------------

class TestSignalFileCount(unittest.TestCase):
    """File count roundness."""

    def test_single_file(self):
        self.assertAlmostEqual(_signal_file_count(1), 0.7)

    def test_five_files(self):
        self.assertAlmostEqual(_signal_file_count(5), 0.6)

    def test_three_files(self):
        self.assertAlmostEqual(_signal_file_count(3), 0.2)

    def test_zero_files(self):
        self.assertAlmostEqual(_signal_file_count(0), 0.5)

    def test_seven_files(self):
        val = _signal_file_count(7)
        self.assertAlmostEqual(val, 0.4)


# ---------------------------------------------------------------------------
# Signal: timing_regularity
# ---------------------------------------------------------------------------

class TestSignalTimingRegularity(unittest.TestCase):
    """Timing regularity detection."""

    def test_perfectly_regular(self):
        # Exactly 600s apart
        ts = [1000, 1600, 2200, 2800, 3400, 4000]
        val = _signal_timing_regularity(ts)
        self.assertGreaterEqual(val, 0.9)

    def test_very_irregular(self):
        ts = [1000, 1001, 5000, 5002, 9999, 10000]
        val = _signal_timing_regularity(ts)
        self.assertLessEqual(val, 0.3)

    def test_too_few_timestamps(self):
        val = _signal_timing_regularity([1000, 1600])
        self.assertAlmostEqual(val, 0.3)

    def test_moderate_regularity(self):
        ts = [1000, 1400, 2100, 2500, 3300]
        val = _signal_timing_regularity(ts)
        self.assertGreater(val, 0.1)
        self.assertLess(val, 0.9)


# ---------------------------------------------------------------------------
# Signal: change_scope
# ---------------------------------------------------------------------------

class TestSignalChangeScope(unittest.TestCase):
    """Change scope analysis."""

    def test_balanced_changes(self):
        val = _signal_change_scope(7, 50, 50)
        self.assertAlmostEqual(val, 0.6)

    def test_all_insertions(self):
        val = _signal_change_scope(3, 100, 0)
        self.assertAlmostEqual(val, 0.3)

    def test_all_deletions(self):
        val = _signal_change_scope(3, 0, 100)
        self.assertAlmostEqual(val, 0.3)

    def test_zero_changes(self):
        val = _signal_change_scope(0, 0, 0)
        self.assertAlmostEqual(val, 0.5)


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

class TestComputeScore(unittest.TestCase):
    """Weighted score computation."""

    def test_all_high_signals(self):
        signals = {k: 1.0 for k in [
            "message_pattern", "message_length", "length_variance",
            "file_count", "timing_regularity", "change_scope",
        ]}
        self.assertEqual(_compute_score(signals), 100)

    def test_all_low_signals(self):
        signals = {k: 0.0 for k in [
            "message_pattern", "message_length", "length_variance",
            "file_count", "timing_regularity", "change_scope",
        ]}
        self.assertEqual(_compute_score(signals), 0)

    def test_empty_signals(self):
        self.assertEqual(_compute_score({}), 50)

    def test_partial_signals(self):
        signals = {"message_pattern": 1.0, "file_count": 0.0}
        score = _compute_score(signals)
        self.assertGreater(score, 0)
        self.assertLess(score, 100)


# ---------------------------------------------------------------------------
# Verdict mapping
# ---------------------------------------------------------------------------

class TestScoreToVerdict(unittest.TestCase):
    """Score to verdict mapping."""

    def test_automated(self):
        self.assertEqual(_score_to_verdict(80), "automated")
        self.assertEqual(_score_to_verdict(100), "automated")
        self.assertEqual(_score_to_verdict(75), "automated")

    def test_likely_auto(self):
        self.assertEqual(_score_to_verdict(50), "likely_auto")
        self.assertEqual(_score_to_verdict(74), "likely_auto")

    def test_likely_human(self):
        self.assertEqual(_score_to_verdict(25), "likely_human")
        self.assertEqual(_score_to_verdict(49), "likely_human")

    def test_human(self):
        self.assertEqual(_score_to_verdict(0), "human")
        self.assertEqual(_score_to_verdict(24), "human")


# ---------------------------------------------------------------------------
# classify_commit — integration
# ---------------------------------------------------------------------------

class TestClassifyCommit(unittest.TestCase):
    """Full classification pipeline."""

    def test_obvious_bot_commit(self):
        commit = {
            "message": "catch-up: commit pending changes before process restart",
            "files_changed": 7,
            "insertions": 76,
            "deletions": 55,
            "timestamp_epoch": 1700000000,
        }
        history_msgs = [
            "catch-up: commit pending changes before process restart",
            "catch-up: commit pending changes before process restart",
            "catch-up: commit pending changes before process restart",
            "catch-up: commit pending changes before process restart",
            "catch-up: commit pending changes before process restart",
        ]
        history_ts = [
            1699998200, 1699998800, 1699999400, 1700000000, 1700000600,
        ]
        report = classify_commit(commit, history_msgs, history_ts)
        self.assertIsInstance(report, SentinelReport)
        self.assertIn(report.verdict, ("automated", "likely_auto"))
        self.assertGreater(report.score, 40)
        self.assertTrue(report.is_automated())

    def test_obvious_human_commit(self):
        commit = {
            "message": "feat(ui): redesign the dashboard with new colour scheme",
            "files_changed": 12,
            "insertions": 340,
            "deletions": 20,
            "timestamp_epoch": 1700050000,
        }
        history_msgs = [
            "fix: resolve login timeout",
            "docs: update README",
            "WIP: working on new feature",
            "refactor(auth): simplify token handling",
            "Initial commit",
        ]
        history_ts = [
            1700000000, 1700010000, 1700025000, 1700030000, 1700040000,
        ]
        report = classify_commit(commit, history_msgs, history_ts)
        self.assertIn(report.verdict, ("human", "likely_human"))
        self.assertFalse(report.is_automated())

    def test_minimal_commit(self):
        commit = {"message": "stuff", "files_changed": 1}
        report = classify_commit(commit)
        self.assertIsInstance(report, SentinelReport)
        self.assertGreaterEqual(report.score, 0)
        self.assertLessEqual(report.score, 100)

    def test_empty_message(self):
        commit = {"message": "", "files_changed": 0}
        report = classify_commit(commit)
        self.assertIsNotNone(report.verdict)

    def test_message_hash_present(self):
        commit = {"message": "test commit", "files_changed": 1}
        report = classify_commit(commit)
        self.assertEqual(len(report.message_hash), 12)

    def test_summary_format(self):
        commit = {"message": "test", "files_changed": 3}
        report = classify_commit(commit)
        s = report.summary()
        self.assertIn("commit_sentinel:", s)
        self.assertIn("score=", s)
        self.assertIn("verdict=", s)

    def test_to_dict(self):
        commit = {"message": "test", "files_changed": 3}
        report = classify_commit(commit)
        d = report.to_dict()
        self.assertIn("score", d)
        self.assertIn("verdict", d)
        self.assertIn("signals", d)
        self.assertIn("message_hash", d)


# ---------------------------------------------------------------------------
# classify_history
# ---------------------------------------------------------------------------

class TestClassifyHistory(unittest.TestCase):
    """Batch classification."""

    def test_empty_history(self):
        self.assertEqual(classify_history([]), [])

    def test_single_commit(self):
        commits = [{"message": "feat: add thing", "files_changed": 5, "timestamp_epoch": 1000}]
        reports = classify_history(commits)
        self.assertEqual(len(reports), 1)

    def test_mixed_history(self):
        commits = [
            {"message": "feat: initial", "files_changed": 3, "timestamp_epoch": 1000},
            {"message": "catch-up: commit pending", "files_changed": 7, "timestamp_epoch": 1600},
            {"message": "fix: bug in auth", "files_changed": 2, "timestamp_epoch": 2500},
            {"message": "catch-up: commit pending", "files_changed": 7, "timestamp_epoch": 3100},
            {"message": "docs: update README", "files_changed": 1, "timestamp_epoch": 9000},
        ]
        reports = classify_history(commits)
        self.assertEqual(len(reports), 5)
        # Bot commits should score higher than human ones
        self.assertGreater(reports[1].score, reports[0].score)

    def test_automation_ratio_empty(self):
        self.assertEqual(automation_ratio([]), 0.0)

    def test_automation_ratio_all_auto(self):
        reports = [
            SentinelReport(score=90, verdict="automated"),
            SentinelReport(score=80, verdict="automated"),
        ]
        self.assertAlmostEqual(automation_ratio(reports), 1.0)

    def test_automation_ratio_mixed(self):
        reports = [
            SentinelReport(score=90, verdict="automated"),
            SentinelReport(score=10, verdict="human"),
        ]
        self.assertAlmostEqual(automation_ratio(reports), 0.5)


if __name__ == "__main__":
    unittest.main()
