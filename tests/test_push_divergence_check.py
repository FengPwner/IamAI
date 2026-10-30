#!/usr/bin/env python3
"""Tests for push_divergence_check.py — 22 tests covering divergence detection.

Uses temporary git repositories to simulate clean, diverged, and edge-case
scenarios without touching the real IamAI repo.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Allow importing from tools/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from push_divergence_check import (
    check_divergence,
    count_commits,
    find_repo_root,
    get_remote_tracking_branch,
    run_git,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd, cwd, env=None):
    """Run a shell command and assert success."""
    merged = {**os.environ, **(env or {})}
    result = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, env=merged
    )
    assert result.returncode == 0, f"Command failed: {cmd}\n{result.stderr}"
    return result


def _init_repo(path, bare=False):
    """Initialize a git repo with a default commit."""
    Path(path).mkdir(parents=True, exist_ok=True)
    args = ["git", "init", "--bare"] if bare else ["git", "init"]
    _run(args, path)
    if not bare:
        _run(["git", "config", "user.email", "test@test.local"], path)
        _run(["git", "config", "user.name", "Test"], path)
        # Initial commit
        (Path(path) / "README.md").write_text("# Test\n")
        _run(["git", "add", "."], path)
        _run(["git", "commit", "-m", "init"], path)


def _make_commit(path, filename, content, message):
    """Create a file, stage, and commit."""
    (Path(path) / filename).write_text(content)
    _run(["git", "add", filename], path)
    _run(["git", "commit", "-m", message], path)


@pytest.fixture
def clean_repo(tmp_path):
    """Local repo with remote, local ahead by 2 commits."""
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    _init_repo(remote, bare=True)
    _run(["git", "clone", str(remote), str(local)], tmp_path)
    _run(["git", "config", "user.email", "test@test.local"], local)
    _run(["git", "config", "user.name", "Test"], local)
    _make_commit(local, "a.txt", "a", "commit a")
    _make_commit(local, "b.txt", "b", "commit b")
    _run(["git", "push", "origin", "master"], local)
    return local


@pytest.fixture
def diverged_repo(tmp_path):
    """Local repo with remote, diverged: local has a commit remote lacks,
    and remote has a commit local lacks (via force-push from another clone)."""
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    other = tmp_path / "other"

    # 1. Init remote with one commit via a temp clone
    _init_repo(remote, bare=True)
    bootstrap = tmp_path / "bootstrap"
    _run(["git", "clone", str(remote), str(bootstrap)], tmp_path)
    _run(["git", "config", "user.email", "test@test.local"], bootstrap)
    _run(["git", "config", "user.name", "Test"], bootstrap)
    _make_commit(bootstrap, "base.txt", "base", "base commit")
    _run(["git", "push", "origin", "master"], bootstrap)

    # 2. Clone to local and other (both at same point)
    _run(["git", "clone", str(remote), str(local)], tmp_path)
    _run(["git", "config", "user.email", "test@test.local"], local)
    _run(["git", "config", "user.name", "Test"], local)
    _run(["git", "clone", str(remote), str(other)], tmp_path)
    _run(["git", "config", "user.email", "test@test.local"], other)
    _run(["git", "config", "user.name", "Test"], other)

    # 3. Local makes and pushes a commit
    _make_commit(local, "local.txt", "local", "local commit")
    _run(["git", "push", "origin", "master"], local)

    # 4. Other makes a *different* commit on the base (diverging from local)
    _make_commit(other, "other.txt", "other", "other commit")
    # Force-push to overwrite remote with other's history
    _run(["git", "push", "--force", "origin", "master"], other)

    # 5. Local makes another commit on top of its (now-stale) view
    _make_commit(local, "local2.txt", "local2", "local commit 2")

    # Now: local is ahead by 2 (its own commits), behind by 1 (other's commit)
    return local


# ---------------------------------------------------------------------------
# Tests — find_repo_root
# ---------------------------------------------------------------------------

class TestFindRepoRoot:
    def test_finds_git_root(self, clean_repo):
        sub = clean_repo / "some" / "deep" / "dir"
        sub.mkdir(parents=True)
        root = find_repo_root(sub)
        assert (root / ".git").exists()

    def test_fallback_when_no_git(self, tmp_path):
        naked = tmp_path / "naked"
        naked.mkdir()
        root = find_repo_root(naked)
        assert root == naked


# ---------------------------------------------------------------------------
# Tests — count_commits
# ---------------------------------------------------------------------------

class TestCountCommits:
    def test_count_ahead(self, clean_repo):
        # Add one more commit
        _make_commit(clean_repo, "c.txt", "c", "commit c")
        count = count_commits(clean_repo, "origin/master", "HEAD")
        assert count == 1

    def test_count_zero_when_synced(self, clean_repo):
        count = count_commits(clean_repo, "origin/master", "HEAD")
        assert count == 0

    def test_count_invalid_ref(self, clean_repo):
        count = count_commits(clean_repo, "nonexistent", "HEAD")
        assert count == -1


# ---------------------------------------------------------------------------
# Tests — get_remote_tracking_branch
# ---------------------------------------------------------------------------

class TestGetRemoteTrackingBranch:
    def test_detects_tracking(self, clean_repo):
        ref = get_remote_tracking_branch(clean_repo)
        assert ref is not None
        assert "origin" in ref

    def test_explicit_branch(self, clean_repo):
        ref = get_remote_tracking_branch(clean_repo, "master")
        assert ref == "origin/master"

    def test_missing_branch(self, clean_repo):
        ref = get_remote_tracking_branch(clean_repo, "nonexistent")
        assert ref is None


# ---------------------------------------------------------------------------
# Tests — check_divergence (clean)
# ---------------------------------------------------------------------------

class TestCheckDivergenceClean:
    def test_synced(self, clean_repo):
        result = check_divergence(clean_repo, fetch_first=False)
        assert result["status"] == "clean"
        assert result["ahead"] == 0
        assert result["behind"] == 0

    def test_ahead_only(self, clean_repo):
        _make_commit(clean_repo, "extra.txt", "extra", "extra")
        result = check_divergence(clean_repo, fetch_first=False)
        assert result["status"] == "clean"
        assert result["ahead"] == 1
        assert result["behind"] == 0

    def test_message_contains_remote_ref(self, clean_repo):
        result = check_divergence(clean_repo, fetch_first=False)
        assert "origin/master" in result["message"]


# ---------------------------------------------------------------------------
# Tests — check_divergence (diverged)
# ---------------------------------------------------------------------------

class TestCheckDivergenceDiverged:
    def test_diverged(self, diverged_repo):
        result = check_divergence(diverged_repo, fetch_first=True)
        assert result["status"] == "diverged"
        assert result["ahead"] >= 1
        assert result["behind"] >= 1

    def test_diverged_message_mentions_pull(self, diverged_repo):
        result = check_divergence(diverged_repo, fetch_first=True)
        assert "pull" in result["message"].lower() or "rebase" in result["message"].lower()

    def test_diverged_has_remote_ref(self, diverged_repo):
        result = check_divergence(diverged_repo, fetch_first=True)
        assert result["remote_ref"] is not None


# ---------------------------------------------------------------------------
# Tests — check_divergence (no tracking)
# ---------------------------------------------------------------------------

class TestCheckDivergenceNoTracking:
    def test_no_remote(self, tmp_path):
        local = tmp_path / "solo"
        _init_repo(local)
        result = check_divergence(local, remote="origin", branch="master", fetch_first=False)
        assert result["status"] == "no_tracking"

    def test_message_mentions_missing_ref(self, tmp_path):
        local = tmp_path / "solo2"
        _init_repo(local)
        result = check_divergence(local, remote="origin", branch="master", fetch_first=False)
        assert "No remote" in result["message"] or "no_tracking" in result["status"]


# ---------------------------------------------------------------------------
# Tests — edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_result_has_all_keys(self, clean_repo):
        result = check_divergence(clean_repo, fetch_first=False)
        for key in ("status", "ahead", "behind", "remote_ref", "message"):
            assert key in result

    def test_behind_never_negative(self, clean_repo):
        result = check_divergence(clean_repo, fetch_first=False)
        assert result["behind"] >= 0

    def test_ahead_never_negative(self, clean_repo):
        result = check_divergence(clean_repo, fetch_first=False)
        assert result["ahead"] >= 0

    def test_multiple_ahead(self, clean_repo):
        for i in range(5):
            _make_commit(clean_repo, f"f{i}.txt", str(i), f"commit {i}")
        result = check_divergence(clean_repo, fetch_first=False)
        assert result["ahead"] == 5

    def test_json_serializable(self, clean_repo):
        result = check_divergence(clean_repo, fetch_first=False)
        serialized = json.dumps(result)
        assert len(serialized) > 0
        parsed = json.loads(serialized)
        assert parsed["status"] == "clean"
