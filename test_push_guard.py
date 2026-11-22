#!/usr/bin/env python3
"""Tests for tools/push_guard.py — 18 tests.

Covers: clean push, dirty push with stash, push rejection + retry,
double rejection, network failure, timeout, dry run, status report.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

# allow importing from tools/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))

from push_guard import (
    guarded_push,
    status_report,
    _is_dirty,
    _stash_push,
    _push,
    _pull_rebase,
    PushGuardError,
    MAX_PUSH_ATTEMPTS,
)


class TestGuardedPushCleanTree(unittest.TestCase):
    """Push succeeds on a clean working tree with no conflicts."""

    @patch("push_guard._push", return_value=(True, ""))
    @patch("push_guard._pull_rebase", return_value=(True, 1))
    @patch("push_guard._stash_push", return_value=False)
    def test_clean_push_succeeds(self, mock_stash, mock_pull, mock_push):
        result = guarded_push(cwd="/tmp/fake")
        self.assertTrue(result["ok"])
        self.assertFalse(result["stash_used"])
        self.assertEqual(result["push_attempts"], 1)
        self.assertIsNone(result["error"])
        mock_stash.assert_called_once()
        mock_pull.assert_called_once()
        mock_push.assert_called_once()

    @patch("push_guard._push", return_value=(True, ""))
    @patch("push_guard._pull_rebase", return_value=(True, 1))
    @patch("push_guard._stash_push", return_value=False)
    def test_steps_logged(self, mock_stash, mock_pull, mock_push):
        result = guarded_push(cwd="/tmp/fake")
        self.assertGreater(len(result["steps"]), 0)
        # first step should mention working tree
        self.assertIn("clean", result["steps"][0].lower())


class TestGuardedPushDirtyTree(unittest.TestCase):
    """Push succeeds after stashing and popping dirty changes."""

    @patch("push_guard._stash_pop", return_value=True)
    @patch("push_guard._push", return_value=(True, ""))
    @patch("push_guard._pull_rebase", return_value=(True, 1))
    @patch("push_guard._stash_push", return_value=True)
    def test_dirty_push_with_stash(self, mock_stash, mock_pull, mock_push, mock_pop):
        result = guarded_push(cwd="/tmp/fake")
        self.assertTrue(result["ok"])
        self.assertTrue(result["stash_used"])
        self.assertEqual(result["push_attempts"], 1)
        mock_pop.assert_called_once()

    @patch("push_guard._stash_pop", return_value=False)
    @patch("push_guard._push", return_value=(True, ""))
    @patch("push_guard._pull_rebase", return_value=(True, 1))
    @patch("push_guard._stash_push", return_value=True)
    def test_stash_pop_failure_warns(self, mock_stash, mock_pull, mock_push, mock_pop):
        result = guarded_push(cwd="/tmp/fake")
        self.assertTrue(result["ok"])
        self.assertTrue(result["stash_used"])
        # should have a warning in steps
        warnings = [s for s in result["steps"] if "warning" in s.lower()]
        self.assertGreater(len(warnings), 0)


class TestGuardedPushRejection(unittest.TestCase):
    """Push is rejected once, retry after rebase succeeds."""

    @patch("push_guard._stash_pop", return_value=True)
    @patch(
        "push_guard._push",
        side_effect=[
            (False, "push rejected (non-fast-forward)"),
            (True, ""),
        ],
    )
    @patch(
        "push_guard._pull_rebase",
        side_effect=[(True, 1), (True, 1)],
    )
    @patch("push_guard._stash_push", return_value=True)
    def test_rejection_retry_succeeds(
        self, mock_stash, mock_pull, mock_push, mock_pop
    ):
        result = guarded_push(cwd="/tmp/fake")
        self.assertTrue(result["ok"])
        self.assertEqual(result["push_attempts"], 2)
        self.assertEqual(result["rebase_count"], 2)  # 1 from initial + 1 from retry

    @patch("push_guard._push", side_effect=[(False, "rejected"), (False, "rejected")])
    @patch("push_guard._pull_rebase", side_effect=[(True, 1), (True, 1)])
    @patch("push_guard._stash_push", return_value=False)
    def test_double_rejection_fails(self, mock_stash, mock_pull, mock_push):
        result = guarded_push(cwd="/tmp/fake")
        self.assertFalse(result["ok"])
        self.assertEqual(result["push_attempts"], MAX_PUSH_ATTEMPTS)
        self.assertIn("force-push", result["error"])


class TestGuardedPushFailures(unittest.TestCase):
    """Network failure, timeout, and rebase conflict scenarios."""

    @patch(
        "push_guard._pull_rebase",
        return_value=(False, 0),
    )
    @patch("push_guard._stash_push", return_value=False)
    def test_pull_failure_attempts_push(self, mock_stash, mock_pull):
        """Even if pull fails, we attempt push (might be up to date)."""
        with patch("push_guard._push", return_value=(True, "")):
            result = guarded_push(cwd="/tmp/fake")
            self.assertTrue(result["ok"])

    @patch("push_guard._stash_push", return_value=False)
    def test_pull_timeout(self, mock_stash):
        """Pull timeout returns error."""
        with patch(
            "push_guard._pull_rebase",
            side_effect=subprocess.TimeoutExpired("git pull", 60),
        ):
            result = guarded_push(cwd="/tmp/fake")
            self.assertFalse(result["ok"])
            self.assertIn("timeout", result["error"].lower())

    @patch("push_guard._push", side_effect=subprocess.TimeoutExpired("git push", 60))
    @patch("push_guard._pull_rebase", return_value=(True, 1))
    @patch("push_guard._stash_push", return_value=False)
    def test_push_timeout(self, mock_stash, mock_pull, mock_push):
        result = guarded_push(cwd="/tmp/fake")
        self.assertFalse(result["ok"])
        # at least one timeout error
        self.assertIn("timeout", result["error"].lower())

    @patch("push_guard._stash_push", side_effect=subprocess.TimeoutExpired("git stash", 60))
    def test_stash_timeout(self, mock_stash):
        result = guarded_push(cwd="/tmp/fake")
        self.assertFalse(result["ok"])
        self.assertIn("timeout", result["error"].lower())

    @patch("push_guard._pull_rebase", return_value=(False, 0))
    @patch(
        "push_guard._push",
        side_effect=[(False, "rejected"), (False, "rejected again")],
    )
    @patch("push_guard._stash_push", return_value=False)
    def test_rebase_fails_during_retry(self, mock_stash, mock_push, mock_pull):
        """If rebase fails during retry, error is returned."""
        # first pull fails, push fails, retry pull fails → error
        result = guarded_push(cwd="/tmp/fake")
        self.assertFalse(result["ok"])


class TestGuardedPushDryRun(unittest.TestCase):
    """Dry run shows steps without executing."""

    def test_dry_run(self):
        result = guarded_push(cwd="/tmp/fake", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["steps"]), 5)
        for step in result["steps"]:
            self.assertIn("dry-run", step.lower())


class TestGuardedPushRetryRebaseFailure(unittest.TestCase):
    """Rebase failure during retry attempt."""

    @patch("push_guard._push", side_effect=[(False, "rejected"), (False, "rejected")])
    @patch(
        "push_guard._pull_rebase",
        side_effect=[(True, 1), (False, 0)],  # first ok, retry fails
    )
    @patch("push_guard._stash_push", return_value=False)
    def test_retry_rebase_failure(self, mock_stash, mock_pull, mock_push):
        result = guarded_push(cwd="/tmp/fake")
        self.assertFalse(result["ok"])
        self.assertIn("rebase failed", result["error"].lower())


class TestStatusReport(unittest.TestCase):
    """Status report returns expected structure."""

    @patch("push_guard._run_git")
    def test_status_report_clean(self, mock_run):
        def side_effect(args, cwd, timeout=60):
            r = MagicMock()
            r.returncode = 0
            if args[0] == "status":
                r.stdout = ""  # clean
            elif args[0] == "log":
                r.stdout = "abc1234 some commit message"
            elif args[0] == "rev-parse":
                r.stdout = "main"
            elif args[0] == "rev-list":
                r.stdout = "3"
            return r

        mock_run.side_effect = side_effect
        report = status_report(cwd="/tmp/fake")
        self.assertFalse(report["dirty"])
        self.assertEqual(report["branch"], "main")
        self.assertEqual(report["unpushed_commits"], "3")
        self.assertIn("abc1234", report["head"])
        self.assertIn("timestamp", report)

    @patch("push_guard._run_git")
    def test_status_report_dirty(self, mock_run):
        def side_effect(args, cwd, timeout=60):
            r = MagicMock()
            r.returncode = 0
            if args[0] == "status":
                r.stdout = " M some_file.py\n"
            elif args[0] == "log":
                r.stdout = "def5678 another commit"
            elif args[0] == "rev-parse":
                r.stdout = "feature-branch"
            elif args[0] == "rev-list":
                r.stdout = "0"
            return r

        mock_run.side_effect = side_effect
        report = status_report(cwd="/tmp/fake")
        self.assertTrue(report["dirty"])
        self.assertEqual(report["branch"], "feature-branch")
        self.assertEqual(report["unpushed_commits"], "0")


class TestStatusReportJsonSerializable(unittest.TestCase):
    """Status report must be JSON serializable."""

    @patch("push_guard._run_git")
    def test_json_serializable(self, mock_run):
        def side_effect(args, cwd, timeout=60):
            r = MagicMock()
            r.returncode = 0
            r.stdout = "ok"
            return r

        mock_run.side_effect = side_effect
        report = status_report(cwd="/tmp/fake")
        # should not raise
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
