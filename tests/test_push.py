"""Tests for iamai.push: safe push with automatic rebase recovery.

The push module refuses to force-push and instead fetch-rebases when rejected.
These tests cover the happy path, rebase recovery, merge fallback, and the
refusal to run destructive git commands.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.push import (
    _conflicted,
    _identity,
    _run,
    push_with_rebase,
    safe_push_cli,
    FORCE_FLAGS,
    STATE_PATH_RE,
)


# --- helpers ---------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        capture_output=True, text=True, timeout=30,
    )
    return remote


@pytest.fixture
def local_repo(tmp_path: Path, bare_remote: Path) -> Path:
    repo = tmp_path / "local"
    _git(tmp_path, "clone", str(bare_remote), str(repo))
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@test.local")
    _git(repo, "checkout", "-b", "main")
    readme = repo / "README.md"
    readme.write_text("# test\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "push", "-u", "origin", "main")
    return repo


# --- _run: force flag refusal ---------------------------------------------


@pytest.mark.parametrize("flag", FORCE_FLAGS)
def test_run_refuses_force_flags(tmp_path: Path, flag: str):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ValueError, match="refusing to run a destructive"):
        _run(repo, "push", flag, "origin", "main")


def test_run_allows_normal_commands(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", str(repo)],
        capture_output=True, text=True, timeout=30,
    )
    code, out = _run(repo, "status", "--short")
    assert code == 0


# --- _identity ------------------------------------------------------------


def test_identity_returns_author_from_head(local_repo: Path):
    ident = _identity(local_repo)
    assert ident is not None
    assert ident[0] == "test"
    assert ident[1] == "test@test.local"


def test_identity_returns_none_in_empty_repo(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(
        ["git", "init", str(empty)],
        capture_output=True, text=True, timeout=30,
    )
    ident = _identity(empty)
    assert ident is None


# --- _conflicted ----------------------------------------------------------


def test_conflicted_empty_when_no_conflicts(local_repo: Path):
    assert _conflicted(local_repo) == []


# --- STATE_PATH_RE --------------------------------------------------------


@pytest.mark.parametrize("path,expected", [
    ("data/writer_state.qwen.json", True),
    ("data/strokes.jsonl", False),
    ("data/writer_state.json", True),
    ("notes/history.md", False),
    ("data/subdir/state.json", False),
])
def test_state_path_regex(path: str, expected: bool):
    assert (STATE_PATH_RE.match(path) is not None) == expected


# --- push_with_rebase: happy path -----------------------------------------


def test_push_with_rebase_succeeds_first_try(local_repo: Path):
    # Make a local commit and push
    (local_repo / "file1.txt").write_text("hello\n")
    _git(local_repo, "add", ".")
    _git(local_repo, "commit", "-m", "add file1")

    result = push_with_rebase(local_repo)
    assert result["ok"] is True
    assert result["strategy"] == "push"
    # detail contains git's raw push output (e.g. "To ... HEAD -> main")
    assert result["detail"]


# --- push_with_rebase: rebase recovery ------------------------------------


def test_push_with_rebase_recovers_after_rejection(
    tmp_path: Path, bare_remote: Path
):
    """Two clones push divergent commits; second must rebase."""
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"

    _git(tmp_path, "clone", str(bare_remote), str(repo_a))
    _git(repo_a, "config", "user.name", "a")
    _git(repo_a, "config", "user.email", "a@test.local")
    _git(repo_a, "checkout", "-b", "main")
    (repo_a / "a.txt").write_text("from a\n")
    _git(repo_a, "add", ".")
    _git(repo_a, "commit", "-m", "a's commit")
    _git(repo_a, "push", "-u", "origin", "main")

    _git(tmp_path, "clone", str(bare_remote), str(repo_b))
    _git(repo_b, "config", "user.name", "b")
    _git(repo_b, "config", "user.email", "b@test.local")
    _git(repo_b, "checkout", "-b", "main")
    (repo_b / "b.txt").write_text("from b\n")
    _git(repo_b, "add", ".")
    _git(repo_b, "commit", "-m", "b's commit")

    result = push_with_rebase(repo_b)
    assert result["ok"] is True
    assert result["strategy"] == "rebase-then-push"
    assert result["attempts"] >= 1


def test_push_with_rebase_limited_attempts(
    tmp_path: Path, bare_remote: Path
):
    """When rebase can't resolve, attempts are bounded."""
    repo = tmp_path / "repo"
    _git(tmp_path, "clone", str(bare_remote), str(repo))
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@test.local")
    _git(repo, "checkout", "-b", "main")
    (repo / "f.txt").write_text("original\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "local")
    _git(repo, "push", "-u", "origin", "main")

    # Create a conflicting commit on remote via another clone
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(bare_remote), str(other))
    _git(other, "config", "user.name", "other")
    _git(other, "config", "user.email", "other@test.local")
    # Checkout the remote main branch (clone may not set it up correctly)
    _git(other, "fetch", "origin")
    _git(other, "checkout", "-B", "main", "origin/main")
    (other / "f.txt").write_text("conflicting\n")
    _git(other, "add", ".")
    _git(other, "commit", "-m", "conflict")
    _git(other, "push", "origin", "main")

    # Local also modifies the same file (conflict)
    (repo / "f.txt").write_text("also conflicting\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "local conflict")

    result = push_with_rebase(repo, attempts=2)
    # Should fail or use merge fallback
    assert result["strategy"] in ("blocked", "merge-then-push")
    assert result["attempts"] <= 2


# --- safe_push_cli --------------------------------------------------------


def test_safe_push_cli_success(local_repo: Path, capsys):
    (local_repo / "cli.txt").write_text("cli\n")
    _git(local_repo, "add", ".")
    _git(local_repo, "commit", "-m", "cli test")

    rc = safe_push_cli(local_repo)
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True


def test_safe_push_cli_not_a_repo(tmp_path: Path, capsys):
    not_repo = tmp_path / "not_a_repo"
    not_repo.mkdir()
    rc = safe_push_cli(not_repo)
    assert rc == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is False
    assert "not a git repo" in data["detail"]


def test_safe_push_cli_stashes_and_restores(local_repo: Path, capsys):
    """Uncommitted changes should be stashed before push and restored after."""
    (local_repo / "dirty.txt").write_text("uncommitted\n")
    (local_repo / "committed.txt").write_text("will commit\n")
    _git(local_repo, "add", "committed.txt")
    _git(local_repo, "commit", "-m", "add committed")

    rc = safe_push_cli(local_repo)
    assert rc == 0

    # Dirty file should still be there (stash was popped)
    assert (local_repo / "dirty.txt").exists()
    assert (local_repo / "dirty.txt").read_text() == "uncommitted\n"


# --- push_with_rebase: branch does not exist remotely yet -----------------


def test_push_with_rebase_new_branch(local_repo: Path):
    _git(local_repo, "checkout", "-b", "new-branch")
    (local_repo / "new.txt").write_text("new\n")
    _git(local_repo, "add", ".")
    _git(local_repo, "commit", "-m", "new branch commit")

    result = push_with_rebase(local_repo, branch="new-branch")
    # The first push fails because origin/new-branch doesn't exist,
    # then the retry succeeds
    assert result["ok"] is True
