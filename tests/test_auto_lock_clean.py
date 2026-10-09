#!/usr/bin/env python3
"""Tests for tools/auto_lock_clean.py — stale lock detection and cleanup."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from auto_lock_clean import (
    clean,
    exit_code,
    format_text,
    is_stale,
    lock_age,
    lock_path,
    run,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal repo-like directory with .git/."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    return tmp_path


class TestLockPath:
    def test_returns_git_index_lock(self, tmp_repo: Path) -> None:
        result = lock_path(tmp_repo)
        assert result == tmp_repo / ".git" / "index.lock"


class TestLockAge:
    def test_returns_none_when_absent(self, tmp_repo: Path) -> None:
        assert lock_age(lock_path(tmp_repo)) is None

    def test_returns_age_when_present(self, tmp_repo: Path) -> None:
        lock = lock_path(tmp_repo)
        lock.touch()
        now = time.time()
        age = lock_age(lock, now=now)
        assert age is not None
        assert age >= 0
        assert age < 2  # just created

    def test_returns_none_on_os_error(self, tmp_repo: Path) -> None:
        lock = lock_path(tmp_repo)
        lock.touch()
        # Remove the file so stat() fails
        lock.unlink()
        assert lock_age(lock) is None


class TestIsStale:
    def test_false_when_absent(self, tmp_repo: Path) -> None:
        assert is_stale(lock_path(tmp_repo)) is False

    def test_false_when_fresh(self, tmp_repo: Path) -> None:
        lock = lock_path(tmp_repo)
        lock.touch()
        assert is_stale(lock, threshold=300) is False

    def test_true_when_old(self, tmp_repo: Path) -> None:
        lock = lock_path(tmp_repo)
        lock.touch()
        # Set mtime to 10 minutes ago
        old_time = time.time() - 600
        import os
        os.utime(lock, (old_time, old_time))
        assert is_stale(lock, threshold=300) is True

    def test_boundary_at_threshold(self, tmp_repo: Path) -> None:
        lock = lock_path(tmp_repo)
        lock.touch()
        old_time = time.time() - 300
        import os
        os.utime(lock, (old_time, old_time))
        assert is_stale(lock, threshold=300) is True


class TestClean:
    def test_removes_existing_lock(self, tmp_repo: Path) -> None:
        lock = lock_path(tmp_repo)
        lock.touch()
        result = clean(lock)
        assert result["action"] == "cleaned"
        assert not lock.exists()

    def test_noop_when_absent(self, tmp_repo: Path) -> None:
        lock = lock_path(tmp_repo)
        result = clean(lock)
        assert result["action"] == "none"

    def test_error_on_permission_denied(self, tmp_repo: Path) -> None:
        lock = lock_path(tmp_repo)
        lock.touch()
        # Make the parent directory read-only
        git_dir = tmp_repo / ".git"
        git_dir.chmod(0o444)
        try:
            result = clean(lock)
            # On some systems this may succeed; on others it returns error
            assert result["action"] in ("cleaned", "error")
        finally:
            git_dir.chmod(0o755)


class TestRun:
    def test_clean_state(self, tmp_repo: Path) -> None:
        report = run(repo=tmp_repo)
        assert report["exists"] is False
        assert report["stale"] is False
        assert report["action"] == "none"

    def test_stale_lock_cleaned(self, tmp_repo: Path) -> None:
        lock = lock_path(tmp_repo)
        lock.touch()
        old_time = time.time() - 600
        import os
        os.utime(lock, (old_time, old_time))
        report = run(repo=tmp_repo, threshold=120)
        assert report["stale"] is True
        assert report["action"] == "cleaned"
        assert not lock.exists()

    def test_stale_lock_dry_run(self, tmp_repo: Path) -> None:
        lock = lock_path(tmp_repo)
        lock.touch()
        old_time = time.time() - 600
        import os
        os.utime(lock, (old_time, old_time))
        report = run(repo=tmp_repo, threshold=120, dry_run=True)
        assert report["stale"] is True
        assert report["action"] == "dry_run"
        assert lock.exists()  # not removed

    def test_fresh_lock_not_touched(self, tmp_repo: Path) -> None:
        lock = lock_path(tmp_repo)
        lock.touch()
        report = run(repo=tmp_repo, threshold=300)
        assert report["stale"] is False
        assert report["action"] == "none"
        assert lock.exists()


class TestExitCode:
    def test_zero_for_clean_state(self) -> None:
        assert exit_code({"action": "none", "stale": False}) == 0

    def test_zero_after_cleaning(self) -> None:
        assert exit_code({"action": "cleaned", "stale": True}) == 0

    def test_one_for_dry_run_stale(self) -> None:
        assert exit_code({"action": "dry_run", "stale": True}) == 1

    def test_two_for_error(self) -> None:
        assert exit_code({"action": "error", "stale": True}) == 2


class TestFormatText:
    def test_no_lock(self) -> None:
        assert "clean" in format_text({"exists": False, "action": "none"})

    def test_cleaned(self) -> None:
        text = format_text({"exists": True, "age_seconds": 500.0,
                            "stale": True, "action": "cleaned"})
        assert "cleaned" in text
        assert "500" in text

    def test_dry_run(self) -> None:
        text = format_text({"exists": True, "age_seconds": 500.0,
                            "stale": True, "action": "dry_run"})
        assert "dry run" in text

    def test_fresh_lock(self) -> None:
        text = format_text({"exists": True, "age_seconds": 10.0,
                            "stale": False, "action": "none"})
        assert "fresh" in text


class TestCLI:
    def test_json_output(self, tmp_repo: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "auto_lock_clean.py"),
             "--repo", str(tmp_repo), "--json"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["exists"] is False

    def test_dry_run_exit_code(self, tmp_repo: Path) -> None:
        lock = lock_path(tmp_repo)
        lock.touch()
        old_time = time.time() - 600
        import os
        os.utime(lock, (old_time, old_time))
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "auto_lock_clean.py"),
             "--repo", str(tmp_repo), "--dry-run", "--threshold", "120"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 1
        assert lock.exists()  # not removed
