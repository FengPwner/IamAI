"""Tests for iamai.caretaker — the automated reclamation recovery sequence.

The caretaker runs a fixed sequence: kill stale pids, stash, rebase, pop,
restart, verify. Each step is tested independently so that a failure in one
does not mask a failure in another. The full intervention() is tested last,
using the same mocking strategy.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.caretaker import (
    InterventionResult,
    _kill_stale_pids,
    _has_unstaged,
    _stash,
    _rebase,
    _stash_pop,
    _verify_pids,
    intervene,
)


# --- InterventionResult dataclass -------------------------------------------


def test_result_success_when_all_steps_pass():
    r = InterventionResult(
        killed_stale=True,
        stashed=True,
        rebased=True,
        stash_popped=True,
        restarted=True,
        verified=True,
        writer_pid=123,
        batch_pid=124,
    )
    assert r.success is True
    assert r.failed_step is None
    assert "123" in r.summary()


def test_result_failed_step_returns_first_failure():
    r = InterventionResult(
        killed_stale=True,
        stashed=True,
        rebased=False,
    )
    assert r.success is False
    assert r.failed_step == "rebased"


def test_result_summary_shows_completed_steps():
    r = InterventionResult(
        killed_stale=True,
        stashed=True,
        rebased=False,
        error="rebase conflict in data/strokes.jsonl",
    )
    s = r.summary()
    assert "rebased" in s
    assert "killed stale" in s
    assert "conflict" in s


def test_result_failed_step_none_when_all_pass():
    r = InterventionResult(
        killed_stale=True,
        stashed=True,
        rebased=True,
        stash_popped=True,
        restarted=True,
        verified=True,
    )
    assert r.failed_step is None


# --- _kill_stale_pids -------------------------------------------------------


def test_kill_stale_pids_no_pidfiles(tmp_path):
    """No pidfiles = nothing to kill, returns True."""
    assert _kill_stale_pids(tmp_path, "test") is True


def test_kill_stale_pids_dead_pidfile(tmp_path):
    """Pidfile referencing a dead process: remove the file, return True."""
    pidfile = tmp_path / "iamai-writer-test.pid"
    pidfile.write_text("999999")  # almost certainly not a live pid
    assert _kill_stale_pids(tmp_path, "test") is True
    assert not pidfile.exists()


# --- _has_unstaged ----------------------------------------------------------


def test_has_unstaged_clean_repo(tmp_path):
    """A fresh git repo with no changes has no unstaged work."""
    import subprocess
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(tmp_path), capture_output=True)
    assert _has_unstaged(tmp_path) is False


def test_has_unstaged_dirty_repo(tmp_path):
    """A repo with a modified file has unstaged work."""
    import subprocess
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(tmp_path), capture_output=True)
    f = tmp_path / "a.txt"
    f.write_text("hello")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
    f.write_text("changed")
    assert _has_unstaged(tmp_path) is True


# --- _stash -----------------------------------------------------------------


def test_stash_clean_repo(tmp_path):
    """Stashing a clean repo succeeds (nothing to save)."""
    import subprocess
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(tmp_path), capture_output=True)
    f = tmp_path / "a.txt"
    f.write_text("hello")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
    ok, _ = _stash(tmp_path)
    assert ok is True  # "No local changes to save" is still exit 0


# --- _rebase ----------------------------------------------------------------


def test_rebase_no_upstream_commits(tmp_path):
    """Rebase on a branch that has no new commits succeeds (noop)."""
    import subprocess
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(tmp_path), capture_output=True)
    f = tmp_path / "a.txt"
    f.write_text("hello")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
    # No remote configured, so rebase against HEAD should fail gracefully
    ok, msg = _rebase(tmp_path, "origin", "main")
    # This will fail because there is no origin remote — that is the expected behavior
    assert ok is False
    assert any(w in msg.lower() for w in ("failed", "error", "abort", "fatal", "invalid"))


# --- _stash_pop -------------------------------------------------------------


def test_stash_pop_no_stash(tmp_path):
    """Popping when there is no stash succeeds (nothing to pop)."""
    import subprocess
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    ok, msg = _stash_pop(tmp_path)
    assert ok is True
    assert "no stash" in msg.lower() or "not ours" in msg.lower() or msg == ""


# --- _verify_pids -----------------------------------------------------------


def test_verify_pids_no_files(tmp_path):
    """No pidfiles = not verified."""
    ok, w, b = _verify_pids(tmp_path, "test")
    assert ok is False
    assert w is None
    assert b is None


def test_verify_pids_dead_pid(tmp_path):
    """Pidfile with a dead pid = not verified."""
    pidfile = tmp_path / "iamai-writer-test.pid"
    pidfile.write_text("999999")
    ok, w, b = _verify_pids(tmp_path, "test")
    assert ok is False


def test_verify_pids_live_pid(tmp_path):
    """Pidfile with our own pid = verified (we are alive)."""
    my_pid = os.getpid()
    (tmp_path / "iamai-writer-test.pid").write_text(str(my_pid))
    (tmp_path / "iamai-batch-test.pid").write_text(str(my_pid))
    ok, w, b = _verify_pids(tmp_path, "test")
    assert ok is True
    assert w == my_pid
    assert b == my_pid


# --- intervene (integration with mocks) -------------------------------------


@patch("iamai.caretaker._restart")
@patch("iamai.caretaker._stash_pop")
@patch("iamai.caretaker._rebase")
@patch("iamai.caretaker._stash")
@patch("iamai.caretaker._has_unstaged")
@patch("iamai.caretaker._kill_stale_pids")
@patch("iamai.caretaker._verify_pids")
@patch("iamai.caretaker._run")
def test_intervene_full_success(
    mock_run, mock_verify, mock_kill, mock_has_unstaged,
    mock_stash, mock_rebase, mock_stash_pop, mock_restart,
):
    mock_kill.return_value = True
    mock_has_unstaged.return_value = True
    mock_stash.return_value = (True, "Saved working directory")
    mock_run.return_value = (0, "")  # fetch
    mock_rebase.return_value = (True, "Successfully rebased")
    mock_stash_pop.return_value = (True, "Dropped stash")
    mock_restart.return_value = (True, "writer pid 100: up\nbatch pid 101: up")
    mock_verify.return_value = (True, 100, 101)

    result = intervene(
        repo=Path("/tmp/fake"),
        writer_id="test",
        pid_dir=Path("/tmp/fake/pids"),
    )
    assert result.success is True
    assert result.writer_pid == 100
    assert result.batch_pid == 101


@patch("iamai.caretaker._rebase")
@patch("iamai.caretaker._stash")
@patch("iamai.caretaker._has_unstaged")
@patch("iamai.caretaker._kill_stale_pids")
@patch("iamai.caretaker._run")
def test_intervene_stops_at_rebase_failure(
    mock_run, mock_kill, mock_has_unstaged, mock_stash, mock_rebase,
):
    mock_kill.return_value = True
    mock_has_unstaged.return_value = True
    mock_stash.return_value = (True, "Saved")
    mock_run.return_value = (0, "")  # fetch
    mock_rebase.return_value = (False, "CONFLICT in data/strokes.jsonl")

    result = intervene(
        repo=Path("/tmp/fake"),
        writer_id="test",
        pid_dir=Path("/tmp/fake/pids"),
    )
    assert result.success is False
    assert result.failed_step == "rebased"
    assert "conflict" in result.error.lower()
    assert result.stashed is True  # stash succeeded before rebase failed


@patch("iamai.caretaker._run")
@patch("iamai.caretaker._kill_stale_pids")
def test_intervene_stops_at_fetch_failure(mock_kill, mock_run):
    mock_kill.return_value = True
    # _has_unstaged calls _run internally; we need to handle that
    def run_side_effect(cmd, **kwargs):
        if "fetch" in cmd:
            return (1, "fatal: 'origin' does not appear to be a git repository")
        if "status" in cmd:
            return (0, "")  # clean tree
        return (0, "")

    mock_run.side_effect = run_side_effect

    result = intervene(
        repo=Path("/tmp/fake"),
        writer_id="test",
        pid_dir=Path("/tmp/fake/pids"),
    )
    assert result.success is False
    assert "fetch" in result.error.lower()
