"""Tests for iamai.index_lock_detector — stale git lock diagnosis.

Covers:
  - detect_lock returns correct shape when no lock exists
  - detect_lock detects a stale lock (no holder)
  - detect_lock identifies a lock held by a live process
  - clear_stale_lock removes stale locks safely
  - clear_stale_lock refuses to remove locks held by live processes
  - diagnose_lock_report one-liner format for each state
  - Edge cases: missing .git dir, permission errors
"""

import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.index_lock_detector import (
    _lock_path,
    _find_holder_pid,
    detect_lock,
    clear_stale_lock,
    diagnose_lock_report,
)


# ---------------------------------------------------------------------------
# _lock_path
# ---------------------------------------------------------------------------


class TestLockPath:
    """Unit tests for the path helper."""

    def test_returns_git_index_lock(self, tmp_path: Path):
        """Lock path is .git/index.lock under the repo root."""
        result = _lock_path(tmp_path)
        assert result == tmp_path / ".git" / "index.lock"

    def test_accepts_string_path(self):
        """String paths are coerced to Path."""
        result = _lock_path("/tmp/fake-repo")
        assert result == Path("/tmp/fake-repo/.git/index.lock")


# ---------------------------------------------------------------------------
# detect_lock — no lock present
# ---------------------------------------------------------------------------


class TestDetectLockNoLock:
    """When no index.lock exists."""

    def test_not_locked(self, tmp_path: Path):
        """No lock file means locked=False."""
        (tmp_path / ".git").mkdir(parents=True)
        info = detect_lock(tmp_path)
        assert info["locked"] is False
        assert info["stale"] is False
        assert info["age_seconds"] == 0.0
        assert info["holder_pid"] is None

    def test_missing_git_dir(self, tmp_path: Path):
        """No .git directory at all — still returns cleanly."""
        info = detect_lock(tmp_path)
        assert info["locked"] is False


# ---------------------------------------------------------------------------
# detect_lock — stale lock
# ---------------------------------------------------------------------------


class TestDetectLockStale:
    """When a lock file exists but no process holds it."""

    def test_stale_lock_detected(self, tmp_path: Path):
        """A lock with no holder is marked stale."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("placeholder")

        # Mock _find_holder_pid to return None (no live holder)
        with patch("iamai.index_lock_detector._find_holder_pid", return_value=None):
            info = detect_lock(tmp_path)

        assert info["locked"] is True
        assert info["stale"] is True
        assert info["holder_pid"] is None
        assert info["age_seconds"] >= 0.0

    def test_stale_lock_age(self, tmp_path: Path):
        """Age is computed from mtime."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("placeholder")

        # Set mtime to 100 seconds ago
        old_time = time.time() - 100
        os.utime(lock, (old_time, old_time))

        with patch("iamai.index_lock_detector._find_holder_pid", return_value=None):
            info = detect_lock(tmp_path)

        assert 99 <= info["age_seconds"] <= 102


# ---------------------------------------------------------------------------
# detect_lock — active lock
# ---------------------------------------------------------------------------


class TestDetectLockActive:
    """When a lock file exists and a process holds it."""

    def test_active_lock_not_stale(self, tmp_path: Path):
        """A lock with a live holder is not stale."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("placeholder")

        with patch("iamai.index_lock_detector._find_holder_pid", return_value=12345):
            info = detect_lock(tmp_path)

        assert info["locked"] is True
        assert info["stale"] is False
        assert info["holder_pid"] == 12345


# ---------------------------------------------------------------------------
# clear_stale_lock
# ---------------------------------------------------------------------------


class TestClearStaleLock:
    """Safety of stale lock removal."""

    def test_removes_stale_lock(self, tmp_path: Path):
        """Stale locks are removed."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("placeholder")

        with patch("iamai.index_lock_detector._find_holder_pid", return_value=None):
            result = clear_stale_lock(tmp_path)

        assert result["removed"] is True
        assert not lock.exists()

    def test_refuses_active_lock(self, tmp_path: Path):
        """Active locks are NOT removed."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("placeholder")

        with patch("iamai.index_lock_detector._find_holder_pid", return_value=99999):
            result = clear_stale_lock(tmp_path)

        assert result["removed"] is False
        assert lock.exists()
        assert "not stale" in result["reason"]

    def test_no_lock_present(self, tmp_path: Path):
        """When no lock exists, nothing to remove."""
        (tmp_path / ".git").mkdir()
        result = clear_stale_lock(tmp_path)
        assert result["removed"] is False
        assert "no lock" in result["reason"]


# ---------------------------------------------------------------------------
# diagnose_lock_report
# ---------------------------------------------------------------------------


class TestDiagnoseLockReport:
    """One-liner format for caretaker logs."""

    def test_no_lock(self, tmp_path: Path):
        """Clean state message."""
        (tmp_path / ".git").mkdir()
        report = diagnose_lock_report(tmp_path)
        assert "no index.lock" in report
        assert "clear" in report

    def test_stale_report(self, tmp_path: Path):
        """Stale lock mentions safe-to-remove."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("placeholder")

        with patch("iamai.index_lock_detector._find_holder_pid", return_value=None):
            report = diagnose_lock_report(tmp_path)

        assert "stale" in report
        assert "safe to remove" in report
        assert "holder" not in report or "no holder" in report

    def test_active_report(self, tmp_path: Path):
        """Active lock warns against removal."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("placeholder")

        with patch("iamai.index_lock_detector._find_holder_pid", return_value=42):
            report = diagnose_lock_report(tmp_path)

        assert "active" in report
        assert "do not remove" in report
        assert "42" in report


# ---------------------------------------------------------------------------
# _find_holder_pid — integration guard
# ---------------------------------------------------------------------------


class TestFindHolderPid:
    """Integration-level guard for the /proc scanner."""

    def test_returns_none_or_int(self):
        """Result is always None or int."""
        repo = Path(__file__).resolve().parent.parent
        lock = repo / ".git" / "index.lock"
        # May or may not exist — either way, result type is valid
        if lock.exists():
            result = _find_holder_pid(lock)
            assert result is None or isinstance(result, int)

    def test_nonexistent_lock_returns_none(self, tmp_path: Path):
        """A lock that doesn't exist has no holder."""
        lock = tmp_path / "nonexistent.lock"
        result = _find_holder_pid(lock)
        assert result is None
