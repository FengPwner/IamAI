"""Tests for tools/stale_lock_detector.py.

Covers: find_lock path resolution, lock_age_seconds (present, missing,
custom clock), is_stale threshold logic, clean_lock (exists, absent),
detect report shape, format_text messages, and CLI exit codes.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import stale_lock_detector as sld  # noqa: E402


@pytest.fixture
def fake_repo(tmp_path):
    """Create a minimal repo layout with .git directory."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    return tmp_path


class TestFindLock:
    def test_returns_expected_path(self, fake_repo):
        lock = sld.find_lock(fake_repo)
        assert lock == fake_repo / ".git" / "index.lock"


class TestLockAgeSeconds:
    def test_missing_lock_returns_none(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        assert sld.lock_age_seconds(lock) is None

    def test_existing_lock_returns_age(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        lock.touch()
        now = time.time() + 100
        age = sld.lock_age_seconds(lock, now=now)
        assert age is not None
        assert age >= 100

    def test_custom_clock(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        lock.touch()
        mtime = lock.stat().st_mtime
        age = sld.lock_age_seconds(lock, now=mtime + 42.5)
        assert abs(age - 42.5) < 0.1


class TestIsStale:
    def test_missing_is_not_stale(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        assert sld.is_stale(lock) is False

    def test_fresh_lock_is_not_stale(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        lock.touch()
        now = time.time() + 10  # 10 seconds old
        assert sld.is_stale(lock, threshold=300, now=now) is False

    def test_old_lock_is_stale(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        lock.touch()
        now = time.time() + 600  # 600 seconds old
        assert sld.is_stale(lock, threshold=300, now=now) is True

    def test_exact_threshold_is_stale(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        lock.touch()
        mtime = lock.stat().st_mtime
        assert sld.is_stale(lock, threshold=300, now=mtime + 300) is True

    def test_custom_threshold(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        lock.touch()
        now = time.time() + 50
        assert sld.is_stale(lock, threshold=30, now=now) is True
        assert sld.is_stale(lock, threshold=100, now=now) is False


class TestCleanLock:
    def test_clean_existing_lock(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        lock.touch()
        assert lock.exists()
        result = sld.clean_lock(lock)
        assert result is True
        assert not lock.exists()

    def test_clean_missing_lock(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        result = sld.clean_lock(lock)
        assert result is False


class TestDetect:
    def test_report_no_lock(self, fake_repo):
        report = sld.detect(repo=fake_repo)
        assert report["exists"] is False
        assert report["stale"] is False
        assert report["age_seconds"] is None
        assert report["threshold_seconds"] == 300

    def test_report_stale_lock(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        lock.touch()
        now = time.time() + 600
        report = sld.detect(repo=fake_repo, now=now)
        assert report["exists"] is True
        assert report["stale"] is True
        assert report["age_seconds"] >= 600

    def test_report_fresh_lock(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        lock.touch()
        now = time.time() + 10
        report = sld.detect(repo=fake_repo, now=now)
        assert report["exists"] is True
        assert report["stale"] is False

    def test_custom_threshold_in_report(self, fake_repo):
        report = sld.detect(repo=fake_repo, threshold=120)
        assert report["threshold_seconds"] == 120

    def test_lock_path_in_report(self, fake_repo):
        report = sld.detect(repo=fake_repo)
        assert report["lock_path"].endswith(".git/index.lock")


class TestFormatText:
    def test_no_lock_message(self):
        report = {"exists": False, "stale": False, "age_seconds": None, "threshold_seconds": 300}
        assert "no lock" in sld.format_text(report).lower()

    def test_stale_message(self):
        report = {"exists": True, "stale": True, "age_seconds": 612.3, "threshold_seconds": 300}
        text = sld.format_text(report)
        assert "stale" in text.lower()
        assert "612" in text

    def test_fresh_message(self):
        report = {"exists": True, "stale": False, "age_seconds": 45.0, "threshold_seconds": 300}
        text = sld.format_text(report)
        assert "fresh" in text.lower()


class TestCLI:
    def test_exit_zero_no_lock(self, fake_repo):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "stale_lock_detector.py"), "--repo", str(fake_repo)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "no lock" in result.stdout.lower()

    def test_exit_one_stale_lock(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        lock.touch()
        # set mtime to 10 minutes ago
        old_time = time.time() - 600
        import os
        os.utime(lock, (old_time, old_time))
        result = subprocess.run(
            [sys.executable, str(TOOLS / "stale_lock_detector.py"), "--repo", str(fake_repo)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "stale" in result.stdout.lower()

    def test_json_output(self, fake_repo):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "stale_lock_detector.py"), "--repo", str(fake_repo), "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["exists"] is False

    def test_clean_removes_stale_lock(self, fake_repo):
        lock = fake_repo / ".git" / "index.lock"
        lock.touch()
        old_time = time.time() - 600
        import os
        os.utime(lock, (old_time, old_time))
        result = subprocess.run(
            [sys.executable, str(TOOLS / "stale_lock_detector.py"),
             "--repo", str(fake_repo), "--clean"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert not lock.exists()
