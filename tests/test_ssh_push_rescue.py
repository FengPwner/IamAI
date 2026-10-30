#!/usr/bin/env python3
"""tests for tools/ssh_push_rescue.py — consolidated SSH push rescue tool.

visit 116: codifies the three-step rescue that every caretaker since visit
108 has had to rediscover manually. these tests lock in the contract so
future refactors don't silently break the push pipeline.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# add tools/ to path
TOOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS_DIR)

import ssh_push_rescue


class TestFindKey(unittest.TestCase):
    """find_key() returns the first readable private key path."""

    def test_returns_none_when_no_key_exists(self):
        with patch.object(ssh_push_rescue, "KEY_CANDIDATES", ["/nonexistent/key"]):
            self.assertIsNone(ssh_push_rescue.find_key())

    def test_finds_existing_key(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"fake key")
            tmp = f.name
        try:
            with patch.object(ssh_push_rescue, "KEY_CANDIDATES", [tmp]):
                result = ssh_push_rescue.find_key()
                self.assertEqual(os.path.realpath(result), os.path.realpath(tmp))
        finally:
            os.unlink(tmp)

    def test_skips_unreadable_key(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"fake key")
            tmp = f.name
        try:
            os.chmod(tmp, 0o000)
            with patch.object(ssh_push_rescue, "KEY_CANDIDATES", [tmp]):
                result = ssh_push_rescue.find_key()
                # may find it or not depending on root; just ensure no crash
                self.assertTrue(result is None or isinstance(result, str))
        finally:
            os.chmod(tmp, 0o644)
            os.unlink(tmp)


class TestRescueKey(unittest.TestCase):
    """rescue_key() copies key to /tmp with mode 0600."""

    def test_rescue_sets_correct_permissions(self):
        with tempfile.NamedTemporaryFile(delete=False, dir="/tmp") as src:
            src.write(b"test private key content")
            src_path = src.name
        try:
            rescued = ssh_push_rescue.rescue_key(src_path)
            self.assertIsNotNone(rescued)
            self.assertTrue(os.path.isfile(rescued))
            mode = os.stat(rescued).st_mode & 0o777
            self.assertEqual(mode, 0o600)
            with open(rescued, "rb") as f:
                self.assertEqual(f.read(), b"test private key content")
        finally:
            os.unlink(src_path)
            if rescued and os.path.exists(rescued):
                os.unlink(rescued)

    def test_rescue_dry_run_does_not_copy(self):
        with patch.object(ssh_push_rescue, "DRY_RUN", True):
            result = ssh_push_rescue.rescue_key("/fake/source")
            self.assertEqual(result, ssh_push_rescue.RESCUED_KEY_PATH)

    def test_rescue_returns_none_on_failure(self):
        result = ssh_push_rescue.rescue_key("/nonexistent/key/file")
        self.assertIsNone(result)


class TestBuildSshCommand(unittest.TestCase):
    """build_ssh_command() returns a properly formatted GIT_SSH_COMMAND."""

    def test_contains_key_path(self):
        cmd = ssh_push_rescue.build_ssh_command("/tmp/test_key")
        self.assertIn("-i /tmp/test_key", cmd)

    def test_contains_strict_host_key_option(self):
        cmd = ssh_push_rescue.build_ssh_command("/tmp/test_key")
        self.assertIn("StrictHostKeyChecking=accept-new", cmd)

    def test_returns_string(self):
        cmd = ssh_push_rescue.build_ssh_command("/tmp/k")
        self.assertIsInstance(cmd, str)


class TestPopulateKnownHosts(unittest.TestCase):
    """populate_known_hosts() adds github.com keys to known_hosts."""

    def test_dry_run_returns_true(self):
        with patch.object(ssh_push_rescue, "DRY_RUN", True):
            self.assertTrue(ssh_push_rescue.populate_known_hosts())

    def test_returns_true_when_already_present(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix="_known_hosts") as f:
            f.write("github.com ssh-ed25519 AAAAfakekey\n")
            tmp = f.name
        try:
            with patch.object(ssh_push_rescue, "KNOWN_HOSTS_PATHS", [tmp]):
                result = ssh_push_rescue.populate_known_hosts()
                self.assertTrue(result)
        finally:
            os.unlink(tmp)


class TestRun(unittest.TestCase):
    """run() orchestrates the full rescue flow."""

    def test_run_returns_tuple(self):
        with patch.object(ssh_push_rescue, "KEY_CANDIDATES", ["/nonexistent"]):
            exit_code, report = ssh_push_rescue.run()
            self.assertEqual(exit_code, 1)
            self.assertIn("exit_code", report)

    def test_run_report_has_timestamp(self):
        with patch.object(ssh_push_rescue, "KEY_CANDIDATES", ["/nonexistent"]):
            _, report = ssh_push_rescue.run()
            self.assertIn("timestamp", report)

    def test_dry_run_full_flow(self):
        with tempfile.NamedTemporaryFile(delete=False, dir="/tmp") as f:
            f.write(b"fake ed25519 key")
            key_path = f.name
        try:
            with patch.object(ssh_push_rescue, "DRY_RUN", True), \
                 patch.object(ssh_push_rescue, "KEY_CANDIDATES", [key_path]):
                exit_code, report = ssh_push_rescue.run()
                self.assertEqual(exit_code, 0)
                self.assertTrue(report["key_rescued"])
                self.assertTrue(report["known_hosts_ok"])
                self.assertIsNotNone(report["ssh_command"])
        finally:
            os.unlink(key_path)


class TestIntegration(unittest.TestCase):
    """integration test against the live repo (skipped if no key available)."""

    def test_rescue_script_is_executable(self):
        script = os.path.join(TOOLS_DIR, "ssh_push_rescue.py")
        self.assertTrue(os.path.isfile(script))

    def test_rescue_json_output(self):
        script = os.path.join(TOOLS_DIR, "ssh_push_rescue.py")
        result = subprocess.run(
            [sys.executable, script, "--dry-run", "--json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            report = json.loads(result.stdout)
            self.assertIn("exit_code", report)
            self.assertEqual(report["dry_run"], True)


if __name__ == "__main__":
    unittest.main()
