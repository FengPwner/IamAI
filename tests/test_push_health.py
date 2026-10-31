"""Tests for iamai.push_health — SSH deploy-key pre-flight checks.

Covers:
  - key_mode_ok: permissions boundary (0600 ok, 0644 not, missing file)
  - PushDiagnosis: healthy property, dataclass immutability
  - format_diagnosis: output for healthy vs each failure mode
  - diagnose_push: integration-ish check with real temp key files
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.push_health import (
    PushDiagnosis,
    diagnose_push,
    format_diagnosis,
    key_mode_ok,
)


# -- key_mode_ok -------------------------------------------------------------

class TestKeyModeOk:
    def test_mode_600_is_ok(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key")
        key.chmod(0o600)
        assert key_mode_ok(key) is True

    def test_mode_400_is_ok(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key")
        key.chmod(0o400)
        assert key_mode_ok(key) is True

    def test_mode_644_is_not_ok(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key")
        key.chmod(0o644)
        assert key_mode_ok(key) is False

    def test_mode_777_is_not_ok(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key")
        key.chmod(0o777)
        assert key_mode_ok(key) is False

    def test_mode_660_is_not_ok(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key")
        key.chmod(0o660)
        assert key_mode_ok(key) is False

    def test_missing_file_returns_false(self, tmp_path):
        assert key_mode_ok(tmp_path / "nonexistent") is False

    def test_directory_returns_false(self, tmp_path):
        d = tmp_path / "not_a_file"
        d.mkdir()
        d.chmod(0o600)
        assert key_mode_ok(d) is False

    def test_accepts_string_path(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake-key")
        key.chmod(0o600)
        assert key_mode_ok(str(key)) is True


# -- PushDiagnosis -----------------------------------------------------------

class TestPushDiagnosis:
    def test_healthy_when_all_true(self):
        d = PushDiagnosis(
            key_exists=True,
            key_permissions_ok=True,
            ssh_connects=True,
            key_path="/tmp/key",
            remote_host="github.com",
        )
        assert d.healthy is True

    def test_unhealthy_when_key_missing(self):
        d = PushDiagnosis(
            key_exists=False,
            key_permissions_ok=False,
            ssh_connects=False,
            key_path="/tmp/key",
            remote_host="github.com",
        )
        assert d.healthy is False

    def test_unhealthy_when_perms_bad(self):
        d = PushDiagnosis(
            key_exists=True,
            key_permissions_ok=False,
            ssh_connects=False,
            key_path="/tmp/key",
            remote_host="github.com",
        )
        assert d.healthy is False

    def test_unhealthy_when_ssh_fails(self):
        d = PushDiagnosis(
            key_exists=True,
            key_permissions_ok=True,
            ssh_connects=False,
            key_path="/tmp/key",
            remote_host="github.com",
        )
        assert d.healthy is False

    def test_frozen_dataclass(self):
        d = PushDiagnosis(
            key_exists=True,
            key_permissions_ok=True,
            ssh_connects=True,
            key_path="/tmp/key",
            remote_host="github.com",
        )
        with pytest.raises(AttributeError):
            d.key_exists = False  # type: ignore[misc]


# -- format_diagnosis --------------------------------------------------------

class TestFormatDiagnosis:
    def test_healthy_output(self):
        d = PushDiagnosis(True, True, True, "/tmp/key", "github.com")
        assert format_diagnosis(d) == "push pre-flight: OK"

    def test_missing_key(self):
        d = PushDiagnosis(False, False, False, "/tmp/nope", "github.com")
        out = format_diagnosis(d)
        assert "FAIL" in out
        assert "key missing" in out
        assert "/tmp/nope" in out

    def test_bad_permissions(self):
        d = PushDiagnosis(True, False, False, "/tmp/key", "github.com")
        out = format_diagnosis(d)
        assert "FAIL" in out
        assert "too open" in out

    def test_ssh_failure(self):
        d = PushDiagnosis(True, True, False, "/tmp/key", "github.com")
        out = format_diagnosis(d)
        assert "FAIL" in out
        assert "ssh fails" in out
        assert "github.com" in out


# -- diagnose_push -----------------------------------------------------------

class TestDiagnosePush:
    def test_missing_key_short_circuits(self, tmp_path):
        fake_key = tmp_path / "missing_key"
        d = diagnose_push(
            remote_url="git@github.com:FengPwner/IamAI.git",
            key_path=str(fake_key),
            timeout=2,
        )
        assert d.key_exists is False
        assert d.key_permissions_ok is False
        assert d.ssh_connects is False
        assert d.healthy is False

    def test_bad_perms_short_circuits_ssh(self, tmp_path):
        key = tmp_path / "bad_key"
        key.write_text("fake")
        key.chmod(0o777)
        d = diagnose_push(
            remote_url="git@github.com:FengPwner/IamAI.git",
            key_path=str(key),
            timeout=2,
        )
        assert d.key_exists is True
        assert d.key_permissions_ok is False
        # SSH should not have been attempted with bad perms
        assert d.ssh_connects is False

    def test_extracts_host_from_url(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake")
        key.chmod(0o600)
        # Even if SSH fails (no real server), host extraction should work
        d = diagnose_push(
            remote_url="git@gitlab.example.com:user/repo.git",
            key_path=str(key),
            timeout=2,
        )
        assert d.remote_host == "gitlab.example.com"

    def test_default_remote_host(self):
        d = diagnose_push(
            remote_url="malformed-url",
            key_path="/tmp/nonexistent_key_12345",
            timeout=1,
        )
        assert d.remote_host == "github.com"
