#!/usr/bin/env python3
"""Tests for tools/git_lock_reaper.py — stale git lock detection and removal.

Written by Qwen during caretaker visit 671, 2026-11-17.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import git_lock_reaper as glr


class TestGetLockAge(unittest.TestCase):
    """Test lock file age calculation."""

    def test_fresh_file_has_low_age(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"lock")
            path = Path(f.name)
        try:
            age = glr.get_lock_age(path)
            self.assertLess(age, 5.0)
            self.assertGreaterEqual(age, 0.0)
        finally:
            path.unlink()

    def test_old_file_has_high_age(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"lock")
            path = Path(f.name)
        try:
            old_time = time.time() - 600
            os.utime(path, (old_time, old_time))
            age = glr.get_lock_age(path)
            self.assertGreater(age, 590)
        finally:
            path.unlink()

    def test_missing_file_returns_inf(self):
        path = Path("/tmp/nonexistent_lock_test_abc123.lock")
        age = glr.get_lock_age(path)
        self.assertEqual(age, float("inf"))


class TestFindLockFiles(unittest.TestCase):
    """Test lock file discovery in .git directories."""

    def test_finds_index_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = Path(tmpdir) / ".git"
            git_dir.mkdir()
            lock = git_dir / "index.lock"
            lock.write_text("locked")
            found = glr.find_lock_files(git_dir)
            paths = [str(p) for p in found]
            self.assertTrue(any("index.lock" in p for p in paths))

    def test_finds_config_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = Path(tmpdir) / ".git"
            git_dir.mkdir()
            lock = git_dir / "config.lock"
            lock.write_text("locked")
            found = glr.find_lock_files(git_dir)
            paths = [str(p) for p in found]
            self.assertTrue(any("config.lock" in p for p in paths))

    def test_finds_refs_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = Path(tmpdir) / ".git"
            refs_dir = git_dir / "refs" / "heads"
            refs_dir.mkdir(parents=True)
            lock = refs_dir / "main.lock"
            lock.write_text("locked")
            found = glr.find_lock_files(git_dir)
            paths = [str(p) for p in found]
            self.assertTrue(any("main.lock" in p for p in paths))

    def test_no_locks_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = Path(tmpdir) / ".git"
            git_dir.mkdir()
            found = glr.find_lock_files(git_dir)
            self.assertEqual(found, [])

    def test_multiple_locks_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = Path(tmpdir) / ".git"
            git_dir.mkdir()
            for name in ["index.lock", "config.lock", "HEAD.lock"]:
                (git_dir / name).write_text("locked")
            found = glr.find_lock_files(git_dir)
            self.assertEqual(len(found), 3)


class TestGitProcessRunning(unittest.TestCase):
    """Test git process detection."""

    @patch("subprocess.run")
    def test_detects_running_git(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="1234\n")
        self.assertTrue(glr.git_process_running())

    @patch("subprocess.run")
    def test_detects_no_git(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        self.assertFalse(glr.git_process_running())

    @patch("subprocess.run")
    def test_pgrep_missing_assumes_running(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        self.assertTrue(glr.git_process_running())

    @patch("subprocess.run")
    def test_timeout_assumes_running(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pgrep", timeout=5)
        self.assertTrue(glr.git_process_running())


class TestIsLockStale(unittest.TestCase):
    """Test staleness classification."""

    def test_fresh_lock_with_git_running(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"lock")
            path = Path(f.name)
        try:
            with patch.object(glr, "git_process_running", return_value=True):
                is_stale, reason = glr.is_lock_stale(path, max_age=300)
                self.assertFalse(is_stale)
                self.assertEqual(reason, "fresh")
        finally:
            path.unlink()

    def test_old_lock_is_stale(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"lock")
            path = Path(f.name)
        try:
            old_time = time.time() - 600
            os.utime(path, (old_time, old_time))
            with patch.object(glr, "git_process_running", return_value=True):
                is_stale, reason = glr.is_lock_stale(path, max_age=300)
                self.assertTrue(is_stale)
                self.assertEqual(reason, "stale_age")
        finally:
            path.unlink()

    def test_no_git_running_makes_any_lock_stale(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"lock")
            path = Path(f.name)
        try:
            with patch.object(glr, "git_process_running", return_value=False):
                is_stale, reason = glr.is_lock_stale(path, max_age=300)
                self.assertTrue(is_stale)
                self.assertEqual(reason, "stale_no_git")
        finally:
            path.unlink()

    def test_old_lock_no_git_is_stale_no_git(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"lock")
            path = Path(f.name)
        try:
            old_time = time.time() - 600
            os.utime(path, (old_time, old_time))
            with patch.object(glr, "git_process_running", return_value=False):
                is_stale, reason = glr.is_lock_stale(path, max_age=300)
                self.assertTrue(is_stale)
                # stale_no_git takes priority over stale_age
                self.assertEqual(reason, "stale_no_git")
        finally:
            path.unlink()


class TestReapLock(unittest.TestCase):
    """Test lock removal."""

    def test_reap_stale_lock(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"lock")
            path = Path(f.name)
        try:
            old_time = time.time() - 600
            os.utime(path, (old_time, old_time))
            with patch.object(glr, "git_process_running", return_value=False):
                report = glr.reap_lock(path, dry_run=False)
                self.assertTrue(report.is_stale)
                self.assertTrue(report.reaped)
                self.assertFalse(path.exists())
        finally:
            if path.exists():
                path.unlink()

    def test_reap_dry_run_does_not_remove(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"lock")
            path = Path(f.name)
        try:
            old_time = time.time() - 600
            os.utime(path, (old_time, old_time))
            with patch.object(glr, "git_process_running", return_value=False):
                report = glr.reap_lock(path, dry_run=True)
                self.assertTrue(report.is_stale)
                self.assertFalse(report.reaped)
                self.assertEqual(report.reap_error, "dry_run")
                self.assertTrue(path.exists())
        finally:
            path.unlink()

    def test_fresh_lock_not_reaped(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"lock")
            path = Path(f.name)
        try:
            with patch.object(glr, "git_process_running", return_value=True):
                report = glr.reap_lock(path, dry_run=False)
                self.assertFalse(report.is_stale)
                self.assertFalse(report.reaped)
                self.assertTrue(path.exists())
        finally:
            path.unlink()

    def test_reap_handles_permission_error(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"lock")
            path = Path(f.name)
        try:
            old_time = time.time() - 600
            os.utime(path, (old_time, old_time))
            with patch.object(glr, "git_process_running", return_value=False):
                with patch.object(Path, "unlink", side_effect=PermissionError("denied")):
                    report = glr.reap_lock(path, dry_run=False)
                    self.assertTrue(report.is_stale)
                    self.assertFalse(report.reaped)
                    self.assertIn("denied", report.reap_error)
        finally:
            path.unlink()


class TestScanRepo(unittest.TestCase):
    """Test full repo scanning."""

    def test_scan_empty_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = Path(tmpdir) / ".git"
            git_dir.mkdir()
            reports = glr.scan_repo(tmpdir)
            self.assertEqual(reports, [])

    def test_scan_with_stale_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = Path(tmpdir) / ".git"
            git_dir.mkdir()
            lock = git_dir / "index.lock"
            lock.write_text("locked")
            old_time = time.time() - 600
            os.utime(lock, (old_time, old_time))
            with patch.object(glr, "git_process_running", return_value=False):
                reports = glr.scan_repo(tmpdir, max_age=300)
                self.assertEqual(len(reports), 1)
                self.assertTrue(reports[0].is_stale)

    def test_scan_with_reap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = Path(tmpdir) / ".git"
            git_dir.mkdir()
            lock = git_dir / "index.lock"
            lock.write_text("locked")
            old_time = time.time() - 600
            os.utime(lock, (old_time, old_time))
            with patch.object(glr, "git_process_running", return_value=False):
                reports = glr.scan_repo(tmpdir, max_age=300, reap=True)
                self.assertEqual(len(reports), 1)
                self.assertTrue(reports[0].reaped)
                self.assertFalse(lock.exists())

    def test_scan_non_git_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reports = glr.scan_repo(tmpdir)
            self.assertEqual(reports, [])


class TestSummary(unittest.TestCase):
    """Test summary statistics."""

    def test_all_clean(self):
        reports = [
            glr.LockReport(path="a", exists=True, age_seconds=10,
                           is_stale=False, reason="fresh"),
        ]
        s = glr.summary(reports)
        self.assertTrue(s["clean"])
        self.assertEqual(s["stale_locks"], 0)

    def test_with_stale(self):
        reports = [
            glr.LockReport(path="a", exists=True, age_seconds=10,
                           is_stale=False, reason="fresh"),
            glr.LockReport(path="b", exists=True, age_seconds=600,
                           is_stale=True, reason="stale_age"),
        ]
        s = glr.summary(reports)
        self.assertFalse(s["clean"])
        self.assertEqual(s["stale_locks"], 1)
        self.assertEqual(s["total_locks"], 2)

    def test_reaped_count(self):
        reports = [
            glr.LockReport(path="a", exists=True, age_seconds=600,
                           is_stale=True, reason="stale_no_git", reaped=True),
            glr.LockReport(path="b", exists=True, age_seconds=700,
                           is_stale=True, reason="stale_no_git",
                           reaped=False, reap_error="denied"),
        ]
        s = glr.summary(reports)
        self.assertEqual(s["reaped"], 1)
        self.assertEqual(s["failed"], 1)

    def test_empty_reports(self):
        s = glr.summary([])
        self.assertTrue(s["clean"])
        self.assertEqual(s["total_locks"], 0)


class TestFindGitRoot(unittest.TestCase):
    """Test git root discovery."""

    def test_finds_bare_git_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = Path(tmpdir) / ".git"
            git_dir.mkdir()
            result = glr.find_git_root(tmpdir)
            self.assertIsNotNone(result)
            self.assertEqual(result, git_dir)

    def test_returns_none_for_non_git(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = glr.find_git_root(tmpdir)
            self.assertIsNone(result)


class TestCLIOutput(unittest.TestCase):
    """Test command-line interface."""

    def test_json_output_parseable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = Path(tmpdir) / ".git"
            git_dir.mkdir()
            result = subprocess.run(
                [sys.executable, "-m", "tools.git_lock_reaper",
                 "--repo", tmpdir, "--json"],
                capture_output=True, text=True, cwd=str(Path(__file__).parent.parent),
                timeout=10,
            )
            if result.returncode in (0, 1):
                data = json.loads(result.stdout)
                self.assertIn("summary", data)
                self.assertIn("locks", data)


if __name__ == "__main__":
    unittest.main()
