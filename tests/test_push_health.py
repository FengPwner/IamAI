#!/usr/bin/env python3
"""Tests for iamai.push_health — push readiness checker."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from iamai.push_health import PushHealth, PushStatus


class TestPushStatus:
    """PushStatus dataclass tests."""
    
    def test_ready_status(self):
        s = PushStatus(ready=True, status="ready")
        assert s.ready is True
        assert s.status == "ready"
        assert s.error is None
    
    def test_no_key_status(self):
        s = PushStatus(ready=False, status="no_key", error="missing")
        assert s.ready is False
        assert s.status == "no_key"
        assert s.error == "missing"
    
    def test_default_fields(self):
        s = PushStatus(ready=False, status="no_key")
        assert s.ssh_key_path is None
        assert s.ssh_key_exists is False
        assert s.ssh_key_readable is False
        assert s.ssh_agent_has_key is False
        assert s.dry_run_success is False


class TestPushHealthInit:
    """PushHealth initialization tests."""
    
    def test_default_repo_path(self):
        checker = PushHealth()
        assert checker.repo_path == Path(".").resolve()
    
    def test_explicit_repo_path(self, tmp_path):
        checker = PushHealth(repo_path=str(tmp_path))
        assert checker.repo_path == tmp_path.resolve()
    
    def test_explicit_key_path(self, tmp_path):
        key = tmp_path / "my_key"
        key.write_text("fake key")
        checker = PushHealth(key_path=str(key))
        assert checker.key_path == key
    
    def test_no_key_path(self):
        checker = PushHealth()
        assert checker.key_path is None


class TestFindSSHKey:
    """SSH key discovery tests."""
    
    def test_finds_explicit_key(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----")
        checker = PushHealth(key_path=str(key))
        found = checker._find_ssh_key()
        assert found == key
    
    def test_returns_none_for_missing_explicit_key(self, tmp_path):
        checker = PushHealth(key_path=str(tmp_path / "nonexistent"))
        assert checker._find_ssh_key() is None
    
    def test_finds_key_in_default_locations(self, tmp_path, monkeypatch):
        fake_ssh = tmp_path / ".ssh"
        fake_ssh.mkdir()
        key = fake_ssh / "id_ed25519"
        key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----")
        
        monkeypatch.setattr(Path, "expanduser", lambda self: Path(str(self).replace("~", str(tmp_path))))
        checker = PushHealth()
        found = checker._find_ssh_key()
        assert found is not None
    
    def test_returns_none_when_no_keys_exist(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "expanduser", lambda self: Path(str(self).replace("~", str(tmp_path))))
        checker = PushHealth()
        assert checker._find_ssh_key() is None


class TestKeyReadable:
    """SSH key readability tests."""
    
    def test_readable_valid_key(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nfake content\n-----END OPENSSH PRIVATE KEY-----")
        checker = PushHealth()
        assert checker._key_readable(key) is True
    
    def test_unreadable_empty_file(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("")
        checker = PushHealth()
        assert checker._key_readable(key) is False
    
    def test_unreadable_wrong_content(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("this is not a key file")
        checker = PushHealth()
        assert checker._key_readable(key) is False
    
    def test_unreadable_missing_file(self, tmp_path):
        checker = PushHealth()
        assert checker._key_readable(tmp_path / "nope") is False


class TestSSHAgent:
    """ssh-agent detection tests."""
    
    def test_agent_has_keys(self):
        checker = PushHealth()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "2048 SHA256:abc key1 (RSA)"
        with patch("subprocess.run", return_value=mock_result):
            assert checker._check_ssh_agent() is True
    
    def test_agent_no_identities(self):
        checker = PushHealth()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "The agent has no identities."
        with patch("subprocess.run", return_value=mock_result):
            assert checker._check_ssh_agent() is False
    
    def test_agent_ssh_add_missing(self):
        checker = PushHealth()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert checker._check_ssh_agent() is False
    
    def test_agent_timeout(self):
        checker = PushHealth()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh-add", 5)):
            assert checker._check_ssh_agent() is False


class TestDryRunPush:
    """Push dry-run tests."""
    
    def test_successful_push(self, tmp_path):
        checker = PushHealth(repo_path=str(tmp_path))
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = "Everything up-to-date"
        with patch("subprocess.run", return_value=mock_result):
            ok, err = checker._dry_run_push()
            assert ok is True
            assert err is None
    
    def test_failed_push(self, tmp_path):
        checker = PushHealth(repo_path=str(tmp_path))
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "Permission denied (publickey)."
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            ok, err = checker._dry_run_push()
            assert ok is False
            assert "Permission denied" in err
    
    def test_timeout_push(self, tmp_path):
        checker = PushHealth(repo_path=str(tmp_path))
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            ok, err = checker._dry_run_push()
            assert ok is False
            assert "timed out" in err.lower()


class TestFullCheck:
    """Integration-level check tests."""
    
    def test_no_key_returns_no_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "expanduser", lambda self: Path(str(self).replace("~", str(tmp_path))))
        checker = PushHealth()
        result = checker.check()
        assert result.ready is False
        assert result.status == "no_key"
    
    def test_ready_when_all_good(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----")
        checker = PushHealth(repo_path=str(tmp_path), key_path=str(key))
        
        with patch.object(checker, "_check_ssh_agent", return_value=True), \
             patch.object(checker, "_dry_run_push", return_value=(True, None)):
            result = checker.check()
            assert result.ready is True
            assert result.status == "ready"
            assert result.dry_run_success is True
    
    def test_push_failed_status(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----")
        checker = PushHealth(repo_path=str(tmp_path), key_path=str(key))
        
        with patch.object(checker, "_check_ssh_agent", return_value=False), \
             patch.object(checker, "_dry_run_push", return_value=(False, "remote error")):
            result = checker.check()
            assert result.ready is False
            assert result.status == "push_failed"
            assert result.error == "remote error"


class TestCLI:
    """CLI output tests."""
    
    def test_json_output(self, tmp_path, capsys):
        key = tmp_path / "id_ed25519"
        key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----")
        
        from iamai.push_health import main
        with patch("sys.argv", ["push_health", "--repo", str(tmp_path), "--key", str(key), "--json"]):
            with patch.object(PushHealth, "check", return_value=PushStatus(ready=True, status="ready")):
                main()
        
        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["ready"] is True
        assert data["status"] == "ready"
    
    def test_text_output_ready(self, tmp_path, capsys):
        from iamai.push_health import main
        with patch("sys.argv", ["push_health", "--repo", str(tmp_path)]):
            with patch.object(PushHealth, "check", return_value=PushStatus(
                ready=True, status="ready", ssh_key_path="/root/.ssh/id_ed25519"
            )):
                main()
        
        output = capsys.readouterr().out
        assert "✓" in output
        assert "ready" in output
    
    def test_text_output_not_ready(self, tmp_path, capsys):
        from iamai.push_health import main
        with patch("sys.argv", ["push_health", "--repo", str(tmp_path)]):
            with patch.object(PushHealth, "check", return_value=PushStatus(
                ready=False, status="no_key", error="No SSH key found"
            )):
                main()
        
        output = capsys.readouterr().out
        assert "✗" in output
        assert "no_key" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
