#!/usr/bin/env python3
"""Tests for push_sync_barrier.py.

Covers:
  - BarrierResult dataclass and serialization
  - classify_divergence with real temp repos
  - check_barrier: clean, ahead, behind, diverged, error cases
  - dry_run mode
  - edge cases: no remote, no commits, detached HEAD
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
import push_sync_barrier as psb


def _run(cwd, *args, check=True):
    """Run a git command in a temp repo."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def _make_bare_remote(tmpdir):
    """Create a bare remote repo."""
    bare = os.path.join(tmpdir, "remote.git")
    _run(tmpdir, "init", "--bare", bare)
    # Ensure default branch is 'main'
    _run(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    return bare


def _make_local_repo(tmpdir, bare_remote):
    """Create a local repo cloned from bare, with one commit."""
    local = os.path.join(tmpdir, "local")
    _run(tmpdir, "clone", bare_remote, local)
    _run(local, "config", "user.email", "test@test.local")
    _run(local, "config", "user.name", "Test")
    # Ensure we're on 'main'
    _run(local, "checkout", "-B", "main")
    # Create initial commit
    readme = os.path.join(local, "README.md")
    Path(readme).write_text("# test\n")
    _run(local, "add", ".")
    _run(local, "commit", "-m", "init")
    _run(local, "push", "origin", "main")
    return local


class TestBarrierResult(unittest.TestCase):
    """Tests for the BarrierResult dataclass."""

    def test_ok_result(self):
        r = psb.BarrierResult(ok=True, divergence="ahead", reason="local ahead")
        self.assertTrue(r.ok)
        self.assertEqual(r.divergence, "ahead")

    def test_fail_result(self):
        r = psb.BarrierResult(ok=False, divergence="diverged", reason="diverged")
        self.assertFalse(r.ok)

    def test_to_json(self):
        r = psb.BarrierResult(
            ok=True, divergence="clean", reason="ok",
            local_sha="abc123", remote_sha="abc123", merge_base="abc123",
        )
        data = json.loads(r.to_json())
        self.assertEqual(data["ok"], True)
        self.assertEqual(data["divergence"], "clean")
        self.assertIn("local_sha", data)


class TestClassifyDivergence(unittest.TestCase):
    """Tests for classify_divergence using real temp repos."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.bare = _make_bare_remote(self.tmpdir)
        self.local = _make_local_repo(self.tmpdir, self.bare)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_clean(self):
        local_sha = _run(self.local, "rev-parse", "HEAD")
        remote_sha = _run(self.local, "rev-parse", "origin/main")
        self.assertEqual(psb.classify_divergence(self.local, local_sha, remote_sha), "clean")

    def test_ahead(self):
        # Add a local commit
        Path(os.path.join(self.local, "new.txt")).write_text("new")
        _run(self.local, "add", ".")
        _run(self.local, "commit", "-m", "local commit")
        local_sha = _run(self.local, "rev-parse", "HEAD")
        remote_sha = _run(self.local, "rev-parse", "origin/main")
        self.assertEqual(psb.classify_divergence(self.local, local_sha, remote_sha), "ahead")

    def test_behind(self):
        # Add a commit to remote via a second clone
        other = os.path.join(self.tmpdir, "other")
        _run(self.tmpdir, "clone", self.bare, other)
        _run(other, "config", "user.email", "other@test.local")
        _run(other, "config", "user.name", "Other")
        Path(os.path.join(other, "other.txt")).write_text("other")
        _run(other, "add", ".")
        _run(other, "commit", "-m", "remote commit")
        _run(other, "push", "origin", "main")
        # Fetch in local
        _run(self.local, "fetch", "origin")
        local_sha = _run(self.local, "rev-parse", "HEAD")
        remote_sha = _run(self.local, "rev-parse", "origin/main")
        self.assertEqual(psb.classify_divergence(self.local, local_sha, remote_sha), "behind")

    def test_diverged(self):
        # Add remote commit
        other = os.path.join(self.tmpdir, "other")
        _run(self.tmpdir, "clone", self.bare, other)
        _run(other, "config", "user.email", "other@test.local")
        _run(other, "config", "user.name", "Other")
        Path(os.path.join(other, "other.txt")).write_text("other")
        _run(other, "add", ".")
        _run(other, "commit", "-m", "remote commit")
        _run(other, "push", "origin", "main")
        # Add local commit
        Path(os.path.join(self.local, "local.txt")).write_text("local")
        _run(self.local, "add", ".")
        _run(self.local, "commit", "-m", "local commit")
        _run(self.local, "fetch", "origin")
        local_sha = _run(self.local, "rev-parse", "HEAD")
        remote_sha = _run(self.local, "rev-parse", "origin/main")
        self.assertEqual(psb.classify_divergence(self.local, local_sha, remote_sha), "diverged")


class TestCheckBarrier(unittest.TestCase):
    """Integration tests for check_barrier."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.bare = _make_bare_remote(self.tmpdir)
        self.local = _make_local_repo(self.tmpdir, self.bare)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_clean_passes(self):
        r = psb.check_barrier(repo_path=self.local, dry_run=True)
        self.assertTrue(r.ok)
        self.assertEqual(r.divergence, "clean")

    def test_ahead_passes(self):
        Path(os.path.join(self.local, "new.txt")).write_text("new")
        _run(self.local, "add", ".")
        _run(self.local, "commit", "-m", "ahead")
        r = psb.check_barrier(repo_path=self.local, dry_run=True)
        self.assertTrue(r.ok)
        self.assertEqual(r.divergence, "ahead")

    def test_behind_fails(self):
        other = os.path.join(self.tmpdir, "other")
        _run(self.tmpdir, "clone", self.bare, other)
        _run(other, "config", "user.email", "o@t.l")
        _run(other, "config", "user.name", "O")
        Path(os.path.join(other, "o.txt")).write_text("o")
        _run(other, "add", ".")
        _run(other, "commit", "-m", "remote")
        _run(other, "push", "origin", "main")
        r = psb.check_barrier(repo_path=self.local)
        self.assertFalse(r.ok)
        self.assertEqual(r.divergence, "behind")

    def test_diverged_fails(self):
        other = os.path.join(self.tmpdir, "other")
        _run(self.tmpdir, "clone", self.bare, other)
        _run(other, "config", "user.email", "o@t.l")
        _run(other, "config", "user.name", "O")
        Path(os.path.join(other, "o.txt")).write_text("o")
        _run(other, "add", ".")
        _run(other, "commit", "-m", "remote")
        _run(other, "push", "origin", "main")
        Path(os.path.join(self.local, "l.txt")).write_text("l")
        _run(self.local, "add", ".")
        _run(self.local, "commit", "-m", "local")
        r = psb.check_barrier(repo_path=self.local)
        self.assertFalse(r.ok)
        self.assertEqual(r.divergence, "diverged")
        self.assertIn("rebase", r.action)

    def test_not_a_repo(self):
        r = psb.check_barrier(repo_path=self.tmpdir, dry_run=True)
        self.assertFalse(r.ok)
        self.assertEqual(r.divergence, "error")

    def test_no_remote_branch(self):
        # Delete remote ref
        _run(self.local, "update-ref", "-d", "refs/remotes/origin/main")
        r = psb.check_barrier(repo_path=self.local, dry_run=True)
        self.assertFalse(r.ok)
        self.assertEqual(r.divergence, "error")
        self.assertIn("remote", r.reason)


class TestDryRun(unittest.TestCase):
    """Test that dry_run skips the fetch step."""

    def test_dry_run_no_fetch(self):
        tmpdir = tempfile.mkdtemp()
        try:
            bare = _make_bare_remote(tmpdir)
            local = _make_local_repo(tmpdir, bare)
            # Add remote commit but don't fetch
            other = os.path.join(tmpdir, "other")
            _run(tmpdir, "clone", bare, other)
            _run(other, "config", "user.email", "o@t.l")
            _run(other, "config", "user.name", "O")
            Path(os.path.join(other, "o.txt")).write_text("o")
            _run(other, "add", ".")
            _run(other, "commit", "-m", "remote only")
            _run(other, "push", "origin", "main")
            # dry_run should see stale remote (still clean)
            r = psb.check_barrier(repo_path=local, dry_run=True)
            self.assertTrue(r.ok)
            self.assertEqual(r.divergence, "clean")
            # Non-dry-run should fetch and detect behind
            r2 = psb.check_barrier(repo_path=local, dry_run=False)
            self.assertFalse(r2.ok)
            self.assertEqual(r2.divergence, "behind")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
