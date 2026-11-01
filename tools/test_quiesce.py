#!/usr/bin/env python3
"""Tests for tools/quiesce.py — writer quiescence gate."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from quiesce import snapshot_tree, pid_alive, main


class TestSnapshotTree(unittest.TestCase):
    """snapshot_tree should return a deterministic hash for the same tree state."""

    def test_returns_string(self):
        result = snapshot_tree()
        self.assertIsInstance(result, str)
        self.assertEqual(len(result), 64)  # sha256 hex digest

    def test_deterministic(self):
        """Two consecutive calls on a quiet tree return the same hash."""
        h1 = snapshot_tree()
        h2 = snapshot_tree()
        self.assertEqual(h1, h2)


class TestPidAlive(unittest.TestCase):
    """pid_alive should detect whether a process is actually running."""

    def test_missing_file(self):
        self.assertFalse(pid_alive(Path("/tmp/nonexistent-pid-file-xyz")))

    def test_stale_pid(self):
        """A pid file pointing to a dead process returns False."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            f.write("999999999\n")
            path = Path(f.name)
        try:
            self.assertFalse(pid_alive(path))
        finally:
            path.unlink(missing_ok=True)

    def test_current_process(self):
        """A pid file with our own PID returns True."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            f.write(str(os.getpid()) + "\n")
            path = Path(f.name)
        try:
            self.assertTrue(pid_alive(path))
        finally:
            path.unlink(missing_ok=True)


class TestMainWriterNotRunning(unittest.TestCase):
    """main() should exit 0 with WRITER_NOT_RUNNING when no writer is active."""

    def test_writer_not_running(self):
        """With a nonexistent pid file, quiesce exits 0 immediately."""
        fake_pid = Path("/tmp/test-quiesce-writer-not-running.pid")
        fake_pause = Path("/tmp/test-quiesce-writer-not-running-pause")
        fake_pid.unlink(missing_ok=True)
        fake_pause.unlink(missing_ok=True)

        with patch("quiesce.writer_mod") as mock_writer, \
             patch.object(sys, "argv", ["quiesce.py"]):
            mock_writer.pid_file.return_value = fake_pid
            mock_writer.pause_file.return_value = fake_pause
            ret = main()
            self.assertEqual(ret, 0)
            # Pause file should NOT have been touched (writer not running).
            self.assertFalse(fake_pause.exists())

        fake_pid.unlink(missing_ok=True)
        fake_pause.unlink(missing_ok=True)


class TestMainQuiescent(unittest.TestCase):
    """main() should detect quiescence when a running writer is paused."""

    def test_quiescent_when_tree_stable(self):
        """Simulate a running writer: quiesce should detect stable tree."""
        # Use our own PID as the "writer" so pid_alive returns True.
        fake_pid = Path("/tmp/test-quiesce-writer.pid")
        fake_pause = Path("/tmp/test-quiesce-writer-pause")
        fake_pid.write_text(str(os.getpid()) + "\n")
        fake_pause.unlink(missing_ok=True)

        try:
            with patch("quiesce.writer_mod") as mock_writer:
                mock_writer.pid_file.return_value = fake_pid
                mock_writer.pause_file.return_value = fake_pause
                # Override sys.argv for argparse.
                with patch.object(sys, "argv", ["quiesce.py", "--quiet-seconds", "2", "--timeout", "10"]):
                    ret = main()
                    self.assertEqual(ret, 0)
            # Pause file should have been created.
            self.assertTrue(fake_pause.exists())
        finally:
            fake_pid.unlink(missing_ok=True)
            fake_pause.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
