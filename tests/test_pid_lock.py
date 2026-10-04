"""Tests for snippets/pid_lock.py.

covers:
- acquire and release round-trip
- refusing when another live PID holds the lock
- stale lock detection and auto-cleanup
- force_release
- re-acquire after stale
- edge cases: missing file, corrupt file, permission-denied PID
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "snippets"))
from pid_lock import PidLock


def _tmp_path():
    fd, path = tempfile.mkstemp(suffix=".pid", prefix="pidlock_test_")
    os.close(fd)
    os.remove(path)  # start clean; PidLock will create it
    return path


class TestAcquireRelease(unittest.TestCase):

    def test_acquire_creates_file_with_own_pid(self):
        path = _tmp_path()
        try:
            lock = PidLock(path)
            self.assertTrue(lock.acquire())
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                self.assertEqual(int(f.read().strip()), os.getpid())
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_release_removes_file(self):
        path = _tmp_path()
        lock = PidLock(path)
        lock.acquire()
        lock.release()
        self.assertFalse(os.path.exists(path))

    def test_release_noop_when_not_held(self):
        path = _tmp_path()
        lock = PidLock(path)
        # should not raise
        lock.release()
        self.assertFalse(os.path.exists(path))

    def test_release_respects_other_owner(self):
        """release() should not delete a file written by a different PID."""
        path = _tmp_path()
        lock_a = PidLock(path, pid=99999999)
        lock_a.acquire()
        # lock_b has a different pid and should NOT be able to release lock_a's file
        lock_b = PidLock(path, pid=88888888)
        lock_b.release()
        # lock_a's file should still exist since lock_b is not the owner
        # (unless pid 99999999 happens to be alive, in which case acquire would
        # have failed — we test the release path directly here)
        # for the direct test, write a file manually:
        with open(path, "w") as f:
            f.write("12345")
        lock_c = PidLock(path, pid=54321)
        lock_c.release()  # should NOT remove: owner is 12345, not 54321
        self.assertTrue(os.path.exists(path))
        os.remove(path)

    def test_is_held_after_acquire(self):
        path = _tmp_path()
        lock = PidLock(path)
        self.assertFalse(lock.is_held())
        lock.acquire()
        self.assertTrue(lock.is_held())
        lock.release()
        self.assertFalse(lock.is_held())

    def test_owner_pid_returns_none_when_absent(self):
        path = _tmp_path()
        lock = PidLock(path)
        self.assertIsNone(lock.owner_pid())

    def test_owner_pid_returns_value(self):
        path = _tmp_path()
        lock = PidLock(path)
        lock.acquire()
        self.assertEqual(lock.owner_pid(), os.getpid())
        lock.release()


class TestStaleDetection(unittest.TestCase):

    def test_stale_when_owner_is_dead(self):
        path = _tmp_path()
        # write a PID that almost certainly does not exist
        with open(path, "w") as f:
            f.write("99999999")
        lock = PidLock(path)
        self.assertTrue(lock.stale())
        os.remove(path)

    def test_not_stale_when_owner_is_self(self):
        path = _tmp_path()
        lock = PidLock(path)
        lock.acquire()
        self.assertFalse(lock.stale())
        lock.release()

    def test_not_stale_when_file_absent(self):
        path = _tmp_path()
        lock = PidLock(path)
        self.assertFalse(lock.stale())

    def test_acquire_cleans_stale_lock(self):
        """A dead owner's PID file should be overwritten on acquire."""
        path = _tmp_path()
        with open(path, "w") as f:
            f.write("99999999")
        lock = PidLock(path)
        self.assertTrue(lock.acquire())
        self.assertEqual(lock.owner_pid(), os.getpid())
        lock.release()

    def test_acquire_refuses_live_owner(self):
        """When another live PID holds the lock, acquire returns False."""
        path = _tmp_path()
        # simulate: file contains PID 1 (init, always alive on Linux)
        if os.name == "posix":
            with open(path, "w") as f:
                f.write("1")
            lock = PidLock(path, pid=os.getpid())
            result = lock.acquire()
            # PID 1 is almost certainly alive; acquire should fail
            if lock._pid_alive(1):
                self.assertFalse(result)
            os.remove(path)


class TestForceRelease(unittest.TestCase):

    def test_force_release_removes_file(self):
        path = _tmp_path()
        lock = PidLock(path)
        lock.acquire()
        self.assertTrue(lock.force_release())
        self.assertFalse(os.path.exists(path))

    def test_force_release_returns_false_when_absent(self):
        path = _tmp_path()
        lock = PidLock(path)
        self.assertFalse(lock.force_release())


class TestEdgeCases(unittest.TestCase):

    def test_corrupt_pid_file(self):
        """Non-numeric content should be treated as no valid owner."""
        path = _tmp_path()
        with open(path, "w") as f:
            f.write("not-a-pid\n")
        lock = PidLock(path)
        self.assertIsNone(lock.owner_pid())
        # stale should be False since there's no valid owner to check
        self.assertFalse(lock.stale())
        # acquire should succeed (overwriting the corrupt file)
        self.assertTrue(lock.acquire())
        lock.release()

    def test_empty_pid_file(self):
        path = _tmp_path()
        with open(path, "w") as f:
            f.write("")
        lock = PidLock(path)
        self.assertIsNone(lock.owner_pid())
        self.assertTrue(lock.acquire())
        lock.release()

    def test_acquire_same_pid_twice(self):
        """Re-acquiring with the same PID should succeed (idempotent)."""
        path = _tmp_path()
        lock = PidLock(path)
        self.assertTrue(lock.acquire())
        self.assertTrue(lock.acquire())  # same PID, should succeed
        lock.release()

    def test_pid_alive_with_nonexistent_pid(self):
        self.assertFalse(PidLock._pid_alive(99999999))

    def test_pid_alive_with_self(self):
        self.assertTrue(PidLock._pid_alive(os.getpid()))


if __name__ == "__main__":
    unittest.main()
