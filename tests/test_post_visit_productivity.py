#!/usr/bin/env python3
"""Tests for post_visit_productivity — 28 test cases."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.post_visit_productivity import (  # noqa: E402
    Commit,
    ProductivityReport,
    classify_commit,
    compute_productivity,
    format_report,
    get_commits_since,
)


# ---------------------------------------------------------------------------
# classify_commit — repair patterns
# ---------------------------------------------------------------------------

class TestClassifyRepair(unittest.TestCase):
    """Commit messages that should classify as repair."""

    def test_catch_up_dash(self):
        self.assertEqual(classify_commit("catch-up: commit pending changes"), "repair")

    def test_catch_up_space(self):
        self.assertEqual(classify_commit("catch up on missed commits"), "repair")

    def test_lock_clean(self):
        self.assertEqual(classify_commit("lock clean: remove stale .lock file"), "repair")

    def test_lock_repair(self):
        self.assertEqual(classify_commit("lock repair after crash"), "repair")

    def test_state_reset(self):
        self.assertEqual(classify_commit("state reset: clear corrupted state"), "repair")

    def test_merge_fix(self):
        self.assertEqual(classify_commit("merge fix: resolve conflict in strokes.jsonl"), "repair")

    def test_backlog_drain(self):
        self.assertEqual(classify_commit("backlog drain: flush 12 pending files"), "repair")

    def test_pending_changes_before(self):
        self.assertEqual(
            classify_commit("catch-up: commit pending changes before process restart"),
            "repair",
        )

    def test_stale_lock(self):
        self.assertEqual(classify_commit("remove stale lock from crashed writer"), "repair")

    def test_orphan_cleanup(self):
        self.assertEqual(classify_commit("orphan cleanup: remove dangling refs"), "repair")


# ---------------------------------------------------------------------------
# classify_commit — progress patterns
# ---------------------------------------------------------------------------

class TestClassifyProgress(unittest.TestCase):
    """Commit messages that should classify as progress."""

    def test_add_module(self):
        self.assertEqual(classify_commit("add stroke_yield_analyzer + 15 tests"), "progress")

    def test_new_module(self):
        self.assertEqual(classify_commit("new module: cadence_adherence"), "progress")

    def test_new_test(self):
        self.assertEqual(classify_commit("new test: test_stall_forecaster"), "progress")

    def test_implement(self):
        self.assertEqual(classify_commit("implement post-visit productivity tracker"), "progress")

    def test_caretaker_visit(self):
        self.assertEqual(
            classify_commit("caretaker visit 762: add process_memory_tracker + 28 tests"),
            "progress",
        )

    def test_stroke_count(self):
        self.assertEqual(classify_commit("stroke 40591: tree is 2551 files"), "progress")

    def test_tree_size(self):
        self.assertEqual(
            classify_commit("tree is 2551 files; 658451 lines is a lot for a toy"),
            "progress",
        )

    def test_lines_across(self):
        self.assertEqual(
            classify_commit("656856 lines across 2545 tracked files, 1066 commits deep"),
            "progress",
        )

    def test_python_files(self):
        self.assertEqual(
            classify_commit("1745 python files, 6891 logged thoughts"),
            "progress",
        )

    def test_commit_count(self):
        self.assertEqual(
            classify_commit("commit 1060: the count of times this repo was pushed"),
            "progress",
        )


# ---------------------------------------------------------------------------
# classify_commit — unknown / edge cases
# ---------------------------------------------------------------------------

class TestClassifyEdge(unittest.TestCase):
    """Commit messages that should be unknown or edge cases."""

    def test_empty_message(self):
        self.assertEqual(classify_commit(""), "unknown")

    def test_garbage(self):
        self.assertEqual(classify_commit("xyzzy plugh abracadabra"), "unknown")

    def test_simple_message(self):
        self.assertEqual(classify_commit("update README"), "unknown")

    def test_repair_takes_priority(self):
        # "catch-up" is repair even though it might also match progress
        msg = "catch-up: commit 1050: progress milestone"
        self.assertEqual(classify_commit(msg), "repair")

    def test_case_insensitive_repair(self):
        self.assertEqual(classify_commit("CATCH-UP: pending"), "repair")

    def test_case_insensitive_progress(self):
        self.assertEqual(classify_commit("ADD new feature"), "progress")


# ---------------------------------------------------------------------------
# compute_productivity
# ---------------------------------------------------------------------------

class TestComputeProductivity(unittest.TestCase):
    """Productivity computation from commit lists."""

    def _make_commit(self, classification: str, msg: str = "test") -> Commit:
        return Commit(
            hash="abc1234",
            timestamp=datetime.now(timezone.utc),
            message=msg,
            classification=classification,
        )

    def test_empty_commits(self):
        now = datetime.now(timezone.utc)
        r = compute_productivity([], now, now)
        self.assertEqual(r.total_commits, 0)
        self.assertEqual(r.progress_ratio, 0.0)
        self.assertEqual(r.verdict, "no_data")

    def test_all_progress(self):
        now = datetime.now(timezone.utc)
        commits = [self._make_commit("progress") for _ in range(10)]
        r = compute_productivity(commits, now, now)
        self.assertEqual(r.progress_ratio, 1.0)
        self.assertEqual(r.verdict, "healthy")

    def test_all_repair(self):
        now = datetime.now(timezone.utc)
        commits = [self._make_commit("repair") for _ in range(5)]
        r = compute_productivity(commits, now, now)
        self.assertEqual(r.progress_ratio, 0.0)
        self.assertEqual(r.repair_ratio, 1.0)
        self.assertEqual(r.verdict, "unhealthy")

    def test_mixed_healthy(self):
        now = datetime.now(timezone.utc)
        commits = [self._make_commit("progress") for _ in range(7)]
        commits += [self._make_commit("repair") for _ in range(3)]
        r = compute_productivity(commits, now, now)
        self.assertEqual(r.progress_ratio, 0.7)
        self.assertEqual(r.verdict, "healthy")

    def test_mixed_boundary(self):
        now = datetime.now(timezone.utc)
        commits = [self._make_commit("progress") for _ in range(4)]
        commits += [self._make_commit("repair") for _ in range(6)]
        r = compute_productivity(commits, now, now)
        self.assertEqual(r.progress_ratio, 0.4)
        self.assertEqual(r.verdict, "mixed")

    def test_unknown_counted_correctly(self):
        now = datetime.now(timezone.utc)
        commits = [
            self._make_commit("progress"),
            self._make_commit("repair"),
            self._make_commit("unknown"),
        ]
        r = compute_productivity(commits, now, now)
        self.assertEqual(r.unknown_count, 1)
        self.assertEqual(r.total_commits, 3)


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport(unittest.TestCase):
    """Report formatting."""

    def test_format_contains_verdict(self):
        now = datetime.now(timezone.utc)
        report = ProductivityReport(
            window_start=now.isoformat(),
            window_end=now.isoformat(),
            total_commits=5,
            progress_count=4,
            repair_count=1,
            unknown_count=0,
            progress_ratio=0.8,
            repair_ratio=0.2,
            verdict="healthy",
            commits=[],
        )
        text = format_report(report)
        self.assertIn("healthy", text)
        self.assertIn("80.0%", text)

    def test_format_empty_report(self):
        now = datetime.now(timezone.utc)
        report = ProductivityReport(
            window_start=now.isoformat(),
            window_end=now.isoformat(),
            total_commits=0,
            progress_count=0,
            repair_count=0,
            unknown_count=0,
            progress_ratio=0.0,
            repair_ratio=0.0,
            verdict="no_data",
            commits=[],
        )
        text = format_report(report)
        self.assertIn("no_data", text)
        self.assertIn("0", text)


if __name__ == "__main__":
    unittest.main()
