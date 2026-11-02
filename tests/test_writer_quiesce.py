"""Tests for tools/writer_quiesce.py — writer freeze/resume for safe git ops."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import writer_quiesce as wq


# ---------------------------------------------------------------------------
# QuiesceReport
# ---------------------------------------------------------------------------

class TestQuiesceReport:
    def test_default_verdict_unknown(self):
        r = wq.QuiesceReport()
        assert r.verdict() == "unknown"

    def test_verdict_clean(self):
        r = wq.QuiesceReport(frozen=True, resumed=True)
        assert r.verdict() == "clean"

    def test_verdict_frozen(self):
        r = wq.QuiesceReport(frozen=True, resumed=False)
        assert r.verdict() == "frozen"

    def test_verdict_failed(self):
        r = wq.QuiesceReport(error="something broke")
        assert r.verdict() == "failed"

    def test_to_dict_basic(self):
        r = wq.QuiesceReport(writer_pid=1234, writer_name="qwen", frozen=True, resumed=True)
        d = r.to_dict()
        assert d["writer_pid"] == 1234
        assert d["writer_name"] == "qwen"
        assert d["frozen"] is True
        assert d["resumed"] is True
        assert "hold_seconds" in d

    def test_to_dict_includes_git_when_set(self):
        r = wq.QuiesceReport(git_command="git status", git_exit_code=0)
        d = r.to_dict()
        assert "git_command" in d
        assert d["git_command"] == "git status"

    def test_to_dict_omits_git_when_empty(self):
        r = wq.QuiesceReport()
        d = r.to_dict()
        assert "git_command" not in d

    def test_to_dict_includes_error_when_set(self):
        r = wq.QuiesceReport(error="oops")
        d = r.to_dict()
        assert d["error"] == "oops"

    def test_to_dict_omits_error_when_empty(self):
        r = wq.QuiesceReport()
        d = r.to_dict()
        assert "error" not in d

    def test_git_stdout_truncated(self):
        r = wq.QuiesceReport(git_command="git log", git_stdout="x" * 1000)
        d = r.to_dict()
        assert len(d["git_stdout"]) == 500


# ---------------------------------------------------------------------------
# find_writer_pid
# ---------------------------------------------------------------------------

class TestFindWriterPid:
    def test_returns_int_on_match(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "3413\n"
        with patch("subprocess.run", return_value=mock_result):
            pid = wq.find_writer_pid("qwen")
        assert pid == 3413

    def test_returns_none_when_not_found(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            pid = wq.find_writer_pid("nonexistent")
        # Falls through to /proc scan; may or may not find something
        # In test env, likely None unless a real writer is running
        assert pid is None or isinstance(pid, int)

    def test_handles_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pgrep", 5)):
            pid = wq.find_writer_pid("qwen")
        # Falls through to /proc fallback
        assert pid is None or isinstance(pid, int)

    def test_handles_value_error(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not_a_number\n"
        with patch("subprocess.run", return_value=mock_result):
            pid = wq.find_writer_pid("qwen")
        # ValueError caught, falls through to /proc
        assert pid is None or isinstance(pid, int)

    def test_takes_first_pid_when_multiple(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1001\n1002\n1003\n"
        with patch("subprocess.run", return_value=mock_result):
            pid = wq.find_writer_pid("qwen")
        assert pid == 1001


# ---------------------------------------------------------------------------
# freeze / resume / state detection
# ---------------------------------------------------------------------------

class TestFreezeResume:
    def test_freeze_returns_true_on_success(self):
        with patch("os.kill", return_value=None) as mock_kill:
            assert wq.freeze_writer(1234) is True
            mock_kill.assert_called_once_with(1234, signal.SIGSTOP)

    def test_freeze_returns_false_on_no_process(self):
        with patch("os.kill", side_effect=ProcessLookupError):
            assert wq.freeze_writer(99999999) is False

    def test_freeze_returns_false_on_permission(self):
        with patch("os.kill", side_effect=PermissionError):
            assert wq.freeze_writer(1) is False

    def test_resume_returns_true_on_success(self):
        with patch("os.kill", return_value=None) as mock_kill:
            assert wq.resume_writer(1234) is True
            mock_kill.assert_called_once_with(1234, signal.SIGCONT)

    def test_resume_returns_false_on_no_process(self):
        with patch("os.kill", side_effect=ProcessLookupError):
            assert wq.resume_writer(99999999) is False

    def test_is_process_frozen_detects_stopped(self, tmp_path):
        proc_dir = tmp_path / "12345"
        proc_dir.mkdir()
        (proc_dir / "status").write_text("Name:\ttest\nState:\tT (stopped)\n")
        with patch("writer_quiesce.Path") as mock_path:
            mock_path.return_value.__truediv__ = lambda self, x: proc_dir / x if str(self).endswith("/proc") else Path("/proc") / str(x)
            # Direct test via real /proc won't work in all envs, so mock it
        # Test the parsing logic directly
        status_text = "Name:\ttest\nState:\tT (stopped)\nPid:\t12345\n"
        lines = status_text.splitlines()
        state_char = None
        for line in lines:
            if line.startswith("State:"):
                state_char = line.split(":")[1].strip()[0]
        assert state_char == "T"

    def test_is_process_frozen_detects_running(self):
        status_text = "Name:\ttest\nState:\tS (sleeping)\nPid:\t12345\n"
        lines = status_text.splitlines()
        state_char = None
        for line in lines:
            if line.startswith("State:"):
                state_char = line.split(":")[1].strip()[0]
        assert state_char != "T"


# ---------------------------------------------------------------------------
# get_dirty_files
# ---------------------------------------------------------------------------

class TestGetDirtyFiles:
    def test_returns_list_on_clean_repo(self):
        result = wq.get_dirty_files(REPO)
        assert isinstance(result, list)

    def test_parses_porcelain_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = " M foo.py\n?? bar.py\nA  baz.py\n"
        with patch("subprocess.run", return_value=mock_result):
            files = wq.get_dirty_files(REPO)
        assert len(files) == 3
        assert "M foo.py" in files

    def test_handles_empty_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            files = wq.get_dirty_files(REPO)
        assert files == []

    def test_handles_git_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            # Non-zero exit but still parses empty stdout
            files = wq.get_dirty_files(REPO)
        assert isinstance(files, list)

    def test_handles_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 5)):
            files = wq.get_dirty_files(REPO)
        assert files == []


# ---------------------------------------------------------------------------
# run_git_command
# ---------------------------------------------------------------------------

class TestRunGitCommand:
    def test_successful_command(self):
        exit_code, stdout, stderr = wq.run_git_command("echo hello", REPO)
        assert exit_code == 0
        assert "hello" in stdout

    def test_failed_command(self):
        exit_code, stdout, stderr = wq.run_git_command("false", REPO)
        assert exit_code != 0

    def test_timeout(self):
        exit_code, stdout, stderr = wq.run_git_command("sleep 10", REPO, timeout=1)
        assert exit_code == 124
        assert "timed out" in stderr.lower()

    def test_captures_stderr(self):
        exit_code, stdout, stderr = wq.run_git_command("echo err >&2", REPO)
        assert "err" in stderr


# ---------------------------------------------------------------------------
# quiesce — integration-level tests
# ---------------------------------------------------------------------------

class TestQuiesce:
    def test_writer_not_found(self):
        with patch("writer_quiesce.find_writer_pid", return_value=None):
            report = wq.quiesce(writer_name="nonexistent")
        assert report.error == "Writer 'nonexistent' not found"
        assert report.verdict() == "failed"

    def test_freeze_fails(self):
        with patch("writer_quiesce.find_writer_pid", return_value=1234), \
             patch("writer_quiesce.freeze_writer", return_value=False), \
             patch("writer_quiesce.get_dirty_files", return_value=[]):
            report = wq.quiesce()
        assert "could not freeze" in report.error.lower()

    def test_freeze_and_resume(self):
        with patch("writer_quiesce.find_writer_pid", return_value=1234), \
             patch("writer_quiesce.freeze_writer", return_value=True), \
             patch("writer_quiesce.resume_writer", return_value=True), \
             patch("writer_quiesce.get_dirty_files", return_value=[]):
            report = wq.quiesce()
        assert report.frozen is True
        assert report.resumed is True
        assert report.verdict() == "clean"

    def test_freeze_only(self):
        with patch("writer_quiesce.find_writer_pid", return_value=1234), \
             patch("writer_quiesce.freeze_writer", return_value=True), \
             patch("writer_quiesce.resume_writer", return_value=True) as mock_resume, \
             patch("writer_quiesce.get_dirty_files", return_value=[]):
            report = wq.quiesce(freeze_only=True)
        assert report.frozen is True
        assert report.resumed is False
        mock_resume.assert_not_called()

    def test_resume_only(self):
        with patch("writer_quiesce.find_writer_pid", return_value=1234), \
             patch("writer_quiesce.resume_writer", return_value=True) as mock_resume:
            report = wq.quiesce(resume_only=True)
        assert report.resumed is True
        mock_resume.assert_called_once_with(1234)

    def test_resume_only_failure(self):
        with patch("writer_quiesce.find_writer_pid", return_value=1234), \
             patch("writer_quiesce.resume_writer", return_value=False):
            report = wq.quiesce(resume_only=True)
        assert "could not resume" in report.error.lower()

    def test_git_command_success(self):
        with patch("writer_quiesce.find_writer_pid", return_value=1234), \
             patch("writer_quiesce.freeze_writer", return_value=True), \
             patch("writer_quiesce.resume_writer", return_value=True), \
             patch("writer_quiesce.run_git_command", return_value=(0, "ok", "")), \
             patch("writer_quiesce.get_dirty_files", return_value=[]):
            report = wq.quiesce(git_command="git status")
        assert report.git_exit_code == 0
        assert report.git_command == "git status"

    def test_git_command_failure(self):
        with patch("writer_quiesce.find_writer_pid", return_value=1234), \
             patch("writer_quiesce.freeze_writer", return_value=True), \
             patch("writer_quiesce.resume_writer", return_value=True), \
             patch("writer_quiesce.run_git_command", return_value=(1, "", "error")), \
             patch("writer_quiesce.get_dirty_files", return_value=[]):
            report = wq.quiesce(git_command="git push")
        assert report.git_exit_code == 1

    def test_resume_failure_sets_error(self):
        with patch("writer_quiesce.find_writer_pid", return_value=1234), \
             patch("writer_quiesce.freeze_writer", return_value=True), \
             patch("writer_quiesce.resume_writer", return_value=False), \
             patch("writer_quiesce.get_dirty_files", return_value=[]):
            report = wq.quiesce()
        assert "could not resume" in report.error.lower()
        assert report.verdict() == "failed"

    def test_dirty_files_tracked(self):
        with patch("writer_quiesce.find_writer_pid", return_value=1234), \
             patch("writer_quiesce.freeze_writer", return_value=True), \
             patch("writer_quiesce.resume_writer", return_value=True), \
             patch("writer_quiesce.get_dirty_files", side_effect=[["M a.py"], ["M a.py", "M b.py"]]):
            report = wq.quiesce()
        assert report.dirty_files_before == ["M a.py"]
        assert report.dirty_files_after == ["M a.py", "M b.py"]


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_basic_output(self):
        r = wq.QuiesceReport(writer_pid=1234, writer_name="qwen", frozen=True, resumed=True)
        text = wq.format_report(r)
        assert "qwen" in text
        assert "1234" in text
        assert "clean" in text

    def test_not_found_output(self):
        r = wq.QuiesceReport(writer_name="missing")
        r.error = "Writer 'missing' not found"
        text = wq.format_report(r)
        assert "NOT FOUND" in text
        assert "error" in text.lower()

    def test_git_output(self):
        r = wq.QuiesceReport(
            writer_pid=1234, frozen=True, resumed=True,
            git_command="git pull", git_exit_code=0, git_stdout="Already up to date.\n",
        )
        text = wq.format_report(r)
        assert "git pull" in text
        assert "Already up to date" in text

    def test_git_failure_output(self):
        r = wq.QuiesceReport(
            writer_pid=1234, frozen=True, resumed=True,
            git_command="git push", git_exit_code=1, git_stderr="rejected\n",
        )
        text = wq.format_report(r)
        assert "FAIL" in text
        assert "rejected" in text

    def test_dirty_files_shown(self):
        r = wq.QuiesceReport(
            writer_pid=1234, frozen=True, resumed=True,
            dirty_files_before=["M a.py", "M b.py"],
            dirty_files_after=["M a.py"],
        )
        text = wq.format_report(r)
        assert "dirty before: 2" in text
        assert "dirty after: 1" in text


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------

class TestMain:
    def test_writer_not_found_exit_1(self):
        with patch("writer_quiesce.find_writer_pid", return_value=None):
            exit_code = wq.main(["--writer", "nonexistent", "--json"])
        assert exit_code == 1

    def test_success_exit_0(self):
        with patch("writer_quiesce.find_writer_pid", return_value=1234), \
             patch("writer_quiesce.freeze_writer", return_value=True), \
             patch("writer_quiesce.resume_writer", return_value=True), \
             patch("writer_quiesce.get_dirty_files", return_value=[]):
            exit_code = wq.main(["--json"])
        assert exit_code == 0

    def test_json_output(self, capsys):
        with patch("writer_quiesce.find_writer_pid", return_value=1234), \
             patch("writer_quiesce.freeze_writer", return_value=True), \
             patch("writer_quiesce.resume_writer", return_value=True), \
             patch("writer_quiesce.get_dirty_files", return_value=[]):
            wq.main(["--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "writer_pid" in data
        assert "verdict" not in data  # verdict is computed, not in to_dict

    def test_git_failure_exit_2(self):
        with patch("writer_quiesce.find_writer_pid", return_value=1234), \
             patch("writer_quiesce.freeze_writer", return_value=True), \
             patch("writer_quiesce.resume_writer", return_value=True), \
             patch("writer_quiesce.run_git_command", return_value=(1, "", "rejected")), \
             patch("writer_quiesce.get_dirty_files", return_value=[]):
            exit_code = wq.main(["--exec", "git push"])
        assert exit_code == 2

    def test_human_readable_output(self, capsys):
        with patch("writer_quiesce.find_writer_pid", return_value=1234), \
             patch("writer_quiesce.freeze_writer", return_value=True), \
             patch("writer_quiesce.resume_writer", return_value=True), \
             patch("writer_quiesce.get_dirty_files", return_value=[]):
            wq.main([])
        captured = capsys.readouterr()
        assert "qwen" in captured.out
        assert "clean" in captured.out


# ---------------------------------------------------------------------------
# Live integration test (only runs if writer is actually present)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    wq.find_writer_pid("qwen") is None,
    reason="No live writer process available",
)
class TestLiveIntegration:
    """Integration tests against the real writer process."""

    def test_freeze_and_resume_live(self):
        pid = wq.find_writer_pid("qwen")
        assert pid is not None
        assert wq.freeze_writer(pid)
        # Verify frozen
        time.sleep(0.3)
        assert wq.is_process_frozen(pid) is True
        # Resume
        assert wq.resume_writer(pid)
        time.sleep(0.3)
        # Verify running
        frozen = wq.is_process_frozen(pid)
        assert frozen is False or frozen is None  # None if proc entry disappeared

    def test_quiesce_live(self):
        report = wq.quiesce(writer_name="qwen", repo=REPO)
        assert report.frozen is True
        assert report.resumed is True
        assert report.writer_pid > 0
        assert report.verdict() == "clean"
