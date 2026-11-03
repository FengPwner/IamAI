#!/usr/bin/env python3
"""Tests for stale_stash_cleaner.py"""

import json
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, ".")
from tools.stale_stash_cleaner import (
    StashEntry,
    STALE_PATTERNS,
    list_stashes,
    drop_stash,
    main,
    run_git,
)


class TestStashEntry(unittest.TestCase):
    def test_to_dict(self):
        e = StashEntry(ref="stash@{0}", index=0, message="test msg",
                       is_stale=True, reason="test reason")
        d = e.to_dict()
        self.assertEqual(d["ref"], "stash@{0}")
        self.assertEqual(d["index"], 0)
        self.assertEqual(d["message"], "test msg")
        self.assertTrue(d["is_stale"])
        self.assertEqual(d["reason"], "test reason")


class TestStalePatterns(unittest.TestCase):
    """Verify each known stale pattern matches its target message."""

    def test_catch_up_stash(self):
        import re
        msg = "WIP on main: 82be722 catch-up: commit pending changes before process restart"
        matched = any(re.search(p, msg) for p, _ in STALE_PATTERNS)
        self.assertTrue(matched)

    def test_pre_rebase_stash(self):
        import re
        msg = "On main: caretaker-pre-rebase"
        matched = any(re.search(p, msg) for p, _ in STALE_PATTERNS)
        self.assertTrue(matched)

    def test_timed_pre_rebase(self):
        import re
        msg = "WIP on main: 82be722 pre-rebase-1793668040"
        matched = any(re.search(p, msg) for p, _ in STALE_PATTERNS)
        self.assertTrue(matched)

    def test_push_sync_test(self):
        import re
        msg = "On main: push-sync-test"
        matched = any(re.search(p, msg) for p, _ in STALE_PATTERNS)
        self.assertTrue(matched)

    def test_non_stale_not_matched(self):
        import re
        msg = "WIP on main: abc1234 feature: added new tool"
        matched = any(re.search(p, msg) for p, _ in STALE_PATTERNS)
        self.assertFalse(matched)


class TestListStashes(unittest.TestCase):
    @patch("tools.stale_stash_cleaner.run_git")
    def test_parses_stash_list(self, mock_git):
        mock_git.return_value = MagicMock(
            returncode=0,
            stdout=(
                "stash@{0}: WIP on main: 82be722 catch-up: commit pending\n"
                "stash@{1}: On main: feature-branch\n"
                "stash@{2}: WIP on main: abc1234 pre-rebase-9999\n"
            ),
        )
        entries = list_stashes()
        self.assertEqual(len(entries), 3)
        self.assertTrue(entries[0].is_stale)
        self.assertFalse(entries[1].is_stale)
        self.assertTrue(entries[2].is_stale)

    @patch("tools.stale_stash_cleaner.run_git")
    def test_empty_stash_list(self, mock_git):
        mock_git.return_value = MagicMock(returncode=0, stdout="")
        entries = list_stashes()
        self.assertEqual(len(entries), 0)

    @patch("tools.stale_stash_cleaner.run_git")
    def test_git_failure_returns_empty(self, mock_git):
        mock_git.return_value = MagicMock(returncode=1, stdout="")
        entries = list_stashes()
        self.assertEqual(len(entries), 0)

    @patch("tools.stale_stash_cleaner.run_git")
    def test_malformed_lines_skipped(self, mock_git):
        mock_git.return_value = MagicMock(
            returncode=0,
            stdout="this is not a stash line\nstash@{0}: valid entry\n",
        )
        entries = list_stashes()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].ref, "stash@{0}")


class TestDropStash(unittest.TestCase):
    @patch("tools.stale_stash_cleaner.run_git")
    def test_drop_success(self, mock_git):
        mock_git.return_value = MagicMock(returncode=0)
        self.assertTrue(drop_stash("stash@{0}"))
        mock_git.assert_called_once_with("stash", "drop", "stash@{0}")

    @patch("tools.stale_stash_cleaner.run_git")
    def test_drop_failure(self, mock_git):
        mock_git.return_value = MagicMock(returncode=1)
        self.assertFalse(drop_stash("stash@{99}"))


class TestMainDryRun(unittest.TestCase):
    @patch("tools.stale_stash_cleaner.run_git")
    def test_dry_run_no_drop(self, mock_git):
        def side_effect(*args):
            if args == ("rev-parse", "--is-inside-work-tree"):
                return MagicMock(returncode=0, stdout="true\n")
            if args == ("stash", "list"):
                return MagicMock(
                    returncode=0,
                    stdout="stash@{0}: WIP on main: abc catch-up: test\n",
                )
            return MagicMock(returncode=0, stdout="")

        mock_git.side_effect = side_effect
        sys.argv = ["stale_stash_cleaner.py"]
        # Should not raise
        main()
        # Should NOT have called stash drop
        drop_calls = [c for c in mock_git.call_args_list
                      if c[0] and c[0][0] == "stash" and c[0][1] == "drop"]
        self.assertEqual(len(drop_calls), 0)


class TestMainJSON(unittest.TestCase):
    @patch("tools.stale_stash_cleaner.run_git")
    def test_json_output(self, mock_git):
        def side_effect(*args):
            if args == ("rev-parse", "--is-inside-work-tree"):
                return MagicMock(returncode=0, stdout="true\n")
            if args == ("stash", "list"):
                return MagicMock(
                    returncode=0,
                    stdout="stash@{0}: On main: caretaker-pre-rebase\n",
                )
            return MagicMock(returncode=0, stdout="")

        mock_git.side_effect = side_effect
        sys.argv = ["stale_stash_cleaner.py", "--json"]

        import io
        captured = io.StringIO()
        sys.stdout = captured
        try:
            main()
        finally:
            sys.stdout = sys.__stdout__

        output = json.loads(captured.getvalue())
        self.assertEqual(output["stale_count"], 1)
        self.assertEqual(output["action"], "dry-run")


class TestMainDrop(unittest.TestCase):
    @patch("tools.stale_stash_cleaner.run_git")
    def test_drop_mode(self, mock_git):
        calls = []

        def side_effect(*args):
            calls.append(args)
            if args == ("rev-parse", "--is-inside-work-tree"):
                return MagicMock(returncode=0, stdout="true\n")
            if args == ("stash", "list"):
                return MagicMock(
                    returncode=0,
                    stdout=(
                        "stash@{0}: On main: caretaker-pre-rebase\n"
                        "stash@{1}: WIP on main: abc catch-up: commit\n"
                    ),
                )
            if args[0] == "stash" and args[1] == "drop":
                return MagicMock(returncode=0)
            return MagicMock(returncode=0, stdout="")

        mock_git.side_effect = side_effect
        sys.argv = ["stale_stash_cleaner.py", "--drop"]
        main()

        drop_calls = [c for c in calls if len(c) >= 2 and c[0] == "stash" and c[1] == "drop"]
        self.assertEqual(len(drop_calls), 2)


class TestMainNotRepo(unittest.TestCase):
    @patch("tools.stale_stash_cleaner.run_git")
    def test_not_a_repo(self, mock_git):
        mock_git.return_value = MagicMock(returncode=128, stdout="")
        sys.argv = ["stale_stash_cleaner.py"]
        with self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
