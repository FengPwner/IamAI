"""Tests for tools/post_restart_push_fix.sh — post-restart push divergence resolver.

Uses temporary bare repos as remotes and clones to exercise the three
paths: in-sync, local-ahead, and diverged.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "post_restart_push_fix.sh"


def _run(cwd: Path, *cmd: str, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = {**os.environ, **(env or {})}
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, env=merged)


def _init_bare(tmp_path: Path, name: str = "remote.git") -> Path:
    bare = tmp_path / name
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(bare), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True, capture_output=True,
    )
    return bare


def _clone(bare: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", str(bare), str(dest)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(dest), "config", "user.email", "test@test.local"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(dest), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    return dest


def _commit(path: Path, filename: str, content: str, msg: str) -> None:
    target = path / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", msg, "--allow-empty"],
        check=True, capture_output=True,
    )


def _run_tool(local: Path, remote_name: str = "origin", branch: str = "main") -> subprocess.CompletedProcess:
    """Run the fix script targeting the test repo."""
    return _run(local, "bash", str(TOOL), "--repo", str(local), remote_name, branch)


@pytest.fixture
def repo_env(tmp_path: Path):
    """Create a bare remote + local clone, return (local, remote)."""
    bare = _init_bare(tmp_path)
    local = _clone(bare, tmp_path / "local")
    # Need an initial commit so main exists
    _commit(local, "README.md", "# test\n", "initial commit")
    _run(local, "git", "push", "origin", "main")
    return local, bare


def test_in_sync(repo_env):
    """When local and remote are in sync, script exits 0 with nothing to do."""
    local, remote = repo_env
    result = _run_tool(local)
    assert result.returncode == 0
    assert "in sync" in result.stdout or "nothing to do" in result.stdout


def test_local_ahead(repo_env):
    """When local has commits remote doesn't, script pushes them."""
    local, remote = repo_env
    _commit(local, "new.md", "local content\n", "local commit")
    result = _run_tool(local)
    assert result.returncode == 0
    assert "push succeeded" in result.stdout or "local ahead" in result.stdout


def test_diverged(repo_env):
    """When both sides diverge, script merges and pushes."""
    local, remote = repo_env

    # Create a clone to simulate a second writer
    other = _clone(remote, local.parent / "other")
    _run(other, "git", "pull", "origin", "main")

    # Local writer commits
    _commit(local, "local_file.md", "from local\n", "local stroke")
    # Other writer commits and pushes
    _commit(other, "other_file.md", "from other\n", "other stroke")
    _run(other, "git", "push", "origin", "main")

    # Now local is diverged: has local_file.md but not other_file.md
    result = _run_tool(local)
    assert result.returncode == 0
    assert "diverged" in result.stdout or "merge" in result.stdout
    assert "push succeeded" in result.stdout

    # Verify both files exist after merge
    assert (local / "local_file.md").exists()
    assert (local / "other_file.md").exists()


def test_diverged_with_uncommitted(repo_env):
    """When diverged with uncommitted changes, script stashes and restores."""
    local, remote = repo_env

    other = _clone(remote, local.parent / "other")
    _run(other, "git", "pull", "origin", "main")

    _commit(local, "local_file.md", "from local\n", "local stroke")
    _commit(other, "other_file.md", "from other\n", "other stroke")
    _run(other, "git", "push", "origin", "main")

    # Create uncommitted changes
    (local / "dirty.md").write_text("uncommitted\n")

    result = _run_tool(local)
    assert result.returncode == 0
    assert "push succeeded" in result.stdout

    # Uncommitted file should still be there
    assert (local / "dirty.md").exists()
    assert (local / "dirty.md").read_text() == "uncommitted\n"


def test_remote_ahead_fast_forward(repo_env):
    """When only remote is ahead, script fast-forwards."""
    local, remote = repo_env

    other = _clone(remote, local.parent / "other")
    _run(other, "git", "pull", "origin", "main")
    _commit(other, "other_only.md", "from other\n", "other stroke")
    _run(other, "git", "push", "origin", "main")

    result = _run_tool(local)
    assert result.returncode == 0
    assert "fast-forwarded" in result.stdout
    assert (local / "other_only.md").exists()
