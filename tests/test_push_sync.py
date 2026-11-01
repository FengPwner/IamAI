"""Tests for tools/push_sync.py — the push sync automation tool."""

import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import tools.push_sync as ps


class TestHasUnpushedCommits(unittest.TestCase):
    """Test detection of local-only commits."""

    @patch("tools.push_sync.run")
    def test_has_unpushed(self, mock_run):
        mock_run.return_value = (0, "abc123 some commit\n", "")
        self.assertTrue(ps.has_unpushed_commits())

    @patch("tools.push_sync.run")
    def test_no_unpushed(self, mock_run):
        mock_run.return_value = (0, "", "")
        self.assertFalse(ps.has_unpushed_commits())

    @patch("tools.push_sync.run")
    def test_error_means_no_unpushed(self, mock_run):
        mock_run.return_value = (128, "", "fatal")
        self.assertFalse(ps.has_unpushed_commits())


class TestHasUnfetchedRemoteCommits(unittest.TestCase):
    """Test detection of remote-only commits."""

    @patch("tools.push_sync.run")
    def test_has_remote(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # fetch
            (0, "xyz789 remote commit\n", ""),  # log
        ]
        self.assertTrue(ps.has_unfetched_remote_commits())

    @patch("tools.push_sync.run")
    def test_no_remote(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # fetch
            (0, "", ""),  # log
        ]
        self.assertFalse(ps.has_unfetched_remote_commits())


class TestWorkingTreeClean(unittest.TestCase):
    """Test working tree cleanliness check."""

    @patch("tools.push_sync.run")
    def test_clean(self, mock_run):
        mock_run.return_value = (0, "", "")
        self.assertTrue(ps.is_working_tree_clean())

    @patch("tools.push_sync.run")
    def test_dirty(self, mock_run):
        mock_run.return_value = (0, " M data/strokes.jsonl\n", "")
        self.assertFalse(ps.is_working_tree_clean())


class TestTryPush(unittest.TestCase):
    """Test push attempt."""

    @patch("tools.push_sync.run")
    def test_push_success(self, mock_run):
        mock_run.return_value = (0, "done\n", "")
        self.assertTrue(ps.try_push())

    @patch("tools.push_sync.run")
    def test_push_rejected(self, mock_run):
        mock_run.return_value = (1, "", "rejected\n")
        self.assertFalse(ps.try_push())


class TestTryRebase(unittest.TestCase):
    """Test rebase attempt."""

    @patch("tools.push_sync.run")
    def test_rebase_success(self, mock_run):
        mock_run.return_value = (0, "rebasing...\n", "")
        ok, conflicts = ps.try_rebase()
        self.assertTrue(ok)
        self.assertEqual(conflicts, [])

    @patch("tools.push_sync.run")
    def test_rebase_conflict(self, mock_run):
        mock_run.side_effect = [
            (1, "", "CONFLICT"),  # rebase fails
            (0, "notes/reading.md\n", ""),  # diff --name-only
        ]
        ok, conflicts = ps.try_rebase()
        self.assertFalse(ok)
        self.assertEqual(conflicts, ["notes/reading.md"])


class TestResolveUnionConflicts(unittest.TestCase):
    """Test auto-resolution of union-merge file conflicts."""

    @patch("tools.push_sync.run")
    def test_resolve_union_file(self, mock_run):
        mock_run.return_value = (0, "", "")
        resolved, unresolvable = ps.resolve_union_conflicts(
            ["data/strokes.jsonl", "notes/reading.md"]
        )
        self.assertEqual(resolved, ["data/strokes.jsonl", "notes/reading.md"])
        self.assertEqual(unresolvable, [])

    @patch("tools.push_sync.run")
    def test_unresolvable_non_union(self, mock_run):
        resolved, unresolvable = ps.resolve_union_conflicts(
            ["tools/push_sync.py", "README.md"]
        )
        self.assertEqual(resolved, [])
        self.assertEqual(unresolvable, ["tools/push_sync.py", "README.md"])

    @patch("tools.push_sync.run")
    def test_checkout_failure_marks_unresolvable(self, mock_run):
        mock_run.return_value = (1, "", "error")
        resolved, unresolvable = ps.resolve_union_conflicts(
            ["data/strokes.jsonl"]
        )
        self.assertEqual(resolved, [])
        self.assertEqual(unresolvable, ["data/strokes.jsonl"])


class TestSyncDryRun(unittest.TestCase):
    """Test dry-run mode doesn't modify anything."""

    @patch("tools.push_sync.try_push")
    @patch("tools.push_sync.has_unfetched_remote_commits")
    @patch("tools.push_sync.has_unpushed_commits")
    @patch("tools.push_sync.run")
    def test_in_sync(self, mock_run, mock_local, mock_remote, mock_push):
        mock_local.return_value = False
        mock_remote.return_value = False
        ok, msg = ps.sync(dry_run=True)
        self.assertTrue(ok)
        self.assertIn("sync", msg)

    @patch("tools.push_sync.try_push")
    @patch("tools.push_sync.has_unfetched_remote_commits")
    @patch("tools.push_sync.has_unpushed_commits")
    @patch("tools.push_sync.run")
    def test_only_local(self, mock_run, mock_local, mock_remote, mock_push):
        mock_local.return_value = True
        mock_remote.return_value = False
        ok, msg = ps.sync(dry_run=True)
        self.assertTrue(ok)
        self.assertIn("push", msg)

    @patch("tools.push_sync.try_push")
    @patch("tools.push_sync.has_unfetched_remote_commits")
    @patch("tools.push_sync.has_unpushed_commits")
    @patch("tools.push_sync.run")
    def test_only_remote(self, mock_run, mock_local, mock_remote, mock_push):
        mock_local.return_value = False
        mock_remote.return_value = True
        ok, msg = ps.sync(dry_run=True)
        self.assertTrue(ok)
        self.assertIn("pull", msg)

    @patch("tools.push_sync.is_working_tree_clean")
    @patch("tools.push_sync.try_push")
    @patch("tools.push_sync.has_unfetched_remote_commits")
    @patch("tools.push_sync.has_unpushed_commits")
    @patch("tools.push_sync.run")
    def test_divergence(
        self, mock_run, mock_local, mock_remote, mock_push, mock_clean
    ):
        mock_local.return_value = True
        mock_remote.return_value = True
        ok, msg = ps.sync(dry_run=True)
        self.assertTrue(ok)
        self.assertIn("rebase", msg)


class TestSyncExecution(unittest.TestCase):
    """Test actual sync paths (mocked git)."""

    @patch("tools.push_sync.try_push")
    @patch("tools.push_sync.has_unfetched_remote_commits")
    @patch("tools.push_sync.has_unpushed_commits")
    @patch("tools.push_sync.run")
    def test_in_sync_no_op(self, mock_run, mock_local, mock_remote, mock_push):
        mock_local.return_value = False
        mock_remote.return_value = False
        ok, msg = ps.sync()
        self.assertTrue(ok)
        self.assertIn("sync", msg)
        mock_push.assert_not_called()

    @patch("tools.push_sync.try_push")
    @patch("tools.push_sync.has_unfetched_remote_commits")
    @patch("tools.push_sync.has_unpushed_commits")
    @patch("tools.push_sync.run")
    def test_push_only(self, mock_run, mock_local, mock_remote, mock_push):
        mock_local.return_value = True
        mock_remote.return_value = False
        mock_push.return_value = True
        ok, msg = ps.sync()
        self.assertTrue(ok)
        self.assertIn("pushed", msg)

    @patch("tools.push_sync.run")
    @patch("tools.push_sync.try_push")
    @patch("tools.push_sync.has_unfetched_remote_commits")
    @patch("tools.push_sync.has_unpushed_commits")
    def test_pull_only(self, mock_local, mock_remote, mock_push, mock_run):
        mock_local.return_value = False
        mock_remote.return_value = True
        mock_run.return_value = (0, "", "")
        ok, msg = ps.sync()
        self.assertTrue(ok)
        self.assertIn("pulled", msg)

    @patch("tools.push_sync.abort_rebase")
    @patch("tools.push_sync.resolve_union_conflicts")
    @patch("tools.push_sync.try_rebase")
    @patch("tools.push_sync.is_working_tree_clean")
    @patch("tools.push_sync.try_push")
    @patch("tools.push_sync.has_unfetched_remote_commits")
    @patch("tools.push_sync.has_unpushed_commits")
    @patch("tools.push_sync.run")
    def test_diverge_rebase_success(
        self,
        mock_run,
        mock_local,
        mock_remote,
        mock_push,
        mock_clean,
        mock_rebase,
        mock_resolve,
        mock_abort,
    ):
        mock_local.return_value = True
        mock_remote.return_value = True
        mock_clean.return_value = True
        mock_rebase.return_value = (True, [])
        mock_push.return_value = True
        ok, msg = ps.sync()
        self.assertTrue(ok)
        self.assertIn("rebased and pushed", msg)

    @patch("tools.push_sync.abort_rebase")
    @patch("tools.push_sync.resolve_union_conflicts")
    @patch("tools.push_sync.try_rebase")
    @patch("tools.push_sync.is_working_tree_clean")
    @patch("tools.push_sync.try_push")
    @patch("tools.push_sync.has_unfetched_remote_commits")
    @patch("tools.push_sync.has_unpushed_commits")
    @patch("tools.push_sync.run")
    def test_diverge_conflict_unresolvable(
        self,
        mock_run,
        mock_local,
        mock_remote,
        mock_push,
        mock_clean,
        mock_rebase,
        mock_resolve,
        mock_abort,
    ):
        mock_local.return_value = True
        mock_remote.return_value = True
        mock_clean.return_value = True
        mock_rebase.return_value = (False, ["tools/push_sync.py"])
        mock_resolve.return_value = ([], ["tools/push_sync.py"])
        ok, msg = ps.sync()
        self.assertFalse(ok)
        self.assertIn("unresolvable", msg)
        mock_abort.assert_called()

    @patch("tools.push_sync.abort_rebase")
    @patch("tools.push_sync.resolve_union_conflicts")
    @patch("tools.push_sync.try_rebase")
    @patch("tools.push_sync.is_working_tree_clean")
    @patch("tools.push_sync.try_push")
    @patch("tools.push_sync.has_unfetched_remote_commits")
    @patch("tools.push_sync.has_unpushed_commits")
    @patch("tools.push_sync.run")
    def test_force_reset_on_conflict(
        self,
        mock_run,
        mock_local,
        mock_remote,
        mock_push,
        mock_clean,
        mock_rebase,
        mock_resolve,
        mock_abort,
    ):
        mock_local.return_value = True
        mock_remote.return_value = True
        mock_clean.return_value = True
        mock_rebase.return_value = (False, ["tools/push_sync.py"])
        mock_resolve.return_value = ([], ["tools/push_sync.py"])
        mock_run.return_value = (0, "", "")
        ok, msg = ps.sync(force=True)
        self.assertTrue(ok)
        self.assertIn("force-reset", msg)


class TestUnionFiles(unittest.TestCase):
    """Test that UNION_FILES set is correct."""

    def test_strokes_jsonl_included(self):
        self.assertIn("data/strokes.jsonl", ps.UNION_FILES)

    def test_devlog_included(self):
        self.assertIn("docs/DEVLOG.md", ps.UNION_FILES)

    def test_garden_included(self):
        self.assertIn("docs/GARDEN.md", ps.UNION_FILES)

    def test_metrics_included(self):
        self.assertIn("docs/METRICS.md", ps.UNION_FILES)

    def test_notes_included(self):
        self.assertIn("notes/reading.md", ps.UNION_FILES)
        self.assertIn("notes/history.md", ps.UNION_FILES)

    def test_no_random_files(self):
        self.assertNotIn("README.md", ps.UNION_FILES)
        self.assertNotIn("tools/push_sync.py", ps.UNION_FILES)


if __name__ == "__main__":
    unittest.main()
