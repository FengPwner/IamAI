#!/usr/bin/env python3
"""tests for push_key_watchdog.py — 14 tests covering probe, failure logging,
cooldown logic, and remediation hints."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import push_key_watchdog as pkw


class TestFingerprint(unittest.TestCase):
    """fingerprint extraction from ssh-keygen output."""

    @patch("push_key_watchdog.subprocess.run")
    def test_extracts_sha256(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="256 SHA256:abc123 user@host (ED25519)\n",
        )
        result = pkw.fingerprint(Path("/tmp/fake_key"))
        self.assertEqual(result, "SHA256:abc123")

    @patch("push_key_watchdog.subprocess.run")
    def test_returns_empty_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = pkw.fingerprint(Path("/tmp/fake_key"))
        self.assertEqual(result, "")

    @patch("push_key_watchdog.subprocess.run", side_effect=Exception("timeout"))
    def test_returns_empty_on_exception(self, mock_run):
        result = pkw.fingerprint(Path("/tmp/fake_key"))
        self.assertEqual(result, "")


class TestProbeSsh(unittest.TestCase):
    """ssh connectivity probe and status classification."""

    @patch("push_key_watchdog.subprocess.run")
    def test_ok_when_accepted(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr="Hi FengPwner! You've successfully authenticated.",
        )
        result = pkw.probe_ssh()
        self.assertEqual(result["status"], "ok")

    @patch("push_key_watchdog.subprocess.run")
    def test_key_rejected(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=255,
            stderr="git@github.com: Permission denied (publickey).",
        )
        result = pkw.probe_ssh()
        self.assertEqual(result["status"], "key_rejected")

    @patch("push_key_watchdog.subprocess.run")
    def test_network_unreachable(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=255,
            stderr="ssh: Could not resolve hostname github.com",
        )
        result = pkw.probe_ssh()
        self.assertEqual(result["status"], "network")


class TestRemediationHint(unittest.TestCase):
    """action hints for each probe status."""

    def test_ok_hint(self):
        hint = pkw.remediation_hint({"status": "ok", "detail": ""}, None)
        self.assertIn("accepted", hint)

    def test_key_rejected_with_pub(self):
        with tempfile.TemporaryDirectory() as td:
            key = Path(td) / "id_ed25519"
            pub = key.with_name("id_ed25519.pub")
            key.write_text("fake private key")
            pub.write_text("ssh-ed25519 AAAA... user@host")
            hint = pkw.remediation_hint(
                {"status": "key_rejected", "detail": ""}, key,
            )
            self.assertIn("NOT REGISTERED", hint)
            self.assertIn("settings/ssh/new", hint)

    def test_no_key_hint(self):
        hint = pkw.remediation_hint(
            {"status": "key_rejected", "detail": ""}, None,
        )
        self.assertIn("NO SSH KEY", hint)

    def test_network_hint(self):
        hint = pkw.remediation_hint(
            {"status": "network", "detail": ""}, None,
        )
        self.assertIn("retry", hint.lower())


class TestCooldown(unittest.TestCase):
    """cooldown window for suppressing repeated push attempts."""

    def test_set_and_check_cooldown(self):
        with tempfile.TemporaryDirectory() as td:
            pkw.DATA_DIR = Path(td)
            pkw.COOLDOWN_FILE = Path(td) / "push_cooldown_until.txt"
            pkw.set_cooldown(300)
            self.assertTrue(pkw.check_cooldown())

    def test_expired_cooldown(self):
        with tempfile.TemporaryDirectory() as td:
            pkw.DATA_DIR = Path(td)
            pkw.COOLDOWN_FILE = Path(td) / "push_cooldown_until.txt"
            pkw.COOLDOWN_FILE.write_text(str(int(time.time()) - 10))
            self.assertFalse(pkw.check_cooldown())

    def test_missing_cooldown_file(self):
        with tempfile.TemporaryDirectory() as td:
            pkw.COOLDOWN_FILE = Path(td) / "nonexistent.txt"
            self.assertFalse(pkw.check_cooldown())


class TestRecordFailure(unittest.TestCase):
    """failure logging to jsonl."""

    def test_appends_record(self):
        with tempfile.TemporaryDirectory() as td:
            pkw.DATA_DIR = Path(td)
            pkw.FAILURE_LOG = Path(td) / "failures.jsonl"
            rec = pkw.record_failure(
                Path("/tmp/key"),
                {"status": "key_rejected", "detail": "denied"},
                "test",
            )
            self.assertEqual(rec["probe_status"], "key_rejected")
            self.assertTrue(pkw.FAILURE_LOG.exists())
            lines = pkw.FAILURE_LOG.read_text().strip().split("\n")
            self.assertEqual(len(lines), 1)
            parsed = json.loads(lines[0])
            self.assertEqual(parsed["action"], "test")


if __name__ == "__main__":
    unittest.main()
