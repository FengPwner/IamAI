#!/usr/bin/env python3
"""Tests for tools/post_push_verifier.py

Run: python3 -m pytest tests/test_post_push_verifier.py -v
Or:  python3 tests/test_post_push_verifier.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from post_push_verifier import (
    get_local_head,
    get_remote_head,
    get_local_branch_head,
    get_ahead_behind,
    verify_push,
    format_text,
    run_git,
)


class TestRunGit(unittest.TestCase):
    """Tests for the run_git helper."""

    def test_run_git_success(self):
        stdout, stderr, rc = run_git("version")
        self.assertEqual(rc, 0)
        self.assertIn("git version", stdout)

    def test_run_git_invalid_command(self):
        stdout, stderr, rc = run_git("nonexistent-subcommand-xyz")
        self.assertNotEqual(rc, 0)


class TestGetLocalHead(unittest.TestCase):
    """Tests for get_local_head."""

    def test_returns_hash_in_git_repo(self):
        head = get_local_head(".")
        self.assertIsNotNone(head)
        self.assertRegex(head, r"^[0-9a-f]{40}$")

    def test_returns_none_for_non_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            head = get_local_head(tmpdir)
            self.assertIsNone(head)


class TestGetRemoteHead(unittest.TestCase):
    """Tests for get_remote_head."""

    def test_returns_hash_for_valid_remote(self):
        # This test requires network access and a valid remote
        head = get_remote_head(".", "origin", "main")
        if head is not None:
            self.assertRegex(head, r"^[0-9a-f]{40}$")

    def test_returns_none_for_invalid_remote(self):
        head = get_remote_head(".", "nonexistent-remote-xyz", "main")
        self.assertIsNone(head)

    def test_returns_none_for_invalid_branch(self):
        head = get_remote_head(".", "origin", "nonexistent-branch-xyz")
        self.assertIsNone(head)


class TestGetLocalBranchHead(unittest.TestCase):
    """Tests for get_local_branch_head."""

    def test_returns_hash_for_tracked_branch(self):
        head = get_local_branch_head(".", "origin", "main")
        if head is not None:
            self.assertRegex(head, r"^[0-9a-f]{40}$")

    def test_returns_none_for_missing_branch(self):
        head = get_local_branch_head(".", "origin", "nonexistent-branch-xyz")
        self.assertIsNone(head)


class TestGetAheadBehind(unittest.TestCase):
    """Tests for get_ahead_behind."""

    def test_returns_tuple_for_valid_branch(self):
        ahead, behind = get_ahead_behind(".", "origin", "main")
        if ahead is not None:
            self.assertIsInstance(ahead, int)
            self.assertIsInstance(behind, int)
            self.assertGreaterEqual(ahead, 0)
            self.assertGreaterEqual(behind, 0)

    def test_returns_none_for_invalid_branch(self):
        ahead, behind = get_ahead_behind(".", "origin", "nonexistent-xyz")
        self.assertIsNone(ahead)
        self.assertIsNone(behind)


class TestVerifyPush(unittest.TestCase):
    """Tests for the main verify_push function."""

    def test_returns_dict_with_required_keys(self):
        result = verify_push(".")
        required_keys = {
            "verified", "local_head", "remote_head",
            "local_tracking", "ahead", "behind",
            "timestamp", "error",
        }
        self.assertEqual(set(result.keys()), required_keys)

    def test_verified_is_bool(self):
        result = verify_push(".")
        self.assertIsInstance(result["verified"], bool)

    def test_non_repo_returns_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = verify_push(tmpdir)
            self.assertFalse(result["verified"])
            self.assertIsNotNone(result["error"])

    def test_timestamp_is_iso_format(self):
        result = verify_push(".")
        self.assertIn("T", result["timestamp"])
        self.assertIn("+", result["timestamp"])

    def test_local_head_is_hash_or_none(self):
        result = verify_push(".")
        if result["local_head"]:
            self.assertRegex(result["local_head"], r"^[0-9a-f]{40}$")


class TestFormatText(unittest.TestCase):
    """Tests for format_text output."""

    def test_verified_output(self):
        result = {
            "verified": True,
            "local_head": "a" * 40,
            "remote_head": "a" * 40,
            "local_tracking": "a" * 40,
            "ahead": 0,
            "behind": 0,
            "timestamp": "2026-10-31T12:00:00+00:00",
            "error": None,
        }
        text = format_text(result)
        self.assertIn("VERIFIED", text)
        self.assertIn("aaaaaa", text)

    def test_diverged_output(self):
        result = {
            "verified": False,
            "local_head": "a" * 40,
            "remote_head": "b" * 40,
            "local_tracking": "b" * 40,
            "ahead": 1,
            "behind": 0,
            "timestamp": "2026-10-31T12:00:00+00:00",
            "error": None,
        }
        text = format_text(result)
        self.assertIn("DIVERGED", text)

    def test_error_output(self):
        result = {
            "verified": False,
            "local_head": None,
            "remote_head": None,
            "local_tracking": None,
            "ahead": None,
            "behind": None,
            "timestamp": "2026-10-31T12:00:00+00:00",
            "error": "not a git repository",
        }
        text = format_text(result)
        self.assertIn("ERROR", text)
        self.assertIn("not a git repository", text)

    def test_truncated_hashes(self):
        result = {
            "verified": True,
            "local_head": "abcdef1234567890" + "0" * 24,
            "remote_head": "abcdef1234567890" + "0" * 24,
            "local_tracking": "abcdef1234567890" + "0" * 24,
            "ahead": 0,
            "behind": 0,
            "timestamp": "2026-10-31T12:00:00+00:00",
            "error": None,
        }
        text = format_text(result)
        # Hashes should be truncated to 12 chars
        self.assertIn("abcdef123456", text)
        self.assertNotIn("abcdef1234567890", text)


class TestJsonOutput(unittest.TestCase):
    """Tests ensuring the result dict is JSON-serializable."""

    def test_json_serializable(self):
        result = verify_push(".")
        json_str = json.dumps(result)
        self.assertIsInstance(json_str, str)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["verified"], result["verified"])

    def test_json_error_case(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = verify_push(tmpdir)
            json_str = json.dumps(result)
            parsed = json.loads(json_str)
            self.assertFalse(parsed["verified"])
            self.assertIsNotNone(parsed["error"])


if __name__ == "__main__":
    unittest.main()
