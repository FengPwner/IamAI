#!/usr/bin/env python3
"""Tests for process_liveness.py — process health checker."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from process_liveness import (
    ProcessStatus,
    _read_pidfile,
    _is_alive,
    _pidfile_mtime,
    _process_command,
    check_process,
)


class TestProcessStatus(unittest.TestCase):
    """Test the ProcessStatus dataclass and verdict logic."""

    def test_healthy_verdict(self):
        s = ProcessStatus(
            name="writer", pidfile="/tmp/x.pid", pid=1234,
            alive=True, pidfile_exists=True, pidfile_stale=False,
            uptime_seconds=300.0, command="python3 writer_loop.py",
        )
        self.assertEqual(s.verdict, "healthy")

    def test_stale_pidfile_verdict(self):
        s = ProcessStatus(
            name="batch", pidfile="/tmp/x.pid", pid=9999,
            alive=False, pidfile_exists=True, pidfile_stale=True,
            uptime_seconds=None, command=None,
        )
        self.assertEqual(s.verdict, "stale_pidfile")

    def test_no_pidfile_verdict(self):
        s = ProcessStatus(
            name="writer", pidfile="/tmp/x.pid", pid=None,
            alive=False, pidfile_exists=False, pidfile_stale=False,
            uptime_seconds=None, command=None,
        )
        self.assertEqual(s.verdict, "no_pidfile")

    def test_dead_verdict(self):
        s = ProcessStatus(
            name="batch", pidfile="/tmp/x.pid", pid=5555,
            alive=False, pidfile_exists=True, pidfile_stale=False,
            uptime_seconds=None, command=None,
        )
        self.assertEqual(s.verdict, "dead")


class TestReadPidfile(unittest.TestCase):
    def test_valid_pidfile(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            f.write("12345\n")
            f.flush()
            self.assertEqual(_read_pidfile(f.name), 12345)
        os.unlink(f.name)

    def test_missing_pidfile(self):
        self.assertIsNone(_read_pidfile("/tmp/nonexistent_pid_file_xyz.pid"))

    def test_empty_pidfile(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            f.write("")
            f.flush()
            self.assertIsNone(_read_pidfile(f.name))
        os.unlink(f.name)

    def test_corrupt_pidfile(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            f.write("not_a_number\n")
            f.flush()
            self.assertIsNone(_read_pidfile(f.name))
        os.unlink(f.name)


class TestIsAlive(unittest.TestCase):
    def test_current_process_alive(self):
        self.assertTrue(_is_alive(os.getpid()))

    def test_nonexistent_pid(self):
        # PID 999999 is very unlikely to exist
        self.assertFalse(_is_alive(999999))


class TestCheckProcess(unittest.TestCase):
    def test_no_pidfile(self):
        status = check_process("test", "/tmp/nonexistent_test_pidfile.pid")
        self.assertFalse(status.alive)
        self.assertFalse(status.pidfile_exists)
        self.assertEqual(status.verdict, "no_pidfile")

    def test_stale_pidfile(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            f.write("999999\n")
            f.flush()
            status = check_process("test", f.name)
            self.assertFalse(status.alive)
            self.assertTrue(status.pidfile_exists)
            self.assertTrue(status.pidfile_stale)
            self.assertEqual(status.verdict, "stale_pidfile")
        os.unlink(f.name)

    def test_live_process(self):
        """Start a real process and verify it's detected as healthy."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
                f.write(str(proc.pid))
                f.flush()
                status = check_process("test", f.name)
                self.assertTrue(status.alive)
                self.assertTrue(status.pidfile_exists)
                self.assertFalse(status.pidfile_stale)
                self.assertEqual(status.verdict, "healthy")
                self.assertIsNotNone(status.uptime_seconds)
            os.unlink(f.name)
        finally:
            proc.terminate()
            proc.wait()


class TestProcessCommand(unittest.TestCase):
    def test_self_command(self):
        cmd = _process_command(os.getpid())
        self.assertIsNotNone(cmd)
        self.assertIn("python", cmd.lower())

    def test_nonexistent_command(self):
        cmd = _process_command(999999)
        self.assertIsNone(cmd)


class TestCLIOuptut(unittest.TestCase):
    """Test the script's CLI output in both text and JSON modes."""

    def _run_cli(self, *extra_args, writer_id="test_liveness_cli"):
        script = str(Path(__file__).resolve().parent.parent / "tools" / "process_liveness.py")
        cmd = [sys.executable, script, "--writer", writer_id] + list(extra_args)
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result

    def test_text_output(self):
        result = self._run_cli()
        # Should mention both writer and batch
        self.assertIn("writer", result.stdout)
        self.assertIn("batch", result.stdout)
        # Should exit 1 since no processes are running for test writer id
        self.assertEqual(result.returncode, 1)

    def test_json_output(self):
        result = self._run_cli("--json")
        data = json.loads(result.stdout)
        self.assertIn("writer", data)
        self.assertIn("batch", data)
        self.assertIn("all_healthy", data)
        self.assertFalse(data["all_healthy"])


if __name__ == "__main__":
    unittest.main()
