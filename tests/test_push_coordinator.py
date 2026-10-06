"""Tests for iamai.push_coordinator — file-based push mutex."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.push_coordinator import (
    AcquireResult,
    LockInfo,
    acquire,
    release,
    _read_lock,
    _write_lock,
    _remove_lock,
)


# -- LockInfo --


class TestLockInfo:
    """LockInfo dataclass methods."""

    def test_not_expired(self):
        info = LockInfo(agent="qwen", pid=1, acquired_at=100.0, expires_at=200.0)
        assert not info.is_expired(now=150.0)

    def test_expired(self):
        info = LockInfo(agent="qwen", pid=1, acquired_at=100.0, expires_at=200.0)
        assert info.is_expired(now=200.0)

    def test_expired_past(self):
        info = LockInfo(agent="qwen", pid=1, acquired_at=100.0, expires_at=200.0)
        assert info.is_expired(now=300.0)

    def test_is_held_by_match(self):
        info = LockInfo(agent="qwen", pid=42, acquired_at=0, expires_at=0)
        assert info.is_held_by("qwen", 42)

    def test_is_held_by_wrong_agent(self):
        info = LockInfo(agent="qwen", pid=42, acquired_at=0, expires_at=0)
        assert not info.is_held_by("guoban", 42)

    def test_is_held_by_wrong_pid(self):
        info = LockInfo(agent="qwen", pid=42, acquired_at=0, expires_at=0)
        assert not info.is_held_by("qwen", 99)


# -- _read_lock / _write_lock --


class TestLockIO:
    """Lock file read/write round-trips."""

    def test_write_then_read(self, tmp_path):
        p = tmp_path / "push.lock"
        info = LockInfo(agent="qwen", pid=100, acquired_at=1.0, expires_at=121.0)
        _write_lock(p, info)
        result = _read_lock(p)
        assert result is not None
        assert result.agent == "qwen"
        assert result.pid == 100
        assert result.acquired_at == 1.0
        assert result.expires_at == 121.0

    def test_read_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent.lock"
        assert _read_lock(p) is None

    def test_read_corrupt_json(self, tmp_path):
        p = tmp_path / "push.lock"
        p.write_text("not json{{{", encoding="utf-8")
        assert _read_lock(p) is None

    def test_read_wrong_schema(self, tmp_path):
        p = tmp_path / "push.lock"
        p.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        assert _read_lock(p) is None

    def test_write_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "deep" / "nested" / "push.lock"
        info = LockInfo(agent="test", pid=1, acquired_at=0, expires_at=60)
        _write_lock(p, info)
        assert p.exists()
        assert _read_lock(p) is not None


# -- _remove_lock --


class TestRemoveLock:
    """Lock removal safety checks."""

    def test_remove_own_lock(self, tmp_path):
        p = tmp_path / "push.lock"
        info = LockInfo(agent="qwen", pid=50, acquired_at=0, expires_at=100)
        _write_lock(p, info)
        assert _remove_lock(p, info) is True
        assert not p.exists()

    def test_remove_someone_elses_lock(self, tmp_path):
        p = tmp_path / "push.lock"
        holder = LockInfo(agent="guoban", pid=60, acquired_at=0, expires_at=100)
        _write_lock(p, holder)
        intruder = LockInfo(agent="qwen", pid=50, acquired_at=0, expires_at=100)
        assert _remove_lock(p, intruder) is False
        assert p.exists()

    def test_remove_missing_lock(self, tmp_path):
        p = tmp_path / "push.lock"
        info = LockInfo(agent="qwen", pid=50, acquired_at=0, expires_at=100)
        assert _remove_lock(p, info) is True  # already gone = fine


# -- acquire (fresh) --


class TestAcquireFresh:
    """Acquire when no lock file exists."""

    def test_acquire_empty(self, tmp_path):
        p = tmp_path / "push.lock"
        result = acquire("qwen", lock_path=p, hold_seconds=60)
        assert result.acquired is True
        assert result.stolen is False
        assert result.previous_holder is None

        lock = _read_lock(p)
        assert lock is not None
        assert lock.agent == "qwen"

    def test_acquire_writes_lock_file(self, tmp_path):
        p = tmp_path / "push.lock"
        acquire("qwen", lock_path=p, hold_seconds=120)
        lock = _read_lock(p)
        assert lock is not None
        assert lock.expires_at - lock.acquired_at == 120


# -- acquire (steal expired) --


class TestAcquireSteal:
    """Acquire by stealing an expired lock."""

    def test_steal_expired_lock(self, tmp_path):
        p = tmp_path / "push.lock"
        # Write a lock that expired long ago
        stale = LockInfo(agent="guoban", pid=999, acquired_at=0.0, expires_at=10.0)
        _write_lock(p, stale)

        clock = [100.0]
        result = acquire(
            "qwen", lock_path=p, hold_seconds=60,
            now_fn=lambda: clock[0],
        )
        assert result.acquired is True
        assert result.stolen is True
        assert result.previous_holder is not None
        assert result.previous_holder.agent == "guoban"


# -- acquire (timeout) --


class TestAcquireTimeout:
    """Acquire times out when lock is held by another agent."""

    def test_timeout_on_held_lock(self, tmp_path):
        p = tmp_path / "push.lock"
        clock = [1000.0]

        # guoban holds a valid lock
        holder = LockInfo(
            agent="guoban", pid=888,
            acquired_at=clock[0], expires_at=clock[0] + 300,
        )
        _write_lock(p, holder)

        # qwen tries to acquire with zero wait
        result = acquire(
            "qwen", lock_path=p, hold_seconds=60,
            wait_seconds=0, now_fn=lambda: clock[0],
        )
        assert result.acquired is False
        assert result.error is not None
        assert "timed out" in result.error
        assert "guoban" in result.error


# -- acquire (refresh own lock) --


class TestAcquireRefresh:
    """Re-acquiring your own lock refreshes the expiry."""

    def test_refresh_own_lock(self, tmp_path):
        p = tmp_path / "push.lock"
        clock = [1000.0]

        result1 = acquire(
            "qwen", lock_path=p, hold_seconds=60,
            now_fn=lambda: clock[0],
        )
        assert result1.acquired is True

        clock[0] += 30  # 30 seconds later
        result2 = acquire(
            "qwen", lock_path=p, hold_seconds=60,
            now_fn=lambda: clock[0],
        )
        assert result2.acquired is True

        lock = _read_lock(p)
        # Expiry should be refreshed from the second acquire time
        assert lock.expires_at == clock[0] + 60


# -- release --


class TestRelease:
    """Release function behavior."""

    def test_release_own_lock(self, tmp_path):
        p = tmp_path / "push.lock"
        acquire("qwen", lock_path=p, hold_seconds=60)
        assert release("qwen", lock_path=p) is True
        assert not p.exists()

    def test_release_stolen_lock(self, tmp_path):
        """If someone stole the lock, release returns False."""
        p = tmp_path / "push.lock"
        acquire("qwen", lock_path=p, hold_seconds=60)

        # Simulate steal: overwrite with guoban's lock
        # (we need to match PID, so use os.getpid since acquire uses it)
        import os
        guoban_lock = LockInfo(
            agent="guoban", pid=os.getpid() + 1,
            acquired_at=0, expires_at=9999,
        )
        _write_lock(p, guoban_lock)

        assert release("qwen", lock_path=p) is False
        assert p.exists()  # guoban's lock survives

    def test_release_missing_lock(self, tmp_path):
        p = tmp_path / "push.lock"
        # No lock to release — should be fine
        assert release("qwen", lock_path=p) is True


# -- integration: full acquire-push-release cycle --


class TestIntegration:
    """End-to-end acquire → release cycle."""

    def test_full_cycle(self, tmp_path):
        p = tmp_path / "push.lock"
        result = acquire("qwen", lock_path=p, hold_seconds=60)
        assert result.acquired is True

        # ... do the push ...

        assert release("qwen", lock_path=p) is True
        assert not p.exists()

    def test_two_agents_serialize(self, tmp_path):
        """Two agents cannot hold the lock simultaneously."""
        p = tmp_path / "push.lock"
        clock = [1000.0]

        r1 = acquire(
            "qwen", lock_path=p, hold_seconds=60,
            wait_seconds=0, now_fn=lambda: clock[0],
        )
        assert r1.acquired is True

        # guoban tries immediately — should fail
        r2 = acquire(
            "guoban", lock_path=p, hold_seconds=60,
            wait_seconds=0, now_fn=lambda: clock[0],
        )
        assert r2.acquired is False

        # qwen releases, guoban can now acquire
        release("qwen", lock_path=p)
        r3 = acquire(
            "guoban", lock_path=p, hold_seconds=60,
            wait_seconds=0, now_fn=lambda: clock[0],
        )
        assert r3.acquired is True
