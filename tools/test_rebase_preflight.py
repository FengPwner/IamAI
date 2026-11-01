#!/usr/bin/env python3
"""Tests for tools/rebase_preflight.py — divergence detector and auto-resolver."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import rebase_preflight as rp


class TestRun(unittest.TestCase):
    """run() should return a CompletedProcess with captured output."""

    def test_echo(self):
        result = rp.run(["echo", "hello"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello", result.stdout)

    def test_failure(self):
        result = rp.run(["false"])
        self.assertNotEqual(result.returncode, 0)


class TestTreeIsDirty(unittest.TestCase):
    """tree_is_dirty should detect uncommitted changes."""

    def test_current_repo(self):
        """The IamAI repo has a running writer, so it's likely dirty."""
        original_dir = os.getcwd()
        try:
            os.chdir(REPO)
            # We just need it to return a bool
            result = rp.tree_is_dirty()
            self.assertIsInstance(result, bool)
        finally:
            os.chdir(original_dir)


class TestFetch(unittest.TestCase):
    """fetch should return True on success, False on failure."""

    def test_fetch_bad_remote(self):
        """Fetching from a nonexistent remote should return False."""
        result = rp.fetch("nonexistent-remote-xyz")
        self.assertFalse(result)


class TestPreflightCheck(unittest.TestCase):
    """preflight_check should return a well-formed status dict."""

    def test_returns_dict_with_required_keys(self):
        """Even with a bad remote, the result should have all required keys."""
        status = rp.preflight_check(remote="nonexistent-xyz", branch="main")
        required_keys = {"action", "diverged", "remote_ahead",
                         "local_ahead", "dirty", "success", "message"}
        self.assertEqual(set(status.keys()), required_keys)
        self.assertFalse(status["success"])

    def test_dry_run_flag(self):
        """Dry run should not modify anything."""
        status = rp.preflight_check(remote="nonexistent-xyz",
                                     branch="main", dry_run=True)
        self.assertFalse(status["success"])
        self.assertIn("could not fetch", status["message"])


class TestStashOperations(unittest.TestCase):
    """stash_push and stash_pop should return bools."""

    def test_stash_push_returns_bool(self):
        """stash_push on a clean tree still returns True (nothing to stash)."""
        result = rp.stash_push("test-stash-msg")
        self.assertIsInstance(result, bool)

    def test_stash_pop_no_stash(self):
        """stash_pop with no stash entries should return False."""
        # Only test if stash list is empty-ish
        check = rp.run(["git", "stash", "list"])
        if not check.stdout.strip():
            result = rp.stash_pop()
            self.assertFalse(result)


class TestRebase(unittest.TestCase):
    """rebase should return False when target doesn't exist."""

    def test_rebase_nonexistent(self):
        result = rp.rebase("nonexistent-remote", "nonexistent-branch")
        self.assertFalse(result)


class TestGetRepoRoot(unittest.TestCase):
    """get_repo_root should find a valid git repo."""

    def test_in_repo(self):
        original_dir = os.getcwd()
        try:
            os.chdir(REPO)
            root = rp.get_repo_root()
            self.assertTrue((root / ".git").exists())
        finally:
            os.chdir(original_dir)


if __name__ == "__main__":
    unittest.main()
