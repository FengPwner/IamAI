#!/usr/bin/env python3
"""tests for push_pre_sync.py — unit-level checks on the sync logic.

these tests mock subprocess.run so they don't need a real git repo or
network access. they cover the decision tree: diverged? stash? rebase? pop?
"""

import importlib.util
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# import the module under test from its file path
_module_path = Path(__file__).parent / "push_pre_sync.py"
spec = importlib.util.spec_from_file_location("push_pre_sync", _module_path)
pps = importlib.util.module_from_spec(spec)
sys.modules["push_pre_sync"] = pps  # required for @patch to find the right object
spec.loader.exec_module(pps)


class TestIsDiverged(unittest.TestCase):
    """is_diverged() reads rev-list output to detect behind > 0."""

    @patch("push_pre_sync.run")
    def test_not_diverged_when_equal(self, mock_run):
        mock_run.return_value = (0, "3\t0\n", "")
        self.assertFalse(pps.is_diverged())

    @patch("push_pre_sync.run")
    def test_diverged_when_behind(self, mock_run):
        mock_run.return_value = (0, "2\t5\n", "")
        self.assertTrue(pps.is_diverged())

    @patch("push_pre_sync.run")
    def test_not_diverged_when_ahead_only(self, mock_run):
        mock_run.return_value = (0, "7\t0\n", "")
        self.assertFalse(pps.is_diverged())

    @patch("push_pre_sync.run")
    def test_not_diverged_on_git_error(self, mock_run):
        mock_run.return_value = (128, "", "fatal: no upstream")
        self.assertFalse(pps.is_diverged())


class TestHasUncommitted(unittest.TestCase):
    """has_uncommitted() checks porcelain output."""

    @patch("push_pre_sync.run")
    def test_clean(self, mock_run):
        mock_run.return_value = (0, "", "")
        self.assertFalse(pps.has_uncommitted())

    @patch("push_pre_sync.run")
    def test_dirty(self, mock_run):
        mock_run.return_value = (0, " M notes/foo.md\n", "")
        self.assertTrue(pps.has_uncommitted())


class TestSync(unittest.TestCase):
    """sync() decision logic."""

    @patch("push_pre_sync.is_diverged", return_value=False)
    def test_already_sync(self, _):
        ok, msg = pps.sync(apply=False)
        self.assertTrue(ok)
        self.assertIn("already in sync", msg)

    @patch("push_pre_sync.is_diverged", return_value=True)
    def test_diverged_no_apply(self, _):
        ok, msg = pps.sync(apply=False)
        self.assertFalse(ok)
        self.assertIn("--apply", msg)

    @patch("push_pre_sync.run")
    @patch("push_pre_sync.has_uncommitted", return_value=False)
    @patch("push_pre_sync.is_diverged", return_value=True)
    def test_diverged_apply_clean(self, _, __, mock_run):
        mock_run.return_value = (0, "Successfully rebased", "")
        ok, msg = pps.sync(apply=True)
        self.assertTrue(ok)
        self.assertIn("synced", msg)

    @patch("push_pre_sync.run")
    @patch("push_pre_sync.has_uncommitted", return_value=True)
    @patch("push_pre_sync.is_diverged", return_value=True)
    def test_diverged_apply_with_stash(self, _, __, mock_run):
        # stash → rebase → pop all succeed
        mock_run.return_value = (0, "ok", "")
        ok, msg = pps.sync(apply=True)
        self.assertTrue(ok)
        calls = [c[0][0] for c in mock_run.call_args_list]
        # verify stash was called first
        self.assertIn("stash", calls[0])
        # verify rebase was called
        self.assertTrue(any("rebase" in str(c) for c in calls))

    @patch("push_pre_sync.run")
    @patch("push_pre_sync.has_uncommitted", return_value=True)
    @patch("push_pre_sync.is_diverged", return_value=True)
    def test_rebase_failure_aborts_and_pops(self, _, __, mock_run):
        """if rebase fails, must abort and restore stash."""
        def side_effect(cmd, **kw):
            if "stash" in cmd and "push" in cmd:
                return (0, "", "")
            if "pull" in cmd:
                return (1, "", "CONFLICT")
            if "rebase" in cmd and "--abort" in cmd:
                return (0, "", "")
            if "stash" in cmd and "pop" in cmd:
                return (0, "", "")
            return (0, "", "")

        mock_run.side_effect = side_effect
        ok, msg = pps.sync(apply=True)
        self.assertFalse(ok)
        self.assertIn("rebase failed", msg)


if __name__ == "__main__":
    unittest.main()
