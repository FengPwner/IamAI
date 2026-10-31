"""tests for merge_guard — pre-push divergence detection and auto-merge."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

# allow importing from tools/
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from merge_guard import (
    check_divergence,
    get_heads,
    has_dirty_index,
    has_unstaged_changes,
    auto_merge,
    run,
)


@pytest.fixture
def temp_repo(tmp_path):
    """create a minimal git repo with one commit for testing."""
    repo = tmp_path / "test_repo"
    repo.mkdir()

    run("git init", cwd=str(repo))
    run('git config user.email "test@test.local"', cwd=str(repo))
    run('git config user.name "Test"', cwd=str(repo))
    run("git checkout -b main", cwd=str(repo))

    readme = repo / "README.md"
    readme.write_text("# test\n")
    run("git add .", cwd=str(repo))
    run('git commit -m "initial"', cwd=str(repo))

    return str(repo)


@pytest.fixture
def temp_repo_with_remote(tmp_path):
    """create a repo with a bare remote for divergence testing."""
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], capture_output=True, check=True
    )

    repo = tmp_path / "test_repo"
    repo.mkdir()
    run("git init", cwd=str(repo))
    run('git config user.email "test@test.local"', cwd=str(repo))
    run('git config user.name "Test"', cwd=str(repo))
    run("git checkout -b main", cwd=str(repo))

    readme = repo / "README.md"
    readme.write_text("# test\n")
    run("git add .", cwd=str(repo))
    run('git commit -m "initial"', cwd=str(repo))
    run(f"git remote add origin {remote}", cwd=str(repo))
    run("git push -u origin main", cwd=str(repo))

    return str(repo), str(remote)


class TestCheckDivergence:
    def test_up_to_date(self):
        """same local and remote = up to date."""
        heads = ("abc123", "abc123", "abc123")
        result = check_divergence(heads)
        assert result["status"] == "up_to_date"
        assert result["safe_to_push"] is True
        assert result["diverged"] is False

    def test_ahead(self):
        """local ahead of remote (remote == base) = safe to push."""
        heads = ("def456", "abc123", "abc123")
        result = check_divergence(heads)
        assert result["status"] == "ahead"
        assert result["safe_to_push"] is True

    def test_behind(self):
        """local behind remote (local == base) = needs pull."""
        heads = ("abc123", "def456", "abc123")
        result = check_divergence(heads)
        assert result["status"] == "behind"
        assert result["safe_to_push"] is False
        assert result.get("needs_pull") is True

    def test_diverged(self):
        """both moved from base = diverged."""
        heads = ("aaa111", "bbb222", "ccc333")
        result = check_divergence(heads)
        assert result["status"] == "diverged"
        assert result["diverged"] is True
        assert result["safe_to_push"] is False

    def test_fetch_failed(self):
        """None heads = fetch failed."""
        result = check_divergence(None)
        assert result["status"] == "fetch_failed"
        assert result["safe_to_push"] is False


class TestDirtyChecks:
    def test_clean_repo(self, temp_repo):
        """fresh commit = nothing dirty."""
        assert has_dirty_index(temp_repo) is False
        assert has_unstaged_changes(temp_repo) is False

    def test_staged_changes(self, temp_repo):
        """staged file = dirty index."""
        p = Path(temp_repo) / "new.txt"
        p.write_text("hello")
        run("git add new.txt", cwd=temp_repo)
        assert has_dirty_index(temp_repo) is True

    def test_unstaged_changes(self, temp_repo):
        """modified but not staged = unstaged changes."""
        p = Path(temp_repo) / "README.md"
        p.write_text("# modified\n")
        assert has_unstaged_changes(temp_repo) is True
        assert has_dirty_index(temp_repo) is False


class TestAutoMerge:
    def test_dry_run(self, temp_repo):
        """dry run returns success without doing anything."""
        ok, msg = auto_merge(temp_repo, dry_run=True)
        assert ok is True
        assert "dry-run" in msg

    def test_no_remote_no_merge(self, temp_repo):
        """repo without origin/main remote — merge should fail gracefully."""
        # no origin configured, so merge origin/main will fail
        ok, msg = auto_merge(temp_repo, dry_run=False)
        assert ok is False

    def test_merge_clean(self, temp_repo_with_remote):
        """diverged repos should merge cleanly when changes don't overlap."""
        repo, remote = temp_repo_with_remote

        # create a divergent commit on remote side
        clone = Path(repo).parent / "clone"
        clone.mkdir()
        run(f"git clone {remote} {clone}", cwd=str(clone.parent))
        run('git config user.email "other@test.local"', cwd=str(clone))
        run('git config user.name "Other"', cwd=str(clone))
        (clone / "remote_file.txt").write_text("from remote\n")
        run("git add .", cwd=str(clone))
        run('git commit -m "remote change"', cwd=str(clone))
        run("git push origin main", cwd=str(clone))

        # create a local-only change
        (Path(repo) / "local_file.txt").write_text("from local\n")
        run("git add .", cwd=repo)
        run('git commit -m "local change"', cwd=repo)

        # fetch to update origin/main
        run("git fetch origin", cwd=repo)

        # now merge
        ok, msg = auto_merge(repo)
        assert ok is True
        assert "merged" in msg.lower() or "success" in msg.lower()

    def test_merge_with_unstaged_stashes_first(self, temp_repo_with_remote):
        """unstaged changes should be stashed before merge attempt."""
        repo, remote = temp_repo_with_remote

        # create remote divergence
        clone = Path(repo).parent / "clone2"
        clone.mkdir()
        run(f"git clone {remote} {clone}", cwd=str(clone.parent))
        run('git config user.email "other@test.local"', cwd=str(clone))
        run('git config user.name "Other"', cwd=str(clone))
        (clone / "other.txt").write_text("remote\n")
        run("git add .", cwd=str(clone))
        run('git commit -m "remote"', cwd=str(clone))
        run("git push origin main", cwd=str(clone))

        # local commit
        (Path(repo) / "local.txt").write_text("local\n")
        run("git add .", cwd=repo)
        run('git commit -m "local"', cwd=repo)

        # unstaged change in a different file
        (Path(repo) / "dirty.txt").write_text("dirty\n")

        run("git fetch origin", cwd=repo)

        ok, msg = auto_merge(repo, verbose=True)
        assert ok is True
        # dirty.txt should still exist after stash pop
        assert (Path(repo) / "dirty.txt").exists()


class TestGetHeads:
    def test_no_remote_returns_none(self, temp_repo):
        """repo without remote should return None from get_heads."""
        result = get_heads(temp_repo)
        assert result is None

    def test_with_remote(self, temp_repo_with_remote):
        """repo with remote should return tuple of hashes."""
        repo, _ = temp_repo_with_remote
        result = get_heads(repo)
        assert result is not None
        local, remote, base = result
        assert len(local) == 40
        assert local == remote  # just pushed, should be same
        assert local == base
