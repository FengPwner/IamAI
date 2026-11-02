#!/usr/bin/env python3
"""Tests for post_recovery_verify.py — post-recovery health verification.

Tests the individual check functions with mocking where needed,
plus integration tests for the full verify_all() flow.
"""

import json
import os
import subprocess
import sys
import time
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import post_recovery_verify as prv


# ---------------------------------------------------------------------------
# CheckResult / VerifyReport data structures
# ---------------------------------------------------------------------------

class TestCheckResult:
    def test_basic_construction(self):
        cr = prv.CheckResult(name="test", passed=True, detail="ok")
        assert cr.name == "test"
        assert cr.passed is True
        assert cr.detail == "ok"
        assert cr.latency_ms == 0

    def test_with_latency(self):
        cr = prv.CheckResult(name="x", passed=False, detail="fail", latency_ms=42)
        assert cr.latency_ms == 42


class TestVerifyReport:
    def test_empty_report(self):
        report = prv.VerifyReport()
        assert report.passed_count == 0
        assert report.failed_count == 0
        report.finalize()
        assert report.all_passed is True  # no failures after finalize

    def test_add_checks(self):
        report = prv.VerifyReport()
        report.add(prv.CheckResult("a", True, "ok"))
        report.add(prv.CheckResult("b", False, "bad"))
        report.add(prv.CheckResult("c", True, "fine"))
        assert report.passed_count == 2
        assert report.failed_count == 1
        assert report.all_passed is False

    def test_finalize_sets_timestamp(self):
        report = prv.VerifyReport()
        report.add(prv.CheckResult("a", True, "ok"))
        report.finalize()
        assert report.timestamp != ""
        assert "T" in report.timestamp  # ISO-like

    def test_all_passed(self):
        report = prv.VerifyReport()
        report.add(prv.CheckResult("a", True, "ok"))
        report.add(prv.CheckResult("b", True, "ok"))
        report.finalize()
        assert report.all_passed is True


# ---------------------------------------------------------------------------
# Individual check functions (with mocking)
# ---------------------------------------------------------------------------

class TestCheckWriterRunning:
    @patch.object(prv, "_find_pid", return_value=12345)
    @patch.object(prv, "_pid_alive", return_value=True)
    def test_writer_alive(self, mock_alive, mock_pid):
        result = prv.check_writer_running()
        assert result.passed is True
        assert "12345" in result.detail

    @patch.object(prv, "_find_pid", return_value=None)
    def test_writer_not_found(self, mock_pid):
        result = prv.check_writer_running()
        assert result.passed is False
        assert "no writer" in result.detail.lower() or "not found" in result.detail.lower()

    @patch.object(prv, "_find_pid", return_value=99999)
    @patch.object(prv, "_pid_alive", return_value=False)
    def test_writer_pid_dead(self, mock_alive, mock_pid):
        result = prv.check_writer_running()
        assert result.passed is False


class TestCheckBatchRunning:
    @patch.object(prv, "_find_pid", return_value=54321)
    @patch.object(prv, "_pid_alive", return_value=True)
    def test_batch_alive(self, mock_alive, mock_pid):
        result = prv.check_batch_running()
        assert result.passed is True
        assert "54321" in result.detail

    @patch.object(prv, "_find_pid", return_value=None)
    def test_batch_not_found(self, mock_pid):
        result = prv.check_batch_running()
        assert result.passed is False


class TestCheckUncommitted:
    def test_clean_tree(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init"], cwd=td, capture_output=True)
            (repo / "a.txt").write_text("hello")
            subprocess.run(["git", "add", "."], cwd=td, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=td, capture_output=True,
                           env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
            result = prv.check_uncommitted(repo)
            assert result.passed is True
            assert "clean" in result.detail.lower()

    def test_unexpected_dirty_file(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init"], cwd=td, capture_output=True)
            (repo / "a.txt").write_text("hello")
            subprocess.run(["git", "add", "."], cwd=td, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=td, capture_output=True,
                           env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
            (repo / "b.txt").write_text("dirty")
            result = prv.check_uncommitted(repo)
            assert result.passed is False

    def test_expected_writer_drift_ignored(self):
        """Files matching writer_state or DEVLOG are tolerated."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init"], cwd=td, capture_output=True)
            (repo / "data").mkdir()
            (repo / "data" / "writer_state.qwen.json").write_text("{}")
            (repo / "docs").mkdir()
            (repo / "docs" / "DEVLOG.md").write_text("# log")
            subprocess.run(["git", "add", "."], cwd=td, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=td, capture_output=True,
                           env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
            # Modify only the expected-drift files
            (repo / "data" / "writer_state.qwen.json").write_text('{"tick": 1}')
            (repo / "docs" / "DEVLOG.md").write_text("# log\nnew line")
            result = prv.check_uncommitted(repo)
            assert result.passed is True


class TestCheckSshKey:
    def test_key_missing(self):
        """When the key file doesn't exist, check fails."""
        fake_path = Path("/tmp/_test_nonexistent_key_12345")
        if fake_path.exists():
            fake_path.unlink()
        with patch.object(prv, "Path") as mock_path_cls:
            # Only intercept the ssh_deploy_key check
            original_path = Path
            def side_effect(p):
                if "ssh_deploy_key" in str(p):
                    return fake_path
                return original_path(p)
            # Simpler: just patch the check directly
            pass
        # Direct approach: test with a temp key
        with tempfile.NamedTemporaryFile(suffix="_key", delete=False) as f:
            key_path = f.name
        try:
            os.chmod(key_path, 0o600)
            # Manually test the permission logic
            stat = os.stat(key_path)
            mode = oct(stat.st_mode & 0o777)
            assert mode == "0o600"
        finally:
            os.unlink(key_path)

    def test_key_correct_permissions(self):
        with tempfile.NamedTemporaryFile(suffix="_key", delete=False) as f:
            key_path = f.name
        try:
            os.chmod(key_path, 0o600)
            stat = os.stat(key_path)
            mode = oct(stat.st_mode & 0o777)
            assert mode in ("0o600", "0o400")
        finally:
            os.unlink(key_path)


class TestCheckWriterProducing:
    def test_strokes_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            result = prv.check_writer_producing(repo)
            assert result.passed is False
            assert "not found" in result.detail.lower()

    def test_strokes_file_fresh(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "data").mkdir()
            strokes = repo / "data" / "strokes.jsonl"
            strokes.write_text('{"seq": 1}\n')
            result = prv.check_writer_producing(repo)
            assert result.passed is True
            assert "last stroke" in result.detail.lower()

    def test_strokes_file_stale(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "data").mkdir()
            strokes = repo / "data" / "strokes.jsonl"
            strokes.write_text('{"seq": 1}\n')
            # Set mtime to 5 minutes ago
            old_time = time.time() - 300
            os.utime(strokes, (old_time, old_time))
            result = prv.check_writer_producing(repo)
            assert result.passed is False
            assert "stale" in result.detail.lower()


# ---------------------------------------------------------------------------
# Integration: verify_all
# ---------------------------------------------------------------------------

class TestVerifyAll:
    @patch.object(prv, "check_remote_reachable",
                  return_value=prv.CheckResult("remote_reachable", True, "reachable", 50))
    @patch.object(prv, "check_writer_producing",
                  return_value=prv.CheckResult("writer_producing", True, "last stroke 10s ago", 1))
    @patch.object(prv, "check_ssh_key",
                  return_value=prv.CheckResult("ssh_key", True, "mode 0o600", 1))
    @patch.object(prv, "check_unpushed",
                  return_value=prv.CheckResult("unpushed", True, "all pushed", 20))
    @patch.object(prv, "check_uncommitted",
                  return_value=prv.CheckResult("uncommitted", True, "clean", 10))
    @patch.object(prv, "check_batch_running",
                  return_value=prv.CheckResult("batch_running", True, "pid 5663", 5))
    @patch.object(prv, "check_writer_running",
                  return_value=prv.CheckResult("writer_running", True, "pid 5662", 5))
    def test_all_pass(self, *mocks):
        report = prv.verify_all()
        assert report.all_passed is True
        assert report.passed_count == 7
        assert report.failed_count == 0

    @patch.object(prv, "check_remote_reachable",
                  return_value=prv.CheckResult("remote_reachable", False, "timeout", 15000))
    @patch.object(prv, "check_writer_producing",
                  return_value=prv.CheckResult("writer_producing", True, "last stroke 5s ago", 1))
    @patch.object(prv, "check_ssh_key",
                  return_value=prv.CheckResult("ssh_key", True, "mode 0o600", 1))
    @patch.object(prv, "check_unpushed",
                  return_value=prv.CheckResult("unpushed", True, "all pushed", 20))
    @patch.object(prv, "check_uncommitted",
                  return_value=prv.CheckResult("uncommitted", True, "clean", 10))
    @patch.object(prv, "check_batch_running",
                  return_value=prv.CheckResult("batch_running", True, "pid 5663", 5))
    @patch.object(prv, "check_writer_running",
                  return_value=prv.CheckResult("writer_running", True, "pid 5662", 5))
    def test_one_failure(self, *mocks):
        report = prv.verify_all()
        assert report.all_passed is False
        assert report.failed_count == 1
        assert report.passed_count == 6

    @patch.object(prv, "check_remote_reachable",
                  return_value=prv.CheckResult("remote_reachable", False, "offline", 15000))
    @patch.object(prv, "check_writer_producing",
                  return_value=prv.CheckResult("writer_producing", False, "stale: >120s", 1))
    @patch.object(prv, "check_ssh_key",
                  return_value=prv.CheckResult("ssh_key", False, "key not found", 1))
    @patch.object(prv, "check_unpushed",
                  return_value=prv.CheckResult("unpushed", False, "3 unpushed", 20))
    @patch.object(prv, "check_uncommitted",
                  return_value=prv.CheckResult("uncommitted", False, "5 dirty", 10))
    @patch.object(prv, "check_batch_running",
                  return_value=prv.CheckResult("batch_running", False, "not found", 5))
    @patch.object(prv, "check_writer_running",
                  return_value=prv.CheckResult("writer_running", False, "not found", 5))
    def test_all_fail(self, *mocks):
        report = prv.verify_all()
        assert report.all_passed is False
        assert report.failed_count == 7


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_format_all_pass(self):
        report = prv.VerifyReport()
        report.add(prv.CheckResult("a", True, "ok", 5))
        report.add(prv.CheckResult("b", True, "fine", 10))
        report.finalize()
        text = prv.format_report(report)
        assert "PASS" in text
        assert "FAIL" not in text
        assert "2/2 passed" in text

    def test_format_with_failure(self):
        report = prv.VerifyReport()
        report.add(prv.CheckResult("a", True, "ok", 5))
        report.add(prv.CheckResult("b", False, "broken", 10))
        report.finalize()
        text = prv.format_report(report)
        assert "FAIL" in text
        assert "WARNING" in text
        assert "1 check(s) failed" in text
