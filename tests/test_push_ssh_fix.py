#!/usr/bin/env python3
"""Tests for push_ssh_fix.py — SSH key permission repair on overlay filesystems.

Covers:
- key_permissions_ok: correctly identifies 0600/0400 vs 0777
- rescue_key_to_tmp: copies key and sets 0600 in /tmp
- configure_git_ssh: writes core.sshCommand pointing to rescued key
- main() flow: end-to-end on a simulated overlay scenario

Run:
    python3 -m pytest tests/test_push_ssh_fix.py -v
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure the tools directory is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import push_ssh_fix as psf


class TestKeyPermissionsOk:
    def test_accepts_0600(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake-key")
        os.chmod(key, 0o600)
        assert psf.key_permissions_ok(key) is True

    def test_accepts_0400(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake-key")
        os.chmod(key, 0o400)
        assert psf.key_permissions_ok(key) is True

    def test_rejects_0777(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake-key")
        os.chmod(key, 0o777)
        assert psf.key_permissions_ok(key) is False

    def test_rejects_0644(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake-key")
        os.chmod(key, 0o644)
        assert psf.key_permissions_ok(key) is False


class TestRescueKeyToTmp:
    def test_copies_and_sets_permissions(self, tmp_path):
        source = tmp_path / "source_key"
        source.write_text("ssh-ed25519 AAAA... test@test")
        os.chmod(source, 0o777)  # simulate overlay

        dest = tmp_path / "rescued_key"
        with patch.object(psf, "TMP_KEY", dest):
            result = psf.rescue_key_to_tmp(source)

        assert result == dest
        assert dest.read_text() == "ssh-ed25519 AAAA... test@test"
        assert (dest.stat().st_mode & 0o777) == 0o600

    def test_dry_run_does_not_copy(self, tmp_path):
        source = tmp_path / "source_key"
        source.write_text("secret")
        dest = tmp_path / "rescued_key"

        with patch.object(psf, "TMP_KEY", dest):
            result = psf.rescue_key_to_tmp(source, dry_run=True)

        assert result == dest
        assert not dest.exists()


class TestConfigureGitSsh:
    def test_sets_core_ssh_command(self, tmp_path):
        # Create a temporary git repo
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)

        key_path = Path("/tmp/test_key")
        with patch.object(psf, "REPO", repo):
            result = psf.configure_git_ssh(key_path)

        assert result is True
        r = subprocess.run(
            ["git", "config", "core.sshCommand"],
            cwd=repo, capture_output=True, text=True
        )
        assert "/tmp/test_key" in r.stdout
        assert "StrictHostKeyChecking=no" in r.stdout

    def test_dry_run_does_not_configure(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)

        key_path = Path("/tmp/test_key")
        with patch.object(psf, "REPO", repo):
            result = psf.configure_git_ssh(key_path, dry_run=True)

        assert result is True
        r = subprocess.run(
            ["git", "config", "core.sshCommand"],
            cwd=repo, capture_output=True, text=True
        )
        # Should not have been set
        assert r.returncode != 0 or "/tmp/test_key" not in r.stdout


class TestChmodStrict:
    def test_succeeds_on_normal_fs(self, tmp_path):
        f = tmp_path / "f"
        f.write_text("x")
        os.chmod(f, 0o777)
        assert psf.chmod_strict(f, 0o600) is True
        assert (f.stat().st_mode & 0o777) == 0o600

    def test_detects_overlay_failure(self, tmp_path):
        """Simulate overlay by mocking os.chmod to be a no-op."""
        f = tmp_path / "f"
        f.write_text("x")
        os.chmod(f, 0o777)

        original_chmod = os.chmod
        def noop_chmod(path, mode):
            pass  # overlay: chmod silently ignored

        with patch("os.chmod", side_effect=noop_chmod):
            result = psf.chmod_strict(f, 0o600)

        assert result is False  # permission didn't change


class TestFindWorkingKey:
    def test_returns_none_when_no_keys_exist(self):
        with patch.object(psf, "KNOWN_KEY_LOCATIONS", [Path("/nonexistent/key")]):
            assert psf.find_working_key() is None

    def test_finds_authenticating_key(self, tmp_path):
        key = tmp_path / "good_key"
        key.write_text("valid")

        mock_result = MagicMock()
        mock_result.stderr = "Hi FengPwner/IamAI! You've successfully authenticated"

        with patch.object(psf, "KNOWN_KEY_LOCATIONS", [key]):
            with patch.object(psf, "_run", return_value=mock_result):
                assert psf.find_working_key() == key


class TestMainFlow:
    def test_no_key_found(self):
        with patch.object(psf, "KNOWN_KEY_LOCATIONS", [Path("/nonexistent")]):
            assert psf.main() == 1

    def test_key_already_healthy(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("ok")
        os.chmod(key, 0o600)

        with patch.object(psf, "KNOWN_KEY_LOCATIONS", [key]):
            with patch.object(psf, "configure_git_ssh", return_value=True) as mock_cfg:
                assert psf.main() == 0
                mock_cfg.assert_called_once()

    def test_overlay_rescue_path(self, tmp_path):
        """Full flow: key at 0777, chmod fails, rescue to /tmp succeeds."""
        key = tmp_path / "overlay_key"
        key.write_text("ssh-ed25519 rescued")
        os.chmod(key, 0o777)

        rescued = tmp_path / "tmp_key"

        with patch.object(psf, "KNOWN_KEY_LOCATIONS", [key]):
            with patch.object(psf, "chmod_strict", return_value=False):
                with patch.object(psf, "TMP_KEY", rescued):
                    with patch.object(psf, "configure_git_ssh", return_value=True):
                        with patch.object(psf, "verify_push", return_value=True):
                            assert psf.main() == 0

        assert rescued.exists()
        assert (rescued.stat().st_mode & 0o777) == 0o600
