"""Tests for snippets/push_guard.py — the safe push wrapper.

These tests use a temporary git repo to exercise the real git commands
rather than mocking subprocess. a repo takes ~50ms to create; the
clarity is worth it.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

# ensure the snippets directory is importable
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "snippets"))

from push_guard import (
    PushResult,
    guarded_push,
    is_clean,
    pop_stash,
    pull_rebase,
    stash_if_dirty,
    try_push,
)


def _run(cmd, cwd):
    """Helper: run a git command in a directory."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)


def _make_repo():
    """Create a bare-bones git repo with one commit, return its path."""
    d = tempfile.mkdtemp(prefix="push_guard_test_")
    _run(["git", "init"], d)
    _run(["git", "config", "user.email", "test@test"], d)
    _run(["git", "config", "user.name", "test"], d)
    Path(d, "README.md").write_text("# test\n")
    _run(["git", "add", "."], d)
    _run(["git", "commit", "-m", "init"], d)
    return d


def _branch(d):
    """Return the current branch name of a repo."""
    r = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=d, capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def _make_bare_clone(src):
    """Clone src as a bare repo to act as 'origin', return its path."""
    d = tempfile.mkdtemp(prefix="push_guard_origin_")
    _run(["git", "clone", "--bare", src, d], src)
    # point src's origin at the bare clone (set-url if origin exists, else add)
    r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=src, capture_output=True)
    if r.returncode == 0:
        _run(["git", "remote", "set-url", "origin", d], src)
    else:
        _run(["git", "remote", "add", "origin", d], src)
    # detect default branch name
    r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=src, capture_output=True, text=True, check=True)
    branch = r.stdout.strip()
    _run(["git", "push", "-u", "origin", branch], src)
    return d


class TestIsClean(unittest.TestCase):
    def test_clean_repo(self):
        d = _make_repo()
        self.assertTrue(is_clean(d))

    def test_dirty_repo(self):
        d = _make_repo()
        Path(d, "new.txt").write_text("dirty")
        self.assertFalse(is_clean(d))


class TestStashIfDirty(unittest.TestCase):
    def test_no_stash_when_clean(self):
        d = _make_repo()
        self.assertFalse(stash_if_dirty(d))

    def test_stash_when_dirty(self):
        d = _make_repo()
        Path(d, "new.txt").write_text("dirty")
        _run(["git", "add", "new.txt"], d)
        self.assertTrue(stash_if_dirty(d))
        # after stash, tree should be clean
        self.assertTrue(is_clean(d))


class TestPullRebase(unittest.TestCase):
    def test_pull_succeeds_with_no_remote_changes(self):
        d = _make_repo()
        origin = _make_bare_clone(d)
        br = _branch(d)
        self.assertTrue(pull_rebase(d, br))

    def test_pull_with_remote_ahead(self):
        d = _make_repo()
        origin = _make_bare_clone(d)
        br = _branch(d)
        # add a commit directly on the bare clone via a second clone
        clone2 = tempfile.mkdtemp(prefix="push_guard_clone2_")
        _run(["git", "clone", origin, clone2], origin)
        _run(["git", "config", "user.email", "test@test"], clone2)
        _run(["git", "config", "user.name", "test"], clone2)
        Path(clone2, "remote_file.txt").write_text("from remote")
        _run(["git", "add", "."], clone2)
        _run(["git", "commit", "-m", "remote change"], clone2)
        _run(["git", "push", "origin", br], clone2)
        # now d is behind; pull --rebase should succeed
        self.assertTrue(pull_rebase(d, br))
        # and the remote file should now exist locally
        self.assertTrue(Path(d, "remote_file.txt").exists())


class TestGuardedPush(unittest.TestCase):
    def test_happy_path(self):
        d = _make_repo()
        origin = _make_bare_clone(d)
        br = _branch(d)
        # add a local commit
        Path(d, "local.txt").write_text("local change")
        _run(["git", "add", "."], d)
        _run(["git", "commit", "-m", "local"], d)
        result = guarded_push(d, br)
        self.assertTrue(result.success)
        self.assertEqual(result.retries, 0)

    def test_push_race_recovery(self):
        """Simulate the classic push-race: remote advances while local is working."""
        d = _make_repo()
        origin = _make_bare_clone(d)
        br = _branch(d)
        # local commit
        Path(d, "local.txt").write_text("local")
        _run(["git", "add", "."], d)
        _run(["git", "commit", "-m", "local"], d)
        # remote commit (via clone2)
        clone2 = tempfile.mkdtemp(prefix="push_guard_race_")
        _run(["git", "clone", origin, clone2], origin)
        _run(["git", "config", "user.email", "test@test"], clone2)
        _run(["git", "config", "user.name", "test"], clone2)
        Path(clone2, "remote.txt").write_text("remote")
        _run(["git", "add", "."], clone2)
        _run(["git", "commit", "-m", "remote"], clone2)
        _run(["git", "push", "origin", br], clone2)
        # guarded_push should handle the race: pull-rebase then push
        result = guarded_push(d, br)
        self.assertTrue(result.success)
        self.assertTrue(result.rebased)

    def test_dirty_tree_stashed_and_restored(self):
        """Working tree with uncommitted changes should be stashed then popped."""
        d = _make_repo()
        origin = _make_bare_clone(d)
        br = _branch(d)
        # create uncommitted change
        Path(d, "wip.txt").write_text("work in progress")
        _run(["git", "add", "wip.txt"], d)
        result = guarded_push(d, br)
        self.assertTrue(result.success)
        # wip.txt should still be in the working tree after stash pop
        self.assertTrue(Path(d, "wip.txt").exists())
        self.assertEqual(Path(d, "wip.txt").read_text(), "work in progress")


class TestPushResult(unittest.TestCase):
    def test_result_fields(self):
        r = PushResult(success=True, rebased=True, retries=0, message="ok")
        self.assertTrue(r.success)
        self.assertTrue(r.rebased)
        self.assertEqual(r.retries, 0)
        self.assertEqual(r.message, "ok")

    def test_result_is_frozen(self):
        r = PushResult(success=False, rebased=False, retries=1, message="fail")
        with self.assertRaises(AttributeError):
            r.message = "changed"


if __name__ == "__main__":
    unittest.main()
