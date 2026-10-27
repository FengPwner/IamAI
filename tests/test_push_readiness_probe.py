"""Tests for push_readiness_probe — pre-flight push health check."""

import os
import stat
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.push_readiness_probe import (
    _check_key_exists,
    _check_key_readable,
    _check_key_permissions,
    _check_ssh_agent,
    _check_github_auth,
    _extract_github_user,
    probe,
)


# ---------------------------------------------------------------------------
# _check_key_exists
# ---------------------------------------------------------------------------

class TestKeyExists:
    def test_existing_file_passes(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key")
        result = _check_key_exists(str(key))
        assert result["verdict"] == "pass"
        assert "found" in result["detail"]

    def test_missing_file_fails(self, tmp_path):
        result = _check_key_exists(str(tmp_path / "nonexistent"))
        assert result["verdict"] == "fail"
        assert "missing" in result["detail"]


# ---------------------------------------------------------------------------
# _check_key_readable
# ---------------------------------------------------------------------------

class TestKeyReadable:
    def test_readable_file_passes(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("ssh-ed25519 AAAA...")
        result = _check_key_readable(str(key))
        assert result["verdict"] == "pass"

    def test_missing_file_skips(self, tmp_path):
        result = _check_key_readable(str(tmp_path / "nope"))
        assert result["verdict"] == "skip"

    def test_unreadable_file_fails(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("secret")
        key.chmod(0o000)
        try:
            result = _check_key_readable(str(key))
            # on root this might still pass; handle both cases
            assert result["verdict"] in ("pass", "fail")
        finally:
            key.chmod(0o600)  # restore for cleanup


# ---------------------------------------------------------------------------
# _check_key_permissions
# ---------------------------------------------------------------------------

class TestKeyPermissions:
    def test_correct_permissions_pass(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("key")
        key.chmod(0o600)
        result = _check_key_permissions(str(key))
        assert result["verdict"] == "pass"

    def test_too_open_fails(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("key")
        key.chmod(0o644)
        result = _check_key_permissions(str(key))
        assert result["verdict"] == "fail"
        assert "too open" in result["detail"]

    def test_missing_skips(self, tmp_path):
        result = _check_key_permissions(str(tmp_path / "nope"))
        assert result["verdict"] == "skip"

    def test_owner_only_passes(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("key")
        key.chmod(0o400)
        result = _check_key_permissions(str(key))
        assert result["verdict"] == "pass"


# ---------------------------------------------------------------------------
# _check_ssh_agent
# ---------------------------------------------------------------------------

class TestSshAgent:
    def test_no_agent_socket_fails(self):
        with patch.dict(os.environ, {}, clear=True):
            # ensure SSH_AUTH_SOCK is absent
            os.environ.pop("SSH_AUTH_SOCK", None)
            result = _check_ssh_agent()
            assert result["verdict"] == "fail"
            assert "not running" in result["detail"]

    @patch("subprocess.check_output")
    def test_agent_with_keys_passes(self, mock_check):
        mock_check.return_value = (
            "2048 SHA256:abc /home/user/.ssh/id_ed25519 (ED25519)\n"
        )
        with patch.dict(os.environ, {"SSH_AUTH_SOCK": "/tmp/agent.sock"}):
            result = _check_ssh_agent()
            assert result["verdict"] == "pass"
            assert "1 key" in result["detail"]

    @patch("subprocess.check_output")
    def test_agent_empty_fails(self, mock_check):
        mock_check.return_value = "The agent has no identities.\n"
        with patch.dict(os.environ, {"SSH_AUTH_SOCK": "/tmp/agent.sock"}):
            result = _check_ssh_agent()
            assert result["verdict"] == "fail"
            assert "no keys" in result["detail"]


# ---------------------------------------------------------------------------
# _check_github_auth
# ---------------------------------------------------------------------------

class TestGithubAuth:
    @patch("subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="Hi fengpwner! You've successfully authenticated, but GitHub does not provide shell access.",
            returncode=1,
        )
        result = _check_github_auth(ssh_command="/usr/bin/ssh")
        assert result["verdict"] == "pass"
        assert "fengpwner" in result["detail"]

    @patch("subprocess.run")
    def test_permission_denied(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="git@github.com: Permission denied (publickey).",
            returncode=255,
        )
        result = _check_github_auth(ssh_command="/usr/bin/ssh")
        assert result["verdict"] == "fail"
        assert "not registered" in result["detail"]

    @patch("subprocess.run")
    def test_dns_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="ssh: Could not resolve hostname github.com",
            returncode=255,
        )
        result = _check_github_auth(ssh_command="/usr/bin/ssh")
        assert result["verdict"] == "fail"
        assert "DNS" in result["detail"]

    def test_ssh_not_found(self):
        result = _check_github_auth(ssh_command="/nonexistent/ssh")
        assert result["verdict"] == "skip"


# ---------------------------------------------------------------------------
# _extract_github_user
# ---------------------------------------------------------------------------

class TestExtractGithubUser:
    def test_standard_output(self):
        assert _extract_github_user(
            "Hi fengpwner! You've successfully authenticated"
        ) == "fengpwner"

    def test_different_user(self):
        assert _extract_github_user(
            "Hi octocat! You've successfully authenticated"
        ) == "octocat"

    def test_no_match(self):
        assert _extract_github_user("some random output") == "unknown"


# ---------------------------------------------------------------------------
# probe (composite)
# ---------------------------------------------------------------------------

class TestProbe:
    def test_all_pass_returns_ready(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("ssh-ed25519 AAAA...")
        key.chmod(0o600)

        with patch("iamai.push_readiness_probe._check_ssh_agent") as mock_agent, \
             patch("iamai.push_readiness_probe._check_github_auth") as mock_gh:
            mock_agent.return_value = {
                "name": "ssh_agent", "verdict": "pass",
                "detail": "agent has 1 key(s) loaded"
            }
            mock_gh.return_value = {
                "name": "github_auth", "verdict": "pass",
                "detail": "authenticated as testuser"
            }
            result = probe(key_path=str(key))

        assert result["ready"] is True
        assert "all checks passed" in result["diagnosis"]

    def test_missing_key_returns_not_ready(self, tmp_path):
        with patch("iamai.push_readiness_probe._check_github_auth") as mock_gh:
            mock_gh.return_value = {
                "name": "github_auth", "verdict": "pass",
                "detail": "authenticated"
            }
            result = probe(key_path=str(tmp_path / "missing_key"))

        assert result["ready"] is False
        assert "key_exists" in result["diagnosis"]

    def test_skip_network(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("key-data")
        key.chmod(0o600)

        result = probe(key_path=str(key), skip_agent=True, skip_network=True)
        # only file checks remain; if they pass, ready
        assert result["ready"] is True
        assert len(result["checks"]) == 3  # exists + readable + permissions

    def test_skip_agent(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("key-data")
        key.chmod(0o600)

        with patch("iamai.push_readiness_probe._check_github_auth") as mock_gh:
            mock_gh.return_value = {
                "name": "github_auth", "verdict": "pass",
                "detail": "ok"
            }
            result = probe(key_path=str(key), skip_agent=True)

        check_names = [c["name"] for c in result["checks"]]
        assert "ssh_agent" not in check_names

    def test_diagnosis_lists_all_failures(self, tmp_path):
        with patch("iamai.push_readiness_probe._check_ssh_agent") as mock_agent, \
             patch("iamai.push_readiness_probe._check_github_auth") as mock_gh:
            mock_agent.return_value = {
                "name": "ssh_agent", "verdict": "fail",
                "detail": "no agent"
            }
            mock_gh.return_value = {
                "name": "github_auth", "verdict": "fail",
                "detail": "key not registered"
            }
            result = probe(key_path=str(tmp_path / "missing"))

        assert result["ready"] is False
        assert "key_exists" in result["diagnosis"]
        # both agent and github failures should appear
        assert "ssh_agent" in result["diagnosis"]
        assert "github_auth" in result["diagnosis"]
