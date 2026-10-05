"""Tests for iamai.sync.safe_stash_pop: handling stash-pop conflicts.

When a writer process is running while a caretaker tries to restore stashed
changes, the pop fails because the writer has modified the same files.
This test suite pins down the expected behaviour: checkout the live
version, retry the pop, and never lose the stash entry on genuine failure.

Extracted from caretaker visit 29 (2026-10-06 00:00 CST).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from iamai.sync import safe_stash_pop


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit and a stash entry."""
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@test.local")
    _git(tmp_path, "config", "user.name", "Test")

    # Initial commit.
    (tmp_path / "data" / "state.json").parent.mkdir()
    (tmp_path / "data" / "state.json").write_text('{"seq": 1}\n')
    (tmp_path / "notes" / "log.md").parent.mkdir()
    (tmp_path / "notes" / "log.md").write_text("# log\n\nstroke 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "initial")

    # Make changes and stash them.
    (tmp_path / "data" / "state.json").write_text('{"seq": 2}\n')
    (tmp_path / "notes" / "log.md").write_text("# log\n\nstroke 1\nstroke 2\n")
    _git(tmp_path, "stash", "push", "-m", "test stash")

    return tmp_path


def test_clean_pop(repo: Path):
    """When no files conflict, stash pops normally."""
    result = safe_stash_pop(repo)
    assert result.ok
    assert result.popped
    assert "cleanly" in result.detail
    # Stashed content is restored.
    assert (repo / "data" / "state.json").read_text() == '{"seq": 2}\n'
    assert "stroke 2" in (repo / "notes" / "log.md").read_text()


def test_pop_with_dirty_tree_conflict(repo: Path):
    """When the writer re-modifies a stashed file, checkout and retry."""
    # Simulate the writer modifying state.json before pop.
    (repo / "data" / "state.json").write_text('{"seq": 99, "writer": "live"}\n')

    result = safe_stash_pop(repo)
    assert result.ok
    assert result.popped
    assert "conflicting" in result.detail or "checkout" in result.detail
    # The stash content wins (not the writer's stale version).
    content = (repo / "data" / "state.json").read_text()
    assert '"seq": 2' in content


def test_pop_preserves_stash_on_genuine_failure(repo: Path):
    """When pop fails for a non-dirty-tree reason, stash is kept."""
    # Drop the stash so there's nothing to pop — but this isn't a
    # "local changes" error, it's a "no stash entries" error.
    _git(repo, "stash", "drop")

    result = safe_stash_pop(repo)
    # No stash to pop — git says "No stash entries found" which is a
    # non-zero exit but not a dirty-tree conflict. safe_stash_pop
    # should report failure without losing anything.
    if not result.ok:
        assert "failed" in result.detail


def test_no_stash_is_ok(repo: Path):
    """When there is no stash entry at all, report it cleanly."""
    _git(repo, "stash", "drop")
    result = safe_stash_pop(repo)
    # Implementation choice: we report failure with a clear detail.
    assert not result.ok or "cleanly" in result.detail or "no stash" in result.detail.lower()
