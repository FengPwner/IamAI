"""Tests for iamai.sync_fence"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from iamai.sync_fence import LockInfo, SyncFence, _pid_alive


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Create a minimal fake repo with a .git directory."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    return tmp_path


@pytest.fixture()
def fence(repo: Path) -> SyncFence:
    return SyncFence(repo_path=repo, owner="test", timeout=2.0)


# ---------------------------------------------------------------------------
# LockInfo
# ---------------------------------------------------------------------------

class TestLockInfo:
    def test_not_stale_when_alive_and_fresh(self):
        info = LockInfo(pid=os.getpid(), owner="x",
                        acquired_at=time.time(), repo_path="/tmp")
        assert not info.is_stale(max_age=60)

    def test_stale_when_pid_dead(self):
        # PID 1 is init — alive on most systems, so use a clearly dead PID.
        info = LockInfo(pid=999_999_999, owner="x",
                        acquired_at=time.time(), repo_path="/tmp")
        assert info.is_stale(max_age=60)

    def test_stale_when_too_old(self):
        info = LockInfo(pid=os.getpid(), owner="x",
                        acquired_at=time.time() - 1000, repo_path="/tmp")
        assert info.is_stale(max_age=60)


# ---------------------------------------------------------------------------
# _pid_alive
# ---------------------------------------------------------------------------

class TestPidAlive:
    def test_current_pid_is_alive(self):
        assert _pid_alive(os.getpid())

    def test_bogus_pid_is_dead(self):
        assert not _pid_alive(999_999_999)


# ---------------------------------------------------------------------------
# SyncFence — basic acquire / release
# ---------------------------------------------------------------------------

class TestBasicAcquireRelease:
    def test_acquire_creates_lock_file(self, fence: SyncFence):
        assert fence.acquire()
        assert fence.lock_path.exists()

    def test_release_removes_lock_file(self, fence: SyncFence):
        fence.acquire()
        fence.release()
        assert not fence.lock_path.exists()

    def test_double_release_is_safe(self, fence: SyncFence):
        fence.acquire()
        fence.release()
        fence.release()  # should not raise

    def test_acquire_returns_true(self, fence: SyncFence):
        assert fence.acquire() is True

    def test_is_locked_reflects_state(self, fence: SyncFence):
        assert not fence.is_locked()
        fence.acquire()
        assert fence.is_locked()
        fence.release()
        assert not fence.is_locked()


# ---------------------------------------------------------------------------
# Lock metadata
# ---------------------------------------------------------------------------

class TestLockMetadata:
    def test_info_returns_none_when_unlocked(self, fence: SyncFence):
        assert fence.info() is None

    def test_info_contains_owner_and_pid(self, fence: SyncFence):
        fence.acquire()
        info = fence.info()
        assert info is not None
        assert info.pid == os.getpid()
        assert info.owner == "test"
        assert info.repo_path == str(fence.repo_path)

    def test_info_acquired_at_is_recent(self, fence: SyncFence):
        before = time.time()
        fence.acquire()
        info = fence.info()
        assert info.acquired_at >= before
        assert info.acquired_at <= time.time()

    def test_corrupt_lockfile_returns_none(self, fence: SyncFence):
        fence.lock_path.write_text("not json {{{")
        assert fence.info() is None


# ---------------------------------------------------------------------------
# Non-blocking acquire
# ---------------------------------------------------------------------------

class TestNonBlocking:
    def test_nonblocking_fails_when_held_by_self(self, fence: SyncFence):
        # First acquire succeeds.
        fence.acquire()
        # Second non-blocking attempt fails (same PID, lock exists).
        fence2 = SyncFence(repo_path=fence.repo_path, owner="other",
                           timeout=0.5)
        assert fence2.acquire(block=False) is False

    def test_nonblocking_succeeds_when_free(self, fence: SyncFence):
        assert fence.acquire(block=False) is True


# ---------------------------------------------------------------------------
# Stale lock reclamation
# ---------------------------------------------------------------------------

class TestStaleReclamation:
    def test_reclaim_dead_pid_lock(self, repo: Path):
        # Write a lock file with a dead PID.
        lock_path = repo / ".git" / "sync_fence.lock"
        lock_path.write_text(json.dumps({
            "pid": 999_999_999,
            "owner": "ghost",
            "acquired_at": time.time(),
            "repo_path": str(repo),
        }))
        fence = SyncFence(repo_path=repo, owner="reclaimer", timeout=2.0)
        assert fence.acquire() is True
        info = fence.info()
        assert info.owner == "reclaimer"

    def test_reclaim_old_lock(self, repo: Path):
        lock_path = repo / ".git" / "sync_fence.lock"
        lock_path.write_text(json.dumps({
            "pid": os.getpid(),
            "owner": "sleeper",
            "acquired_at": time.time() - 9999,
            "repo_path": str(repo),
        }))
        fence = SyncFence(repo_path=repo, owner="reclaimer",
                          timeout=2.0, stale_after=60.0)
        assert fence.acquire() is True
        assert fence.info().owner == "reclaimer"


# ---------------------------------------------------------------------------
# break_lock
# ---------------------------------------------------------------------------

class TestBreakLock:
    def test_break_removes_lock(self, fence: SyncFence):
        fence.acquire()
        old = fence.break_lock(reason="test")
        assert not fence.lock_path.exists()
        assert old is not None
        assert old.owner == "test"

    def test_break_when_no_lock(self, fence: SyncFence):
        result = fence.break_lock()
        assert result is None

    def test_break_corrupt_lock(self, fence: SyncFence):
        fence.lock_path.write_text("garbage")
        old = fence.break_lock()
        assert old is None  # couldn't parse
        assert not fence.lock_path.exists()


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    def test_with_statement(self, fence: SyncFence):
        with fence:
            assert fence.lock_path.exists()
        assert not fence.lock_path.exists()

    def test_release_on_exception(self, fence: SyncFence):
        with pytest.raises(ValueError):
            with fence:
                assert fence.lock_path.exists()
                raise ValueError("boom")
        assert not fence.lock_path.exists()

    def test_timeout_raises(self, repo: Path):
        # Pre-create a lock held by our own PID (not stale).
        f1 = SyncFence(repo_path=repo, owner="holder", timeout=2.0)
        f1.acquire()
        f2 = SyncFence(repo_path=repo, owner="waiter", timeout=0.3,
                        stale_after=9999)
        with pytest.raises(TimeoutError):
            with f2:
                pass
        f1.release()


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

class TestTimeout:
    def test_blocking_respects_timeout(self, repo: Path):
        f1 = SyncFence(repo_path=repo, owner="holder", timeout=5.0)
        f1.acquire()
        f2 = SyncFence(repo_path=repo, owner="waiter", timeout=0.3,
                        stale_after=9999)
        start = time.monotonic()
        result = f2.acquire(block=True)
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed >= 0.2  # waited at least close to timeout
        f1.release()


# ---------------------------------------------------------------------------
# Atomic create (O_EXCL)
# ---------------------------------------------------------------------------

class TestAtomicCreate:
    def test_concurrent_acquire_only_one_wins(self, repo: Path):
        f1 = SyncFence(repo_path=repo, owner="a", timeout=0.5)
        f2 = SyncFence(repo_path=repo, owner="b", timeout=0.5,
                        stale_after=9999)
        assert f1.acquire(block=False) is True
        assert f2.acquire(block=False) is False
        f1.release()
        assert f2.acquire(block=False) is True
        f2.release()
