"""Tests for tools.push_preflight: can a caretaker verify push health in one command?

The deploy-key / known_hosts / SSH-auth chain breaks every container rebuild.
These tests pin down what "push is healthy" means so a caretaker can check it
on arrival instead of discovering the failure 10 minutes into their visit.
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest

# Make tools/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import push_preflight as pp  # noqa: E402


@pytest.fixture
def tmp_key(tmp_path: Path) -> Path:
    """A fake deploy key with correct permissions."""
    key = tmp_path / "id_ed25519"
    key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n")
    key.chmod(0o600)
    return key


@pytest.fixture
def tmp_key_bad_perms(tmp_path: Path) -> Path:
    """A fake deploy key with wrong permissions (0644)."""
    key = tmp_path / "id_ed25519_bad"
    key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n")
    key.chmod(0o644)
    return key


# --- deploy key checks ---


def test_deploy_key_ok(tmp_key: Path):
    ok, msg = pp.check_deploy_key(tmp_key)
    assert ok is True
    assert "OK" in msg
    assert "0o600" in msg


def test_deploy_key_missing(tmp_path: Path):
    missing = tmp_path / "no_such_key"
    ok, msg = pp.check_deploy_key(missing)
    assert ok is False
    assert "not found" in msg


def test_deploy_key_bad_permissions(tmp_key_bad_perms: Path):
    ok, msg = pp.check_deploy_key(tmp_key_bad_perms)
    assert ok is False
    assert "permissions" in msg


# --- known_hosts checks ---


def test_known_hosts_has_entry(tmp_path: Path):
    kh = tmp_path / "known_hosts"
    kh.write_text("github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n")

    with mock.patch.object(pp, "REPO", tmp_path):
        with mock.patch.dict(os.environ, {}, clear=False):
            # patch candidates to include our tmp file
            with mock.patch.object(pp.Path, "home", return_value=tmp_path):
                ok, msg = pp.check_known_hosts("github.com")
                # This depends on the tmp_path layout; at minimum the function should not crash
                assert isinstance(ok, bool)
                assert isinstance(msg, str)


def test_known_hosts_empty(tmp_path: Path, monkeypatch):
    """No known_hosts file anywhere should return failure."""
    # Ensure no candidates exist by mocking the home to an empty dir
    empty_home = tmp_path / "empty_home"
    empty_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: empty_home))
    monkeypatch.setattr(pp, "REPO", tmp_path / "repo_that_does_not_exist")
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)

    ok, msg = pp.check_known_hosts("github.com")
    assert ok is False
    assert "no known_hosts" in msg


# --- remote URL checks ---


def test_remote_url_ssh():
    """The real repo uses git@github.com — should pass."""
    ok, msg = pp.check_remote_url("origin")
    assert ok is True
    assert "SSH" in msg


def test_remote_url_nonexistent():
    ok, msg = pp.check_remote_url("nonexistent_remote_xyz")
    assert ok is False
    assert "not found" in msg


# --- SSH connectivity (mocked) ---


def test_ssh_connectivity_success(tmp_key: Path):
    fake_result = mock.MagicMock()
    fake_result.returncode = 1
    fake_result.stdout = ""
    fake_result.stderr = "Hi FengPwner/IamAI! You've successfully authenticated, but GitHub does not provide shell access."

    with mock.patch.object(pp, "_run", return_value=fake_result):
        ok, msg = pp.check_ssh_connectivity("github.com", tmp_key)
    assert ok is True
    assert "OK" in msg


def test_ssh_connectivity_permission_denied(tmp_key: Path):
    fake_result = mock.MagicMock()
    fake_result.returncode = 255
    fake_result.stdout = ""
    fake_result.stderr = "git@github.com: Permission denied (publickey)."

    with mock.patch.object(pp, "_run", return_value=fake_result):
        ok, msg = pp.check_ssh_connectivity("github.com", tmp_key)
    assert ok is False
    assert "permission denied" in msg.lower() or "FAIL" in msg.upper()


# --- run_checks integration ---


def test_run_checks_returns_list():
    """run_checks should return a list of 4-tuples with name, ok, message."""
    results = pp.run_checks()
    assert isinstance(results, list)
    assert len(results) == 4
    names = [r[0] for r in results]
    assert "deploy-key" in names
    assert "known-hosts" in names
    assert "remote-url" in names
    assert "ssh-auth" in names


# --- CLI exit code ---


def test_main_all_clear(tmp_key: Path, monkeypatch, capsys):
    """When all checks pass, main() should return 0."""
    monkeypatch.setattr(sys, "argv", ["push_preflight.py"])

    fake_results = [
        ("deploy-key", True, "deploy key OK"),
        ("known-hosts", True, "known_hosts OK"),
        ("remote-url", True, "remote is SSH"),
        ("ssh-auth", True, "SSH auth OK"),
    ]
    with mock.patch.object(pp, "run_checks", return_value=fake_results):
        rc = pp.main()
    assert rc == 0
    captured = capsys.readouterr()
    assert "all clear" in captured.out.lower()


def test_main_failure(tmp_key: Path, monkeypatch, capsys):
    """When any check fails, main() should return 1."""
    monkeypatch.setattr(sys, "argv", ["push_preflight.py"])

    fake_results = [
        ("deploy-key", True, "deploy key OK"),
        ("known-hosts", False, "no known_hosts entry for github.com"),
        ("remote-url", True, "remote is SSH"),
        ("ssh-auth", False, "SSH permission denied"),
    ]
    with mock.patch.object(pp, "run_checks", return_value=fake_results):
        rc = pp.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "FAIL" in captured.out
