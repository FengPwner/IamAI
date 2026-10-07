"""Tests for iamai.pre_push_sync -- atomic sync-before-push protocol."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iamai.pre_push_sync import (
    Phase,
    SyncResult,
    _ahead_count,
    _dirty_files,
    _has_divergence,
    sync_and_push,
)


# ---------------------------------------------------------------------------
# Helpers: create tiny git repos in tmp_path for integration-style tests
# ---------------------------------------------------------------------------


def _init_repo(p: Path, *, bare: bool = False) -> Path:
    """Initialise a git repo at *p* with one commit."""
    p.mkdir(parents=True, exist_ok=True)
    if bare:
        subprocess.run(
            ["git", "init", "--bare"],
            cwd=p, capture_output=True, check=True,
        )
        return p
    subprocess.run(["git", "init"], cwd=p, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=p, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tester"],
        cwd=p, capture_output=True,
    )
    # Rename default branch to main
    subprocess.run(
        ["git", "checkout", "-b", "main"],
        cwd=p, capture_output=True,
    )
    # Initial commit so HEAD exists
    (p / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=p, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=p, capture_output=True,
    )
    return p


def _make_bare_origin(tmp_path: Path, name: str = "origin") -> Path:
    """Create a bare origin repo initialised with one commit.

    Uses a temporary working repo to create the initial commit, then
    clones it bare. This avoids the 'refusing to update checked out
    branch' error when tests push to the origin.
    """
    work = tmp_path / f"{name}_work"
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=work, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=work, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tester"],
        cwd=work, capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-b", "main"],
        cwd=work, capture_output=True,
    )
    (work / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=work, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=work, capture_output=True,
    )
    bare = tmp_path / name
    subprocess.run(
        ["git", "clone", "--bare", str(work), str(bare)],
        capture_output=True, check=True,
    )
    return bare


def _clone(src: Path, dst: Path) -> Path:
    """Clone *src* into *dst*."""
    subprocess.run(
        ["git", "clone", str(src), str(dst)],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=dst, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tester"],
        cwd=dst, capture_output=True,
    )
    return dst


# ---------------------------------------------------------------------------
# _has_divergence
# ---------------------------------------------------------------------------


def test_no_divergence_after_clone(tmp_path: Path):
    origin = _make_bare_origin(tmp_path)
    clone = _clone(origin, tmp_path / "clone")
    assert _has_divergence(clone) is False


def test_divergence_after_local_commit(tmp_path: Path):
    origin = _make_bare_origin(tmp_path)
    clone = _clone(origin, tmp_path / "clone")
    # Add a local commit
    (clone / "new.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=clone, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "local change"],
        cwd=clone, capture_output=True,
    )
    assert _has_divergence(clone) is True


def test_no_divergence_after_push(tmp_path: Path):
    origin = _make_bare_origin(tmp_path)
    clone = _clone(origin, tmp_path / "clone")
    (clone / "new.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=clone, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "local change"],
        cwd=clone, capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=clone, capture_output=True,
    )
    assert _has_divergence(clone) is False


# ---------------------------------------------------------------------------
# _dirty_files
# ---------------------------------------------------------------------------


def test_clean_repo_no_dirty_files(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    assert _dirty_files(repo) == []


def test_dirty_after_modification(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("changed\n")
    dirty = _dirty_files(repo)
    assert len(dirty) >= 1


def test_dirty_after_new_untracked(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "new_file.txt").write_text("untracked\n")
    dirty = _dirty_files(repo)
    assert any("new_file.txt" in d for d in dirty)


# ---------------------------------------------------------------------------
# _ahead_count
# ---------------------------------------------------------------------------


def test_ahead_count_zero_initially(tmp_path: Path):
    origin = _make_bare_origin(tmp_path)
    clone = _clone(origin, tmp_path / "clone")
    assert _ahead_count(clone) == 0


def test_ahead_count_after_local_commit(tmp_path: Path):
    origin = _make_bare_origin(tmp_path)
    clone = _clone(origin, tmp_path / "clone")
    (clone / "x.txt").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=clone, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "ahead"],
        cwd=clone, capture_output=True,
    )
    assert _ahead_count(clone) == 1


# ---------------------------------------------------------------------------
# sync_and_push: happy path (no divergence)
# ---------------------------------------------------------------------------


def test_sync_no_divergence_pushes_cleanly(tmp_path: Path):
    origin = _make_bare_origin(tmp_path)
    clone = _clone(origin, tmp_path / "clone")
    result = sync_and_push(clone, message="test sync")
    assert result.ok is True
    assert result.divergence is False
    assert result.pushed is True


def test_sync_commits_pending_files(tmp_path: Path):
    origin = _make_bare_origin(tmp_path)
    clone = _clone(origin, tmp_path / "clone")
    (clone / "pending.txt").write_text("pending content\n")
    result = sync_and_push(clone, message="commit pending")
    assert result.ok is True
    assert result.pushed is True
    # Verify the file was committed
    dirty = _dirty_files(clone)
    assert dirty == []


# ---------------------------------------------------------------------------
# sync_and_push: with divergence
# ---------------------------------------------------------------------------


def test_sync_with_divergence_rebases_and_pushes(tmp_path: Path):
    origin = _make_bare_origin(tmp_path)
    clone_a = _clone(origin, tmp_path / "clone_a")
    clone_b = _clone(origin, tmp_path / "clone_b")

    # clone_a pushes a commit
    (clone_a / "a.txt").write_text("from a\n")
    subprocess.run(["git", "add", "."], cwd=clone_a, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "from a"],
        cwd=clone_a, capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=clone_a, capture_output=True,
    )

    # clone_b makes a local commit (now diverged)
    (clone_b / "b.txt").write_text("from b\n")
    subprocess.run(["git", "add", "."], cwd=clone_b, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "from b"],
        cwd=clone_b, capture_output=True,
    )

    # sync_and_push should detect divergence, rebase, and push
    result = sync_and_push(clone_b, message="sync with divergence")
    assert result.divergence is True
    assert result.rebased is True
    assert result.ok is True
    assert result.pushed is True


def test_sync_with_divergence_and_dirty_tree(tmp_path: Path):
    origin = _make_bare_origin(tmp_path)
    clone_a = _clone(origin, tmp_path / "clone_a")
    clone_b = _clone(origin, tmp_path / "clone_b")

    # clone_a pushes
    (clone_a / "a.txt").write_text("from a\n")
    subprocess.run(["git", "add", "."], cwd=clone_a, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "from a"],
        cwd=clone_a, capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=clone_a, capture_output=True,
    )

    # clone_b has both committed and uncommitted changes
    (clone_b / "b.txt").write_text("from b\n")
    subprocess.run(["git", "add", "."], cwd=clone_b, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "from b"],
        cwd=clone_b, capture_output=True,
    )
    (clone_b / "dirty.txt").write_text("uncommitted\n")

    result = sync_and_push(clone_b, message="sync dirty + diverged")
    assert result.divergence is True
    assert result.stashed is True
    assert result.ok is True


# ---------------------------------------------------------------------------
# sync_and_push: error handling
# ---------------------------------------------------------------------------


def test_sync_nonexistent_path():
    result = sync_and_push("/nonexistent/path/to/repo")
    assert result.ok is False
    assert result.phase == Phase.PROBE
    assert result.detail == "not a git repository"


# ---------------------------------------------------------------------------
# SyncResult
# ---------------------------------------------------------------------------


def test_sync_result_as_dict():
    r = SyncResult(
        ok=True, phase=Phase.DONE, divergence=False,
        stashed=False, rebased=False, pushed=True, detail="",
    )
    d = r.as_dict()
    assert d["ok"] is True
    assert d["phase"] == "done"
    assert d["pushed"] is True
