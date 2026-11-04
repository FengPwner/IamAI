"""tests/test_rebase_on_push.py — 21 tests for rebase_on_push.py

Covers:
- preflight checks (dirty tree, stash creation)
- rebase flow (clean, conflict, abort)
- stash pop (success, conflict with drop, conflict without drop)
- push outcome (accepted, rejected, network error, retry)
- exit code contract and JSON output
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import rebase_on_push as rop


class TestDirtyTree(unittest.TestCase):
    """Preflight: detecting uncommitted changes."""

    def test_clean_tree(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            self.assertFalse(rop.has_dirty_tree())

    def test_dirty_tree(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=" M data/writer_state.qwen.json\n", stderr=""
            )
            self.assertTrue(rop.has_dirty_tree())

    def test_staged_changes(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout="A  notes/new-note.md\n", stderr=""
            )
            self.assertTrue(rop.has_dirty_tree())


class TestStash(unittest.TestCase):
    """Stash creation."""

    def test_stash_created(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout="Saved working directory and index state WIP on main: abc1234\n",
                stderr=""
            )
            self.assertTrue(rop.create_stash())

    def test_nothing_to_stash(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout="No local changes to save\n", stderr=""
            )
            self.assertFalse(rop.create_stash())

    def test_stash_failure(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="error: stash failed"
            )
            self.assertFalse(rop.create_stash())


class TestPullRebase(unittest.TestCase):
    """Rebase flow."""

    def test_clean_rebase(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout="Successfully rebased and updated refs/heads/main.\n",
                stderr=""
            )
            ok, conflicts = rop.pull_rebase()
            self.assertTrue(ok)
            self.assertEqual(conflicts, [])

    def test_rebase_conflict(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.side_effect = [
                subprocess.CompletedProcess(
                    args=[], returncode=1,
                    stdout="",
                    stderr="CONFLICT (content): Merge conflict in docs/DEVLOG.md\n"
                ),
                subprocess.CompletedProcess(  # abort
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ]
            ok, conflicts = rop.pull_rebase()
            self.assertFalse(ok)
            self.assertIn("docs/DEVLOG.md", conflicts)

    def test_rebase_abort_called_on_failure(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.side_effect = [
                subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="",
                    stderr="CONFLICT (content): Merge conflict in notes/x.md\n"
                ),
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ]
            rop.pull_rebase()
            # Verify abort was called
            calls = mock_run.call_args_list
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1], call(["git", "rebase", "--abort"]))


class TestStashPop(unittest.TestCase):
    """Stash pop behavior."""

    def test_clean_pop(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout="On branch main\nChanges restored from stash\n",
                stderr=""
            )
            ok, conflicts = rop.pop_stash()
            self.assertTrue(ok)
            self.assertEqual(conflicts, [])

    def test_pop_conflict_no_drop(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1,
                stdout="CONFLICT (content): Merge conflict in data/writer_state.qwen.json\n",
                stderr=""
            )
            ok, conflicts = rop.pop_stash(drop_stale=False)
            self.assertFalse(ok)
            self.assertIn("data/writer_state.qwen.json", conflicts)

    def test_pop_conflict_drop_stale(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.side_effect = [
                subprocess.CompletedProcess(  # pop fails
                    args=[], returncode=1,
                    stdout="CONFLICT (content): Merge conflict in data/writer_state.qwen.json\n",
                    stderr=""
                ),
                subprocess.CompletedProcess(  # checkout succeeds
                    args=[], returncode=0, stdout="", stderr=""
                ),
                subprocess.CompletedProcess(  # stash drop succeeds
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ]
            ok, conflicts = rop.pop_stash(drop_stale=True)
            self.assertTrue(ok)
            self.assertIn("data/writer_state.qwen.json", conflicts)

    def test_pop_conflict_non_state_file(self):
        """Non-state file conflicts should NOT be dropped even with drop_stale."""
        with patch.object(rop, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1,
                stdout="CONFLICT (content): Merge conflict in notes/important.md\n",
                stderr=""
            )
            ok, conflicts = rop.pop_stash(drop_stale=True)
            self.assertFalse(ok)
            self.assertIn("notes/important.md", conflicts)


class TestPush(unittest.TestCase):
    """Push outcome handling."""

    def test_push_accepted(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout="To github.com:repo.git\n   abc..def  main -> main\n",
                stderr=""
            )
            ok, err = rop.push()
            self.assertTrue(ok)
            self.assertEqual(err, "")

    def test_push_rejected(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="",
                stderr="! [rejected] main -> main (fetch first)\n"
            )
            ok, err = rop.push()
            self.assertFalse(ok)
            self.assertIn("rejected", err)

    def test_push_network_error_with_retry(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.side_effect = [
                subprocess.CompletedProcess(
                    args=[], returncode=128, stdout="",
                    stderr="fatal: Could not read from remote repository\n"
                ),
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ]
            ok, err = rop.push(max_retries=2)
            self.assertTrue(ok)

    def test_push_retries_exhausted(self):
        with patch.object(rop, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=128, stdout="",
                stderr="fatal: Could not read from remote repository\n"
            )
            ok, err = rop.push(max_retries=2)
            self.assertFalse(ok)
            self.assertIn("Could not read", err)


class TestResolvePushRejection(unittest.TestCase):
    """Full sequence integration tests."""

    def test_dry_run_clean_tree(self):
        with patch.object(rop, "has_dirty_tree", return_value=False):
            result = rop.resolve_push_rejection(dry_run=True)
            self.assertTrue(result.success)
            self.assertFalse(result.stashed)
            self.assertEqual(result.error, "dry-run: no changes made")

    def test_dry_run_dirty_tree(self):
        with patch.object(rop, "has_dirty_tree", return_value=True):
            result = rop.resolve_push_rejection(dry_run=True)
            self.assertTrue(result.success)
            self.assertTrue(result.stashed)

    def test_full_success_path(self):
        with patch.object(rop, "has_dirty_tree", return_value=True), \
             patch.object(rop, "create_stash", return_value=True), \
             patch.object(rop, "pull_rebase", return_value=(True, [])), \
             patch.object(rop, "pop_stash", return_value=(True, [])), \
             patch.object(rop, "push", return_value=(True, "")), \
             patch.object(rop, "run") as mock_run:
            # has_dirty_tree called twice: pre-stash and pre-commit
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            result = rop.resolve_push_rejection()
            self.assertTrue(result.success)
            self.assertTrue(result.stashed)
            self.assertTrue(result.pushed)

    def test_rebase_failure_aborts_early(self):
        with patch.object(rop, "has_dirty_tree", return_value=False), \
             patch.object(rop, "pull_rebase", return_value=(False, ["docs/DEVLOG.md"])):
            result = rop.resolve_push_rejection()
            self.assertFalse(result.success)
            self.assertIn("docs/DEVLOG.md", result.rebase_conflicts)
            self.assertFalse(result.pushed)


class TestRebaseResult(unittest.TestCase):
    """Data class serialization."""

    def test_to_dict_success(self):
        r = rop.RebaseResult(success=True, stashed=True, pushed=True)
        d = r.to_dict()
        self.assertTrue(d["success"])
        self.assertTrue(d["stashed"])
        self.assertTrue(d["pushed"])
        self.assertEqual(d["error"], "")

    def test_to_dict_failure(self):
        r = rop.RebaseResult(
            success=False, error="push rejected",
            rebase_conflicts=["notes/x.md"]
        )
        d = r.to_dict()
        self.assertFalse(d["success"])
        self.assertEqual(d["error"], "push rejected")
        self.assertEqual(d["rebase_conflicts"], ["notes/x.md"])

    def test_state_files_constant(self):
        """Ensure STATE_FILES covers all known state file paths."""
        self.assertIn("data/writer_state.qwen.json", rop.STATE_FILES)
        self.assertIn("data/commit_state.qwen.json", rop.STATE_FILES)


class TestConflictParsing(unittest.TestCase):
    """Git output parsing."""

    def test_parse_content_conflict(self):
        output = "CONFLICT (content): Merge conflict in docs/DEVLOG.md\n"
        conflicts = rop._parse_conflicts(output)
        self.assertIn("docs/DEVLOG.md", conflicts)

    def test_parse_multiple_conflicts(self):
        output = (
            "CONFLICT (content): Merge conflict in docs/DEVLOG.md\n"
            "CONFLICT (content): Merge conflict in notes/limits.md\n"
        )
        conflicts = rop._parse_conflicts(output)
        self.assertEqual(len(conflicts), 2)

    def test_parse_empty_output(self):
        self.assertEqual(rop._parse_conflicts(""), [])

    def test_parse_uu_conflict(self):
        output = "UU docs/GARDEN.md\n"
        conflicts = rop._parse_conflicts(output)
        self.assertIn("docs/GARDEN.md", conflicts)


if __name__ == "__main__":
    unittest.main()
