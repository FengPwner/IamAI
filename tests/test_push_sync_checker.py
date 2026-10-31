#!/usr/bin/env python3
"""Tests for push_sync_checker.py — 16 tests covering sync state detection,
edge cases, CLI output, and error handling.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from push_sync_checker import (
    SyncStatus,
    check_sync,
    find_repo_root,
    get_current_branch,
    get_remote_tracking,
    get_rev_count,
    get_sha,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def git(args, cwd):
    """Run a git command in cwd."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def make_repo(tmp_path, name="test-repo"):
    """Create a minimal git repo with one initial commit."""
    repo = tmp_path / name
    repo.mkdir()
    git(["init"], repo)
    git(["config", "user.email", "test@test.com"], repo)
    git(["config", "user.name", "Test"], repo)
    (repo / "README.md").write_text("# Test\n")
    git(["add", "."], repo)
    git(["commit", "-m", "init"], repo)
    return repo


def make_bare_remote(tmp_path, repo, name="origin"):
    """Create a bare clone and set it as remote."""
    bare = tmp_path / f"{name}.git"
    subprocess.run(
        ["git", "clone", "--bare", str(repo), str(bare)],
        capture_output=True, text=True,
    )
    git(["remote", "add", name, str(bare)], repo)
    git(["push", name, "master"], repo)
    git(["branch", "--set-upstream-to", f"{name}/master", "master"], repo)
    return bare


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synced_repo(tmp_path):
    """Repo that is in sync with its remote."""
    repo = make_repo(tmp_path, "synced")
    make_bare_remote(tmp_path, repo)
    return repo


@pytest.fixture
def ahead_repo(tmp_path):
    """Repo that is ahead of its remote."""
    repo = make_repo(tmp_path, "ahead")
    bare = make_bare_remote(tmp_path, repo)
    # Add a local-only commit
    (repo / "new.txt").write_text("local change\n")
    git(["add", "."], repo)
    git(["commit", "-m", "local: add new.txt"], repo)
    return repo


@pytest.fixture
def behind_repo(tmp_path):
    """Repo that is behind its remote."""
    repo = make_repo(tmp_path, "behind")
    bare = make_bare_remote(tmp_path, repo)
    # Push a commit directly to bare (simulating another collaborator)
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(bare), str(clone)],
        capture_output=True, text=True,
    )
    git(["config", "user.email", "other@test.com"], clone)
    git(["config", "user.name", "Other"], clone)
    (clone / "remote.txt").write_text("remote change\n")
    git(["add", "."], clone)
    git(["commit", "-m", "remote: add remote.txt"], clone)
    git(["push", "origin", "master"], clone)
    # Fetch in original repo to update tracking
    git(["fetch", "origin"], repo)
    return repo


@pytest.fixture
def diverged_repo(tmp_path):
    """Repo that has diverged from its remote."""
    repo = make_repo(tmp_path, "diverged")
    bare = make_bare_remote(tmp_path, repo)
    # Local commit
    (repo / "local.txt").write_text("local\n")
    git(["add", "."], repo)
    git(["commit", "-m", "local: add local.txt"], repo)
    # Remote commit via clone
    clone = tmp_path / "clone2"
    subprocess.run(
        ["git", "clone", str(bare), str(clone)],
        capture_output=True, text=True,
    )
    git(["config", "user.email", "other@test.com"], clone)
    git(["config", "user.name", "Other"], clone)
    (clone / "remote.txt").write_text("remote\n")
    git(["add", "."], clone)
    git(["commit", "-m", "remote: add remote.txt"], clone)
    git(["push", "origin", "master"], clone)
    git(["fetch", "origin"], repo)
    return repo


@pytest.fixture
def no_tracking_repo(tmp_path):
    """Repo with no remote tracking branch."""
    repo = make_repo(tmp_path, "no-track")
    return repo


# ---------------------------------------------------------------------------
# Tests: sync state detection
# ---------------------------------------------------------------------------

class TestSyncState:
    def test_synced(self, synced_repo):
        status = check_sync(str(synced_repo))
        assert status.state == "synced"
        assert status.ahead == 0
        assert status.behind == 0

    def test_ahead(self, ahead_repo):
        status = check_sync(str(ahead_repo))
        assert status.state == "ahead"
        assert status.ahead == 1
        assert status.behind == 0

    def test_behind(self, behind_repo):
        status = check_sync(str(behind_repo))
        assert status.state == "behind"
        assert status.ahead == 0
        assert status.behind == 1

    def test_diverged(self, diverged_repo):
        status = check_sync(str(diverged_repo))
        assert status.state == "diverged"
        assert status.ahead >= 1
        assert status.behind >= 1

    def test_no_tracking(self, no_tracking_repo):
        status = check_sync(str(no_tracking_repo))
        assert status.state == "no-tracking"
        assert status.remote_branch is None


# ---------------------------------------------------------------------------
# Tests: SyncStatus dataclass
# ---------------------------------------------------------------------------

class TestSyncStatus:
    def test_fields(self):
        s = SyncStatus(
            local_branch="main",
            remote_branch="origin/main",
            ahead=3,
            behind=1,
            state="diverged",
            local_sha="abc1234",
            remote_sha="def5678",
            message="test",
        )
        assert s.local_branch == "main"
        assert s.ahead == 3
        assert s.behind == 1
        assert s.state == "diverged"

    def test_to_dict(self):
        s = SyncStatus(
            local_branch="main",
            remote_branch=None,
            ahead=0,
            behind=0,
            state="no-tracking",
            local_sha="abc",
            remote_sha=None,
            message="no remote",
        )
        d = s.__dict__
        assert d["state"] == "no-tracking"
        assert d["remote_branch"] is None


# ---------------------------------------------------------------------------
# Tests: helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_find_repo_root(self, synced_repo):
        root = find_repo_root(str(synced_repo))
        assert Path(root).is_dir()

    def test_find_repo_root_not_a_repo(self, tmp_path):
        not_a_repo = tmp_path / "not_a_repo"
        not_a_repo.mkdir()
        with pytest.raises(RuntimeError, match="Not a git repo"):
            find_repo_root(str(not_a_repo))

    def test_get_current_branch(self, synced_repo):
        branch = get_current_branch(str(synced_repo))
        assert branch in ("master", "main")

    def test_get_sha(self, synced_repo):
        sha = get_sha(str(synced_repo), "HEAD")
        assert len(sha) >= 7  # short SHA

    def test_get_rev_count_zero_for_same_ref(self, synced_repo):
        count = get_rev_count(str(synced_repo), "HEAD..HEAD")
        assert count == 0


# ---------------------------------------------------------------------------
# Tests: exit code semantics
# ---------------------------------------------------------------------------

class TestExitCodes:
    def _run_checker(self, repo_path):
        """Run the script as a subprocess and return exit code + stdout."""
        script = str(Path(__file__).resolve().parent.parent / "scripts" / "push_sync_checker.py")
        result = subprocess.run(
            [sys.executable, script, "--json", "--repo", str(repo_path)],
            capture_output=True, text=True,
        )
        return result.returncode, result.stdout

    def test_synced_exits_zero(self, synced_repo):
        code, _ = self._run_checker(synced_repo)
        assert code == 0

    def test_ahead_exits_zero(self, ahead_repo):
        code, _ = self._run_checker(ahead_repo)
        assert code == 0

    def test_behind_exits_one(self, behind_repo):
        code, _ = self._run_checker(behind_repo)
        assert code == 1

    def test_diverged_exits_one(self, diverged_repo):
        code, _ = self._run_checker(diverged_repo)
        assert code == 1

    def test_no_tracking_exits_two(self, no_tracking_repo):
        code, _ = self._run_checker(no_tracking_repo)
        assert code == 2


# ---------------------------------------------------------------------------
# Tests: JSON output
# ---------------------------------------------------------------------------

class TestJsonOutput:
    def test_json_parseable(self, ahead_repo):
        script = str(Path(__file__).resolve().parent.parent / "scripts" / "push_sync_checker.py")
        result = subprocess.run(
            [sys.executable, script, "--json", "--repo", str(ahead_repo)],
            capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        assert "state" in data
        assert "ahead" in data
        assert data["state"] == "ahead"
