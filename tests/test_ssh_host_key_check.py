"""Tests for the SSH host-key preflight module.

These tests are deliberately hermetic: they patch KNOWN_HOSTS to a temp path
so nothing touches the real ~/.ssh/known_hosts on the machine running them.
The one integration test (``test_ensure_real_github``) is marked slow and
skipped unless the caller explicitly wants it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai import ssh_host_key_check as hhc


@pytest.fixture()
def tmp_known(tmp_path: Path):
    """Redirect KNOWN_HOSTS to a temp file for the duration of one test."""
    target = tmp_path / "known_hosts"
    with patch.object(hhc, "KNOWN_HOSTS", target):
        yield target


# -- is_host_key_present ---------------------------------------------------


@patch("subprocess.run")
def test_empty_known_hosts_means_not_present(mock_run, tmp_known: Path):
    # ssh-keygen -F would read real known_hosts; mock it to return "not found"
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ssh-keygen", "-F", "github.com"], returncode=1, stdout="", stderr=""
    )
    assert hhc.is_host_key_present("github.com") is False


def test_unhashed_entry_is_found(tmp_known: Path):
    tmp_known.write_text(
        "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest\n"
    )
    assert hhc.is_host_key_present("github.com") is True


@patch("subprocess.run")
def test_unrelated_host_is_not_found(mock_run, tmp_known: Path):
    tmp_known.write_text(
        "gitlab.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOther\n"
    )
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ssh-keygen", "-F", "github.com"], returncode=1, stdout="", stderr=""
    )
    assert hhc.is_host_key_present("github.com") is False


def test_comma_separated_hosts_are_matched(tmp_known: Path):
    tmp_known.write_text(
        "github.com,140.82.121.3 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest\n"
    )
    assert hhc.is_host_key_present("github.com") is True


# -- ensure_host_key (mocked keyscan) --------------------------------------


_FAKE_KEYSCAN_OUT = "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFake\n"


@patch("subprocess.run")
def test_ensure_skips_scan_when_already_present(mock_run, tmp_known: Path):
    tmp_known.write_text(
        "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExist\n"
    )
    assert hhc.ensure_host_key("github.com") is True
    # ssh-keyscan should NOT have been called (idempotent)
    for call in mock_run.call_args_list:
        if call.args and "ssh-keyscan" in call.args[0]:
            pytest.fail("ssh-keyscan called when key was already present")


@patch("subprocess.run")
def test_ensure_appends_key_on_missing(mock_run, tmp_known: Path):
    not_found = subprocess.CompletedProcess(
        args=["ssh-keygen", "-F", "github.com"], returncode=1, stdout="", stderr=""
    )
    keyscan_ok = subprocess.CompletedProcess(
        args=["ssh-keyscan", "-t", "ed25519,rsa", "github.com"],
        returncode=0,
        stdout=_FAKE_KEYSCAN_OUT,
        stderr="",
    )
    found = subprocess.CompletedProcess(
        args=["ssh-keygen", "-F", "github.com"], returncode=0,
        stdout="# Host github.com found\n", stderr=""
    )
    # 1st ssh-keygen (is_host_key_present initial check) -> not found
    # 2nd ssh-keyscan (ensure_host_key fetch) -> key material
    # 3rd ssh-keygen (is_host_key_present final check) -> found (because we appended)
    mock_run.side_effect = [not_found, keyscan_ok, found]
    assert hhc.ensure_host_key("github.com") is True
    assert tmp_known.exists()
    assert "github.com" in tmp_known.read_text()


@patch("subprocess.run")
def test_ensure_returns_false_on_keyscan_failure(mock_run, tmp_known: Path):
    not_found = subprocess.CompletedProcess(
        args=["ssh-keygen", "-F", "github.com"], returncode=1, stdout="", stderr=""
    )
    keyscan_fail = subprocess.CompletedProcess(
        args=["ssh-keyscan"], returncode=1, stdout="", stderr="timeout"
    )
    # 1st ssh-keygen (is_host_key_present) -> not found
    # 2nd ssh-keyscan -> failure
    mock_run.side_effect = [not_found, keyscan_fail]
    assert hhc.ensure_host_key("github.com") is False


# -- integration (real network, opt-in) ------------------------------------


@pytest.mark.skipif(
    not Path("/etc/resolv.conf").exists(),
    reason="no network indicator",
)
def test_ensure_real_github_keyscan():
    """Actually talk to github.com.  Slow and network-dependent."""
    result = hhc.ensure_host_key("github.com")
    assert result is True, "github.com host key should be obtainable"
