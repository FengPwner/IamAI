"""Tests for iamai.push_guard.push_readiness_report."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.push_guard import push_readiness_report


def _run(cmd, cwd=None, check=True):
    """Helper that captures output to suppress git hints."""
    return subprocess.run(
        cmd, cwd=cwd, check=check,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _make_repo(tmp: Path) -> Path:
    """Create a minimal git repo with one commit and a bare remote."""
    repo = tmp / "repo"
    repo.mkdir()
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "test"], cwd=repo)
    _run(["git", "config", "user.email", "test@test"], cwd=repo)
    # Rename default branch to main.
    _run(["git", "checkout", "-b", "main"], cwd=repo)
    (repo / "README.md").write_text("# test\n")
    _run(["git", "add", "."], cwd=repo)
    _run(["git", "commit", "-m", "init"], cwd=repo)

    # Create a bare remote so push/pull tracking refs exist.
    bare = tmp / "remote.git"
    _run(["git", "init", "--bare", str(bare)])
    _run(["git", "remote", "add", "origin", str(bare)], cwd=repo)
    _run(["git", "push", "-u", "origin", "main"], cwd=repo)
    return repo


def test_clean_repo_is_ready(tmp_path):
    """A freshly cloned repo with nothing to push should report ready."""
    repo = _make_repo(tmp_path)
    report = push_readiness_report(repo)
    assert report["ready"] is True
    assert report["dirty_files"] == 0
    assert report["unpushed"] == 0
    assert report["diverged"] is False


def test_dirty_tree_not_ready(tmp_path):
    """Uncommitted changes should mark the repo as not ready."""
    repo = _make_repo(tmp_path)
    (repo / "dirty.txt").write_text("uncommitted\n")
    report = push_readiness_report(repo)
    assert report["ready"] is False
    assert report["dirty_files"] >= 1


def test_unpushed_commits_counted(tmp_path):
    """Local commits not yet pushed should be counted."""
    repo = _make_repo(tmp_path)
    (repo / "new.txt").write_text("new file\n")
    _run(["git", "add", "."], cwd=repo)
    _run(["git", "commit", "-m", "second"], cwd=repo)
    report = push_readiness_report(repo)
    assert report["unpushed"] >= 1
    # Unpushed alone doesn't block readiness — it just means there's work to push.
    assert report["diverged"] is False


def test_diverged_not_ready(tmp_path):
    """When remote has commits local doesn't have, report diverged."""
    repo = _make_repo(tmp_path)

    # Simulate divergence: create a commit on the bare remote via a clone.
    clone = tmp_path / "clone"
    bare = tmp_path / "remote.git"
    _run(["git", "clone", "-b", "main", str(bare), str(clone)])
    _run(["git", "config", "user.name", "other"], cwd=clone)
    _run(["git", "config", "user.email", "other@test"], cwd=clone)
    (clone / "remote.txt").write_text("from remote\n")
    _run(["git", "add", "."], cwd=clone)
    _run(["git", "commit", "-m", "remote commit"], cwd=clone)
    _run(["git", "push", "origin", "main"], cwd=clone)

    # Fetch in the original repo to update tracking refs.
    _run(["git", "fetch", "origin"], cwd=repo)

    report = push_readiness_report(repo)
    assert report["diverged"] is True
    assert report["ready"] is False


def test_stale_lock_detected(tmp_path):
    """An expired push lock file should be flagged as stale."""
    repo = _make_repo(tmp_path)
    lock_dir = repo / "data"
    lock_dir.mkdir(exist_ok=True)
    lock_file = lock_dir / "push.lock"
    lock_file.write_text(json.dumps({
        "agent": "test",
        "pid": 99999,
        "acquired_at": time.time() - 600,
        "expires_at": time.time() - 300,  # expired 5 minutes ago
    }))
    report = push_readiness_report(repo)
    assert report["stale_lock"] is True
    assert report["ready"] is False


def test_fresh_lock_not_stale(tmp_path):
    """A valid, unexpired lock should not be flagged as stale."""
    repo = _make_repo(tmp_path)
    lock_dir = repo / "data"
    lock_dir.mkdir(exist_ok=True)
    lock_file = lock_dir / "push.lock"
    lock_file.write_text(json.dumps({
        "agent": "test",
        "pid": 1,
        "acquired_at": time.time(),
        "expires_at": time.time() + 120,  # valid for 2 more minutes
    }))
    report = push_readiness_report(repo)
    assert report["stale_lock"] is False


def test_no_lock_file_is_none(tmp_path):
    """When no lock file exists, stale_lock should be None (not checked)."""
    repo = _make_repo(tmp_path)
    report = push_readiness_report(repo)
    assert report["stale_lock"] is None


def test_return_keys(tmp_path):
    """Report always contains the expected keys."""
    repo = _make_repo(tmp_path)
    report = push_readiness_report(repo)
    expected_keys = {"ready", "dirty_files", "unpushed", "diverged", "stale_lock"}
    assert set(report.keys()) == expected_keys
