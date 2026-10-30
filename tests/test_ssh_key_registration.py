"""tests for ssh_key_registration module.

these tests verify the fingerprint extraction and connection testing
logic without making actual network calls to github. the network
layer is tested separately by push_preflight.py's integration tests.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from iamai.ssh_key_registration import (
    KeyCheck,
    KeyStatus,
    check_key_registration,
    extract_fingerprint,
    probe_ssh_connection,
)


def test_extract_fingerprint_missing_pub_file(tmp_path: Path):
    """fingerprint extraction returns None when .pub file is missing."""
    key_path = tmp_path / "id_ed25519"
    key_path.write_text("private key content")
    assert extract_fingerprint(key_path) is None


def test_extract_fingerprint_valid_file(tmp_path: Path):
    """fingerprint extraction parses ssh-keygen output correctly."""
    key_path = tmp_path / "id_ed25519"
    pub_path = tmp_path / "id_ed25519.pub"
    key_path.write_text("private key content")
    pub_path.write_text("ssh-ed25519 AAAAC3... user@host")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="256 SHA256:umMVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk user@host (ED25519)\n",
        )
        fingerprint = extract_fingerprint(key_path)
        assert fingerprint == "SHA256:umMVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk"


def test_extract_fingerprint_subprocess_failure(tmp_path: Path):
    """fingerprint extraction returns None on subprocess failure."""
    key_path = tmp_path / "id_ed25519"
    pub_path = tmp_path / "id_ed25519.pub"
    key_path.write_text("private key content")
    pub_path.write_text("ssh-ed25519 AAAAC3... user@host")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert extract_fingerprint(key_path) is None


def test_probe_ssh_connection_success():
    """ssh connection test parses successful authentication output."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,  # github returns exit 1 even on success
            stdout="Hi FengPwner! You've successfully authenticated",
            stderr="",
        )
        success, message = probe_ssh_connection(Path("/tmp/test_key"))
        assert success is True
        assert "Hi FengPwner" in message


def test_probe_ssh_connection_permission_denied():
    """ssh connection test detects permission denied."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=255,
            stdout="",
            stderr="git@github.com: Permission denied (publickey).",
        )
        success, message = probe_ssh_connection(Path("/tmp/test_key"))
        assert success is False
        assert "permission denied" in message.lower()


def test_probe_ssh_connection_timeout():
    """ssh connection test handles timeout gracefully."""
    from subprocess import TimeoutExpired

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = TimeoutExpired(cmd="ssh", timeout=10)
        success, message = probe_ssh_connection(Path("/tmp/test_key"))
        assert success is False
        assert "timeout" in message.lower()


def test_check_key_registration_missing_key(tmp_path: Path):
    """registration check returns UNKNOWN for missing key file."""
    key_path = tmp_path / "nonexistent_key"
    result = check_key_registration(key_path)
    assert result.status == KeyStatus.UNKNOWN
    assert "does not exist" in result.reason


def test_check_key_registration_registered(tmp_path: Path):
    """registration check returns REGISTERED on successful auth."""
    key_path = tmp_path / "id_ed25519"
    pub_path = tmp_path / "id_ed25519.pub"
    key_path.write_text("private key content")
    pub_path.write_text("ssh-ed25519 AAAAC3... user@host")

    with patch("iamai.ssh_key_registration.extract_fingerprint") as mock_fp, \
         patch("iamai.ssh_key_registration.probe_ssh_connection") as mock_conn:
        mock_fp.return_value = "SHA256:testfingerprint"
        mock_conn.return_value = (True, "Hi user!")
        result = check_key_registration(key_path)
        assert result.status == KeyStatus.REGISTERED
        assert result.fingerprint == "SHA256:testfingerprint"


def test_check_key_registration_unregistered(tmp_path: Path):
    """registration check returns UNREGISTERED on permission denied."""
    key_path = tmp_path / "id_ed25519"
    pub_path = tmp_path / "id_ed25519.pub"
    key_path.write_text("private key content")
    pub_path.write_text("ssh-ed25519 AAAAC3... user@host")

    with patch("iamai.ssh_key_registration.extract_fingerprint") as mock_fp, \
         patch("iamai.ssh_key_registration.probe_ssh_connection") as mock_conn:
        mock_fp.return_value = "SHA256:testfingerprint"
        mock_conn.return_value = (False, "permission denied")
        result = check_key_registration(key_path)
        assert result.status == KeyStatus.UNREGISTERED
        assert result.fingerprint == "SHA256:testfingerprint"


def test_check_key_registration_unknown_failure(tmp_path: Path):
    """registration check returns UNKNOWN on non-permission failures."""
    key_path = tmp_path / "id_ed25519"
    pub_path = tmp_path / "id_ed25519.pub"
    key_path.write_text("private key content")
    pub_path.write_text("ssh-ed25519 AAAAC3... user@host")

    with patch("iamai.ssh_key_registration.extract_fingerprint") as mock_fp, \
         patch("iamai.ssh_key_registration.probe_ssh_connection") as mock_conn:
        mock_fp.return_value = "SHA256:testfingerprint"
        mock_conn.return_value = (False, "connection timeout")
        result = check_key_registration(key_path)
        assert result.status == KeyStatus.UNKNOWN
        assert "timeout" in result.reason.lower()
