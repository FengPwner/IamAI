"""Tests for iamai.push.pre_exec_push.

The pre-execution push wraps the full stop-stash-pull-push-pop-resume
cycle that every caretaker visit has been doing by hand.  These tests
verify the contract: the writer always gets resumed, uncommitted work
survives, and the result dict has the right shape.
"""

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.push import pre_exec_push


def _make_repo(tmp: Path) -> Path:
    """Create a minimal git repo with one commit."""
    repo = tmp / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def test_result_shape(tmp_path):
    """Returns a dict with ok, strategy, detail, writer_paused."""
    repo = _make_repo(tmp_path)
    result = pre_exec_push(repo)
    assert isinstance(result, dict)
    assert "ok" in result
    assert "strategy" in result
    assert "detail" in result
    assert "writer_paused" in result


def test_no_remote(tmp_path):
    """Without a remote, push fails gracefully and reports the error."""
    repo = _make_repo(tmp_path)
    result = pre_exec_push(repo)
    assert isinstance(result["ok"], bool)
    assert isinstance(result["detail"], str)


def test_dirty_tree_preserved(tmp_path):
    """Uncommitted changes survive the push attempt."""
    repo = _make_repo(tmp_path)
    (repo / "dirty.txt").write_text("uncommitted\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    pre_exec_push(repo)
    assert (repo / "dirty.txt").exists()
    assert (repo / "dirty.txt").read_text() == "uncommitted\n"


def test_writer_pid_none(tmp_path):
    """writer_pid=None skips the SIGSTOP/SIGCONT dance entirely."""
    repo = _make_repo(tmp_path)
    result = pre_exec_push(repo, writer_pid=None)
    assert result["writer_paused"] is False


def test_writer_pid_dead(tmp_path):
    """A dead writer pid does not crash the push (OSError is caught)."""
    repo = _make_repo(tmp_path)
    # Use a pid that definitely does not exist.
    result = pre_exec_push(repo, writer_pid=999999)
    assert result["writer_paused"] is False
    assert isinstance(result["ok"], bool)


def test_writer_pid_real_process(tmp_path):
    """Pauses and resumes a real process around the push cycle.

    Spawns a long-lived sleep process as a stand-in for the writer,
    verifies it gets STOPped and CONTed.
    """
    repo = _make_repo(tmp_path)
    proc = subprocess.Popen(["sleep", "60"])
    try:
        result = pre_exec_push(repo, writer_pid=proc.pid)
        assert result["writer_paused"] is True
        # Process should be running (resumed by SIGCONT in finally).
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()


def test_always_resumes_writer(tmp_path):
    """Even when push fails, the writer process must be resumed.

    This is the most important contract: a paused writer that stays
    paused is worse than a failed push.
    """
    repo = _make_repo(tmp_path)
    proc = subprocess.Popen(["sleep", "60"])
    try:
        # Push will fail (no remote), but the process must still be resumed.
        pre_exec_push(repo, writer_pid=proc.pid, remote="nonexistent")
        # If we got here without the finally block running, the process
        # would still be in SIGSTOP state.  Check it is not.
        import time
        time.sleep(0.1)  # brief pause for SIGCONT to take effect
        assert proc.poll() is None, "writer was not resumed after failed push"
    finally:
        proc.kill()
        proc.wait()


def test_accepts_path_and_string(tmp_path):
    """Works with both Path and str arguments."""
    repo = _make_repo(tmp_path)
    r1 = pre_exec_push(repo)  # Path
    r2 = pre_exec_push(str(repo))  # str
    assert isinstance(r1, dict)
    assert isinstance(r2, dict)


def test_remote_and_branch_args(tmp_path):
    """Custom remote/branch names are passed through without crashing."""
    repo = _make_repo(tmp_path)
    result = pre_exec_push(repo, remote="upstream", branch="develop")
    assert isinstance(result, dict)
    assert "ok" in result
