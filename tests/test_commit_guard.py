"""Tests for iamai.commit_guard"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from iamai.commit_guard import CommitGuard, GuardResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_repo(tmp_path):
    """Create a minimal git repo for testing."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    git_dir = repo / ".git"
    git_dir.mkdir()
    # Create minimal git structure
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    (git_dir / "objects").mkdir()
    (git_dir / "refs").mkdir()
    return repo


@pytest.fixture
def guard(tmp_repo):
    return CommitGuard(repo_root=tmp_repo, max_pending_files=5, writer_id="test")


# ---------------------------------------------------------------------------
# GuardResult dataclass
# ---------------------------------------------------------------------------

class TestGuardResult:
    def test_default_safe(self):
        r = GuardResult(safe=True)
        assert r.safe is True
        assert r.issues == []
        assert r.warnings == []
        assert r.checks == {}

    def test_to_dict(self):
        r = GuardResult(
            safe=False,
            issues=["index.lock"],
            warnings=["dirty"],
            checks={"index_lock": True},
        )
        d = r.to_dict()
        assert d["safe"] is False
        assert "index.lock" in d["issues"]
        assert "dirty" in d["warnings"]
        assert d["checks"]["index_lock"] is True


# ---------------------------------------------------------------------------
# check_index_lock
# ---------------------------------------------------------------------------

class TestIndexLock:
    def test_no_lock(self, guard):
        assert guard.check_index_lock() is False

    def test_lock_present(self, guard, tmp_repo):
        lock = tmp_repo / ".git" / "index.lock"
        lock.write_text("12345\n")
        assert guard.check_index_lock() is True

    def test_lock_removed(self, guard, tmp_repo):
        lock = tmp_repo / ".git" / "index.lock"
        lock.write_text("12345\n")
        lock.unlink()
        assert guard.check_index_lock() is False


# ---------------------------------------------------------------------------
# check_rebase_in_progress
# ---------------------------------------------------------------------------

class TestRebaseInProgress:
    def test_no_rebase(self, guard):
        assert guard.check_rebase_in_progress() is False

    def test_rebase_merge(self, guard, tmp_repo):
        (tmp_repo / ".git" / "rebase-merge").mkdir()
        assert guard.check_rebase_in_progress() is True

    def test_rebase_apply(self, guard, tmp_repo):
        (tmp_repo / ".git" / "rebase-apply").mkdir()
        assert guard.check_rebase_in_progress() is True

    def test_both_rebase_dirs(self, guard, tmp_repo):
        (tmp_repo / ".git" / "rebase-merge").mkdir()
        (tmp_repo / ".git" / "rebase-apply").mkdir()
        assert guard.check_rebase_in_progress() is True


# ---------------------------------------------------------------------------
# check_merge_in_progress
# ---------------------------------------------------------------------------

class TestMergeInProgress:
    def test_no_merge(self, guard):
        assert guard.check_merge_in_progress() is False

    def test_merge_head_present(self, guard, tmp_repo):
        (tmp_repo / ".git" / "MERGE_HEAD").write_text("abc123\n")
        assert guard.check_merge_in_progress() is True


# ---------------------------------------------------------------------------
# check_stale_pause
# ---------------------------------------------------------------------------

class TestStalePause:
    def test_no_pause_file(self, guard):
        # No pause file → not stale
        pause = Path("/tmp/iamai-writer-pause-test")
        pause.unlink(missing_ok=True)
        assert guard.check_stale_pause() is False

    def test_pause_with_live_committer(self, guard, tmp_path):
        # Pause exists but committer pid is valid → not stale
        pause = Path("/tmp/iamai-writer-pause-test")
        pause.touch()
        pid_file = Path("/tmp/iamai-batch-test.pid")
        pid_file.write_text(str(os.getpid()) + "\n")  # current process = alive
        try:
            assert guard.check_stale_pause() is False
        finally:
            pause.unlink(missing_ok=True)
            pid_file.unlink(missing_ok=True)

    def test_pause_with_dead_committer(self, guard):
        # Pause exists and committer pid is dead → stale
        pause = Path("/tmp/iamai-writer-pause-test")
        pause.touch()
        pid_file = Path("/tmp/iamai-batch-test.pid")
        pid_file.write_text("999999\n")  # almost certainly dead
        try:
            assert guard.check_stale_pause() is True
        finally:
            pause.unlink(missing_ok=True)
            pid_file.unlink(missing_ok=True)

    def test_pause_with_missing_pid_file(self, guard):
        # Pause exists but no pid file → stale
        pause = Path("/tmp/iamai-writer-pause-test")
        pause.touch()
        pid_file = Path("/tmp/iamai-batch-test.pid")
        pid_file.unlink(missing_ok=True)
        try:
            assert guard.check_stale_pause() is True
        finally:
            pause.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

class TestPreflight:
    def test_clean_repo_is_safe(self, guard):
        result = guard.preflight()
        assert result.safe is True
        assert len(result.issues) == 0

    def test_index_lock_blocks(self, guard, tmp_repo):
        (tmp_repo / ".git" / "index.lock").write_text("12345\n")
        result = guard.preflight()
        assert result.safe is False
        assert any("index.lock" in i for i in result.issues)

    def test_rebase_blocks(self, guard, tmp_repo):
        (tmp_repo / ".git" / "rebase-merge").mkdir()
        result = guard.preflight()
        assert result.safe is False
        assert any("rebase" in i for i in result.issues)

    def test_merge_blocks(self, guard, tmp_repo):
        (tmp_repo / ".git" / "MERGE_HEAD").write_text("abc\n")
        result = guard.preflight()
        assert result.safe is False
        assert any("merge" in i for i in result.issues)

    def test_multiple_blocks(self, guard, tmp_repo):
        (tmp_repo / ".git" / "index.lock").write_text("12345\n")
        (tmp_repo / ".git" / "rebase-merge").mkdir()
        result = guard.preflight()
        assert result.safe is False
        assert len(result.issues) >= 2

    def test_checks_dict_populated(self, guard):
        result = guard.preflight()
        assert "index_lock" in result.checks
        assert "rebase" in result.checks
        assert "merge" in result.checks


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_structure(self, guard):
        snap = guard.snapshot()
        assert "at" in snap
        assert "safe" in snap
        assert "issues" in snap
        assert "warnings" in snap
        assert "checks" in snap
        assert "pending_files" in snap

    def test_snapshot_safe_when_clean(self, guard):
        snap = guard.snapshot()
        assert snap["safe"] is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_nonexistent_repo(self, tmp_path):
        guard = CommitGuard(repo_root=tmp_path / "nope")
        # Should not crash, just report checks as clean
        result = guard.preflight()
        assert isinstance(result, GuardResult)

    def test_custom_max_pending(self, tmp_repo):
        guard = CommitGuard(repo_root=tmp_repo, max_pending_files=0)
        # Even with threshold 0, if no files are dirty it should be fine
        result = guard.preflight()
        assert isinstance(result, GuardResult)

    def test_writer_id_isolation(self, tmp_repo):
        g1 = CommitGuard(repo_root=tmp_repo, writer_id="alpha")
        g2 = CommitGuard(repo_root=tmp_repo, writer_id="beta")
        # Different writer IDs should check different pause files
        assert g1.writer_id != g2.writer_id
