"""Tests for iamai.lock_health — git lock file scanner.

Uses process-based staleness detection rather than mtime, because the
repo lives on a FUSE filesystem where directory traversal resets mtime.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.lock_health import scan_locks, summary, _discover_locks, _git_running


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Create a minimal fake repo with a .git directory."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    return tmp_path


def _touch_lock(repo: Path, relpath: str, age: float = 0) -> Path:
    """Create a lock file at *relpath* under repo."""
    lock = repo / relpath
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("")
    if age > 0:
        t = time.time() - age
        os.utime(lock, (t, t))
    return lock


# ---- _git_running ----


def test_git_running_returns_bool():
    result = _git_running()
    assert isinstance(result, bool)


# ---- _discover_locks ----


def test_discover_empty(fake_repo: Path):
    assert _discover_locks(fake_repo) == []


def test_discover_known_path(fake_repo: Path):
    _touch_lock(fake_repo, ".git/index.lock")
    found = _discover_locks(fake_repo)
    assert any("index.lock" in str(f) for f in found)


def test_discover_nested(fake_repo: Path):
    _touch_lock(fake_repo, ".git/refs/heads/main.lock")
    _touch_lock(fake_repo, ".git/refs/custom/something.lock")
    found = _discover_locks(fake_repo)
    assert len(found) >= 1


# ---- scan_locks ----


def test_scan_no_locks(fake_repo: Path):
    with patch("iamai.lock_health._git_running", return_value=False):
        result = scan_locks(repo=fake_repo, max_age=60)
    assert result["total_count"] == 0
    assert result["stale_count"] == 0
    assert result["locks"] == []
    assert result["cleaned"] == 0


@patch("iamai.lock_health._git_running", return_value=False)
def test_scan_stale_no_git_process(mock_git, fake_repo: Path):
    """Lock exists, no git running → stale."""
    _touch_lock(fake_repo, ".git/index.lock")
    result = scan_locks(repo=fake_repo, max_age=60)
    assert result["total_count"] >= 1
    assert result["stale_count"] >= 1
    assert result["git_running"] is False
    stale_entries = [e for e in result["locks"] if e["stale"]]
    assert len(stale_entries) >= 1


@patch("iamai.lock_health._git_running", return_value=True)
def test_scan_fresh_git_running(mock_git, fake_repo: Path):
    """Lock exists, git running, fresh mtime → not stale."""
    _touch_lock(fake_repo, ".git/index.lock")
    result = scan_locks(repo=fake_repo, max_age=999999)
    # git is running AND lock is fresh by age → not stale
    assert result["git_running"] is True
    assert result["stale_count"] == 0


@patch("iamai.lock_health._git_running", return_value=True)
def test_scan_old_lock_git_running(mock_git, fake_repo: Path):
    """Lock exists, git running, but lock is old by age → stale."""
    _touch_lock(fake_repo, ".git/index.lock", age=200)
    result = scan_locks(repo=fake_repo, max_age=60)
    # Even though git is running, the lock is old → stale
    assert result["stale_count"] >= 1


@patch("iamai.lock_health._git_running", return_value=False)
def test_scan_removes_stale(mock_git, fake_repo: Path):
    lock = _touch_lock(fake_repo, ".git/index.lock")
    assert lock.exists()
    result = scan_locks(repo=fake_repo, max_age=60, remove_stale=True)
    assert result["cleaned"] >= 1
    assert not lock.exists()


@patch("iamai.lock_health._git_running", return_value=True)
def test_scan_does_not_remove_fresh(mock_git, fake_repo: Path):
    lock = _touch_lock(fake_repo, ".git/index.lock")
    result = scan_locks(repo=fake_repo, max_age=999999, remove_stale=True)
    assert result["cleaned"] == 0
    assert lock.exists()


@patch("iamai.lock_health._git_running", return_value=False)
def test_scan_multiple_locks(mock_git, fake_repo: Path):
    _touch_lock(fake_repo, ".git/index.lock")
    _touch_lock(fake_repo, ".git/refs/heads/main.lock")
    result = scan_locks(repo=fake_repo, max_age=60)
    assert result["total_count"] >= 2
    assert result["stale_count"] >= 2


# ---- summary ----


@patch("iamai.lock_health._git_running", return_value=False)
def test_summary_no_locks(mock_git, fake_repo: Path):
    s = summary(repo=fake_repo)
    assert "no lock files" in s
    assert "healthy" in s


@patch("iamai.lock_health._git_running", return_value=True)
def test_summary_fresh(mock_git, fake_repo: Path):
    _touch_lock(fake_repo, ".git/index.lock")
    s = summary(repo=fake_repo, max_age=999999)
    assert "healthy" in s
    assert "STALE" not in s


@patch("iamai.lock_health._git_running", return_value=False)
def test_summary_stale(mock_git, fake_repo: Path):
    _touch_lock(fake_repo, ".git/index.lock")
    s = summary(repo=fake_repo, max_age=60)
    assert "STALE" in s
    assert "index.lock" in s
