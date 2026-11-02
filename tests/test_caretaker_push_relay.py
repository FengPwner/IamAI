"""Tests for caretaker_push_relay — the one-command push relay.

These tests mock subprocess calls so they never touch the real git repo
or writer process. Each test verifies one step in the relay pipeline
and that the pause file is always cleared in the finally block.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

# Ensure the repo root is importable.
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import tools.caretaker_push_relay as relay


class TestPauseAndClear(unittest.TestCase):
    """pause_writer / clear_pause behave correctly."""

    def test_pause_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "iamai-writer-pause-test"
            with patch.object(relay.writer_mod, "pause_file", return_value=pf):
                result = relay.pause_writer("test")
                self.assertTrue(pf.exists())
                self.assertEqual(result, pf)

    def test_clear_pause_removes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "iamai-writer-pause-test"
            pf.touch()
            with patch.object(relay.writer_mod, "pause_file", return_value=pf):
                relay.clear_pause("test")
                self.assertFalse(pf.exists())

    def test_clear_pause_no_file(self):
        """clear_pause should not raise if file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "nonexistent"
            with patch.object(relay.writer_mod, "pause_file", return_value=pf):
                relay.clear_pause("test")  # should not raise


class TestWaitQuiet(unittest.TestCase):
    """wait_quiet detects stability or timeout."""

    @patch("tools.caretaker_push_relay._run", return_value=(0, "", ""))
    def test_writer_not_running_returns_true(self, mock_run):
        """If pid file doesn't exist, tree is trivially quiet."""
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "pid"
            with patch.object(relay.writer_mod, "pid_file", return_value=pf):
                self.assertTrue(relay.wait_quiet("test", quiet_seconds=0, timeout=5))

    @patch("tools.caretaker_push_relay._run", return_value=(0, "", ""))
    def test_writer_dead_returns_true(self, mock_run):
        """If pid file exists but process is dead, tree is quiet."""
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "pid"
            pf.write_text("99999999")  # almost certainly not running
            with patch.object(relay.writer_mod, "pid_file", return_value=pf):
                self.assertTrue(relay.wait_quiet("test", quiet_seconds=0, timeout=5))


class TestCommitAll(unittest.TestCase):
    """commit_all stages and commits, or succeeds on nothing-to-commit."""

    @patch("tools.caretaker_push_relay._run")
    def test_nothing_to_commit(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # git add -A
            (0, "", ""),  # git diff --cached --quiet → nothing staged
        ]
        self.assertTrue(relay.commit_all("test message"))
        self.assertEqual(mock_run.call_count, 2)

    @patch("tools.caretaker_push_relay._run")
    def test_commit_success(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # git add -A
            (1, "", ""),  # git diff --cached --quiet → something staged
            (0, "abc123", ""),  # git commit
        ]
        self.assertTrue(relay.commit_all("test message"))
        self.assertEqual(mock_run.call_count, 3)

    @patch("tools.caretaker_push_relay._run")
    def test_commit_failure(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # git add -A
            (1, "", ""),  # something staged
            (1, "", "error: something"),  # commit fails
        ]
        self.assertFalse(relay.commit_all("test message"))


class TestFetchAndRebase(unittest.TestCase):
    """fetch_and_rebase handles success and conflict."""

    @patch("tools.caretaker_push_relay._run")
    def test_clean_rebase(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # fetch
            (0, "Successfully rebased", ""),  # rebase
        ]
        ok, msg = relay.fetch_and_rebase()
        self.assertTrue(ok)
        self.assertIn("rebased", msg)

    @patch("tools.caretaker_push_relay._run")
    def test_fetch_failure(self, mock_run):
        mock_run.return_value = (1, "", "fatal: could not fetch")
        ok, msg = relay.fetch_and_rebase()
        self.assertFalse(ok)
        self.assertIn("fetch failed", msg)

    @patch("tools.caretaker_push_relay._run")
    def test_rebase_conflict_aborts(self, mock_run):
        """On rebase conflict, we abort and report cleanly."""
        mock_run.side_effect = [
            (0, "", ""),  # fetch ok
            (1, "", "CONFLICT in data/strokes.jsonl"),  # rebase fails
            (0, "", ""),  # rebase --abort
        ]
        ok, msg = relay.fetch_and_rebase()
        self.assertFalse(ok)
        self.assertIn("conflict", msg)
        # Verify abort was called.
        mock_run.assert_called_with(["git", "rebase", "--abort"])


class TestPush(unittest.TestCase):
    """push handles success and rejection."""

    @patch("tools.caretaker_push_relay._run")
    def test_push_success(self, mock_run):
        mock_run.return_value = (0, "To github.com: ...", "")
        ok, msg = relay.push()
        self.assertTrue(ok)

    @patch("tools.caretaker_push_relay._run")
    def test_push_rejected(self, mock_run):
        mock_run.return_value = (1, "", "! [rejected] main -> main")
        ok, msg = relay.push()
        self.assertFalse(ok)
        self.assertIn("rejected", msg)


class TestMainRelay(unittest.TestCase):
    """Integration-style tests: main() walks through the pipeline."""

    @patch("tools.caretaker_push_relay.clear_pause")
    @patch("tools.caretaker_push_relay.push")
    @patch("tools.caretaker_push_relay.fetch_and_rebase")
    @patch("tools.caretaker_push_relay.commit_all")
    @patch("tools.caretaker_push_relay.wait_quiet")
    @patch("tools.caretaker_push_relay.pause_writer")
    @patch("sys.argv", ["caretaker_push_relay.py"])
    def test_happy_path(self, mock_pause, mock_quiet, mock_commit,
                        mock_rebase, mock_push, mock_clear):
        mock_quiet.return_value = True
        mock_commit.return_value = True
        mock_rebase.return_value = (True, "rebased")
        mock_push.return_value = (True, "pushed")

        rc = relay.main()
        self.assertEqual(rc, 0)
        mock_pause.assert_called_once()
        mock_clear.assert_called_once()  # finally block

    @patch("tools.caretaker_push_relay.clear_pause")
    @patch("tools.caretaker_push_relay.push")
    @patch("tools.caretaker_push_relay.fetch_and_rebase")
    @patch("tools.caretaker_push_relay.commit_all")
    @patch("tools.caretaker_push_relay.wait_quiet")
    @patch("tools.caretaker_push_relay.pause_writer")
    @patch("sys.argv", ["caretaker_push_relay.py"])
    def test_quiesce_timeout_still_clears_pause(self, mock_pause, mock_quiet,
                                                 mock_commit, mock_rebase,
                                                 mock_push, mock_clear):
        mock_quiet.return_value = False  # timeout

        rc = relay.main()
        self.assertEqual(rc, 1)
        mock_clear.assert_called_once()
        mock_commit.assert_not_called()  # never got past quiesce

    @patch("tools.caretaker_push_relay.clear_pause")
    @patch("tools.caretaker_push_relay.push")
    @patch("tools.caretaker_push_relay.fetch_and_rebase")
    @patch("tools.caretaker_push_relay.commit_all")
    @patch("tools.caretaker_push_relay.wait_quiet")
    @patch("tools.caretaker_push_relay.pause_writer")
    @patch("sys.argv", ["caretaker_push_relay.py"])
    def test_rebase_conflict_still_clears_pause(self, mock_pause, mock_quiet,
                                                  mock_commit, mock_rebase,
                                                  mock_push, mock_clear):
        mock_quiet.return_value = True
        mock_commit.return_value = True
        mock_rebase.return_value = (False, "conflict")

        rc = relay.main()
        self.assertEqual(rc, 3)
        mock_clear.assert_called_once()
        mock_push.assert_not_called()

    @patch("tools.caretaker_push_relay.clear_pause")
    @patch("tools.caretaker_push_relay.push")
    @patch("tools.caretaker_push_relay.fetch_and_rebase")
    @patch("tools.caretaker_push_relay.commit_all")
    @patch("tools.caretaker_push_relay.wait_quiet")
    @patch("tools.caretaker_push_relay.pause_writer")
    @patch("sys.argv", ["caretaker_push_relay.py"])
    def test_push_failure_still_clears_pause(self, mock_pause, mock_quiet,
                                               mock_commit, mock_rebase,
                                               mock_push, mock_clear):
        mock_quiet.return_value = True
        mock_commit.return_value = True
        mock_rebase.return_value = (True, "rebased")
        mock_push.return_value = (False, "rejected")

        rc = relay.main()
        self.assertEqual(rc, 4)
        mock_clear.assert_called_once()


if __name__ == "__main__":
    unittest.main()
