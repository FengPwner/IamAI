"""Tests for iamai.rebase_lock — the pause-settle-rebase-resume cycle.

The module exists because push-race recovery kept failing: the writer
process wrote new strokes during ``git pull --rebase``, creating unstaged
changes that aborted the rebase. The fix was to SIGSTOP the writer first.

These tests cover:
  - SIGSTOP/SIGCONT semantics (pause_writer, resume_writer)
  - settle() detecting a clean tree vs. a continuously dirty one
  - safe_rebase() happy path and failure modes
  - the invariant that the writer is *always* resumed, even on failure
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iamai.rebase_lock import (
    RebaseResult,
    _dirty,
    _settle,
    pause_writer,
    resume_writer,
    safe_rebase,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """A minimal git repo with one committed file."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, check=True, capture_output=True,
    )
    (repo / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo, check=True, capture_output=True,
    )
    return repo


@pytest.fixture
def sleep_process() -> int:
    """Spawn a ``sleep 60`` and return its PID; kill it after the test."""
    proc = subprocess.Popen(
        ["sleep", "60"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    yield proc.pid
    try:
        os.kill(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# pause_writer / resume_writer
# ---------------------------------------------------------------------------


class TestPauseResume:
    def test_pause_sends_sigstop(self, sleep_process: int):
        assert pause_writer(sleep_process) is True
        # Process should be stopped (state T)
        time.sleep(0.1)
        with open(f"/proc/{sleep_process}/status") as f:
            status = f.read()
        assert "T (stopped)" in status or "T" in status.split("State:")[1].split("\n")[0]

    def test_resume_sends_sigcont(self, sleep_process: int):
        pause_writer(sleep_process)
        time.sleep(0.1)
        assert resume_writer(sleep_process) is True
        time.sleep(0.1)
        with open(f"/proc/{sleep_process}/status") as f:
            status = f.read()
        assert "T (stopped)" not in status

    def test_pause_nonexistent_pid(self):
        assert pause_writer(99999999) is False

    def test_resume_nonexistent_pid(self):
        assert resume_writer(99999999) is False


# ---------------------------------------------------------------------------
# _dirty
# ---------------------------------------------------------------------------


class TestDirty:
    def test_clean_repo(self, temp_repo: Path):
        assert _dirty(temp_repo) is False

    def test_dirty_repo(self, temp_repo: Path):
        (temp_repo / "new.txt").write_text("uncommitted\n")
        assert _dirty(temp_repo) is True

    def test_modified_file(self, temp_repo: Path):
        (temp_repo / "README.md").write_text("# modified\n")
        assert _dirty(temp_repo) is True


# ---------------------------------------------------------------------------
# _settle
# ---------------------------------------------------------------------------


class TestSettle:
    def test_clean_tree_settles_fast(self, temp_repo: Path):
        assert _settle(temp_repo, 0.5, poll=0.1) is True

    def test_dirty_tree_never_settles(self, temp_repo: Path):
        (temp_repo / "dirty.txt").write_text("content\n")
        # Use a short max_wait so the test doesn't hang
        assert _settle(temp_repo, 0.5, poll=0.1, max_wait=1.5) is False


# ---------------------------------------------------------------------------
# RebaseResult
# ---------------------------------------------------------------------------


class TestRebaseResult:
    def test_success_shape(self):
        r = RebaseResult(ok=True, rebased=True, duration_s=1.23)
        assert r.ok
        assert r.rebased
        assert r.error is None

    def test_failure_shape(self):
        r = RebaseResult(ok=False, error="rebase conflict", duration_s=0.5)
        assert not r.ok
        assert "conflict" in r.error


# ---------------------------------------------------------------------------
# safe_rebase (mocked git)
# ---------------------------------------------------------------------------


class TestSafeRebase:
    def test_no_writer_pid_skips_pause(self, temp_repo: Path):
        """Without a writer_pid, safe_rebase doesn't try to pause anything."""
        with (
            patch("iamai.rebase_lock._settle", return_value=True),
            patch("iamai.rebase_lock._dirty", return_value=False),
            patch("iamai.rebase_lock._run") as mock_run,
        ):
            mock_run.return_value = (0, "Successfully rebased and updated refs/heads/main.")
            result = safe_rebase(temp_repo, writer_pid=None, settle=0.1)
        assert result.ok
        assert result.rebased

    def test_writer_always_resumed_on_failure(self, temp_repo: Path):
        """Even when rebase fails, the writer must be resumed."""
        with (
            patch("iamai.rebase_lock.pause_writer", return_value=True) as mock_pause,
            patch("iamai.rebase_lock.resume_writer", return_value=True) as mock_resume,
            patch("iamai.rebase_lock._settle", return_value=True),
            patch("iamai.rebase_lock._dirty", return_value=False),
            patch("iamai.rebase_lock._run") as mock_run,
        ):
            # First call: pull --rebase fails
            mock_run.return_value = (1, "error: merge conflict in data/strokes.jsonl")
            result = safe_rebase(temp_repo, writer_pid=12345, settle=0.1)

        assert not result.ok
        mock_pause.assert_called_once_with(12345)
        mock_resume.assert_called_once_with(12345)
        # rebase --abort should have been called
        calls = [c for c in mock_run.call_args_list]
        abort_calls = [c for c in calls if "--abort" in str(c)]
        assert len(abort_calls) >= 1

    def test_settle_failure_returns_error(self, temp_repo: Path):
        with (
            patch("iamai.rebase_lock.pause_writer", return_value=True),
            patch("iamai.rebase_lock.resume_writer", return_value=True),
            patch("iamai.rebase_lock._settle", return_value=False),
        ):
            result = safe_rebase(temp_repo, writer_pid=12345, settle=0.1)
        assert not result.ok
        assert "settle" in result.error

    def test_pause_failure_returns_error(self, temp_repo: Path):
        with patch("iamai.rebase_lock.pause_writer", return_value=False):
            result = safe_rebase(temp_repo, writer_pid=12345, settle=0.1)
        assert not result.ok
        assert "pause" in result.error

    def test_happy_path_full_cycle(self, temp_repo: Path):
        """Full cycle: pause → settle → stash → rebase → pop → resume."""
        with (
            patch("iamai.rebase_lock.pause_writer", return_value=True) as mock_pause,
            patch("iamai.rebase_lock.resume_writer", return_value=True) as mock_resume,
            patch("iamai.rebase_lock._settle", return_value=True),
            patch("iamai.rebase_lock._dirty") as mock_dirty,
            patch("iamai.rebase_lock._run") as mock_run,
        ):
            # dirty=True on first call (stash needed), False on second (after stash)
            mock_dirty.side_effect = [True, False]
            mock_run.side_effect = [
                (0, "Saved working directory"),          # stash
                (0, "Successfully rebased and updated refs/heads/main."),  # pull --rebase
                (0, "Dropped refs/stash@{0}"),           # stash pop
            ]
            result = safe_rebase(temp_repo, writer_pid=12345, settle=0.1)

        assert result.ok
        assert result.rebased
        assert result.stash_applied
        mock_pause.assert_called_once()
        mock_resume.assert_called_once()

    def test_duration_is_measured(self, temp_repo: Path):
        with (
            patch("iamai.rebase_lock._settle", return_value=True),
            patch("iamai.rebase_lock._dirty", return_value=False),
            patch("iamai.rebase_lock._run") as mock_run,
        ):
            mock_run.return_value = (0, "Successfully rebased and updated refs/heads/main.")
            result = safe_rebase(temp_repo, writer_pid=None, settle=0.1)
        assert result.duration_s >= 0
