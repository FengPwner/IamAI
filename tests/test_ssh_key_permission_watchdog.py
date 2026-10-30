#!/usr/bin/env python3
"""tests for ssh_key_permission_watchdog.py"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import ssh_key_permission_watchdog as wdg


class TestGetFileMode(unittest.TestCase):
    """test reading file permission bits."""

    def test_returns_mode(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            os.chmod(f.name, 0o600)
            self.assertEqual(wdg.get_file_mode(f.name), 0o600)
            os.unlink(f.name)

    def test_detects_open_permissions(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            os.chmod(f.name, 0o777)
            self.assertEqual(wdg.get_file_mode(f.name), 0o777)
            os.unlink(f.name)


class TestCheckPrimaryKey(unittest.TestCase):
    """test primary key status detection."""

    def test_missing_key(self):
        with patch.object(wdg, "PRIMARY_KEY", "/nonexistent/key"):
            result = wdg.check_primary_key()
            self.assertEqual(result["status"], "missing")

    def test_ok_permissions(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            os.chmod(f.name, 0o600)
            with patch.object(wdg, "PRIMARY_KEY", f.name):
                result = wdg.check_primary_key()
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["mode"], "0o600")
            os.unlink(f.name)

    def test_too_open_permissions(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            os.chmod(f.name, 0o644)
            with patch.object(wdg, "PRIMARY_KEY", f.name):
                result = wdg.check_primary_key()
                self.assertEqual(result["status"], "too_open")
            os.unlink(f.name)

    def test_777_is_too_open(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            os.chmod(f.name, 0o777)
            with patch.object(wdg, "PRIMARY_KEY", f.name):
                result = wdg.check_primary_key()
                self.assertEqual(result["status"], "too_open")
            os.unlink(f.name)


class TestRescueKey(unittest.TestCase):
    """test key rescue to tmpfs."""

    def test_missing_primary_returns_none(self):
        with patch.object(wdg, "PRIMARY_KEY", "/nonexistent/key"):
            self.assertIsNone(wdg.rescue_key())

    def test_copies_and_sets_permissions(self):
        with tempfile.NamedTemporaryFile(delete=False, mode="w") as src:
            src.write("fake-key-content")
            src.flush()
            rescue_path = src.name + "_rescue"
            with patch.object(wdg, "PRIMARY_KEY", src.name), \
                 patch.object(wdg, "RESCUE_KEY", rescue_path):
                result = wdg.rescue_key()
                self.assertEqual(result, rescue_path)
                self.assertEqual(stat.S_IMODE(os.stat(rescue_path).st_mode), 0o600)
                with open(rescue_path) as f:
                    self.assertEqual(f.read(), "fake-key-content")
                os.unlink(rescue_path)
            os.unlink(src.name)


class TestVerifySSH(unittest.TestCase):
    """test SSH verification."""

    def test_authenticated(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Hi FengPwner/IamAI! You've successfully authenticated"
        with patch("subprocess.run", return_value=mock_result):
            v = wdg.verify_ssh("/tmp/test_key")
            self.assertTrue(v["authenticated"])

    def test_not_authenticated(self):
        mock_result = MagicMock()
        mock_result.returncode = 255
        mock_result.stderr = "Permission denied (publickey)."
        with patch("subprocess.run", return_value=mock_result):
            v = wdg.verify_ssh("/tmp/test_key")
            self.assertFalse(v["authenticated"])

    def test_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 15)):
            v = wdg.verify_ssh("/tmp/test_key")
            self.assertFalse(v["authenticated"])
            self.assertEqual(v["exit_code"], -1)

    def test_ssh_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            v = wdg.verify_ssh("/tmp/test_key")
            self.assertFalse(v["authenticated"])
            self.assertEqual(v["exit_code"], -2)


class TestGitSSHCommand(unittest.TestCase):
    """test GIT_SSH_COMMAND generation."""

    def test_format(self):
        cmd = wdg.git_ssh_command("/tmp/my_key")
        self.assertIn("-i /tmp/my_key", cmd)
        self.assertIn("StrictHostKeyChecking=accept-new", cmd)

    def test_contains_key_path(self):
        cmd = wdg.git_ssh_command("/some/other/path")
        self.assertIn("/some/other/path", cmd)


class TestMainFlow(unittest.TestCase):
    """test the main() exit code logic."""

    def test_missing_key_returns_2(self):
        with patch.object(wdg, "PRIMARY_KEY", "/nonexistent/key"), \
             patch.object(wdg, "JSON_OUT", False):
            self.assertEqual(wdg.main(), 2)

    def test_ok_key_returns_0(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            os.chmod(f.name, 0o600)
            with patch.object(wdg, "PRIMARY_KEY", f.name), \
                 patch.object(wdg, "JSON_OUT", False):
                self.assertEqual(wdg.main(), 0)
            os.unlink(f.name)

    def test_too_open_triggers_rescue(self):
        with tempfile.NamedTemporaryFile(delete=False, mode="w") as src:
            src.write("key")
            src.flush()
            os.chmod(src.name, 0o777)
            rescue_path = src.name + "_rescue"
            with patch.object(wdg, "PRIMARY_KEY", src.name), \
                 patch.object(wdg, "RESCUE_KEY", rescue_path), \
                 patch.object(wdg, "JSON_OUT", False):
                result = wdg.main()
                self.assertIn(result, (1, 3))  # rescued or rescue failed
            if os.path.exists(rescue_path):
                os.unlink(rescue_path)
            os.unlink(src.name)

    def test_json_output_is_valid(self):
        with patch.object(wdg, "PRIMARY_KEY", "/nonexistent/key"), \
             patch.object(wdg, "JSON_OUT", True), \
             patch("sys.stdout") as mock_stdout:
            wdg.main()
            printed = mock_stdout.write.call_args_list[0][0][0]
            report = json.loads(printed)
            self.assertIn("primary_key", report)
            self.assertIn("exit_code", report)


if __name__ == "__main__":
    unittest.main()
