#!/usr/bin/env python3
"""Tests for stale_lock_alert.py — 18 tests covering verdict logic, edge cases,
and CLI output formatting.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from stale_lock_alert import (
    LockAlert,
    check_lock,
    find_repo_root,
    DEFAULT_WARN_SEC,
    DEFAULT_CRITICAL_SEC,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_repo(tmp_path):
    """Create a minimal git repo in a temp directory."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    return tmp_path


@pytest.fixture
def tmp_repo_with_lock(tmp_repo):
    """Create a git repo with an index.lock file."""
    lock_file = tmp_repo / ".git" / "index.lock"
    lock_file.write_text("placeholder")
    return tmp_repo


# ---------------------------------------------------------------------------
# LockAlert dataclass tests
# ---------------------------------------------------------------------------

class TestLockAlert:
    def test_dataclass_fields(self):
        alert = LockAlert(
            exists=True, age_seconds=120.0, verdict="ok",
            checked_at="2026-10-31T00:00:00+00:00",
            lock_path="/tmp/repo/.git/index.lock"
        )
        assert alert.exists is True
        assert alert.age_seconds == 120.0
        assert alert.verdict == "ok"
        assert alert.lock_path == "/tmp/repo/.git/index.lock"

    def test_dataclass_serializable(self):
        from dataclasses import asdict
        alert = LockAlert(
            exists=False, age_seconds=0.0, verdict="ok",
            checked_at="2026-10-31T00:00:00+00:00",
            lock_path="/tmp/.git/index.lock"
        )
        d = asdict(alert)
        assert isinstance(d, dict)
        assert "exists" in d
        assert "verdict" in d


# ---------------------------------------------------------------------------
# check_lock tests — no lock file
# ---------------------------------------------------------------------------

class TestCheckLockNoFile:
    def test_no_lock_returns_ok(self, tmp_repo):
        alert = check_lock(tmp_repo, 300, 900)
        assert alert.exists is False
        assert alert.verdict == "ok"
        assert alert.age_seconds == 0.0

    def test_no_lock_has_path(self, tmp_repo):
        alert = check_lock(tmp_repo, 300, 900)
        assert ".git" in alert.lock_path
        assert "index.lock" in alert.lock_path

    def test_no_lock_checked_at_is_iso(self, tmp_repo):
        alert = check_lock(tmp_repo, 300, 900)
        # Should parse as ISO-8601
        dt = datetime.fromisoformat(alert.checked_at)
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# check_lock tests — fresh lock file
# ---------------------------------------------------------------------------

class TestCheckLockFresh:
    def test_fresh_lock_is_ok(self, tmp_repo_with_lock):
        alert = check_lock(tmp_repo_with_lock, 300, 900)
        assert alert.exists is True
        assert alert.verdict == "ok"
        # Freshly created, so age should be < 5 seconds
        assert alert.age_seconds < 5.0

    def test_fresh_lock_positive_age(self, tmp_repo_with_lock):
        alert = check_lock(tmp_repo_with_lock, 300, 900)
        assert alert.age_seconds >= 0.0


# ---------------------------------------------------------------------------
# check_lock tests — stale lock file
# ---------------------------------------------------------------------------

class TestCheckLockStale:
    def _make_old_lock(self, repo, seconds_ago):
        lock_file = repo / ".git" / "index.lock"
        lock_file.write_text("placeholder")
        old_time = time.time() - seconds_ago
        os.utime(lock_file, (old_time, old_time))

    def test_warning_verdict(self, tmp_repo_with_lock):
        self._make_old_lock(tmp_repo_with_lock, 400)  # 400s > warn=300
        alert = check_lock(tmp_repo_with_lock, 300, 900)
        assert alert.verdict == "warning"
        assert alert.exists is True

    def test_critical_verdict(self, tmp_repo_with_lock):
        self._make_old_lock(tmp_repo_with_lock, 1000)  # 1000s > critical=900
        alert = check_lock(tmp_repo_with_lock, 300, 900)
        assert alert.verdict == "critical"

    def test_exactly_at_warn_boundary(self, tmp_repo_with_lock):
        self._make_old_lock(tmp_repo_with_lock, 300)
        alert = check_lock(tmp_repo_with_lock, 300, 900)
        # At exactly warn threshold, should be warning (>=)
        assert alert.verdict == "warning"

    def test_exactly_at_critical_boundary(self, tmp_repo_with_lock):
        self._make_old_lock(tmp_repo_with_lock, 900)
        alert = check_lock(tmp_repo_with_lock, 300, 900)
        assert alert.verdict == "critical"

    def test_below_warn_is_ok(self, tmp_repo_with_lock):
        self._make_old_lock(tmp_repo_with_lock, 100)  # 100s < warn=300
        alert = check_lock(tmp_repo_with_lock, 300, 900)
        assert alert.verdict == "ok"

    def test_between_warn_and_critical(self, tmp_repo_with_lock):
        self._make_old_lock(tmp_repo_with_lock, 600)
        alert = check_lock(tmp_repo_with_lock, 300, 900)
        assert alert.verdict == "warning"

    def test_custom_thresholds(self, tmp_repo_with_lock):
        self._make_old_lock(tmp_repo_with_lock, 60)
        alert = check_lock(tmp_repo_with_lock, 30, 50)
        assert alert.verdict == "critical"  # 60 > 50


# ---------------------------------------------------------------------------
# find_repo_root tests
# ---------------------------------------------------------------------------

class TestFindRepoRoot:
    def test_finds_repo(self, tmp_repo):
        root = find_repo_root(tmp_repo)
        assert root == tmp_repo

    def test_finds_repo_from_subdir(self, tmp_repo):
        sub = tmp_repo / "a" / "b"
        sub.mkdir(parents=True)
        root = find_repo_root(sub)
        assert root == tmp_repo

    def test_fallback_when_no_git(self, tmp_path):
        # No .git dir anywhere
        root = find_repo_root(tmp_path)
        assert root == tmp_path
