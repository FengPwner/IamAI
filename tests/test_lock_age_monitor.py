"""Tests for iamai.lock_age_monitor."""

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.lock_age_monitor import (
    LockReport,
    _classify,
    _recommendation,
    scan_lock,
)


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_fresh(self):
        assert _classify(5.0, 30, 120) == "fresh"

    def test_fresh_boundary(self):
        assert _classify(29.9, 30, 120) == "fresh"

    def test_aging(self):
        assert _classify(60.0, 30, 120) == "aging"

    def test_aging_boundary(self):
        assert _classify(30.0, 30, 120) == "aging"

    def test_stale(self):
        assert _classify(200.0, 30, 120) == "stale"

    def test_stale_boundary(self):
        assert _classify(120.0, 30, 120) == "stale"

    def test_zero_age(self):
        assert _classify(0.0, 30, 120) == "fresh"

    def test_custom_thresholds(self):
        assert _classify(5.0, 10, 20) == "fresh"
        assert _classify(15.0, 10, 20) == "aging"
        assert _classify(25.0, 10, 20) == "stale"


# ---------------------------------------------------------------------------
# _recommendation
# ---------------------------------------------------------------------------

class TestRecommendation:
    def test_stale_always_remove(self):
        assert _recommendation("stale", pid_alive=True) == "remove"
        assert _recommendation("stale", pid_alive=False) == "remove"

    def test_aging_no_pid(self):
        assert _recommendation("aging", pid_alive=False) == "watch"

    def test_aging_with_pid(self):
        assert _recommendation("aging", pid_alive=True) == "leave"

    def test_fresh_always_leave(self):
        assert _recommendation("fresh", pid_alive=True) == "leave"
        assert _recommendation("fresh", pid_alive=False) == "leave"


# ---------------------------------------------------------------------------
# LockReport
# ---------------------------------------------------------------------------

class TestLockReport:
    def test_to_dict(self):
        r = LockReport(
            repo="/tmp/repo",
            lock_path="/tmp/repo/.git/index.lock",
            exists=True,
            age_seconds=45.0,
            label="aging",
            mtime_epoch=1000.0,
            pid_alive=False,
            recommendation="watch",
        )
        d = r.to_dict()
        assert d["label"] == "aging"
        assert d["age_seconds"] == 45.0
        assert d["recommendation"] == "watch"

    def test_to_json(self):
        r = LockReport(
            repo="/tmp/repo",
            lock_path="/tmp/repo/.git/index.lock",
            exists=False,
            age_seconds=0.0,
            label="none",
            mtime_epoch=0.0,
            pid_alive=False,
            recommendation="nothing",
        )
        j = r.to_json()
        assert '"none"' in j
        assert '"exists": false' in j


# ---------------------------------------------------------------------------
# scan_lock (integration-ish with real temp repo)
# ---------------------------------------------------------------------------

class TestScanLock:
    def test_no_lock_file(self, tmp_path):
        """A repo with .git/ but no lock → exists=False."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        report = scan_lock(str(tmp_path))
        assert report.exists is False
        assert report.label == "none"
        assert report.recommendation == "nothing"

    def test_fresh_lock(self, tmp_path):
        """A just-created lock → fresh."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("pid=12345")

        with patch("iamai.lock_age_monitor._git_process_alive", return_value=True):
            report = scan_lock(str(tmp_path))

        assert report.exists is True
        assert report.label == "fresh"
        assert report.recommendation == "leave"

    def test_stale_lock(self, tmp_path):
        """An old lock → stale, recommend remove."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("pid=99999")
        # backdate mtime by 5 minutes
        old_time = time.time() - 300
        os_utime = (old_time, old_time)
        os.utime(str(lock), os_utime)

        with patch("iamai.lock_age_monitor._git_process_alive", return_value=False):
            report = scan_lock(str(tmp_path))

        assert report.exists is True
        assert report.label == "stale"
        assert report.recommendation == "remove"
        assert report.age_seconds > 200

    def test_not_a_repo(self, tmp_path):
        """A directory without .git → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            scan_lock(str(tmp_path))

    def test_custom_thresholds(self, tmp_path):
        """With very low thresholds, a fresh lock becomes stale."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("pid=12345")
        # backdate by 10 seconds
        old_time = time.time() - 10
        os.utime(str(lock), (old_time, old_time))

        with patch("iamai.lock_age_monitor._git_process_alive", return_value=False):
            report = scan_lock(str(tmp_path), fresh_seconds=2, stale_seconds=5)

        assert report.label == "stale"

    def test_aging_no_process(self, tmp_path):
        """Aging lock with no git process → watch."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("pid=12345")
        old_time = time.time() - 60  # 60s old
        os.utime(str(lock), (old_time, old_time))

        with patch("iamai.lock_age_monitor._git_process_alive", return_value=False):
            report = scan_lock(str(tmp_path))

        assert report.label == "aging"
        assert report.recommendation == "watch"
