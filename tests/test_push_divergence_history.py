#!/usr/bin/env python3
"""Tests for push_divergence_history.py — push rejection pattern analyzer."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

# ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from push_divergence_history import (
    RejectionEvent,
    DivergenceReport,
    extract_visit_number,
    detect_recovery_method,
    is_rejection_event,
    find_repo_root,
    analyze_divergence,
    print_text_report,
)


class TestExtractVisitNumber(unittest.TestCase):
    """Test visit number extraction from commit messages."""

    def test_standard_format(self):
        self.assertEqual(extract_visit_number("caretaker visit 123: something"), 123)

    def test_hyphenated_format(self):
        self.assertEqual(extract_visit_number("caretaker-visit-456-2026-10-31.md"), 456)

    def test_no_visit_number(self):
        self.assertIsNone(extract_visit_number("guoban: note (stroke 274)"))

    def test_visit_in_body(self):
        self.assertEqual(extract_visit_number("visit 507: recovery"), 507)

    def test_multiple_numbers_takes_first(self):
        # should get the first match after "visit"
        result = extract_visit_number("caretaker visit 42: fixed 3 things")
        self.assertEqual(result, 42)


class TestIsRejectionEvent(unittest.TestCase):
    """Test push rejection pattern matching."""

    def test_push_rejected(self):
        self.assertTrue(is_rejection_event("push was rejected by remote"))

    def test_fetch_first(self):
        self.assertTrue(is_rejection_event("error: failed to push — fetch first"))

    def test_rejected_fetch_first(self):
        self.assertTrue(
            is_rejection_event("[rejected] main -> main (fetch first)")
        )

    def test_diverged(self):
        self.assertTrue(is_rejection_event("push diverged from remote"))

    def test_non_fast_forward(self):
        self.assertTrue(is_rejection_event("non-fast-forward update"))

    def test_updates_were_rejected(self):
        self.assertTrue(is_rejection_event("Updates were rejected because the remote"))

    def test_normal_push(self):
        self.assertFalse(is_rejection_event("push succeeded on first attempt"))

    def test_unrelated_commit(self):
        self.assertFalse(is_rejection_event("guoban: note (stroke 273)"))

    def test_case_insensitive(self):
        self.assertTrue(is_rejection_event("PUSH WAS REJECTED"))
        self.assertTrue(is_rejection_event("Fetch First"))

    def test_remote_ahead(self):
        self.assertTrue(is_rejection_event("remote 3 commits ahead"))


class TestDetectRecoveryMethod(unittest.TestCase):
    """Test recovery method detection from commit messages."""

    def test_stash_rebase_push(self):
        msg = "stash-pull_rebase-push recovered the divergence"
        self.assertEqual(detect_recovery_method(msg), "stash-rebase-push")

    def test_auto_rebase(self):
        msg = "auto.rebase handled the divergence"
        self.assertEqual(detect_recovery_method(msg), "stash-rebase-push")

    def test_reset_hard(self):
        msg = "git reset --hard origin/main to sync"
        self.assertEqual(detect_recovery_method(msg), "reset-hard")

    def test_reset_origin(self):
        msg = "reset to origin to get back in sync"
        self.assertEqual(detect_recovery_method(msg), "reset-hard")

    def test_pull_merge(self):
        msg = "pull --no-rebase to merge remote changes"
        self.assertEqual(detect_recovery_method(msg), "pull-merge")

    def test_manual(self):
        msg = "manual recovery after complex conflict"
        self.assertEqual(detect_recovery_method(msg), "manual")

    def test_retry(self):
        msg = "retry push after waiting"
        self.assertEqual(detect_recovery_method(msg), "retry")

    def test_unknown(self):
        msg = "push failed, no details on recovery"
        self.assertEqual(detect_recovery_method(msg), "unknown")


class TestDivergenceReport(unittest.TestCase):
    """Test DivergenceReport data class."""

    def test_default_values(self):
        report = DivergenceReport()
        self.assertEqual(report.total_rejections, 0)
        self.assertEqual(report.total_visits, 0)
        self.assertEqual(report.rejection_rate, 0.0)
        self.assertEqual(report.recent_trend, "unknown")

    def test_to_dict(self):
        report = DivergenceReport(
            total_rejections=5,
            total_visits=20,
            rejection_rate=0.25,
            by_hour={10: 2, 14: 3},
            by_recovery_method={"stash-rebase-push": 3, "reset-hard": 2},
            by_date={"2026-11-01": 2, "2026-11-02": 3},
            recent_trend="worsening",
        )
        d = report.to_dict()
        self.assertEqual(d["total_rejections"], 5)
        self.assertEqual(d["total_visits"], 20)
        self.assertEqual(d["rejection_rate"], 0.25)
        self.assertEqual(d["recent_trend"], "worsening")
        self.assertEqual(d["event_count"], 0)

    def test_to_dict_rounds_rate(self):
        report = DivergenceReport(rejection_rate=0.33333333)
        d = report.to_dict()
        self.assertEqual(d["rejection_rate"], 0.333)


class TestRejectionEvent(unittest.TestCase):
    """Test RejectionEvent data class."""

    def test_creation(self):
        dt = datetime(2026, 11, 3, 7, 0, 0, tzinfo=timezone.utc)
        event = RejectionEvent(
            commit_sha="abc12345",
            date=dt,
            visit_number=507,
            recovery_method="stash-rebase-push",
            message_snippet="push rejected, recovered via stash-rebase",
        )
        self.assertEqual(event.commit_sha, "abc12345")
        self.assertEqual(event.visit_number, 507)
        self.assertEqual(event.recovery_method, "stash-rebase-push")

    def test_none_visit(self):
        dt = datetime(2026, 11, 3, 7, 0, 0, tzinfo=timezone.utc)
        event = RejectionEvent(
            commit_sha="def67890",
            date=dt,
            visit_number=None,
            recovery_method="unknown",
            message_snippet="rejection without visit number",
        )
        self.assertIsNone(event.visit_number)


class TestFindRepoRoot(unittest.TestCase):
    """Test repository root finding."""

    def test_finds_existing_repo(self):
        """Should find the actual IamAI repo root."""
        repo_root = find_repo_root(Path(__file__).resolve().parent.parent)
        self.assertTrue((repo_root / ".git").exists())

    def test_with_none_uses_cwd(self):
        """Should use cwd when no start path given."""
        result = find_repo_root(None)
        self.assertIsInstance(result, Path)


class TestAnalyzeDivergence(unittest.TestCase):
    """Test the main analysis function against the real repo."""

    def test_returns_report(self):
        repo = find_repo_root(Path(__file__).resolve().parent.parent)
        report = analyze_divergence(repo)
        self.assertIsInstance(report, DivergenceReport)
        # the repo definitely has some rejections in its history
        self.assertGreater(report.total_visits, 0)

    def test_with_days_limit(self):
        repo = find_repo_root(Path(__file__).resolve().parent.parent)
        report = analyze_divergence(repo, days=7)
        self.assertIsInstance(report, DivergenceReport)

    def test_empty_repo(self):
        """Should handle a repo with no visit commits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                ["git", "init", tmpdir],
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "-C", tmpdir, "commit", "--allow-empty", "-m", "init"],
                capture_output=True,
                check=True,
                env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com",
                     "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com"},
            )
            report = analyze_divergence(Path(tmpdir))
            self.assertEqual(report.total_visits, 0)
            self.assertEqual(report.total_rejections, 0)
            self.assertEqual(report.rejection_rate, 0.0)


class TestPrintTextReport(unittest.TestCase):
    """Test text report output."""

    def test_no_crash_on_empty(self):
        report = DivergenceReport()
        # should not raise
        print_text_report(report)

    def test_no_crash_with_data(self):
        report = DivergenceReport(
            total_rejections=2,
            total_visits=10,
            rejection_rate=0.2,
            by_hour={7: 1, 15: 1},
            by_recovery_method={"stash-rebase-push": 1, "reset-hard": 1},
            by_date={"2026-11-01": 1, "2026-11-02": 1},
            recent_trend="stable",
        )
        # should not raise
        print_text_report(report)


if __name__ == "__main__":
    unittest.main()
