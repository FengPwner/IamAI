#!/usr/bin/env python3
"""tests for ssh_key_mismatch.py — 22 tests covering fingerprint extraction,
github probing, key discovery, push history detection, and classification logic.

the mismatch detector has a specific job: distinguish "key was never registered"
from "key was swapped out by container recycle." both look identical at the ssh
layer (Permission denied), but the remediation differs — one needs a first-time
setup, the other needs a key swap or re-registration.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai import ssh_key_mismatch as skm
from iamai.ssh_key_mismatch import MismatchKind, MismatchResult


class TestExtractFingerprint(unittest.TestCase):
    """fingerprint extraction from ssh-keygen output."""

    def test_returns_none_when_key_missing(self):
        result = skm._extract_fingerprint(Path("/nonexistent/key"))
        self.assertIsNone(result)

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_extracts_sha256_from_valid_output(self, mock_run):
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"fake key content")
            tmp_path = Path(f.name)
        try:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="256 SHA256:abc123def456 user@host (ED25519)\n",
            )
            result = skm._extract_fingerprint(tmp_path)
            self.assertEqual(result, "SHA256:abc123def456")
        finally:
            tmp_path.unlink()

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_returns_none_on_ssh_keygen_failure(self, mock_run):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"fake key content")
            tmp_path = Path(f.name)
        try:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            result = skm._extract_fingerprint(tmp_path)
            self.assertIsNone(result)
        finally:
            tmp_path.unlink()

    @patch("iamai.ssh_key_mismatch.subprocess.run", side_effect=Exception("timeout"))
    def test_returns_none_on_exception(self, mock_run):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"fake key content")
            tmp_path = Path(f.name)
        try:
            result = skm._extract_fingerprint(tmp_path)
            self.assertIsNone(result)
        finally:
            tmp_path.unlink()

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_returns_none_on_empty_output(self, mock_run):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"fake key content")
            tmp_path = Path(f.name)
        try:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = skm._extract_fingerprint(tmp_path)
            self.assertIsNone(result)
        finally:
            tmp_path.unlink()


class TestProbeGithub(unittest.TestCase):
    """ssh connectivity probe to github.com."""

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_returns_zero_on_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr="Hi FengPwner! You've successfully authenticated.",
        )
        rc, stderr = skm._probe_github()
        self.assertEqual(rc, 0)
        self.assertIn("successfully authenticated", stderr)

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_returns_nonzero_on_permission_denied(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=255,
            stderr="git@github.com: Permission denied (publickey).",
        )
        rc, stderr = skm._probe_github()
        self.assertNotEqual(rc, 0)
        self.assertIn("Permission denied", stderr)

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_returns_negative_on_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=15)
        rc, stderr = skm._probe_github()
        self.assertEqual(rc, -1)
        self.assertIn("timed out", stderr)

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_returns_negative_on_generic_exception(self, mock_run):
        mock_run.side_effect = OSError("network unreachable")
        rc, stderr = skm._probe_github()
        self.assertEqual(rc, -2)
        self.assertIn("network unreachable", stderr)


class TestFindLocalKey(unittest.TestCase):
    """discovery of ssh key in standard locations."""

    def test_returns_none_when_no_candidates_exist(self):
        result = skm._find_local_key(candidates=[
            Path("/nonexistent/path1"),
            Path("/nonexistent/path2"),
        ])
        self.assertIsNone(result)

    def test_returns_first_readable_key(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, mode='w') as f:
            f.write("fake key")
            tmp_path = Path(f.name)
        os.chmod(tmp_path, 0o600)
        try:
            result = skm._find_local_key(candidates=[
                Path("/nonexistent/path1"),
                tmp_path,
            ])
            self.assertEqual(result, tmp_path)
        finally:
            tmp_path.unlink()

    def test_skips_key_with_open_permissions(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, mode='w') as f:
            f.write("fake key")
            tmp_path = Path(f.name)
        os.chmod(tmp_path, 0o644)  # too open
        try:
            result = skm._find_local_key(candidates=[tmp_path])
            self.assertIsNone(result)
        finally:
            tmp_path.unlink()


class TestHasPushHistory(unittest.TestCase):
    """detection of prior successful pushes via git log."""

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_returns_true_when_remote_commits_exist(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="abc1234 feat: add some module\n",
        )
        result = skm._has_push_history(Path("/tmp/repo"))
        self.assertTrue(result)

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_returns_false_when_no_remote_history(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = skm._has_push_history(Path("/tmp/repo"))
        self.assertFalse(result)

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_returns_false_on_git_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="fatal")
        result = skm._has_push_history(Path("/tmp/repo"))
        self.assertFalse(result)


class TestClassifyKeyFailure(unittest.TestCase):
    """end-to-end classification of ssh key failure modes."""

    @patch("iamai.ssh_key_mismatch._find_local_key")
    def test_unknown_when_no_key_found(self, mock_find):
        mock_find.return_value = None
        result = skm.classify_key_failure()
        self.assertEqual(result.kind, MismatchKind.UNKNOWN)
        self.assertIn("no readable ssh key", result.detail)

    @patch("iamai.ssh_key_mismatch._probe_github")
    @patch("iamai.ssh_key_mismatch._extract_fingerprint")
    @patch("iamai.ssh_key_mismatch._find_local_key")
    def test_ok_when_github_accepts(self, mock_find, mock_fp, mock_probe):
        mock_find.return_value = Path("/root/.ssh/id_ed25519")
        mock_fp.return_value = "SHA256:goodfingerprint"
        mock_probe.return_value = (0, "Hi FengPwner!")
        result = skm.classify_key_failure()
        self.assertEqual(result.kind, MismatchKind.OK)
        self.assertEqual(result.local_fingerprint, "SHA256:goodfingerprint")

    @patch("iamai.ssh_key_mismatch._has_push_history")
    @patch("iamai.ssh_key_mismatch._probe_github")
    @patch("iamai.ssh_key_mismatch._extract_fingerprint")
    @patch("iamai.ssh_key_mismatch._find_local_key")
    def test_mismatch_when_history_exists(self, mock_find, mock_fp, mock_probe, mock_hist):
        mock_find.return_value = Path("/root/.ssh/id_ed25519")
        mock_fp.return_value = "SHA256:newkey"
        mock_probe.return_value = (255, "Permission denied (publickey).")
        mock_hist.return_value = True
        result = skm.classify_key_failure(Path("/tmp/repo"))
        self.assertEqual(result.kind, MismatchKind.MISMATCH)
        self.assertIn("container recycle", result.detail)

    @patch("iamai.ssh_key_mismatch._has_push_history")
    @patch("iamai.ssh_key_mismatch._probe_github")
    @patch("iamai.ssh_key_mismatch._extract_fingerprint")
    @patch("iamai.ssh_key_mismatch._find_local_key")
    def test_unregistered_when_no_history(self, mock_find, mock_fp, mock_probe, mock_hist):
        mock_find.return_value = Path("/root/.ssh/id_ed25519")
        mock_fp.return_value = "SHA256:firstkey"
        mock_probe.return_value = (255, "Permission denied (publickey).")
        mock_hist.return_value = False
        result = skm.classify_key_failure(Path("/tmp/repo"))
        self.assertEqual(result.kind, MismatchKind.UNREGISTERED)
        self.assertIn("deploy key", result.detail)

    @patch("iamai.ssh_key_mismatch._probe_github")
    @patch("iamai.ssh_key_mismatch._extract_fingerprint")
    @patch("iamai.ssh_key_mismatch._find_local_key")
    def test_unknown_on_unexpected_response(self, mock_find, mock_fp, mock_probe):
        mock_find.return_value = Path("/root/.ssh/id_ed25519")
        mock_fp.return_value = "SHA256:key123"
        mock_probe.return_value = (255, "Connection refused")
        result = skm.classify_key_failure()
        self.assertEqual(result.kind, MismatchKind.UNKNOWN)
        self.assertIn("unexpected ssh response", result.detail)


class TestMismatchResultDefaults(unittest.TestCase):
    """data structure defaults and timestamp behavior."""

    def test_checked_at_defaults_to_now(self):
        r = MismatchResult(kind=MismatchKind.OK)
        self.assertGreater(r.checked_at, 0)

    def test_explicit_checked_at_preserved(self):
        r = MismatchResult(kind=MismatchKind.OK, checked_at=1000000.0)
        self.assertEqual(r.checked_at, 1000000.0)

    def test_local_fingerprint_defaults_none(self):
        r = MismatchResult(kind=MismatchKind.UNKNOWN)
        self.assertIsNone(r.local_fingerprint)


if __name__ == "__main__":
    unittest.main()
