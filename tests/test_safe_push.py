"""Tests for iamai.safe_push — atomic push sequence for shared repos."""

from __future__ import annotations

import os
import signal
import subprocess
from unittest.mock import MagicMock, patch, call

import pytest

from iamai.safe_push import (
    PushResult,
    _find_writer_pid,
    _git,
    _has_uncommitted,
    _pause_writer,
    _resume_writer,
    safe_push,
)


# ---------------------------------------------------------------------------
# PushResult
# ---------------------------------------------------------------------------

class TestPushResult:
    def test_default_is_failure(self):
        r = PushResult()
        assert r.success is False
        assert r.failed_step is None

    def test_summary_success(self):
        r = PushResult(
            success=True,
            paused=True,
            resumed=True,
            commit_hash="abc1234",
            duration_seconds=2.5,
        )
        s = r.summary()
        assert "safe_push ok" in s
        assert "abc1234" in s
        assert "2.5s" in s

    def test_summary_failure(self):
        r = PushResult(
            success=False,
            failed_step="push",
            error="rejected non-fast-forward",
            resumed=True,
        )
        s = r.summary()
        assert "FAILED" in s
        assert "push" in s
        assert "rejected" in s
        assert "resumed=True" in s

    def test_summary_no_hash(self):
        r = PushResult(success=True, commit_hash=None, paused=True, resumed=True, duration_seconds=1.0)
        s = r.summary()
        assert "?" in s

    def test_steps_log_default_empty(self):
        r = PushResult()
        assert r.steps_log == []


# ---------------------------------------------------------------------------
# _find_writer_pid
# ---------------------------------------------------------------------------

class TestFindWriterPid:
    def test_returns_none_when_no_proc(self, tmp_path):
        # Point at a directory with no numeric entries
        with patch("iamai.safe_push.Path", return_value=tmp_path):
            assert _find_writer_pid("qwen") is None

    def test_finds_matching_process(self, tmp_path):
        # Create a fake /proc structure
        proc_dir = tmp_path / "proc"
        proc_dir.mkdir()
        pid_dir = proc_dir / "12345"
        pid_dir.mkdir()
        cmdline = pid_dir / "cmdline"
        cmdline.write_bytes(b"python\x00writer.py\x00qwen\x00")

        with patch("iamai.safe_push.Path", return_value=proc_dir):
            assert _find_writer_pid("qwen") == 12345

    def test_skips_non_matching_process(self, tmp_path):
        proc_dir = tmp_path / "proc"
        proc_dir.mkdir()
        pid_dir = proc_dir / "12345"
        pid_dir.mkdir()
        cmdline = pid_dir / "cmdline"
        cmdline.write_bytes(b"python\x00server.py\x00")

        with patch("iamai.safe_push.Path", return_value=proc_dir):
            assert _find_writer_pid("qwen") is None

    def test_handles_permission_error(self, tmp_path):
        proc_dir = tmp_path / "proc"
        proc_dir.mkdir()
        pid_dir = proc_dir / "12345"
        pid_dir.mkdir()
        cmdline = pid_dir / "cmdline"
        cmdline.write_bytes(b"python\x00writer\x00qwen\x00")
        cmdline.chmod(0o000)

        with patch("iamai.safe_push.Path", return_value=proc_dir):
            # Should not raise, just skip
            result = _find_writer_pid("qwen")
            # Could be None or 12345 depending on OS permission enforcement
            assert result is None or result == 12345

    def test_skips_non_numeric_entries(self, tmp_path):
        proc_dir = tmp_path / "proc"
        proc_dir.mkdir()
        (proc_dir / "self").mkdir()
        (proc_dir / "meminfo").mkdir()

        with patch("iamai.safe_push.Path", return_value=proc_dir):
            assert _find_writer_pid("qwen") is None


# ---------------------------------------------------------------------------
# _git helper
# ---------------------------------------------------------------------------

class TestGitHelper:
    def test_runs_git_command(self):
        with patch("iamai.safe_push.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "status"], returncode=0, stdout="clean", stderr=""
            )
            result = _git(["status"], cwd="/tmp")
            mock_run.assert_called_once_with(
                ["git", "status"],
                cwd="/tmp",
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0

    def test_passes_args_through(self):
        with patch("iamai.safe_push.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            _git(["pull", "--rebase", "origin", "main"], cwd="/repo")
            args = mock_run.call_args[0][0]
            assert args == ["git", "pull", "--rebase", "origin", "main"]


# ---------------------------------------------------------------------------
# _has_uncommitted
# ---------------------------------------------------------------------------

class TestHasUncommitted:
    def test_clean_tree(self):
        with patch("iamai.safe_push._git") as mock_git:
            mock_git.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            assert _has_uncommitted("/repo") is False

    def test_dirty_tree(self):
        with patch("iamai.safe_push._git") as mock_git:
            mock_git.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=" M file.txt\n", stderr=""
            )
            assert _has_uncommitted("/repo") is True

    def test_whitespace_only_is_clean(self):
        with patch("iamai.safe_push._git") as mock_git:
            mock_git.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="   \n  \n", stderr=""
            )
            assert _has_uncommitted("/repo") is False


# ---------------------------------------------------------------------------
# _pause_writer / _resume_writer
# ---------------------------------------------------------------------------

class TestPauseResume:
    def test_pause_sends_sigstop(self):
        with patch("iamai.safe_push.os.kill") as mock_kill:
            _pause_writer(1234)
            mock_kill.assert_called_once_with(1234, signal.SIGSTOP)

    def test_resume_sends_sigcont(self):
        with patch("iamai.safe_push.os.kill") as mock_kill:
            _resume_writer(1234)
            mock_kill.assert_called_once_with(1234, signal.SIGCONT)

    def test_resume_ignores_dead_process(self):
        with patch("iamai.safe_push.os.kill", side_effect=ProcessLookupError):
            # Should not raise
            _resume_writer(1234)

    def test_resume_ignores_permission_error(self):
        with patch("iamai.safe_push.os.kill", side_effect=PermissionError):
            _resume_writer(1234)


# ---------------------------------------------------------------------------
# safe_push — happy path
# ---------------------------------------------------------------------------

class TestSafePushHappyPath:
    def test_full_sequence_no_changes(self):
        """No uncommitted changes, no commit message → stash skipped."""
        with patch("iamai.safe_push._find_writer_pid", return_value=100), \
             patch("iamai.safe_push._pause_writer") as pause, \
             patch("iamai.safe_push._resume_writer") as resume, \
             patch("iamai.safe_push._has_uncommitted", return_value=False), \
             patch("iamai.safe_push._git") as git:

            git.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="abc1234\n", stderr=""
            )

            result = safe_push("/repo", writer_id="qwen")

            assert result.success is True
            assert result.paused is True
            assert result.resumed is True
            assert result.stashed is False
            assert result.pulled is True
            assert result.pushed is True
            assert result.commit_hash == "abc1234"

            # SIGSTOP before any git, SIGCONT in finally
            pause.assert_called_once_with(100)
            resume.assert_called_once_with(100)

    def test_full_sequence_with_stash(self):
        """Uncommitted changes present → stash and pop."""
        call_count = {"n": 0}

        def has_uncommitted_side_effect(cwd):
            call_count["n"] += 1
            # First call (before stash): dirty
            # Second call (after pop, no commit_message): not called again
            return call_count["n"] == 1

        with patch("iamai.safe_push._find_writer_pid", return_value=200), \
             patch("iamai.safe_push._pause_writer"), \
             patch("iamai.safe_push._resume_writer"), \
             patch("iamai.safe_push._has_uncommitted", side_effect=has_uncommitted_side_effect), \
             patch("iamai.safe_push._git") as git:

            git.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="def5678\n", stderr=""
            )

            result = safe_push("/repo", writer_id="qwen")

            assert result.success is True
            assert result.stashed is True
            assert result.stash_popped is True

    def test_full_sequence_with_commit(self):
        """Uncommitted changes + commit message → commit before push."""
        with patch("iamai.safe_push._find_writer_pid", return_value=300), \
             patch("iamai.safe_push._pause_writer"), \
             patch("iamai.safe_push._resume_writer"), \
             patch("iamai.safe_push._has_uncommitted", return_value=True), \
             patch("iamai.safe_push._git") as git:

            git.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="aabbcc\n", stderr=""
            )

            result = safe_push(
                "/repo", writer_id="qwen", commit_message="test commit"
            )

            assert result.success is True
            assert result.committed is True
            assert result.commit_hash == "aabbcc"

            # Verify commit was called with the right message
            commit_calls = [
                c for c in git.call_args_list
                if c[0][0][0] == "commit"
            ]
            assert len(commit_calls) == 1
            assert "test commit" in commit_calls[0][0][0]


# ---------------------------------------------------------------------------
# safe_push — failure modes
# ---------------------------------------------------------------------------

class TestSafePushFailures:
    def test_no_writer_found(self):
        with patch("iamai.safe_push._find_writer_pid", return_value=None):
            result = safe_push("/repo", writer_id="qwen")
            assert result.success is False
            assert result.failed_step == "find_writer"

    def test_stash_failure(self):
        with patch("iamai.safe_push._find_writer_pid", return_value=100), \
             patch("iamai.safe_push._pause_writer"), \
             patch("iamai.safe_push._resume_writer") as resume, \
             patch("iamai.safe_push._has_uncommitted", return_value=True), \
             patch("iamai.safe_push._git") as git:

            def git_side_effect(args, cwd):
                if args[0] == "stash":
                    return subprocess.CompletedProcess(
                        args=[], returncode=1, stdout="", stderr="stash failed"
                    )
                return subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                )

            git.side_effect = git_side_effect

            result = safe_push("/repo", writer_id="qwen")
            assert result.success is False
            assert result.failed_step == "stash"
            # Writer must still be resumed
            resume.assert_called_once()

    def test_pull_failure(self):
        with patch("iamai.safe_push._find_writer_pid", return_value=100), \
             patch("iamai.safe_push._pause_writer"), \
             patch("iamai.safe_push._resume_writer") as resume, \
             patch("iamai.safe_push._has_uncommitted", return_value=False), \
             patch("iamai.safe_push._git") as git:

            def git_side_effect(args, cwd):
                if args[0] == "pull":
                    return subprocess.CompletedProcess(
                        args=[], returncode=1, stdout="", stderr="CONFLICT"
                    )
                return subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                )

            git.side_effect = git_side_effect

            result = safe_push("/repo", writer_id="qwen")
            assert result.success is False
            assert result.failed_step == "pull_rebase"
            resume.assert_called_once()

    def test_push_failure(self):
        with patch("iamai.safe_push._find_writer_pid", return_value=100), \
             patch("iamai.safe_push._pause_writer"), \
             patch("iamai.safe_push._resume_writer") as resume, \
             patch("iamai.safe_push._has_uncommitted", return_value=False), \
             patch("iamai.safe_push._git") as git:

            def git_side_effect(args, cwd):
                if args[0] == "push":
                    return subprocess.CompletedProcess(
                        args=[], returncode=1, stdout="",
                        stderr="rejected non-fast-forward"
                    )
                return subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="abc\n", stderr=""
                )

            git.side_effect = git_side_effect

            result = safe_push("/repo", writer_id="qwen")
            assert result.success is False
            assert result.failed_step == "push"
            assert "non-fast-forward" in result.error
            resume.assert_called_once()

    def test_unexpected_exception_during_pause_no_resume(self):
        """If _pause_writer itself throws, writer was never frozen,
        so SIGCONT is not needed (and must not be sent)."""
        with patch("iamai.safe_push._find_writer_pid", return_value=100), \
             patch("iamai.safe_push._pause_writer", side_effect=RuntimeError("boom")), \
             patch("iamai.safe_push._resume_writer") as resume:

            result = safe_push("/repo", writer_id="qwen")
            assert result.success is False
            assert result.failed_step == "unexpected"
            assert "boom" in result.error
            # Writer was never paused, so resume must NOT fire
            resume.assert_not_called()

    def test_unexpected_exception_after_pause_resumes_writer(self):
        """If something fails AFTER pause, SIGCONT must fire."""
        with patch("iamai.safe_push._find_writer_pid", return_value=100), \
             patch("iamai.safe_push._pause_writer"), \
             patch("iamai.safe_push._has_uncommitted", side_effect=RuntimeError("late boom")), \
             patch("iamai.safe_push._resume_writer") as resume:

            result = safe_push("/repo", writer_id="qwen")
            assert result.success is False
            assert result.failed_step == "unexpected"
            assert "late boom" in result.error
            resume.assert_called_once()

    def test_stash_pop_failure(self):
        with patch("iamai.safe_push._find_writer_pid", return_value=100), \
             patch("iamai.safe_push._pause_writer"), \
             patch("iamai.safe_push._resume_writer") as resume, \
             patch("iamai.safe_push._has_uncommitted", return_value=True), \
             patch("iamai.safe_push._git") as git:

            call_log = []

            def git_side_effect(args, cwd):
                cmd = " ".join(args)
                call_log.append(cmd)
                if args == ["stash", "pop"]:
                    return subprocess.CompletedProcess(
                        args=[], returncode=1, stdout="", stderr="merge conflict"
                    )
                return subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                )

            git.side_effect = git_side_effect

            result = safe_push("/repo", writer_id="qwen")
            assert result.success is False
            assert result.failed_step == "stash_pop"
            resume.assert_called_once()

    def test_commit_failure(self):
        with patch("iamai.safe_push._find_writer_pid", return_value=100), \
             patch("iamai.safe_push._pause_writer"), \
             patch("iamai.safe_push._resume_writer") as resume, \
             patch("iamai.safe_push._has_uncommitted", return_value=True), \
             patch("iamai.safe_push._git") as git:

            def git_side_effect(args, cwd):
                if args[0] == "commit":
                    return subprocess.CompletedProcess(
                        args=[], returncode=1, stdout="", stderr="nothing to commit"
                    )
                return subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                )

            git.side_effect = git_side_effect

            result = safe_push(
                "/repo", writer_id="qwen", commit_message="test"
            )
            assert result.success is False
            assert result.failed_step == "commit"
            resume.assert_called_once()


# ---------------------------------------------------------------------------
# safe_push — explicit writer_pid
# ---------------------------------------------------------------------------

class TestSafePushExplicitPid:
    def test_uses_provided_pid(self):
        with patch("iamai.safe_push._find_writer_pid") as find, \
             patch("iamai.safe_push._pause_writer") as pause, \
             patch("iamai.safe_push._resume_writer"), \
             patch("iamai.safe_push._has_uncommitted", return_value=False), \
             patch("iamai.safe_push._git") as git:

            git.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="aaa\n", stderr=""
            )

            result = safe_push("/repo", writer_id="qwen", writer_pid=9999)

            assert result.writer_pid == 9999
            find.assert_not_called()
            pause.assert_called_once_with(9999)


# ---------------------------------------------------------------------------
# safe_push — duration tracking
# ---------------------------------------------------------------------------

class TestSafePushDuration:
    def test_duration_is_recorded(self):
        with patch("iamai.safe_push._find_writer_pid", return_value=100), \
             patch("iamai.safe_push._pause_writer"), \
             patch("iamai.safe_push._resume_writer"), \
             patch("iamai.safe_push._has_uncommitted", return_value=False), \
             patch("iamai.safe_push._git") as git:

            git.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="abc\n", stderr=""
            )

            result = safe_push("/repo", writer_id="qwen")
            assert result.duration_seconds >= 0

    def test_duration_on_failure(self):
        with patch("iamai.safe_push._find_writer_pid", return_value=None):
            result = safe_push("/repo", writer_id="qwen")
            assert result.duration_seconds >= 0


# ---------------------------------------------------------------------------
# safe_push — steps_log
# ---------------------------------------------------------------------------

class TestSafePushStepsLog:
    def test_steps_logged_on_success(self):
        with patch("iamai.safe_push._find_writer_pid", return_value=100), \
             patch("iamai.safe_push._pause_writer"), \
             patch("iamai.safe_push._resume_writer"), \
             patch("iamai.safe_push._has_uncommitted", return_value=False), \
             patch("iamai.safe_push._git") as git:

            git.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="abc\n", stderr=""
            )

            result = safe_push("/repo", writer_id="qwen")
            assert len(result.steps_log) >= 4  # stop, skip-stash, pull, push, cont
            assert any("SIGSTOP" in s for s in result.steps_log)
            assert any("SIGCONT" in s for s in result.steps_log)

    def test_steps_logged_on_no_writer(self):
        with patch("iamai.safe_push._find_writer_pid", return_value=None):
            result = safe_push("/repo", writer_id="qwen")
            assert len(result.steps_log) == 1
            assert "no writer found" in result.steps_log[0]
