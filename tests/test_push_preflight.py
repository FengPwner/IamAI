#!/usr/bin/env python3
"""Tests for tools/push_preflight.py — pre-push pipeline health check."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from push_preflight import (
    CheckResult,
    PreflightReport,
    check_lock_file,
    check_working_tree,
    check_rebase_state,
    check_ssh_key,
    check_remote_sync,
    check_writer_pause,
    run_preflight,
    main,
    GIT_DIR,
    DEFAULT_SSH_KEY,
    PAUSE_PATH,
)


# ---------------------------------------------------------------------------
# CheckResult
# ---------------------------------------------------------------------------


class TestCheckResult:
    """Tests for the CheckResult dataclass."""

    def test_blocking_on_fail(self):
        r = CheckResult(name="test", status="fail", message="bad")
        assert r.blocking() is True

    def test_not_blocking_on_pass(self):
        r = CheckResult(name="test", status="pass", message="ok")
        assert r.blocking() is False

    def test_not_blocking_on_warn(self):
        r = CheckResult(name="test", status="warn", message="meh")
        assert r.blocking() is False

    def test_not_blocking_on_skip(self):
        r = CheckResult(name="test", status="skip", message="n/a")
        assert r.blocking() is False

    def test_detail_default_empty(self):
        r = CheckResult(name="x", status="pass", message="ok")
        assert r.detail == ""

    def test_detail_with_value(self):
        r = CheckResult(name="x", status="fail", message="bad", detail="line1\nline2")
        assert "line1" in r.detail


# ---------------------------------------------------------------------------
# PreflightReport
# ---------------------------------------------------------------------------


class TestPreflightReport:
    """Tests for the PreflightReport aggregation."""

    def test_empty_report_passes(self):
        report = PreflightReport()
        assert report.verdict == "pass"
        assert report.remediation == []

    def test_add_pass_keeps_verdict(self):
        report = PreflightReport()
        report.add(CheckResult(name="a", status="pass", message="ok"))
        assert report.verdict == "pass"

    def test_add_fail_sets_verdict(self):
        report = PreflightReport()
        report.add(CheckResult(name="a", status="fail", message="bad"))
        assert report.verdict == "fail"
        assert len(report.remediation) == 1
        assert "[a]" in report.remediation[0]

    def test_add_warn_does_not_fail(self):
        report = PreflightReport()
        report.add(CheckResult(name="a", status="warn", message="meh"))
        assert report.verdict == "pass"

    def test_multiple_failures_accumulate(self):
        report = PreflightReport()
        report.add(CheckResult(name="a", status="fail", message="one"))
        report.add(CheckResult(name="b", status="fail", message="two"))
        report.add(CheckResult(name="c", status="pass", message="ok"))
        assert report.verdict == "fail"
        assert len(report.remediation) == 2

    def test_summary_format(self):
        report = PreflightReport()
        report.add(CheckResult(name="a", status="pass", message="ok"))
        report.add(CheckResult(name="b", status="fail", message="bad"))
        report.add(CheckResult(name="c", status="warn", message="meh"))
        s = report.summary()
        assert "fail" in s
        assert "1 pass" in s
        assert "1 fail" in s
        assert "1 warn" in s

    def test_summary_all_pass(self):
        report = PreflightReport()
        report.add(CheckResult(name="a", status="pass", message="ok"))
        report.add(CheckResult(name="b", status="pass", message="ok"))
        s = report.summary()
        assert "pass" in s
        assert "2 pass" in s


# ---------------------------------------------------------------------------
# check_lock_file
# ---------------------------------------------------------------------------


class TestCheckLockFile:
    """Tests for the lock file check."""

    def test_no_lock_file_passes(self):
        with patch("push_preflight.GIT_DIR") as mock_git:
            mock_lock = MagicMock()
            mock_lock.exists.return_value = False
            mock_git.__truediv__ = lambda self, x: mock_lock
            result = check_lock_file()
            assert result.status == "pass"
            assert result.name == "lock_file"

    def test_lock_file_present_fails(self):
        with patch("push_preflight.GIT_DIR") as mock_git:
            mock_lock = MagicMock()
            mock_lock.exists.return_value = True
            mock_lock.__str__ = lambda self: "/fake/.git/index.lock"
            mock_git.__truediv__ = lambda self, x: mock_lock
            result = check_lock_file()
            assert result.status == "fail"
            assert "index.lock" in result.message


# ---------------------------------------------------------------------------
# check_working_tree
# ---------------------------------------------------------------------------


class TestCheckWorkingTree:
    """Tests for the working tree check."""

    def test_clean_tree_passes(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch("push_preflight._run_git", return_value=mock_result):
            result = check_working_tree()
            assert result.status == "pass"
            assert "clean" in result.message

    def test_dirty_tree_fails(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = " M file1.py\n M file2.md\n"
        with patch("push_preflight._run_git", return_value=mock_result):
            result = check_working_tree()
            assert result.status == "fail"
            assert "2 uncommitted" in result.message

    def test_git_status_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: not a git repository"
        with patch("push_preflight._run_git", return_value=mock_result):
            result = check_working_tree()
            assert result.status == "fail"
            assert "git status failed" in result.message

    def test_single_change(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = " M only_one.py\n"
        with patch("push_preflight._run_git", return_value=mock_result):
            result = check_working_tree()
            assert result.status == "fail"
            assert "1 uncommitted" in result.message

    def test_blank_lines_ignored(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n\n"
        with patch("push_preflight._run_git", return_value=mock_result):
            result = check_working_tree()
            assert result.status == "pass"


# ---------------------------------------------------------------------------
# check_rebase_state
# ---------------------------------------------------------------------------


class TestCheckRebaseState:
    """Tests for the rebase state check."""

    def test_no_rebase_passes(self):
        with patch("push_preflight.GIT_DIR") as mock_git:
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_git.__truediv__ = lambda self, x: mock_path
            result = check_rebase_state()
            assert result.status == "pass"

    def test_rebase_merge_fails(self):
        call_count = [0]

        def mock_truediv(self, x):
            m = MagicMock()
            call_count[0] += 1
            if x == "rebase-merge":
                m.exists.return_value = True
                m.__str__ = lambda self: "/fake/.git/rebase-merge"
            else:
                m.exists.return_value = False
            return m

        with patch("push_preflight.GIT_DIR") as mock_git:
            mock_git.__truediv__ = mock_truediv
            result = check_rebase_state()
            assert result.status == "fail"
            assert "rebase-merge" in result.message

    def test_rebase_apply_fails(self):
        def mock_truediv(self, x):
            m = MagicMock()
            if x == "rebase-merge":
                m.exists.return_value = False
            elif x == "rebase-apply":
                m.exists.return_value = True
                m.__str__ = lambda self: "/fake/.git/rebase-apply"
            else:
                m.exists.return_value = False
            return m

        with patch("push_preflight.GIT_DIR") as mock_git:
            mock_git.__truediv__ = mock_truediv
            result = check_rebase_state()
            assert result.status == "fail"
            assert "rebase-apply" in result.message


# ---------------------------------------------------------------------------
# check_ssh_key
# ---------------------------------------------------------------------------


class TestCheckSSHKey:
    """Tests for the SSH key check."""

    def test_missing_key_fails(self, tmp_path):
        fake_key = tmp_path / "nonexistent_key"
        result = check_ssh_key(fake_key)
        assert result.status == "fail"
        assert "not found" in result.message

    def test_empty_key_fails(self, tmp_path):
        key = tmp_path / "empty_key"
        key.write_text("")
        result = check_ssh_key(key)
        assert result.status == "fail"
        assert "empty" in result.message

    def test_valid_key_passes(self, tmp_path):
        key = tmp_path / "good_key"
        key.write_text("ssh-ed25519 AAAA... test@host")
        result = check_ssh_key(key)
        assert result.status == "pass"
        assert "OK" in result.message

    def test_unreadable_key_fails(self, tmp_path):
        key = tmp_path / "locked_key"
        key.write_text("secret")
        with patch("push_preflight.os.access", return_value=False):
            result = check_ssh_key(key)
            assert result.status == "fail"
            assert "not readable" in result.message


# ---------------------------------------------------------------------------
# check_remote_sync
# ---------------------------------------------------------------------------


class TestCheckRemoteSync:
    """Tests for the remote sync check."""

    def _mock_run_git(self, responses):
        """Create a _run_git mock that returns different results based on args."""
        def side_effect(args, cwd=None):
            key = " ".join(args[:2]) if len(args) >= 2 else args[0]
            for pattern, result in responses.items():
                if pattern in key:
                    return result
            return MagicMock(returncode=1, stdout="", stderr="unknown")
        return side_effect

    def test_same_sha_nothing_to_push(self):
        sha = "abc123def456"
        responses = {
            "rev-parse HEAD": MagicMock(returncode=0, stdout=sha + "\n"),
            "rev-parse origin": MagicMock(returncode=0, stdout=sha + "\n"),
        }
        with patch("push_preflight._run_git", side_effect=self._mock_run_git(responses)):
            result = check_remote_sync()
            assert result.status == "pass"
            assert "nothing to push" in result.message

    def test_local_ahead_safe_to_push(self):
        local_sha = "bbb111"
        remote_sha = "aaa000"
        responses = {
            "rev-parse HEAD": MagicMock(returncode=0, stdout=local_sha + "\n"),
            "rev-parse origin": MagicMock(returncode=0, stdout=remote_sha + "\n"),
            "merge-base": MagicMock(returncode=0, stdout=remote_sha + "\n"),
            "rev-list --count": MagicMock(returncode=0, stdout="3\n"),
        }
        with patch("push_preflight._run_git", side_effect=self._mock_run_git(responses)):
            result = check_remote_sync()
            assert result.status == "pass"
            assert "3 commit(s) ahead" in result.message

    def test_diverged_needs_rebase(self):
        local_sha = "bbb111"
        remote_sha = "ccc222"
        base_sha = "aaa000"
        responses = {
            "rev-parse HEAD": MagicMock(returncode=0, stdout=local_sha + "\n"),
            "rev-parse origin": MagicMock(returncode=0, stdout=remote_sha + "\n"),
            "merge-base": MagicMock(returncode=0, stdout=base_sha + "\n"),
        }
        with patch("push_preflight._run_git", side_effect=self._mock_run_git(responses)):
            result = check_remote_sync()
            assert result.status == "fail"
            assert "diverged" in result.message

    def test_no_remote_branch_warns(self):
        responses = {
            "rev-parse HEAD": MagicMock(returncode=0, stdout="abc\n"),
            "rev-parse origin": MagicMock(returncode=128, stderr="fatal: not found"),
        }
        with patch("push_preflight._run_git", side_effect=self._mock_run_git(responses)):
            result = check_remote_sync()
            assert result.status == "warn"
            assert "not found" in result.message

    def test_local_head_fails(self):
        responses = {
            "rev-parse HEAD": MagicMock(returncode=128, stderr="fatal"),
        }
        with patch("push_preflight._run_git", side_effect=self._mock_run_git(responses)):
            result = check_remote_sync()
            assert result.status == "fail"
            assert "cannot resolve" in result.message


# ---------------------------------------------------------------------------
# check_writer_pause
# ---------------------------------------------------------------------------


class TestCheckWriterPause:
    """Tests for the writer pause check."""

    def test_paused_passes(self, tmp_path):
        sentinel = tmp_path / "pause_sentinel"
        sentinel.touch()
        result = check_writer_pause(sentinel)
        assert result.status == "pass"
        assert "paused" in result.message

    def test_not_paused_warns(self, tmp_path):
        sentinel = tmp_path / "nonexistent_sentinel"
        result = check_writer_pause(sentinel)
        assert result.status == "warn"
        assert "not paused" in result.message


# ---------------------------------------------------------------------------
# run_preflight (integration)
# ---------------------------------------------------------------------------


class TestRunPreflight:
    """Integration tests for the full preflight run."""

    def test_all_checks_run(self):
        """All six checks should appear in the report."""
        with patch("push_preflight.check_lock_file") as m1, \
             patch("push_preflight.check_working_tree") as m2, \
             patch("push_preflight.check_rebase_state") as m3, \
             patch("push_preflight.check_ssh_key") as m4, \
             patch("push_preflight.check_remote_sync") as m5, \
             patch("push_preflight.check_writer_pause") as m6:
            for i, m in enumerate([m1, m2, m3, m4, m5, m6]):
                m.return_value = CheckResult(
                    name=f"check_{i}", status="pass", message="ok"
                )
            report = run_preflight()
            assert len(report.checks) == 6
            assert report.verdict == "pass"

    def test_one_failure_fails_report(self):
        """A single failure should make the whole report fail."""
        with patch("push_preflight.check_lock_file") as m1, \
             patch("push_preflight.check_working_tree") as m2, \
             patch("push_preflight.check_rebase_state") as m3, \
             patch("push_preflight.check_ssh_key") as m4, \
             patch("push_preflight.check_remote_sync") as m5, \
             patch("push_preflight.check_writer_pause") as m6:
            m1.return_value = CheckResult(name="lock_file", status="pass", message="ok")
            m2.return_value = CheckResult(name="working_tree", status="pass", message="ok")
            m3.return_value = CheckResult(name="rebase_state", status="pass", message="ok")
            m4.return_value = CheckResult(name="ssh_key", status="fail", message="missing key")
            m5.return_value = CheckResult(name="remote_sync", status="pass", message="ok")
            m6.return_value = CheckResult(name="writer_pause", status="pass", message="ok")
            report = run_preflight()
            assert report.verdict == "fail"
            assert len(report.remediation) == 1


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for the CLI entry point."""

    def test_pass_exits_zero(self):
        with patch("push_preflight.run_preflight") as mock_pf:
            report = PreflightReport()
            report.add(CheckResult(name="a", status="pass", message="ok"))
            mock_pf.return_value = report
            with patch("sys.argv", ["push_preflight.py"]):
                assert main() == 0

    def test_fail_exits_one(self):
        with patch("push_preflight.run_preflight") as mock_pf:
            report = PreflightReport()
            report.add(CheckResult(name="a", status="fail", message="bad"))
            mock_pf.return_value = report
            with patch("sys.argv", ["push_preflight.py"]):
                assert main() == 1

    def test_strict_warn_exits_one(self):
        with patch("push_preflight.run_preflight") as mock_pf:
            report = PreflightReport()
            report.add(CheckResult(name="a", status="warn", message="meh"))
            mock_pf.return_value = report
            with patch("sys.argv", ["push_preflight.py", "--strict"]):
                assert main() == 1

    def test_json_output(self, capsys):
        with patch("push_preflight.run_preflight") as mock_pf:
            report = PreflightReport()
            report.add(CheckResult(name="a", status="pass", message="ok"))
            mock_pf.return_value = report
            with patch("sys.argv", ["push_preflight.py", "--json"]):
                main()
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert data["verdict"] == "pass"
            assert len(data["checks"]) == 1
