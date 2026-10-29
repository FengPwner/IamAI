#!/usr/bin/env python3
"""Tests for push_readiness_probe module.

These tests validate the readiness probe's logic without requiring
actual SSH access or network connectivity. They mock subprocess calls
to simulate various push-readiness states.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add tools/ to import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import push_readiness_probe as prp


class TestProbeResult(unittest.TestCase):
    """Test the ProbeResult dataclass."""

    def test_basic_creation(self):
        r = prp.ProbeResult(check="test", passed=True, detail="ok")
        self.assertEqual(r.check, "test")
        self.assertTrue(r.passed)
        self.assertEqual(r.detail, "ok")
        self.assertEqual(r.latency_ms, 0)
        self.assertFalse(r.fixable)
        self.assertFalse(r.fixed)

    def test_with_all_fields(self):
        r = prp.ProbeResult(
            check="ssh",
            passed=False,
            detail="host key failed",
            latency_ms=150,
            fixable=True,
            fixed=False,
        )
        self.assertEqual(r.latency_ms, 150)
        self.assertTrue(r.fixable)


class TestCheckKeyExists(unittest.TestCase):
    """Test deploy key existence detection."""

    def test_rescued_key_with_correct_perms(self):
        """Rescued key at /tmp with 0600 perms should pass."""
        with patch.object(prp, "SSH_KEY_RESCUE") as mock_rescue:
            mock_rescue.exists.return_value = True
            mock_stat = MagicMock()
            mock_stat.st_mode = 0o100600
            mock_rescue.stat.return_value = mock_stat
            result = prp.check_key_exists()
            self.assertTrue(result.passed)
            self.assertIn("rescued", result.detail)

    def test_rescued_key_with_wrong_perms(self):
        """Rescued key with bad perms should fail but be fixable."""
        with patch.object(prp, "SSH_KEY_RESCUE") as mock_rescue:
            mock_rescue.exists.return_value = True
            mock_stat = MagicMock()
            mock_stat.st_mode = 0o100777
            mock_rescue.stat.return_value = mock_stat
            result = prp.check_key_exists()
            self.assertFalse(result.passed)
            self.assertTrue(result.fixable)

    def test_workspace_key_not_rescued(self):
        """Workspace key without rescue should fail, be fixable."""
        with patch.object(prp, "SSH_KEY_RESCUE") as mock_rescue, \
             patch.object(prp, "SSH_KEY_WORKSPACE") as mock_ws:
            mock_rescue.exists.return_value = False
            mock_ws.exists.return_value = True
            result = prp.check_key_exists()
            self.assertFalse(result.passed)
            self.assertTrue(result.fixable)
            self.assertIn("not rescued", result.detail)

    def test_no_key_anywhere(self):
        """No key at all should fail and not be fixable."""
        with patch.object(prp, "SSH_KEY_RESCUE") as mock_rescue, \
             patch.object(prp, "SSH_KEY_WORKSPACE") as mock_ws:
            mock_rescue.exists.return_value = False
            mock_ws.exists.return_value = False
            result = prp.check_key_exists()
            self.assertFalse(result.passed)
            self.assertFalse(result.fixable)


class TestCheckSSHConnection(unittest.TestCase):
    """Test SSH connectivity checking."""

    def test_successful_auth(self):
        """GitHub returns 'successfully authenticated' on good auth."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Hi FengPwner! You've successfully authenticated"
        mock_result.returncode = 1  # GitHub returns 1 for auth success

        with patch.object(prp, "_run", return_value=mock_result):
            result = prp.check_ssh_connection("/tmp/fake_key")
            self.assertTrue(result.passed)
            self.assertIn("authenticated", result.detail)

    def test_host_key_verification_failed(self):
        """Host key mismatch should fail and be fixable."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Host key verification failed."
        mock_result.returncode = 255

        with patch.object(prp, "_run", return_value=mock_result):
            result = prp.check_ssh_connection("/tmp/fake_key")
            self.assertFalse(result.passed)
            self.assertTrue(result.fixable)
            self.assertIn("host key", result.detail.lower())

    def test_permission_denied(self):
        """Key not registered should fail and not be fixable."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "git@github.com: Permission denied (publickey)."
        mock_result.returncode = 255

        with patch.object(prp, "_run", return_value=mock_result):
            result = prp.check_ssh_connection("/tmp/fake_key")
            self.assertFalse(result.passed)
            self.assertFalse(result.fixable)
            self.assertIn("permission denied", result.detail.lower())

    def test_ssh_timeout(self):
        """SSH timeout should fail and not be fixable."""
        with patch.object(prp, "_run", side_effect=subprocess.TimeoutExpired("ssh", 10)):
            result = prp.check_ssh_connection("/tmp/fake_key")
            self.assertFalse(result.passed)
            self.assertEqual(result.latency_ms, 10000)

    def test_ssh_not_found(self):
        """Missing ssh binary should fail gracefully."""
        with patch.object(prp, "_run", side_effect=FileNotFoundError):
            result = prp.check_ssh_connection("/tmp/fake_key")
            self.assertFalse(result.passed)
            self.assertIn("ssh binary not found", result.detail)


class TestCheckBranchSync(unittest.TestCase):
    """Test branch synchronization checking."""

    def _mock_run(self, outputs):
        """Helper: create a _run mock that returns different results per call."""
        results = []
        for rc, stdout, stderr in outputs:
            m = MagicMock()
            m.returncode = rc
            m.stdout = stdout
            m.stderr = stderr
            results.append(m)
        return results

    def test_branches_in_sync(self):
        """Same local and remote SHA should pass."""
        sha = "abc1234567890"
        mock_results = self._mock_run([
            (0, "", ""),           # fetch
            (0, sha + "\n", ""),   # local HEAD
            (0, sha + "\n", ""),   # remote HEAD
        ])
        with patch.object(prp, "_run", side_effect=mock_results):
            result = prp.check_branch_sync("/tmp/fake_key")
            self.assertTrue(result.passed)

    def test_local_ahead(self):
        """Local ahead of remote should pass (fast-forward push)."""
        local_sha = "bbb1234567890"
        remote_sha = "aaa1234567890"
        base_sha = remote_sha  # merge-base is remote = local ahead
        mock_results = self._mock_run([
            (0, "", ""),              # fetch
            (0, local_sha + "\n", ""),   # local HEAD
            (0, remote_sha + "\n", ""),  # remote HEAD
            (0, base_sha + "\n", ""),    # merge-base
        ])
        with patch.object(prp, "_run", side_effect=mock_results):
            result = prp.check_branch_sync("/tmp/fake_key")
            self.assertTrue(result.passed)
            self.assertIn("ahead", result.detail)

    def test_local_behind(self):
        """Local behind remote should fail and be fixable."""
        local_sha = "aaa1234567890"
        remote_sha = "bbb1234567890"
        base_sha = local_sha  # merge-base is local = local behind
        mock_results = self._mock_run([
            (0, "", ""),              # fetch
            (0, local_sha + "\n", ""),   # local HEAD
            (0, remote_sha + "\n", ""),  # remote HEAD
            (0, base_sha + "\n", ""),    # merge-base
        ])
        with patch.object(prp, "_run", side_effect=mock_results):
            result = prp.check_branch_sync("/tmp/fake_key")
            self.assertFalse(result.passed)
            self.assertTrue(result.fixable)
            self.assertIn("behind", result.detail)

    def test_diverged(self):
        """Diverged branches should fail and be fixable."""
        local_sha = "aaa1234567890"
        remote_sha = "bbb1234567890"
        base_sha = "ccc1234567890"  # different from both
        mock_results = self._mock_run([
            (0, "", ""),              # fetch
            (0, local_sha + "\n", ""),   # local HEAD
            (0, remote_sha + "\n", ""),  # remote HEAD
            (0, base_sha + "\n", ""),    # merge-base
        ])
        with patch.object(prp, "_run", side_effect=mock_results):
            result = prp.check_branch_sync("/tmp/fake_key")
            self.assertFalse(result.passed)
            self.assertTrue(result.fixable)
            self.assertIn("diverged", result.detail)

    def test_fetch_failure(self):
        """git fetch failure should fail gracefully."""
        mock_results = self._mock_run([
            (128, "", "fatal: Could not read from remote repository."),
        ])
        with patch.object(prp, "_run", side_effect=mock_results):
            result = prp.check_branch_sync("/tmp/fake_key")
            self.assertFalse(result.passed)


class TestRunProbe(unittest.TestCase):
    """Test the full probe orchestration."""

    def test_all_pass(self):
        """All checks passing should yield ready=True."""
        mock_key = prp.ProbeResult(check="key_exists", passed=True, detail="ok", latency_ms=5)
        mock_ssh = prp.ProbeResult(check="ssh_connection", passed=True, detail="ok", latency_ms=200)
        mock_sync = prp.ProbeResult(check="branch_sync", passed=True, detail="ok", latency_ms=500)

        with patch.object(prp, "check_key_exists", return_value=mock_key), \
             patch.object(prp, "check_ssh_connection", return_value=mock_ssh), \
             patch.object(prp, "check_branch_sync", return_value=mock_sync), \
             patch.object(prp, "SSH_KEY_RESCUE") as mock_rescue:
            mock_rescue.exists.return_value = True
            results = prp.run_probe(fix=False)
            self.assertTrue(all(r.passed for r in results))
            self.assertEqual(len(results), 3)

    def test_ssh_fail_skips_sync(self):
        """If SSH fails, branch sync should not run."""
        mock_key = prp.ProbeResult(check="key_exists", passed=True, detail="ok", latency_ms=5)
        mock_ssh = prp.ProbeResult(check="ssh_connection", passed=False, detail="denied", latency_ms=100)

        with patch.object(prp, "check_key_exists", return_value=mock_key), \
             patch.object(prp, "check_ssh_connection", return_value=mock_ssh), \
             patch.object(prp, "check_branch_sync") as mock_sync, \
             patch.object(prp, "SSH_KEY_RESCUE") as mock_rescue:
            mock_rescue.exists.return_value = True
            results = prp.run_probe(fix=False)
            mock_sync.assert_not_called()
            self.assertEqual(len(results), 2)

    def test_fix_mode_repairs_key(self):
        """Fix mode should rescue a failing key check."""
        fail_key = prp.ProbeResult(check="key_exists", passed=False, detail="not rescued", fixable=True)
        pass_key = prp.ProbeResult(check="key_exists", passed=True, detail="rescued", latency_ms=5)
        mock_ssh = prp.ProbeResult(check="ssh_connection", passed=True, detail="ok", latency_ms=200)
        mock_sync = prp.ProbeResult(check="branch_sync", passed=True, detail="ok", latency_ms=500)

        call_count = [0]
        def key_check_side_effect():
            call_count[0] += 1
            return fail_key if call_count[0] == 1 else pass_key

        with patch.object(prp, "check_key_exists", side_effect=key_check_side_effect), \
             patch.object(prp, "check_ssh_connection", return_value=mock_ssh), \
             patch.object(prp, "check_branch_sync", return_value=mock_sync), \
             patch.object(prp, "fix_key_rescue", return_value=True), \
             patch.object(prp, "SSH_KEY_RESCUE") as mock_rescue:
            mock_rescue.exists.return_value = True
            results = prp.run_probe(fix=True)
            self.assertTrue(results[0].fixed)
            self.assertTrue(results[0].passed)


class TestFixFunctions(unittest.TestCase):
    """Test auto-repair functions."""

    def test_fix_key_rescue(self):
        """Key rescue should copy and set permissions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src_key = Path(tmpdir) / "id_ed25519"
            dst_key = Path(tmpdir) / "rescued_key"
            src_key.write_text("fake-key-content")

            with patch.object(prp, "SSH_KEY_WORKSPACE", src_key), \
                 patch.object(prp, "SSH_KEY_RESCUE", dst_key):
                result = prp.fix_key_rescue()
                self.assertTrue(result)
                self.assertTrue(dst_key.exists())
                self.assertEqual(dst_key.stat().st_mode & 0o777, 0o600)

    def test_fix_key_rescue_no_source(self):
        """Key rescue with no source should return False."""
        with patch.object(prp, "SSH_KEY_WORKSPACE") as mock_ws:
            mock_ws.exists.return_value = False
            result = prp.fix_key_rescue()
            self.assertFalse(result)

    def test_fix_known_hosts(self):
        """Known hosts fix should append ssh-keyscan output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            known_hosts = Path(tmpdir) / "known_hosts"
            known_hosts.write_text("existing-entry\n")

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "github.com ssh-ed25519 AAAA-new-key\n"

            with patch.object(prp, "KNOWN_HOSTS_WORKSPACE", known_hosts), \
                 patch.object(prp, "_run", return_value=mock_result):
                result = prp.fix_known_hosts()
                self.assertTrue(result)
                content = known_hosts.read_text()
                self.assertIn("AAAA-new-key", content)
                self.assertIn("existing-entry", content)


class TestJSONOutput(unittest.TestCase):
    """Test machine-readable output format."""

    @patch("push_readiness_probe.run_probe")
    @patch("push_readiness_probe.REPO")
    def test_json_output_structure(self, mock_repo, mock_run_probe):
        """JSON output should contain expected keys."""
        mock_repo.is_dir.return_value = True
        mock_run_probe.return_value = [
            prp.ProbeResult(check="key_exists", passed=True, detail="ok", latency_ms=5),
            prp.ProbeResult(check="ssh_connection", passed=True, detail="ok", latency_ms=200),
            prp.ProbeResult(check="branch_sync", passed=True, detail="ok", latency_ms=500),
        ]
        results = prp.run_probe()
        output = {
            "ready": all(r.passed for r in results),
            "checks": [
                {
                    "check": r.check,
                    "passed": r.passed,
                    "detail": r.detail,
                    "latency_ms": r.latency_ms,
                    "fixable": r.fixable,
                    "fixed": r.fixed,
                }
                for r in results
            ],
        }
        self.assertTrue(output["ready"])
        self.assertEqual(len(output["checks"]), 3)
        self.assertIn("key_exists", output["checks"][0]["check"])


if __name__ == "__main__":
    unittest.main()
