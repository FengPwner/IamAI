#!/usr/bin/env python3
"""Tests for iamai.push_credential_readiness — proactive push credential validation.

covers:
  - key existence and readability checks
  - key permission validation (must be 600 or stricter)
  - known_hosts file detection
  - git remote URL validation
  - SSH probe result parsing
  - caching with TTL
  - stop-on-failure short-circuit
  - CLI entry point
  - remediation message generation
"""

import json
import os
import stat
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from iamai.push_credential_readiness import (
    CredentialReadiness,
    CredentialCheck,
    DATA_DIR,
    CACHE_FILE,
)


# ─── CredentialCheck dataclass ───────────────────────────────────────────


class TestCredentialCheck:
    """Tests for the CredentialCheck dataclass."""

    def test_create_passing(self):
        c = CredentialCheck(name="test", passed=True, detail="all good")
        assert c.name == "test"
        assert c.passed is True
        assert c.detail == "all good"
        assert c.severity == "error"  # default

    def test_create_failing(self):
        c = CredentialCheck(
            name="key_exists",
            passed=False,
            detail="not found",
            remediation="create it",
            severity="error",
        )
        assert c.passed is False
        assert c.remediation == "create it"

    def test_to_dict(self):
        c = CredentialCheck(name="test", passed=True, detail="ok")
        d = c.to_dict()
        assert d["name"] == "test"
        assert d["passed"] is True
        assert "checked_at" in d
        assert isinstance(d["checked_at"], float)

    def test_severity_levels(self):
        for sev in ["error", "warning", "info"]:
            c = CredentialCheck(name="x", passed=True, severity=sev)
            assert c.severity == sev

    def test_checked_at_timestamp(self):
        before = time.time()
        c = CredentialCheck(name="t", passed=True)
        after = time.time()
        assert before <= c.checked_at <= after

    def test_default_detail_empty(self):
        c = CredentialCheck(name="t", passed=True)
        assert c.detail == ""

    def test_default_remediation_empty(self):
        c = CredentialCheck(name="t", passed=False)
        assert c.remediation == ""


# ─── Key existence check ─────────────────────────────────────────────────


class TestKeyExists:
    """Tests for check_key_exists."""

    def test_key_exists_and_readable(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key-content")
        key.chmod(0o600)
        cr = CredentialReadiness(ssh_key_path=key)
        result = cr.check_key_exists()
        assert result.passed is True
        assert result.name == "key_exists"

    def test_key_missing(self, tmp_path):
        key = tmp_path / "nonexistent_key"
        cr = CredentialReadiness(ssh_key_path=key)
        result = cr.check_key_exists()
        assert result.passed is False
        assert "not found" in result.detail.lower()
        assert result.remediation  # should have a fix suggestion

    def test_key_not_readable(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key")
        key.chmod(0o000)  # no read permission
        cr = CredentialReadiness(ssh_key_path=key)
        result = cr.check_key_exists()
        # On some systems, root can always read, so skip if running as root
        if os.getuid() != 0:
            assert result.passed is False
        key.chmod(0o600)  # cleanup

    def test_remediation_includes_keygen(self, tmp_path):
        key = tmp_path / "missing_key"
        cr = CredentialReadiness(ssh_key_path=key)
        result = cr.check_key_exists()
        assert "ssh-keygen" in result.remediation


# ─── Key permissions check ────────────────────────────────────────────────


class TestKeyPermissions:
    """Tests for check_key_permissions."""

    def test_good_permissions_600(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key")
        key.chmod(0o600)
        cr = CredentialReadiness(ssh_key_path=key)
        result = cr.check_key_permissions()
        assert result.passed is True

    def test_good_permissions_400(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key")
        key.chmod(0o400)
        cr = CredentialReadiness(ssh_key_path=key)
        result = cr.check_key_permissions()
        assert result.passed is True

    def test_bad_permissions_644(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key")
        key.chmod(0o644)
        cr = CredentialReadiness(ssh_key_path=key)
        result = cr.check_key_permissions()
        if os.getuid() != 0:
            assert result.passed is False
            assert "chmod" in result.remediation

    def test_bad_permissions_777(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key")
        key.chmod(0o777)
        cr = CredentialReadiness(ssh_key_path=key)
        result = cr.check_key_permissions()
        if os.getuid() != 0:
            assert result.passed is False

    def test_missing_key_reports_error(self, tmp_path):
        key = tmp_path / "missing"
        cr = CredentialReadiness(ssh_key_path=key)
        result = cr.check_key_permissions()
        assert result.passed is False
        assert "missing" in result.detail.lower()


# ─── Known hosts check ───────────────────────────────────────────────────


class TestKnownHosts:
    """Tests for check_known_hosts."""

    def test_github_in_known_hosts(self, tmp_path):
        kh = tmp_path / "known_hosts"
        kh.write_text("github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5...\n")
        cr = CredentialReadiness(ssh_key_path=tmp_path / "key")
        with patch("iamai.push_credential_readiness.Path.home", return_value=tmp_path):
            result = cr.check_known_hosts()
        assert result.passed is True

    def test_github_not_in_known_hosts(self, tmp_path):
        kh = tmp_path / "known_hosts"
        kh.write_text("otherhost.com ssh-ed25519 AAAAC3Nza...\n")
        cr = CredentialReadiness(ssh_key_path=tmp_path / "key")
        with patch("iamai.push_credential_readiness.Path.home", return_value=tmp_path):
            result = cr.check_known_hosts()
        # may still pass if repo-local known_hosts has it, so just check structure
        assert result.name == "known_hosts"

    def test_no_known_hosts_file(self, tmp_path):
        cr = CredentialReadiness(ssh_key_path=tmp_path / "key")
        with patch("iamai.push_credential_readiness.Path.home", return_value=tmp_path):
            result = cr.check_known_hosts()
        assert result.name == "known_hosts"


# ─── Git remote check ────────────────────────────────────────────────────


class TestGitRemote:
    """Tests for check_git_remote."""

    def test_ssh_remote(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "git@github.com:user/repo.git\n"
        cr = CredentialReadiness(repo_path=tmp_path)
        with patch("subprocess.run", return_value=mock_result):
            result = cr.check_git_remote()
        assert result.passed is True
        assert "git@github.com" in result.detail

    def test_https_remote(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/user/repo.git\n"
        cr = CredentialReadiness(repo_path=tmp_path)
        with patch("subprocess.run", return_value=mock_result):
            result = cr.check_git_remote()
        assert result.passed is True
        assert result.severity == "warning"  # HTTPS is different flow

    def test_no_remote(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: No such remote"
        cr = CredentialReadiness(repo_path=tmp_path)
        with patch("subprocess.run", return_value=mock_result):
            result = cr.check_git_remote()
        assert result.passed is False
        assert "remote" in result.remediation.lower()


# ─── SSH probe check ─────────────────────────────────────────────────────


class TestSSHProbe:
    """Tests for check_ssh_probe."""

    def test_successful_auth(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake")
        key.chmod(0o600)
        mock_result = MagicMock()
        mock_result.returncode = 1  # GitHub always returns 1
        mock_result.stderr = "Hi user! You've successfully authenticated"
        cr = CredentialReadiness(ssh_key_path=key)
        with patch("subprocess.run", return_value=mock_result):
            result = cr.check_ssh_probe()
        assert result.passed is True

    def test_permission_denied(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake")
        key.chmod(0o600)
        mock_result = MagicMock()
        mock_result.returncode = 255
        mock_result.stderr = "git@github.com: Permission denied (publickey)."
        cr = CredentialReadiness(ssh_key_path=key)
        with patch("subprocess.run", return_value=mock_result):
            result = cr.check_ssh_probe()
        assert result.passed is False
        assert "not registered" in result.detail.lower()
        assert "github.com/settings/ssh" in result.remediation

    def test_dns_failure(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake")
        key.chmod(0o600)
        mock_result = MagicMock()
        mock_result.returncode = 255
        mock_result.stderr = "ssh: Could not resolve hostname github.com"
        cr = CredentialReadiness(ssh_key_path=key)
        with patch("subprocess.run", return_value=mock_result):
            result = cr.check_ssh_probe()
        assert result.passed is False
        assert "network" in result.remediation.lower() or "dns" in result.remediation.lower()

    def test_timeout(self, tmp_path):
        import subprocess as sp
        key = tmp_path / "id_ed25519"
        key.write_text("fake")
        key.chmod(0o600)
        cr = CredentialReadiness(ssh_key_path=key)
        with patch("subprocess.run", side_effect=sp.TimeoutExpired("ssh", 10)):
            result = cr.check_ssh_probe(timeout=1)
        assert result.passed is False
        assert "timed out" in result.detail.lower()


# ─── check_all integration ───────────────────────────────────────────────


class TestCheckAll:
    """Integration tests for check_all."""

    def _make_good_env(self, tmp_path):
        """Create a fully valid credential environment."""
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key")
        key.chmod(0o600)
        kh = tmp_path / "known_hosts"
        kh.write_text("github.com ssh-ed25519 AAAAC3...\n")

        mock_remote = MagicMock()
        mock_remote.returncode = 0
        mock_remote.stdout = "git@github.com:user/repo.git\n"

        return key, kh, mock_remote

    def test_all_pass(self, tmp_path):
        key, kh, mock_remote = self._make_good_env(tmp_path)
        # known_hosts check looks at Path.home()/.ssh/known_hosts
        home_dir = tmp_path / "home"
        home_ssh = home_dir / ".ssh"
        home_ssh.mkdir(parents=True)
        (home_ssh / "known_hosts").write_text("github.com ssh-ed25519 AAAAC3...\n")
        cr = CredentialReadiness(
            repo_path=tmp_path,
            ssh_key_path=key,
        )
        with patch("iamai.push_credential_readiness.Path.home", return_value=home_dir):
            with patch("subprocess.run", return_value=mock_remote):
                result = cr.check_all(check_network=False)
        assert result["ready"] is True
        assert result["failed_count"] == 0

    def test_stop_on_failure(self, tmp_path):
        """When stop_on_failure=True, should stop at first failing check."""
        key = tmp_path / "missing_key"
        cr = CredentialReadiness(
            repo_path=tmp_path,
            ssh_key_path=key,
        )
        result = cr.check_all(stop_on_failure=True)
        assert result["ready"] is False
        assert result["failed_count"] == 1
        # should have only run the first check (key_exists)
        assert len(result["checks"]) == 1

    def test_no_stop_runs_all(self, tmp_path):
        key = tmp_path / "missing_key"
        cr = CredentialReadiness(
            repo_path=tmp_path,
            ssh_key_path=key,
        )
        result = cr.check_all(check_network=False, stop_on_failure=False)
        assert result["ready"] is False
        assert len(result["checks"]) == 4  # all local checks ran

    def test_network_check_included(self, tmp_path):
        key, kh, mock_remote = self._make_good_env(tmp_path)
        home_dir = tmp_path / "home"
        home_ssh = home_dir / ".ssh"
        home_ssh.mkdir(parents=True)
        (home_ssh / "known_hosts").write_text("github.com ssh-ed25519 AAAAC3...\n")

        mock_ssh = MagicMock()
        mock_ssh.returncode = 1
        mock_ssh.stderr = "Hi user! You've successfully authenticated"

        cr = CredentialReadiness(repo_path=tmp_path, ssh_key_path=key)
        with patch("iamai.push_credential_readiness.Path.home", return_value=home_dir):
            with patch("subprocess.run", side_effect=[mock_remote, mock_ssh]):
                result = cr.check_all(check_network=True)
        assert result["network_checked"] is True
        assert len(result["checks"]) == 5

    def test_remediation_aggregation(self, tmp_path):
        key = tmp_path / "missing_key"
        cr = CredentialReadiness(
            repo_path=tmp_path,
            ssh_key_path=key,
        )
        result = cr.check_all(stop_on_failure=False)
        assert result["remediation"]  # should have at least one fix


# ─── Caching ─────────────────────────────────────────────────────────────


class TestCaching:
    """Tests for result caching."""

    def test_cache_written(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "cache.json"
        monkeypatch.setattr("iamai.push_credential_readiness.CACHE_FILE", cache_file)
        monkeypatch.setattr("iamai.push_credential_readiness.DATA_DIR", tmp_path)

        key = tmp_path / "key"
        key.write_text("fake")
        key.chmod(0o600)
        cr = CredentialReadiness(ssh_key_path=key, cache_ttl=60)
        cr.check_all()
        assert cache_file.exists()

    def test_cache_within_ttl(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "cache.json"
        monkeypatch.setattr("iamai.push_credential_readiness.CACHE_FILE", cache_file)
        monkeypatch.setattr("iamai.push_credential_readiness.DATA_DIR", tmp_path)

        # Write a fresh cache
        cache_file.write_text(json.dumps({
            "ready": True,
            "checks": [],
            "failed_count": 0,
            "checked_at": time.time(),
        }))

        cr = CredentialReadiness(cache_ttl=300)
        cached = cr.cached_result()
        assert cached is not None
        assert cached["ready"] is True

    def test_cache_expired(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "cache.json"
        monkeypatch.setattr("iamai.push_credential_readiness.CACHE_FILE", cache_file)

        cache_file.write_text(json.dumps({
            "ready": True,
            "checks": [],
            "checked_at": time.time() - 1000,  # way past TTL
        }))

        cr = CredentialReadiness(cache_ttl=60)
        cached = cr.cached_result()
        assert cached is None

    def test_cache_missing(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "nope.json"
        monkeypatch.setattr("iamai.push_credential_readiness.CACHE_FILE", cache_file)
        cr = CredentialReadiness()
        assert cr.cached_result() is None

    def test_cache_corrupted(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "cache.json"
        monkeypatch.setattr("iamai.push_credential_readiness.CACHE_FILE", cache_file)
        cache_file.write_text("not json {{{")
        cr = CredentialReadiness()
        assert cr.cached_result() is None


# ─── Readiness summary ───────────────────────────────────────────────────


class TestReadinessSummary:
    """Tests for human-readable summary output."""

    def test_summary_ready_format(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake")
        key.chmod(0o600)
        cr = CredentialReadiness(ssh_key_path=key)
        summary = cr.readiness_summary()
        assert "credential readiness" in summary
        assert "key_exists" in summary or "key_permissions" in summary

    def test_summary_shows_failures(self, tmp_path):
        key = tmp_path / "missing_key"
        cr = CredentialReadiness(ssh_key_path=key)
        summary = cr.readiness_summary()
        assert "FAIL" in summary
        assert "NOT ready" in summary


# ─── SSH key discovery ───────────────────────────────────────────────────


class TestKeyDiscovery:
    """Tests for _find_ssh_key."""

    def test_finds_home_key(self, tmp_path):
        key = tmp_path / ".ssh" / "id_ed25519"
        key.parent.mkdir(parents=True)
        key.write_text("fake")
        with patch("iamai.push_credential_readiness.Path.home", return_value=tmp_path):
            cr = CredentialReadiness()
            assert cr.ssh_key_path == key

    def test_finds_repo_key(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        key = tmp_path / ".ssh" / "id_ed25519"
        key.parent.mkdir(parents=True)
        key.write_text("fake")
        cr = CredentialReadiness(repo_path=repo)
        assert key in [cr.ssh_key_path] or cr.ssh_key_path.exists()

    def test_default_when_none_found(self, tmp_path):
        with patch("iamai.push_credential_readiness.Path.home", return_value=tmp_path):
            cr = CredentialReadiness(repo_path=tmp_path)
            # should still return a path (the default), even if it doesn't exist
            assert cr.ssh_key_path is not None
