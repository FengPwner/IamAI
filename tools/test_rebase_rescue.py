#!/usr/bin/env python3
"""Tests for rebase_rescue.py — state detection and rescue orchestration.

Uses temporary git repos to verify:
    - State detection (detached HEAD, stale lock, stale rebase, divergence)
    - Lock file cleanup
    - Rebase state cleanup
    - Stash-pop cycle
    - Dry-run mode
    - check_state() output format
    - RescueReport summarization

Run: python3 tools/test_rebase_rescue.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).parent))
import rebase_rescue as rr


def git(args, cwd):
    """Run git in a temp repo with predictable identity."""
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "test"
    env["GIT_AUTHOR_EMAIL"] = "test@test.local"
    env["GIT_COMMITTER_NAME"] = "test"
    env["GIT_COMMITTER_EMAIL"] = "test@test.local"
    return subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, env=env
    )


def make_repo(tmp: Path) -> Path:
    """Create a minimal git repo with one commit on main."""
    repo = tmp / "repo"
    repo.mkdir()
    git(["init"], repo)
    git(["checkout", "-b", "main"], repo)
    (repo / "README.md").write_text("# test\n")
    git(["add", "."], repo)
    git(["commit", "-m", "init"], repo)
    return repo


def make_remote(tmp: Path, repo: Path) -> Path:
    """Create a bare clone as 'origin' and configure it."""
    bare = tmp / "origin.git"
    git(["clone", "--bare", str(repo), str(bare)], tmp)
    git(["remote", "add", "origin", str(bare)], repo)
    git(["fetch", "origin"], repo)
    git(["branch", "--set-upstream-to=origin/main", "main"], repo)
    return bare


class TestStateDetection(unittest.TestCase):
    """Test individual state-check functions."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_not_detached(self):
        self.assertFalse(rr.is_detached(self.repo))

    def test_detached(self):
        sha = git(["rev-parse", "HEAD"], self.repo).stdout.strip()
        git(["checkout", sha], self.repo)
        self.assertTrue(rr.is_detached(self.repo))

    def test_no_stale_lock(self):
        self.assertFalse(rr.has_stale_lock(self.repo))

    def test_stale_lock(self):
        (self.repo / ".git" / "index.lock").write_text("")
        self.assertTrue(rr.has_stale_lock(self.repo))

    def test_no_stale_rebase_state(self):
        self.assertFalse(rr.has_stale_rebase_state(self.repo))

    def test_stale_rebase_merge(self):
        (self.repo / ".git" / "rebase-merge").mkdir()
        self.assertTrue(rr.has_stale_rebase_state(self.repo))

    def test_stale_rebase_apply(self):
        (self.repo / ".git" / "rebase-apply").mkdir()
        self.assertTrue(rr.has_stale_rebase_state(self.repo))

    def test_no_unstaged_changes(self):
        self.assertFalse(rr.has_unstaged_changes(self.repo))

    def test_unstaged_changes(self):
        (self.repo / "README.md").write_text("changed\n")
        self.assertTrue(rr.has_unstaged_changes(self.repo))

    def test_get_current_branch(self):
        self.assertEqual(rr.get_current_branch(self.repo), "main")

    def test_get_current_branch_detached(self):
        sha = git(["rev-parse", "HEAD"], self.repo).stdout.strip()
        git(["checkout", sha], self.repo)
        self.assertEqual(rr.get_current_branch(self.repo), "")

    def test_not_diverged(self):
        self.assertFalse(rr.is_diverged(self.repo, "origin", "main"))


class TestDivergenceDetection(unittest.TestCase):
    """Test divergence detection with local and remote changes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.tmp)
        self.bare = make_remote(self.tmp, self.repo)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_diverged_after_both_sides_commit(self):
        # Local commit
        (self.repo / "local.txt").write_text("local\n")
        git(["add", "."], self.repo)
        git(["commit", "-m", "local change"], self.repo)

        # Remote commit (via a second clone)
        clone2 = self.tmp / "clone2"
        git(["clone", str(self.bare), str(clone2)], self.tmp)
        (clone2 / "remote.txt").write_text("remote\n")
        git(["add", "."], clone2)
        git(["commit", "-m", "remote change"], clone2)
        git(["push", "origin", "main"], clone2)

        # Now repo should be diverged from origin/main
        self.assertTrue(rr.is_diverged(self.repo, "origin", "main"))


class TestLockCleanup(unittest.TestCase):
    """Test that rescue() cleans stale lock files."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.tmp)
        self.bare = make_remote(self.tmp, self.repo)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lock_cleaned_during_rescue(self):
        # Create stale lock
        (self.repo / ".git" / "index.lock").write_text("")
        self.assertTrue(rr.has_stale_lock(self.repo))

        # Rescue should clean it (even if nothing else needs doing)
        report = rr.rescue(self.repo, "origin", "main")
        self.assertTrue(report.lock_cleaned)
        self.assertFalse(rr.has_stale_lock(self.repo))


class TestRebaseStateCleanup(unittest.TestCase):
    """Test that rescue() cleans stale rebase directories."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.tmp)
        self.bare = make_remote(self.tmp, self.repo)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rebase_merge_cleaned(self):
        (self.repo / ".git" / "rebase-merge").mkdir()
        report = rr.rescue(self.repo, "origin", "main")
        self.assertTrue(report.rebase_state_cleaned)
        self.assertFalse((self.repo / ".git" / "rebase-merge").exists())

    def test_rebase_apply_cleaned(self):
        (self.repo / ".git" / "rebase-apply").mkdir()
        report = rr.rescue(self.repo, "origin", "main")
        self.assertTrue(report.rebase_state_cleaned)
        self.assertFalse((self.repo / ".git" / "rebase-apply").exists())


class TestDryRun(unittest.TestCase):
    """Test that dry-run doesn't change anything."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dry_run_succeeds(self):
        report = rr.rescue(self.repo, "origin", "main", dry_run=True)
        self.assertTrue(report.success)

    def test_dry_run_no_side_effects(self):
        (self.repo / ".git" / "index.lock").write_text("")
        rr.rescue(self.repo, "origin", "main", dry_run=True)
        # Lock should still exist
        self.assertTrue(rr.has_stale_lock(self.repo))


class TestCheckState(unittest.TestCase):
    """Test check_state() output."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_check_output_format(self):
        output = rr.check_state(self.repo, "origin", "main")
        self.assertIn("branch: main", output)
        self.assertIn("detached: False", output)
        self.assertIn("stale lock: False", output)
        self.assertIn("unstaged changes: False", output)

    def test_check_with_lock(self):
        (self.repo / ".git" / "index.lock").write_text("")
        output = rr.check_state(self.repo, "origin", "main")
        self.assertIn("stale lock: True", output)


class TestRescueReport(unittest.TestCase):
    """Test RescueReport formatting."""

    def test_success_summary(self):
        report = rr.RescueReport(success=True, pushed=True, rebased=True)
        s = report.summarize()
        self.assertIn("OK", s)
        self.assertIn("pushed successfully", s)
        self.assertIn("rebased onto remote", s)

    def test_failure_summary(self):
        report = rr.RescueReport(success=False, error="push failed: rejected")
        s = report.summarize()
        self.assertIn("FAILED", s)
        self.assertIn("push failed: rejected", s)

    def test_log_messages(self):
        report = rr.RescueReport()
        report.log("step one")
        report.log("step two")
        s = report.summarize()
        self.assertIn("step one", s)
        self.assertIn("step two", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
