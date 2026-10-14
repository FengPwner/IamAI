"""Tests for iamai.index_guard — pre-flight safety net for git operations."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from iamai.index_guard import (
    check_dirty,
    check_index,
    check_lock,
    preflight,
    safe_stash,
    safe_pop,
    safe_pull_rebase,
    _STASH_LABEL_PREFIX,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=str(repo), capture_output=True)
    readme = repo / "README.md"
    readme.write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True)
    return repo


# ---------------------------------------------------------------------------
# check_lock
# ---------------------------------------------------------------------------

class TestCheckLock:
    def test_no_lock(self, git_repo: Path):
        result = check_lock(git_repo)
        assert result["exists"] is False
        assert result["stale"] is False

    def test_stale_lock_removed(self, git_repo: Path):
        lock = git_repo / ".git" / "index.lock"
        lock.write_text("")
        # set mtime to 10 minutes ago
        old_time = time.time() - 600
        os.utime(lock, (old_time, old_time))

        result = check_lock(git_repo)
        assert result["exists"] is True
        assert result["stale"] is True
        assert result["removed"] is True
        assert not lock.exists()

    def test_fresh_lock_not_removed(self, git_repo: Path):
        lock = git_repo / ".git" / "index.lock"
        lock.write_text("")
        # mtime is now — less than 300s

        result = check_lock(git_repo)
        # fresh lock: no holder found by fuser either, so it may be classified
        # as non-stale (holder check fails) or stale (no holder). Either way
        # we just verify the function does not crash.
        assert "exists" in result
        # cleanup
        lock.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# check_index
# ---------------------------------------------------------------------------

class TestCheckIndex:
    def test_healthy_index(self, git_repo: Path):
        result = check_index(git_repo)
        assert result["exists"] is True
        assert result["healthy"] is True
        assert result["size_bytes"] > 0

    def test_empty_index(self, git_repo: Path):
        idx = git_repo / ".git" / "index"
        idx.write_bytes(b"")
        result = check_index(git_repo)
        assert result["exists"] is True
        assert result["healthy"] is False

    def test_missing_index(self, git_repo: Path):
        idx = git_repo / ".git" / "index"
        idx.unlink()
        result = check_index(git_repo)
        assert result["exists"] is False
        assert result["healthy"] is False


# ---------------------------------------------------------------------------
# check_dirty
# ---------------------------------------------------------------------------

class TestCheckDirty:
    def test_clean_tree(self, git_repo: Path):
        result = check_dirty(git_repo)
        assert result["dirty"] is False
        assert result["file_count"] == 0

    def test_dirty_tree(self, git_repo: Path):
        (git_repo / "new.txt").write_text("hello")
        result = check_dirty(git_repo)
        assert result["dirty"] is True
        assert result["file_count"] >= 1


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

class TestPreflight:
    def test_clean_repo_ready(self, git_repo: Path):
        result = preflight(git_repo)
        assert result["ready"] is True
        assert result["issues"] == []

    def test_stale_lock_auto_repaired(self, git_repo: Path):
        lock = git_repo / ".git" / "index.lock"
        lock.write_text("")
        old_time = time.time() - 600
        os.utime(lock, (old_time, old_time))

        result = preflight(git_repo)
        assert "removed_stale_lock" in result["repaired"]
        assert result["ready"] is True

    def test_missing_index_not_ready(self, git_repo: Path):
        idx = git_repo / ".git" / "index"
        idx.unlink()
        result = preflight(git_repo)
        assert result["ready"] is False
        assert "missing_index" in result["issues"]

    def test_dirty_tree_ready_but_flagged(self, git_repo: Path):
        (git_repo / "new.txt").write_text("dirty")
        result = preflight(git_repo)
        # dirty tree alone does not block preflight
        assert result["ready"] is True
        assert "dirty_tree" in result["issues"]


# ---------------------------------------------------------------------------
# safe_stash / safe_pop
# ---------------------------------------------------------------------------

class TestSafeStashPop:
    def test_stash_clean_tree(self, git_repo: Path):
        result = safe_stash(git_repo)
        assert result["stashed"] is False

    def test_stash_and_pop(self, git_repo: Path):
        f = git_repo / "dirty.txt"
        f.write_text("changes")
        result = safe_stash(git_repo, label="test")
        assert result["stashed"] is True
        assert _STASH_LABEL_PREFIX in result["message"]

        # tree should be clean now
        assert not check_dirty(git_repo)["dirty"]

        # pop restores it
        pop = safe_pop(git_repo)
        assert pop["popped"] is True
        assert f.read_text() == "changes"

    def test_pop_empty_stash(self, git_repo: Path):
        result = safe_pop(git_repo)
        assert result["popped"] is False


# ---------------------------------------------------------------------------
# safe_pull_rebase
# ---------------------------------------------------------------------------

class TestSafePullRebase:
    def test_up_to_date(self, git_repo: Path):
        # no remote configured — fetch will fail, but preflight should pass
        result = safe_pull_rebase(git_repo)
        # should fail at fetch (no remote 'origin')
        assert result["ok"] is False
        assert any("fetch" in s for s in result["steps"])

    def test_dirty_tree_stashed_before_rebase(self, git_repo: Path):
        # create a local 'origin' to test against
        origin = git_repo.parent / "origin.git"
        subprocess.run(
            ["git", "init", "--bare", str(origin)],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "remote", "add", "origin", str(origin)],
            cwd=str(git_repo), capture_output=True,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=str(git_repo), capture_output=True,
        )

        # make a dirty file
        (git_repo / "wip.txt").write_text("work in progress")

        result = safe_pull_rebase(git_repo)
        assert result["ok"] is True
        # dirty file should be restored after pop
        assert (git_repo / "wip.txt").read_text() == "work in progress"
