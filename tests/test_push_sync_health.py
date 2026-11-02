"""Tests for push_sync_health.py — push-readiness scorer.

Visit 484: 18 tests covering scoring logic, edge cases, exit codes,
and JSON output.  Uses subprocess mocking to avoid real git calls.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import push_sync_health as psh


class TestUncommittedBytes(unittest.TestCase):
    """Tests for uncommitted_bytes()."""

    @patch.object(psh, "_run", return_value=(0, " 3 files changed, 42 insertions(+), 7 deletions(-)"))
    def test_parses_insertions(self, _mock):
        self.assertEqual(psh.uncommitted_bytes("/fake"), 42)

    @patch.object(psh, "_run", return_value=(0, ""))
    def test_empty_output(self, _mock):
        self.assertEqual(psh.uncommitted_bytes("/fake"), 0)

    @patch.object(psh, "_run", return_value=(1, "fatal: not a repo"))
    def test_git_failure(self, _mock):
        self.assertEqual(psh.uncommitted_bytes("/fake"), 0)

    @patch.object(psh, "_run", return_value=(0, " 1 file changed, 1 insertion(+)"))
    def test_single_insertion(self, _mock):
        self.assertEqual(psh.uncommitted_bytes("/fake"), 1)

    @patch.object(psh, "_run", return_value=(0, "no changes"))
    def test_no_insertion_token(self, _mock):
        self.assertEqual(psh.uncommitted_bytes("/fake"), 0)


class TestUnpushedCommits(unittest.TestCase):
    """Tests for unpushed_commits()."""

    @patch.object(psh, "_run", return_value=(0, "5"))
    def test_normal(self, _mock):
        self.assertEqual(psh.unpushed_commits("/fake"), 5)

    @patch.object(psh, "_run", return_value=(0, "0"))
    def test_zero(self, _mock):
        self.assertEqual(psh.unpushed_commits("/fake"), 0)

    @patch.object(psh, "_run", return_value=(128, "fatal"))
    def test_no_remote(self, _mock):
        self.assertEqual(psh.unpushed_commits("/fake"), -1)

    @patch.object(psh, "_run", return_value=(0, "not-a-number"))
    def test_garbage_output(self, _mock):
        self.assertEqual(psh.unpushed_commits("/fake"), -1)


class TestRemoteDiverged(unittest.TestCase):
    """Tests for remote_diverged()."""

    @patch.object(psh, "_run", return_value=(0, "3"))
    def test_diverged(self, _mock):
        self.assertTrue(psh.remote_diverged("/fake"))

    @patch.object(psh, "_run", return_value=(0, "0"))
    def test_not_diverged(self, _mock):
        self.assertFalse(psh.remote_diverged("/fake"))

    @patch.object(psh, "_run", return_value=(128, "fatal"))
    def test_unknown(self, _mock):
        self.assertIsNone(psh.remote_diverged("/fake"))


class TestScorePushHealth(unittest.TestCase):
    """Tests for score_push_health() composition logic."""

    @patch.object(psh, "_run", return_value=(0, ""))
    @patch.object(psh, "remote_diverged", return_value=True)
    @patch.object(psh, "unpushed_commits", return_value=2)
    @patch.object(psh, "uncommitted_bytes", return_value=10)
    def test_diverged_wins(self, *_args):
        score, label, _ = psh.score_push_health("/fake")
        self.assertEqual(score, 0)
        self.assertEqual(label, "diverged")

    @patch.object(psh, "_run", return_value=(0, ""))
    @patch.object(psh, "remote_diverged", return_value=False)
    @patch.object(psh, "unpushed_commits", return_value=0)
    @patch.object(psh, "uncommitted_bytes", return_value=50)
    def test_dirty_tree(self, *_args):
        score, label, _ = psh.score_push_health("/fake")
        self.assertEqual(score, 1)
        self.assertEqual(label, "dirty_tree")

    @patch.object(psh, "_run", return_value=(0, ""))
    @patch.object(psh, "remote_diverged", return_value=False)
    @patch.object(psh, "unpushed_commits", return_value=3)
    @patch.object(psh, "uncommitted_bytes", return_value=0)
    def test_local_debt(self, *_args):
        score, label, _ = psh.score_push_health("/fake")
        self.assertEqual(score, 2)
        self.assertEqual(label, "local_debt")

    @patch.object(psh, "_run", return_value=(0, ""))
    @patch.object(psh, "remote_diverged", return_value=False)
    @patch.object(psh, "unpushed_commits", return_value=0)
    @patch.object(psh, "uncommitted_bytes", return_value=0)
    def test_clean(self, *_args):
        score, label, _ = psh.score_push_health("/fake")
        self.assertEqual(score, 3)
        self.assertEqual(label, "clean")


class TestRunHelper(unittest.TestCase):
    """Tests for the _run() helper."""

    def test_timeout_returns_error(self):
        rc, out = psh._run(["sleep", "60"], cwd=".")
        # should not actually wait 60s; subprocess timeout or our 30s cap
        self.assertEqual(rc, 1)

    def test_missing_command(self):
        rc, out = psh._run(["nonexistent_command_xyz_12345"])
        self.assertEqual(rc, 1)

    def test_successful_command(self):
        rc, out = psh._run(["echo", "hello"])
        self.assertEqual(rc, 0)
        self.assertEqual(out, "hello")


if __name__ == "__main__":
    unittest.main()
