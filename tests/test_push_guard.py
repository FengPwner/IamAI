"""Tests for iamai.push_guard: pre-push divergence detection.

The push_guard module answers one question: will a plain ``git push`` succeed
right now, or does the remote have commits we haven't seen? These tests pin
down the answer for every topology the caretaker might encounter.

After the overnight push-race on 2026-10-05, the caretaker harness needed to
know *before* pushing whether a rebase was required. These tests ensure that
knowledge stays correct as the module evolves.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.push_guard import (
    divergence_info,
    local_head,
    merge_base,
    needs_rebase,
    remote_tip,
)


# --- helpers ---------------------------------------------------------------


def _run(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """Create a bare repo to act as the remote."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        capture_output=True, text=True, timeout=30,
    )
    return remote


@pytest.fixture
def local_repo(tmp_path: Path, bare_remote: Path) -> Path:
    """Clone the bare remote, make an initial commit, push it."""
    repo = tmp_path / "local"
    _run(tmp_path, "clone", str(bare_remote), str(repo))
    _run(repo, "config", "user.name", "test")
    _run(repo, "config", "user.email", "test@test.local")
    # Ensure the branch is named 'main' regardless of system default
    _run(repo, "checkout", "-b", "main")
    readme = repo / "README.md"
    readme.write_text("# test\n")
    _run(repo, "add", ".")
    _run(repo, "commit", "-m", "initial")
    _run(repo, "push", "-u", "origin", "main")
    return repo


# --- local_head / remote_tip -----------------------------------------------


def test_local_head_returns_sha(local_repo: Path):
    head = local_head(local_repo)
    assert head is not None
    assert len(head) == 40


def test_local_head_none_in_empty_repo(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(
        ["git", "init", str(empty)], capture_output=True, text=True, timeout=30,
    )
    assert local_head(empty) is None


def test_remote_tip_returns_sha(local_repo: Path):
    tip = remote_tip(local_repo)
    assert tip is not None
    assert len(tip) == 40


def test_remote_tip_none_when_no_tracking(tmp_path: Path):
    """A freshly init'd repo has no origin/main tracking ref."""
    repo = tmp_path / "isolated"
    repo.mkdir()
    subprocess.run(
        ["git", "init", str(repo)], capture_output=True, text=True, timeout=30,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"], cwd=repo, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=repo, capture_output=True,
    )
    (repo / "f").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "c"], cwd=repo, capture_output=True,
    )
    assert remote_tip(repo) is None


# --- needs_rebase: the core question ---------------------------------------


def test_no_rebase_when_in_sync(local_repo: Path):
    """Local and remote are at the same commit → push is safe."""
    assert needs_rebase(local_repo) is False


def test_no_rebase_when_local_ahead(local_repo: Path):
    """Local has commits remote doesn't have → push should succeed."""
    (local_repo / "a.txt").write_text("a")
    _run(local_repo, "add", ".")
    _run(local_repo, "commit", "-m", "local-only commit")
    assert needs_rebase(local_repo) is False


def test_rebase_needed_when_remote_ahead(local_repo: Path, bare_remote: Path):
    """Remote has commits local doesn't have → push will be rejected."""
    # Simulate another writer pushing to the bare remote
    other = local_repo.parent / "other-writer"
    _run(local_repo.parent, "clone", str(bare_remote), str(other))
    _run(other, "config", "user.name", "other")
    _run(other, "config", "user.email", "other@test.local")
    _run(other, "fetch", "origin")
    _run(other, "checkout", "-B", "main", "origin/main")
    (other / "other.txt").write_text("from another writer")
    _run(other, "add", ".")
    _run(other, "commit", "-m", "other writer's commit")
    _run(other, "push", "origin", "main")

    # Fetch in our local repo to update the tracking ref
    _run(local_repo, "fetch", "origin")

    # Now local's cached remote tip has moved ahead
    assert needs_rebase(local_repo) is True


def test_no_rebase_first_push(tmp_path: Path):
    """No tracking ref exists → first push, nothing to rebase onto."""
    repo = tmp_path / "fresh"
    repo.mkdir()
    subprocess.run(
        ["git", "init", str(repo)], capture_output=True, text=True, timeout=30,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"], cwd=repo, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=repo, capture_output=True,
    )
    (repo / "f").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "c"], cwd=repo, capture_output=True,
    )
    assert needs_rebase(repo) is False


def test_no_rebase_empty_repo(tmp_path: Path):
    """No commits at all → nothing to push, nothing to rebase."""
    empty = tmp_path / "void"
    empty.mkdir()
    subprocess.run(
        ["git", "init", str(empty)], capture_output=True, text=True, timeout=30,
    )
    assert needs_rebase(empty) is False


# --- divergence_info -------------------------------------------------------


def test_divergence_info_in_sync(local_repo: Path):
    info = divergence_info(local_repo)
    assert info["local"] is not None
    assert info["remote"] is not None
    assert info["local"] == info["remote"]
    assert info["local_ahead"] == 0
    assert info["remote_ahead"] == 0
    assert info["needs_rebase"] is False


def test_divergence_info_local_ahead(local_repo: Path):
    (local_repo / "b.txt").write_text("b")
    _run(local_repo, "add", ".")
    _run(local_repo, "commit", "-m", "another local commit")
    info = divergence_info(local_repo)
    assert info["local_ahead"] == 1
    assert info["remote_ahead"] == 0
    assert info["needs_rebase"] is False


def test_divergence_info_remote_ahead(local_repo: Path, bare_remote: Path):
    other = local_repo.parent / "divergent-writer"
    _run(local_repo.parent, "clone", str(bare_remote), str(other))
    _run(other, "config", "user.name", "other")
    _run(other, "config", "user.email", "other@test.local")
    _run(other, "fetch", "origin")
    _run(other, "checkout", "-B", "main", "origin/main")
    (other / "c.txt").write_text("c")
    _run(other, "add", ".")
    _run(other, "commit", "-m", "remote-only commit")
    _run(other, "push", "origin", "main")
    _run(local_repo, "fetch", "origin")

    info = divergence_info(local_repo)
    assert info["remote_ahead"] == 1
    assert info["local_ahead"] == 0
    assert info["needs_rebase"] is True


def test_divergence_info_both_diverged(local_repo: Path, bare_remote: Path):
    """Both sides have unique commits → needs rebase, both counts > 0."""
    # Local makes a commit
    (local_repo / "local.txt").write_text("local")
    _run(local_repo, "add", ".")
    _run(local_repo, "commit", "-m", "local divergence")

    # Remote gets a commit from another writer
    other = local_repo.parent / "div-writer"
    _run(local_repo.parent, "clone", str(bare_remote), str(other))
    _run(other, "config", "user.name", "other")
    _run(other, "config", "user.email", "other@test.local")
    _run(other, "fetch", "origin")
    _run(other, "checkout", "-B", "main", "origin/main")
    (other / "remote.txt").write_text("remote")
    _run(other, "add", ".")
    _run(other, "commit", "-m", "remote divergence")
    _run(other, "push", "origin", "main")

    _run(local_repo, "fetch", "origin")

    info = divergence_info(local_repo)
    assert info["local_ahead"] >= 1
    assert info["remote_ahead"] >= 1
    assert info["needs_rebase"] is True


# --- accepts string paths --------------------------------------------------


def test_accepts_string_path(local_repo: Path):
    assert needs_rebase(str(local_repo)) is False


def test_divergence_info_accepts_string(local_repo: Path):
    info = divergence_info(str(local_repo))
    assert info["local"] is not None
