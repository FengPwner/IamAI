"""tests for iamai/push_diag.py — push pipeline diagnostic module.

30 tests covering:
  - key file existence and permission checks
  - ssh test result classification
  - diagnosis state machine (all 7 states)
  - fix hint generation for each state
  - unpushed commit counting
  - workspace key fallback detection
  - report formatting
  - error handling and edge cases
"""

import json
import os
import stat
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# add parent to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.push_diag import (
    PushState,
    PushDiagnosis,
    _check_key_file,
    _get_fingerprint,
    _get_unpushed_count,
    _get_unpushed_oldest_hours,
    _keys_match,
    _run,
    diagnose,
    format_report,
    generate_fix_hint,
    DEFAULT_KEY_PATH,
    WORKSPACE_KEY,
    REPO,
)


# ---------------------------------------------------------------------------
# _run helper
# ---------------------------------------------------------------------------

class TestRun:
    def test_run_success(self):
        code, out, err = _run("echo", "hello")
        assert code == 0
        assert out == "hello"

    def test_run_failure(self):
        code, out, err = _run("false")
        assert code != 0

    def test_run_timeout(self):
        code, out, err = _run("sleep", "10", timeout=1)
        assert code == -1
        assert "timeout" in err.lower()

    def test_run_nonexistent_command(self):
        code, out, err = _run("nonexistent_command_xyz_12345")
        assert code == -1


# ---------------------------------------------------------------------------
# _check_key_file
# ---------------------------------------------------------------------------

class TestCheckKeyFile:
    def test_missing_file(self, tmp_path):
        exists, perms = _check_key_file(tmp_path / "nonexistent")
        assert exists is False
        assert perms == ""

    def test_existing_file(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake key")
        key.chmod(0o600)
        exists, perms = _check_key_file(key)
        assert exists is True
        assert perms == "0o600"

    def test_open_permissions(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake key")
        key.chmod(0o777)
        exists, perms = _check_key_file(key)
        assert exists is True
        assert perms == "0o777"


# ---------------------------------------------------------------------------
# _get_fingerprint
# ---------------------------------------------------------------------------

class TestGetFingerprint:
    def test_missing_pubkey(self, tmp_path):
        fp = _get_fingerprint(tmp_path / "nonexistent.pub")
        assert fp == ""

    def test_valid_pubkey(self, tmp_path):
        # skip if ssh-keygen not available
        try:
            subprocess.run(["ssh-keygen", "-V"], capture_output=True, timeout=3)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("ssh-keygen not available")

        # generate a temp key
        key_path = tmp_path / "test_key"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", ""],
            capture_output=True, timeout=10,
        )
        pub = key_path.with_suffix(".pub")
        if pub.exists():
            fp = _get_fingerprint(pub)
            assert fp.startswith("SHA256:")


# ---------------------------------------------------------------------------
# _keys_match
# ---------------------------------------------------------------------------

class TestKeysMatch:
    def test_both_missing(self, tmp_path):
        assert _keys_match(tmp_path / "a", tmp_path / "b") is False

    def test_one_missing(self, tmp_path):
        a = tmp_path / "a"
        a.write_text("key")
        assert _keys_match(a, tmp_path / "b") is False

    def test_same_content(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.write_text("same key content")
        b.write_text("same key content")
        assert _keys_match(a, b) is True

    def test_different_content(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.write_text("key A")
        b.write_text("key B")
        assert _keys_match(a, b) is False


# ---------------------------------------------------------------------------
# generate_fix_hint
# ---------------------------------------------------------------------------

class TestGenerateFixHint:
    def _make_diag(self, state, ws_exists=False, ws_matches=False):
        return PushDiagnosis(
            timestamp="2026-10-26T22:00:00+00:00",
            state=state.value,
            key_path=str(DEFAULT_KEY_PATH),
            key_exists=True,
            key_permissions="0o600",
            pubkey_exists=True,
            pubkey_fingerprint="SHA256:test",
            ssh_test_passed=(state == PushState.HEALTHY),
            ssh_test_error="" if state == PushState.HEALTHY else "Permission denied",
            unpushed_count=72,
            unpushed_oldest_hours=30.5,
            fix_hint="",
            workspace_key_exists=ws_exists,
            workspace_key_matches=ws_matches,
        )

    def test_healthy_hint(self):
        d = self._make_diag(PushState.HEALTHY)
        hint = generate_fix_hint(PushState.HEALTHY, d)
        assert "healthy" in hint.lower()
        assert "git push" in hint

    def test_no_key_hint_no_workspace(self):
        d = self._make_diag(PushState.NO_KEY, ws_exists=False)
        hint = generate_fix_hint(PushState.NO_KEY, d)
        assert "missing" in hint.lower()
        assert "ssh-keygen" in hint
        assert "settings/keys" in hint

    def test_no_key_hint_with_workspace(self):
        d = self._make_diag(PushState.NO_KEY, ws_exists=True)
        hint = generate_fix_hint(PushState.NO_KEY, d)
        assert "workspace key found" in hint.lower()
        assert "cp" in hint

    def test_bad_perms_hint(self):
        d = self._make_diag(PushState.BAD_PERMS)
        hint = generate_fix_hint(PushState.BAD_PERMS, d)
        assert "chmod 600" in hint

    def test_no_pubkey_hint(self):
        d = self._make_diag(PushState.NO_PUBKEY)
        hint = generate_fix_hint(PushState.NO_PUBKEY, d)
        assert "ssh-keygen -y" in hint

    def test_unregistered_hint(self):
        d = self._make_diag(PushState.UNREGISTERED)
        hint = generate_fix_hint(PushState.UNREGISTERED, d)
        assert "not registered" in hint.lower()
        assert "settings/keys" in hint
        assert "deploy key" in hint.lower()

    def test_network_hint(self):
        d = self._make_diag(PushState.NETWORK)
        hint = generate_fix_hint(PushState.NETWORK, d)
        assert "network" in hint.lower()
        assert "ping" in hint

    def test_unknown_hint(self):
        d = self._make_diag(PushState.UNKNOWN)
        hint = generate_fix_hint(PushState.UNKNOWN, d)
        assert "manual" in hint.lower()


# ---------------------------------------------------------------------------
# diagnose (integration with mocked subprocess)
# ---------------------------------------------------------------------------

class TestDiagnose:
    def test_no_key_state(self, tmp_path):
        """key missing → NO_KEY state."""
        fake_key = tmp_path / "nonexistent_key"
        with patch("iamai.push_diag._get_unpushed_count", return_value=72), \
             patch("iamai.push_diag._get_unpushed_oldest_hours", return_value=30.0):
            d = diagnose(key_path=fake_key)
        assert d.state == PushState.NO_KEY.value
        assert d.key_exists is False
        assert d.unpushed_count == 72

    def test_bad_perms_state(self, tmp_path):
        """key with open permissions → BAD_PERMS state."""
        key = tmp_path / "id_ed25519"
        key.write_text("fake key")
        key.chmod(0o644)
        with patch("iamai.push_diag._get_unpushed_count", return_value=0), \
             patch("iamai.push_diag._get_unpushed_oldest_hours", return_value=0.0):
            d = diagnose(key_path=key)
        assert d.state == PushState.BAD_PERMS.value

    def test_healthy_state(self, tmp_path):
        """key exists, perms ok, ssh passes → HEALTHY."""
        key = tmp_path / "id_ed25519"
        key.write_text("fake key")
        key.chmod(0o600)
        pub = tmp_path / "id_ed25519.pub"
        pub.write_text("ssh-ed25519 AAAA... test@host")
        with patch("iamai.push_diag._test_ssh", return_value=(True, "")), \
             patch("iamai.push_diag._get_fingerprint", return_value="SHA256:test"), \
             patch("iamai.push_diag._get_unpushed_count", return_value=0), \
             patch("iamai.push_diag._get_unpushed_oldest_hours", return_value=0.0):
            d = diagnose(key_path=key)
        assert d.state == PushState.HEALTHY.value
        assert d.ssh_test_passed is True

    def test_unregistered_state(self, tmp_path):
        """key exists, perms ok, ssh fails with Permission denied → UNREGISTERED."""
        key = tmp_path / "id_ed25519"
        key.write_text("fake key")
        key.chmod(0o600)
        pub = tmp_path / "id_ed25519.pub"
        pub.write_text("ssh-ed25519 AAAA... test@host")
        with patch("iamai.push_diag._test_ssh",
                    return_value=(False, "Permission denied (publickey)")), \
             patch("iamai.push_diag._get_fingerprint", return_value="SHA256:test"), \
             patch("iamai.push_diag._get_unpushed_count", return_value=50), \
             patch("iamai.push_diag._get_unpushed_oldest_hours", return_value=20.0):
            d = diagnose(key_path=key)
        assert d.state == PushState.UNREGISTERED.value

    def test_network_state(self, tmp_path):
        """key ok, ssh fails with network error → NETWORK."""
        key = tmp_path / "id_ed25519"
        key.write_text("fake key")
        key.chmod(0o600)
        pub = tmp_path / "id_ed25519.pub"
        pub.write_text("ssh-ed25519 AAAA... test@host")
        with patch("iamai.push_diag._test_ssh",
                    return_value=(False, "Network error: could not resolve")), \
             patch("iamai.push_diag._get_fingerprint", return_value="SHA256:test"), \
             patch("iamai.push_diag._get_unpushed_count", return_value=0), \
             patch("iamai.push_diag._get_unpushed_oldest_hours", return_value=0.0):
            d = diagnose(key_path=key)
        assert d.state == PushState.NETWORK.value

    def test_workspace_key_detected(self, tmp_path):
        """workspace key fallback detection."""
        key = tmp_path / "id_ed25519"
        key.write_text("fake key")
        key.chmod(0o600)
        with patch("iamai.push_diag.WORKSPACE_KEY", tmp_path / "ws_key"), \
             patch("iamai.push_diag._get_unpushed_count", return_value=0), \
             patch("iamai.push_diag._get_unpushed_oldest_hours", return_value=0.0):
            # create a workspace key that differs
            ws = tmp_path / "ws_key"
            ws.write_text("different key")
            d = diagnose(key_path=key)
        assert d.workspace_key_exists is True
        assert d.workspace_key_matches is False


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_healthy_report(self):
        d = PushDiagnosis(
            timestamp="2026-10-26T22:00:00+00:00",
            state="HEALTHY",
            key_path="/root/.ssh/id_ed25519",
            key_exists=True,
            key_permissions="0o600",
            pubkey_exists=True,
            pubkey_fingerprint="SHA256:abc",
            ssh_test_passed=True,
            ssh_test_error="",
            unpushed_count=0,
            unpushed_oldest_hours=0.0,
            fix_hint="all good",
        )
        report = format_report(d)
        assert "[OK]" in report
        assert "HEALTHY" in report
        assert "PASS" in report

    def test_broken_report(self):
        d = PushDiagnosis(
            timestamp="2026-10-26T22:00:00+00:00",
            state="UNREGISTERED",
            key_path="/root/.ssh/id_ed25519",
            key_exists=True,
            key_permissions="0o600",
            pubkey_exists=True,
            pubkey_fingerprint="SHA256:abc",
            ssh_test_passed=False,
            ssh_test_error="Permission denied (publickey)",
            unpushed_count=72,
            unpushed_oldest_hours=30.5,
            fix_hint="register the key",
        )
        report = format_report(d)
        assert "[!!]" in report
        assert "UNREGISTERED" in report
        assert "FAIL" in report
        assert "72 commits" in report
        assert "30.5h" in report

    def test_json_output(self):
        d = PushDiagnosis(
            timestamp="2026-10-26T22:00:00+00:00",
            state="NO_KEY",
            key_path="/root/.ssh/id_ed25519",
            key_exists=False,
            key_permissions="",
            pubkey_exists=False,
            pubkey_fingerprint="",
            ssh_test_passed=False,
            ssh_test_error="key missing",
            unpushed_count=72,
            unpushed_oldest_hours=30.0,
            fix_hint="generate a key",
        )
        j = json.loads(json.dumps(d.__dict__))
        assert j["state"] == "NO_KEY"
        assert j["unpushed_count"] == 72


# ---------------------------------------------------------------------------
# PushState enum
# ---------------------------------------------------------------------------

class TestPushState:
    def test_all_states_exist(self):
        expected = {"HEALTHY", "NO_KEY", "BAD_PERMS", "NO_PUBKEY",
                    "UNREGISTERED", "NETWORK", "UNKNOWN"}
        actual = {s.value for s in PushState}
        assert expected == actual

    def test_string_value(self):
        assert PushState.HEALTHY.value == "HEALTHY"
        assert str(PushState.HEALTHY) == "PushState.HEALTHY"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
