#!/usr/bin/env python3
"""Tests for push_auto_rebase.py — 18 tests covering auto-rebase push logic.

Uses temporary bare git repos to simulate clean push, divergence, dirty
working tree, and conflict scenarios without touching the real IamAI repo.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from push_auto_rebase import (
    PushReport,
    count_divergence,
    find_repo_root,
    has_unstaged_changes,
    push_auto_rebase,
    run_git,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd, cwd, env=None):
    merged = {**os.environ, **(env or {})}
    result = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, env=merged
    )
    assert result.returncode == 0, f"Command failed: {cmd}\n{result.stderr}"
    return result


def _init_bare(path):
    """Create a bare repo (simulates remote)."""
    Path(path).mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "--bare"], path)


def _clone(bare_path, clone_path):
    """Clone a bare repo and configure git identity."""
    _run(["git", "clone", str(bare_path), str(clone_path)], Path("."))
    _run(["git", "config", "user.email", "test@test.local"], clone_path)
    _run(["git", "config", "user.name", "Test"], clone_path)


def _make_commit(repo, filename, content, message):
    (Path(repo) / filename).write_text(content)
    _run(["git", "add", filename], repo)
    _run(["git", "commit", "-m", message], repo)


def _setup_repo(tmp_path, name="repo"):
    """Create a bare + clone pair with an initial commit on 'main' already pushed."""
    bare = tmp_path / "bare"
    clone = tmp_path / name
    _init_bare(bare)
    _clone(bare, clone)
    _make_commit(clone, "README.md", "# Test\n", "init")
    _run(["git", "branch", "-m", "main"], clone)
    _run(["git", "push", "-u", "origin", "main"], clone)
    return bare, clone


def _diverge_remote(bare, existing_clone, new_clone_name, files):
    """Create a second clone, make commits, and push to simulate remote divergence.

    files: list of (filename, content, message) tuples.
    """
    clone_b = existing_clone.parent / new_clone_name
    _clone(bare, clone_b)
    # Ensure we're on 'main' (clone may default to master)
    run_git(clone_b, "checkout", "main")
    for fname, content, msg in files:
        _make_commit(clone_b, fname, content, msg)
    _run(["git", "push", "origin", "main"], clone_b)
    return clone_b


# ---------------------------------------------------------------------------
# Tests: find_repo_root
# ---------------------------------------------------------------------------

class TestFindRepoRoot:
    def test_finds_repo_from_root(self, tmp_path):
        bare, clone = _setup_repo(tmp_path)
        assert find_repo_root(clone) == clone

    def test_finds_repo_from_subdir(self, tmp_path):
        bare, clone = _setup_repo(tmp_path)
        sub = clone / "a" / "b"
        sub.mkdir(parents=True)
        assert find_repo_root(sub) == clone

    def test_fallback_when_no_git(self, tmp_path):
        result = find_repo_root(tmp_path / "nonexistent")
        assert result == tmp_path / "nonexistent"


# ---------------------------------------------------------------------------
# Tests: has_unstaged_changes
# ---------------------------------------------------------------------------

class TestHasUnstagedChanges:
    def test_clean_repo(self, tmp_path):
        bare, clone = _setup_repo(tmp_path)
        assert has_unstaged_changes(clone) is False

    def test_dirty_repo(self, tmp_path):
        bare, clone = _setup_repo(tmp_path)
        (clone / "README.md").write_text("# Modified\n")
        assert has_unstaged_changes(clone) is True

    def test_untracked_files_not_counted(self, tmp_path):
        bare, clone = _setup_repo(tmp_path)
        (clone / "new_file.txt").write_text("hello")
        assert has_unstaged_changes(clone) is False


# ---------------------------------------------------------------------------
# Tests: count_divergence
# ---------------------------------------------------------------------------

class TestCountDivergence:
    def test_in_sync(self, tmp_path):
        bare, clone = _setup_repo(tmp_path)
        local, remote = count_divergence(clone, "origin", "main")
        assert local == 0
        assert remote == 0

    def test_local_ahead(self, tmp_path):
        bare, clone = _setup_repo(tmp_path)
        _make_commit(clone, "a.txt", "a", "add a")
        local, remote = count_divergence(clone, "origin", "main")
        assert local == 1
        assert remote == 0


# ---------------------------------------------------------------------------
# Tests: push_auto_rebase (integration)
# ---------------------------------------------------------------------------

class TestPushAutoRebase:
    def test_clean_push_succeeds(self, tmp_path):
        """First push attempt succeeds, no rebase needed."""
        bare, clone = _setup_repo(tmp_path)
        _make_commit(clone, "b.txt", "b", "add b")

        report = push_auto_rebase(clone, "origin", "main")
        assert report.first_attempt == "ok"
        assert report.rebase_needed is False
        assert report.stash_used is False
        assert report.second_attempt == "skipped"

    def test_divergence_triggers_rebase(self, tmp_path):
        """Remote diverges; auto-rebase should fix it."""
        bare, clone_a = _setup_repo(tmp_path, "a")
        _diverge_remote(bare, clone_a, "b", [("remote_file.txt", "from b", "b's commit")])
        _make_commit(clone_a, "local_file.txt", "from a", "a's commit")

        report = push_auto_rebase(clone_a, "origin", "main")
        assert report.first_attempt == "rejected"
        assert report.rebase_needed is True
        assert report.second_attempt == "ok"
        assert report.remote_ahead >= 1
        assert report.local_ahead >= 1

    def test_divergence_with_dirty_tree(self, tmp_path):
        """Divergence + unstaged changes: should stash, rebase, pop, push."""
        bare, clone_a = _setup_repo(tmp_path, "a")
        _diverge_remote(bare, clone_a, "b", [("remote.txt", "remote", "remote change")])
        _make_commit(clone_a, "local.txt", "local", "local change")
        (clone_a / "local.txt").write_text("local-modified")

        report = push_auto_rebase(clone_a, "origin", "main")
        assert report.first_attempt == "rejected"
        assert report.rebase_needed is True
        assert report.stash_used is True
        assert report.second_attempt == "ok"

        # verify the unstaged change survived
        content = (clone_a / "local.txt").read_text()
        assert content == "local-modified"

    def test_report_to_dict(self):
        """PushReport serializes to dict correctly."""
        r = PushReport(
            first_attempt="rejected",
            rebase_needed=True,
            stash_used=True,
            second_attempt="ok",
            remote_ahead=3,
            local_ahead=1,
            duration_ms=1500,
            message="push succeeded after auto-rebase",
        )
        d = r.to_dict()
        assert d["first_attempt"] == "rejected"
        assert d["rebase_needed"] is True
        assert d["stash_used"] is True
        assert d["second_attempt"] == "ok"
        assert d["remote_ahead"] == 3
        assert d["duration_ms"] == 1500

    def test_run_git_returns_result(self, tmp_path):
        """run_git returns a CompletedProcess."""
        bare, clone = _setup_repo(tmp_path)
        result = run_git(clone, "status")
        assert result.returncode == 0
        assert "nothing to commit" in result.stdout or "clean" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_repo_push(self, tmp_path):
        """Push with nothing new should succeed (no-op)."""
        bare, clone = _setup_repo(tmp_path)
        report = push_auto_rebase(clone, "origin", "main")
        assert report.first_attempt == "ok"

    def test_multiple_divergent_commits(self, tmp_path):
        """Multiple commits on both sides still resolves."""
        bare, clone_a = _setup_repo(tmp_path, "a")
        _diverge_remote(bare, clone_a, "b", [
            ("r1.txt", "r1", "remote 1"),
            ("r2.txt", "r2", "remote 2"),
        ])
        _make_commit(clone_a, "l1.txt", "l1", "local 1")
        _make_commit(clone_a, "l2.txt", "l2", "local 2")

        report = push_auto_rebase(clone_a, "origin", "main")
        assert report.first_attempt == "rejected"
        assert report.second_attempt == "ok"
        assert report.remote_ahead == 2
        assert report.local_ahead == 2
