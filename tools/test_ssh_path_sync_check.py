#!/usr/bin/env python3
"""Tests for ssh_path_sync_check — the tool that catches the deploy key
disconnect after container rebuilds.

The bug this prevents: workspace .ssh/ survives a rebuild, but ~/.ssh/ is
ephemeral. Push fails with a cryptic SSH error. The caretaker stares at it,
guesses wrong, and wastes a visit.

These tests verify the detection logic (what's missing, what drifted) and
the sync logic (copies the right files with the right permissions).
"""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

# Ensure tools/ is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ssh_path_sync_check import (
    check_sync,
    do_sync,
    _sha256,
    FileStatus,
    SyncReport,
    REQUIRED_FILES,
)


class TestSha256(unittest.TestCase):
    """The hashing helper used to detect drift."""

    def test_returns_hex_digest(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello deploy key")
            f.flush()
            result = _sha256(Path(f.name))
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 64)  # sha256 hex is 64 chars
        os.unlink(f.name)

    def test_returns_none_for_missing_file(self):
        result = _sha256(Path("/tmp/this_file_does_not_exist_xyz"))
        self.assertIsNone(result)

    def test_same_content_same_hash(self):
        with tempfile.NamedTemporaryFile(delete=False) as f1, \
             tempfile.NamedTemporaryFile(delete=False) as f2:
            content = b"identical key material"
            f1.write(content)
            f2.write(content)
            f1.flush()
            f2.flush()
            self.assertEqual(_sha256(Path(f1.name)), _sha256(Path(f2.name)))
        os.unlink(f1.name)
        os.unlink(f2.name)

    def test_different_content_different_hash(self):
        with tempfile.NamedTemporaryFile(delete=False) as f1, \
             tempfile.NamedTemporaryFile(delete=False) as f2:
            f1.write(b"key version A")
            f2.write(b"key version B")
            f1.flush()
            f2.flush()
            self.assertNotEqual(_sha256(Path(f1.name)), _sha256(Path(f2.name)))
        os.unlink(f1.name)
        os.unlink(f2.name)


class TestCheckSync(unittest.TestCase):
    """The detection logic: what's missing, what drifted, is everything synced."""

    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp(prefix="iamai-ws-ssh-"))
        self.home = Path(tempfile.mkdtemp(prefix="iamai-hm-ssh-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workspace, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def _write(self, directory: Path, name: str, content: bytes) -> Path:
        path = directory / name
        path.write_bytes(content)
        return path

    def test_all_synced(self):
        for name in REQUIRED_FILES:
            self._write(self.workspace, name, b"content-A")
            self._write(self.home, name, b"content-A")
        report = check_sync(self.workspace, self.home)
        self.assertTrue(report.synced)
        self.assertEqual(report.missing_in_home, [])
        self.assertEqual(report.drifted, [])

    def test_missing_in_home(self):
        # workspace has the key, home doesn't — classic rebuild scenario
        self._write(self.workspace, "id_ed25519", b"private key")
        # home doesn't have it
        report = check_sync(self.workspace, self.home, required=["id_ed25519"])
        self.assertFalse(report.synced)
        self.assertIn("id_ed25519", report.missing_in_home)

    def test_drifted_content(self):
        # both have the file but with different content — stale key
        self._write(self.workspace, "id_ed25519", b"key version 2")
        self._write(self.home, "id_ed25519", b"key version 1")
        report = check_sync(self.workspace, self.home, required=["id_ed25519"])
        self.assertFalse(report.synced)
        self.assertIn("id_ed25519", report.drifted)

    def test_missing_in_workspace(self):
        # workspace doesn't have the file — nothing to sync from
        self._write(self.home, "known_hosts", b"host keys")
        report = check_sync(self.workspace, self.home, required=["known_hosts"])
        self.assertFalse(report.synced)
        # not in missing_in_home since home has it
        self.assertEqual(report.missing_in_home, [])

    def test_both_missing(self):
        report = check_sync(self.workspace, self.home, required=["id_ed25519"])
        self.assertFalse(report.synced)

    def test_recommendation_when_synced(self):
        for name in REQUIRED_FILES:
            self._write(self.workspace, name, b"x")
            self._write(self.home, name, b"x")
        report = check_sync(self.workspace, self.home)
        self.assertIn("in sync", report.recommendation)

    def test_recommendation_when_missing(self):
        self._write(self.workspace, "id_ed25519", b"key")
        report = check_sync(self.workspace, self.home, required=["id_ed25519"])
        self.assertIn("--sync", report.recommendation)
        self.assertIn("id_ed25519", report.recommendation)

    def test_custom_required_files(self):
        # only check one file
        self._write(self.workspace, "custom.conf", b"config")
        self._write(self.home, "custom.conf", b"config")
        report = check_sync(self.workspace, self.home, required=["custom.conf"])
        self.assertTrue(report.synced)


class TestDoSync(unittest.TestCase):
    """The sync logic: copies missing files with correct permissions."""

    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp(prefix="iamai-ws-ssh-"))
        self.home = Path(tempfile.mkdtemp(prefix="iamai-hm-ssh-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workspace, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def _write(self, directory: Path, name: str, content: bytes) -> Path:
        path = directory / name
        path.write_bytes(content)
        return path

    def test_copies_missing_private_key(self):
        self._write(self.workspace, "id_ed25519", b"secret key material")
        copied = do_sync(self.workspace, self.home, required=["id_ed25519"])
        self.assertIn("id_ed25519", copied)
        # verify content matches
        self.assertEqual(
            (self.home / "id_ed25519").read_bytes(),
            b"secret key material",
        )
        # verify permissions: private key must be 600
        mode = stat.S_IMODE((self.home / "id_ed25519").stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_copies_missing_known_hosts(self):
        self._write(self.workspace, "known_hosts", b"github.com ssh-ed25519 AAAA...")
        copied = do_sync(self.workspace, self.home, required=["known_hosts"])
        self.assertIn("known_hosts", copied)
        # known_hosts should be 644
        mode = stat.S_IMODE((self.home / "known_hosts").stat().st_mode)
        self.assertEqual(mode, 0o644)

    def test_skips_already_synced(self):
        self._write(self.workspace, "config", b"Host github.com\n  IdentityFile ...")
        self._write(self.home, "config", b"Host github.com\n  IdentityFile ...")
        copied = do_sync(self.workspace, self.home, required=["config"])
        self.assertEqual(copied, [])

    def test_overwrites_drifted_file(self):
        self._write(self.workspace, "id_ed25519", b"new key")
        self._write(self.home, "id_ed25519", b"old key")
        copied = do_sync(self.workspace, self.home, required=["id_ed25519"])
        self.assertIn("id_ed25519", copied)
        self.assertEqual((self.home / "id_ed25519").read_bytes(), b"new key")

    def test_creates_home_ssh_dir(self):
        import shutil
        shutil.rmtree(self.home)
        self._write(self.workspace, "id_ed25519", b"key")
        do_sync(self.workspace, self.home, required=["id_ed25519"])
        self.assertTrue(self.home.exists())
        # directory should be 700
        mode = stat.S_IMODE(self.home.stat().st_mode)
        self.assertEqual(mode, 0o700)

    def test_skips_files_missing_from_workspace(self):
        # workspace doesn't have the file — can't sync what doesn't exist
        copied = do_sync(self.workspace, self.home, required=["id_ed25519"])
        self.assertEqual(copied, [])

    def test_pub_key_gets_644(self):
        self._write(self.workspace, "id_ed25519.pub", b"ssh-ed25519 AAAA... user@host")
        copied = do_sync(self.workspace, self.home, required=["id_ed25519.pub"])
        self.assertIn("id_ed25519.pub", copied)
        mode = stat.S_IMODE((self.home / "id_ed25519.pub").stat().st_mode)
        self.assertEqual(mode, 0o644)

    def test_sync_then_check_reports_synced(self):
        """Integration: sync should make check_sync report synced."""
        for name in ["id_ed25519", "id_ed25519.pub", "known_hosts", "config"]:
            self._write(self.workspace, name, f"content-{name}".encode())
        do_sync(self.workspace, self.home, required=["id_ed25519", "id_ed25519.pub", "known_hosts", "config"])
        report = check_sync(self.workspace, self.home, required=["id_ed25519", "id_ed25519.pub", "known_hosts", "config"])
        self.assertTrue(report.synced)


class TestSyncReportProperties(unittest.TestCase):
    """Edge cases in the report dataclass."""

    def test_missing_in_home_only_counts_workspace_present(self):
        files = [
            FileStatus("a", in_workspace=True, in_home=False, match=None),
            FileStatus("b", in_workspace=False, in_home=False, match=None),
            FileStatus("c", in_workspace=True, in_home=True, match=True),
        ]
        report = SyncReport("/ws", "/hm", files, synced=False)
        self.assertEqual(report.missing_in_home, ["a"])

    def test_drifted_only_counts_mismatch(self):
        files = [
            FileStatus("a", in_workspace=True, in_home=True, match=False),
            FileStatus("b", in_workspace=True, in_home=True, match=True),
            FileStatus("c", in_workspace=True, in_home=False, match=None),
        ]
        report = SyncReport("/ws", "/hm", files, synced=False)
        self.assertEqual(report.drifted, ["a"])


if __name__ == "__main__":
    unittest.main()
