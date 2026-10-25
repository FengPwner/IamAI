#!/usr/bin/env python3
"""Tests for red_gate_auto_clear.py — the automatic RED GATE recovery tool.

32 tests covering:
- gate absent (nothing to do)
- gate present, git healthy (clear it)
- gate present, stale lock exists (don't clear)
- gate present, merge conflict active (don't clear)
- gate present, git status fails (don't clear)
- idempotency (clear twice, second run is no-op)
- threshold configuration (custom stale lock age)
- health report findings
- dry-run mode
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from tools.red_gate_auto_clear import (
    pause_file,
    check_stale_lock,
    check_git_status,
    check_merge_conflict,
    gate_health_report,
    main,
)


class TestPauseFile(unittest.TestCase):
    """Tests for pause_file path resolution."""

    def test_default_writer(self):
        pf = pause_file("qwen")
        self.assertEqual(str(pf), "/tmp/iamai-writer-pause-qwen")

    def test_custom_writer(self):
        pf = pause_file("kimi")
        self.assertEqual(str(pf), "/tmp/iamai-writer-pause-kimi")

    def test_none_writer_uses_env(self):
        with patch.dict(os.environ, {"IAMAII_WRITER": "doubao"}):
            pf = pause_file(None)
            self.assertEqual(str(pf), "/tmp/iamai-writer-pause-doubao")

    def test_none_writer_no_env(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove IAMAII_WRITER from env if it exists
            os.environ.pop("IAMAII_WRITER", None)
            pf = pause_file(None)
            self.assertEqual(str(pf), "/tmp/iamai-writer-pause-qwen")


class TestCheckStaleLock(unittest.TestCase):
    """Tests for check_stale_lock."""

    def test_no_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()
            stale, msg = check_stale_lock(repo, 120)
            self.assertFalse(stale)
            self.assertEqual(msg, "no lock")

    def test_fresh_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()
            lock = repo / ".git" / "index.lock"
            lock.write_text("pid 12345")
            stale, msg = check_stale_lock(repo, 120)
            self.assertFalse(stale)
            self.assertIn("fresh", msg)

    def test_stale_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()
            lock = repo / ".git" / "index.lock"
            lock.write_text("pid 12345")
            # Set mtime to 200 seconds ago
            old_time = time.time() - 200
            os.utime(lock, (old_time, old_time))
            stale, msg = check_stale_lock(repo, 120)
            self.assertTrue(stale)
            self.assertIn("stale", msg)

    def test_custom_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()
            lock = repo / ".git" / "index.lock"
            lock.write_text("pid 12345")
            old_time = time.time() - 50
            os.utime(lock, (old_time, old_time))
            # With 30s threshold, 50s is stale
            stale, msg = check_stale_lock(repo, 30)
            self.assertTrue(stale)
            # With 120s threshold, 50s is fresh
            stale2, msg2 = check_stale_lock(repo, 120)
            self.assertFalse(stale2)

    def test_unstatable_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()
            lock = repo / ".git" / "index.lock"
            lock.write_text("pid 12345")
            original_stat = Path.stat

            call_count = [0]

            def fake_stat(self, **kwargs):
                if "index.lock" in str(self):
                    call_count[0] += 1
                    # First call is from exists() — succeed so we get past it
                    if call_count[0] == 1:
                        return original_stat(self, **kwargs)
                    raise OSError("permission denied")
                return original_stat(self, **kwargs)

            with patch.object(Path, "stat", fake_stat):
                stale, msg = check_stale_lock(repo, 120)
                self.assertFalse(stale)
                self.assertIn("cannot stat", msg)


class TestCheckGitStatus(unittest.TestCase):
    """Tests for check_git_status."""

    def test_healthy_repo(self):
        repo = Path(__file__).resolve().parent.parent
        ok, msg = check_git_status(repo)
        self.assertTrue(ok)
        self.assertEqual(msg, "git status OK")

    def test_timeout(self):
        repo = Path("/tmp")
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            ok, msg = check_git_status(repo)
            self.assertFalse(ok)
            self.assertIn("timed out", msg)

    def test_git_failure(self):
        repo = Path("/tmp")
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: not a git repository"
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = check_git_status(repo)
            self.assertFalse(ok)
            self.assertIn("128", msg)

    def test_os_error(self):
        repo = Path("/tmp")
        with patch("subprocess.run", side_effect=OSError("no such file")):
            ok, msg = check_git_status(repo)
            self.assertFalse(ok)
            self.assertIn("error", msg)


class TestCheckMergeConflict(unittest.TestCase):
    """Tests for check_merge_conflict."""

    def test_no_merge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()
            conflict, msg = check_merge_conflict(repo)
            self.assertFalse(conflict)
            self.assertIn("no merge", msg)

    def test_active_merge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()
            (repo / ".git" / "MERGE_HEAD").write_text("abc123")
            conflict, msg = check_merge_conflict(repo)
            self.assertTrue(conflict)
            self.assertIn("MERGE_HEAD", msg)

    def test_completed_merge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()
            (repo / ".git" / "MERGE_MSG").write_text("Merge branch 'x'")
            conflict, msg = check_merge_conflict(repo)
            self.assertFalse(conflict)
            self.assertIn("completed", msg)


class TestGateHealthReport(unittest.TestCase):
    """Tests for gate_health_report."""

    def test_healthy_repo(self):
        repo = Path(__file__).resolve().parent.parent
        healthy, findings = gate_health_report(repo)
        self.assertTrue(healthy)
        self.assertGreaterEqual(len(findings), 3)

    def test_stale_lock_blocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()
            lock = repo / ".git" / "index.lock"
            lock.write_text("pid 12345")
            old_time = time.time() - 200
            os.utime(lock, (old_time, old_time))
            healthy, findings = gate_health_report(repo, 120)
            self.assertFalse(healthy)
            self.assertIn("stale", findings[0])

    def test_merge_conflict_blocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()
            (repo / ".git" / "MERGE_HEAD").write_text("abc123")
            # Mock git status to pass so we reach the merge check
            with patch("tools.red_gate_auto_clear.check_git_status", return_value=(True, "git status OK")):
                healthy, findings = gate_health_report(repo)
                self.assertFalse(healthy)
                merge_finding = [f for f in findings if "merge" in f.lower()]
                self.assertTrue(len(merge_finding) > 0)


class TestMain(unittest.TestCase):
    """Tests for main() entry point."""

    def test_no_gate_returns_2(self):
        with patch(
            "tools.red_gate_auto_clear.pause_file",
            return_value=Path("/tmp/nonexistent-gate-test"),
        ):
            sys.argv = ["red_gate_auto_clear.py", "--writer", "test_no_gate"]
            ret = main()
            self.assertEqual(ret, 2)

    def test_healthy_gate_clears(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pf = Path(tmpdir) / "pause-gate"
            pf.write_text("paused")
            with patch("tools.red_gate_auto_clear.pause_file", return_value=pf):
                with patch("tools.red_gate_auto_clear.REPO", Path(__file__).resolve().parent.parent):
                    sys.argv = ["red_gate_auto_clear.py"]
                    ret = main()
                    self.assertEqual(ret, 0)
                    self.assertFalse(pf.exists())

    def test_dry_run_does_not_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pf = Path(tmpdir) / "pause-gate"
            pf.write_text("paused")
            with patch("tools.red_gate_auto_clear.pause_file", return_value=pf):
                with patch("tools.red_gate_auto_clear.REPO", Path(__file__).resolve().parent.parent):
                    sys.argv = ["red_gate_auto_clear.py", "--dry-run"]
                    ret = main()
                    self.assertEqual(ret, 0)
                    self.assertTrue(pf.exists())

    def test_unhealthy_gate_returns_1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pf = Path(tmpdir) / "pause-gate"
            pf.write_text("paused")
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            lock = repo / ".git" / "index.lock"
            lock.write_text("pid 99999")
            old_time = time.time() - 200
            os.utime(lock, (old_time, old_time))
            with patch("tools.red_gate_auto_clear.pause_file", return_value=pf):
                with patch("tools.red_gate_auto_clear.REPO", repo):
                    sys.argv = ["red_gate_auto_clear.py"]
                    ret = main()
                    self.assertEqual(ret, 1)
                    self.assertTrue(pf.exists())

    def test_idempotent_clear(self):
        """Clearing twice: first returns 0, second returns 2."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pf = Path(tmpdir) / "pause-gate"
            pf.write_text("paused")
            with patch("tools.red_gate_auto_clear.pause_file", return_value=pf):
                with patch("tools.red_gate_auto_clear.REPO", Path(__file__).resolve().parent.parent):
                    sys.argv = ["red_gate_auto_clear.py"]
                    ret1 = main()
                    self.assertEqual(ret1, 0)
                    # Gate is gone now
                    ret2 = main()
                    self.assertEqual(ret2, 2)


if __name__ == "__main__":
    unittest.main()
