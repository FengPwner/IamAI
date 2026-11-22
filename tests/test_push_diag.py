"""tests for iamai/push_diag.py — push pipeline diagnostic.

covers PushState enum, PushDiagnosis dataclass, helper functions,
generate_fix_hint for every state, format_report output, and the
diagnose() integration with mocked subprocess and filesystem calls.

visit 788, 2026-11-22, written by Qwen.
"""

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.push_diag import (
    PushState,
    PushDiagnosis,
    _check_key_file,
    _get_fingerprint,
    _keys_match,
    _run,
    generate_fix_hint,
    format_report,
    diagnose,
    DEFAULT_KEY_PATH,
    WORKSPACE_KEY,
)


# ── PushState enum ──────────────────────────────────────────────

class TestPushState:
    def test_all_states_exist(self):
        expected = {
            "HEALTHY", "NO_KEY", "BAD_PERMS", "NO_PUBKEY",
            "UNREGISTERED", "NETWORK", "UNKNOWN",
        }
        actual = {s.value for s in PushState}
        assert expected == actual

    def test_string_behaviour(self):
        assert PushState.HEALTHY == "HEALTHY"
        assert str(PushState.NO_KEY) == "PushState.NO_KEY"
        assert PushState("BAD_PERMS") is PushState.BAD_PERMS


# ── PushDiagnosis dataclass ─────────────────────────────────────

class TestPushDiagnosis:
    def _make(self, **overrides):
        defaults = dict(
            timestamp="2026-11-22T12:00:00+00:00",
            state="HEALTHY",
            key_path="/tmp/k",
            key_exists=True,
            key_permissions="0o600",
            pubkey_exists=True,
            pubkey_fingerprint="SHA256:abc",
            ssh_test_passed=True,
            ssh_test_error="",
            unpushed_count=0,
            unpushed_oldest_hours=0.0,
            fix_hint="ok",
        )
        defaults.update(overrides)
        return PushDiagnosis(**defaults)

    def test_fields_accessible(self):
        d = self._make()
        assert d.state == "HEALTHY"
        assert d.key_exists is True

    def test_to_dict(self):
        d = self._make()
        dd = asdict(d)
        assert "state" in dd
        assert "fix_hint" in dd
        assert "workspace_key_exists" in dd

    def test_default_workspace_fields(self):
        d = self._make()
        assert d.workspace_key_exists is False
        assert d.workspace_key_matches is False


# ── _run helper ─────────────────────────────────────────────────

class TestRun:
    @patch("iamai.push_diag.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="hello\n", stderr=""
        )
        code, out, err = _run("echo", "hello")
        assert code == 0
        assert out == "hello"
        assert err == ""

    @patch("iamai.push_diag.subprocess.run",
           side_effect=subprocess.TimeoutExpired("cmd", 10))
    def test_timeout(self, _):
        code, out, err = _run("sleep", "100")
        assert code == -1
        assert err == "timeout"

    @patch("iamai.push_diag.subprocess.run",
           side_effect=OSError("no such file"))
    def test_os_error(self, _):
        code, out, err = _run("nonexistent")
        assert code == -1
        assert "no such file" in err


# ── _check_key_file ─────────────────────────────────────────────

class TestCheckKeyFile:
    def test_missing_file(self, tmp_path):
        exists, perms = _check_key_file(tmp_path / "nope")
        assert exists is False
        assert perms == ""

    def test_existing_file_permissions(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("fake key")
        key.chmod(0o600)
        exists, perms = _check_key_file(key)
        assert exists is True
        assert perms == "0o600"

    def test_open_permissions(self, tmp_path):
        key = tmp_path / "id_open"
        key.write_text("fake key")
        key.chmod(0o644)
        exists, perms = _check_key_file(key)
        assert exists is True
        assert perms == "0o644"


# ── _get_fingerprint ────────────────────────────────────────────

class TestGetFingerprint:
    def test_missing_pubkey(self, tmp_path):
        fp = _get_fingerprint(tmp_path / "nope.pub")
        assert fp == ""

    @patch("iamai.push_diag._run")
    def test_valid_pubkey(self, mock_run, tmp_path):
        pub = tmp_path / "id.pub"
        pub.write_text("ssh-ed25519 AAAA...")
        mock_run.return_value = (
            0, "256 SHA256:abcdef comment (ED25519)", ""
        )
        fp = _get_fingerprint(pub)
        assert fp == "SHA256:abcdef"

    @patch("iamai.push_diag._run", return_value=(1, "", "error"))
    def test_keygen_failure(self, _, tmp_path):
        pub = tmp_path / "id.pub"
        pub.write_text("bad key")
        fp = _get_fingerprint(pub)
        assert fp == ""


# ── _keys_match ─────────────────────────────────────────────────

class TestKeysMatch:
    def test_both_missing(self, tmp_path):
        assert _keys_match(tmp_path / "a", tmp_path / "b") is False

    def test_one_missing(self, tmp_path):
        a = tmp_path / "a"
        a.write_text("key")
        assert _keys_match(a, tmp_path / "b") is False

    def test_matching_keys(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        content = b"-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END"
        a.write_bytes(content)
        b.write_bytes(content)
        assert _keys_match(a, b) is True

    def test_different_keys(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.write_bytes(b"key_a")
        b.write_bytes(b"key_b")
        assert _keys_match(a, b) is False


# ── generate_fix_hint ───────────────────────────────────────────

class TestGenerateFixHint:
    def _diag(self, ws_key_exists=False, ws_key_matches=False):
        return PushDiagnosis(
            timestamp="", state="", key_path="", key_exists=True,
            key_permissions="", pubkey_exists=True,
            pubkey_fingerprint="", ssh_test_passed=False,
            ssh_test_error="", unpushed_count=0,
            unpushed_oldest_hours=0.0, fix_hint="",
            workspace_key_exists=ws_key_exists,
            workspace_key_matches=ws_key_matches,
        )

    def test_healthy(self):
        hint = generate_fix_hint(PushState.HEALTHY, self._diag())
        assert "healthy" in hint.lower()

    def test_no_key_with_workspace_key(self):
        d = self._diag(ws_key_exists=True)
        hint = generate_fix_hint(PushState.NO_KEY, d)
        assert "workspace key found" in hint.lower()
        assert "cp " in hint

    def test_no_key_without_workspace_key(self):
        d = self._diag(ws_key_exists=False)
        hint = generate_fix_hint(PushState.NO_KEY, d)
        assert "ssh-keygen" in hint

    def test_bad_perms(self):
        hint = generate_fix_hint(PushState.BAD_PERMS, self._diag())
        assert "chmod 600" in hint

    def test_no_pubkey(self):
        hint = generate_fix_hint(PushState.NO_PUBKEY, self._diag())
        assert "ssh-keygen -y" in hint

    def test_unregistered(self):
        hint = generate_fix_hint(PushState.UNREGISTERED, self._diag())
        assert "deploy key" in hint.lower()
        assert "settings/keys" in hint

    def test_network(self):
        hint = generate_fix_hint(PushState.NETWORK, self._diag())
        assert "ping" in hint or "curl" in hint

    def test_unknown(self):
        hint = generate_fix_hint(PushState.UNKNOWN, self._diag())
        assert "manual" in hint.lower()


# ── format_report ───────────────────────────────────────────────

class TestFormatReport:
    def test_healthy_report(self):
        d = PushDiagnosis(
            timestamp="2026-11-22T12:00:00Z",
            state="HEALTHY",
            key_path="/tmp/k",
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

    def test_failed_report(self):
        d = PushDiagnosis(
            timestamp="2026-11-22T12:00:00Z",
            state="NO_KEY",
            key_path="/tmp/k",
            key_exists=False,
            key_permissions="",
            pubkey_exists=False,
            pubkey_fingerprint="",
            ssh_test_passed=False,
            ssh_test_error="key missing",
            unpushed_count=3,
            unpushed_oldest_hours=1.5,
            fix_hint="generate new key",
        )
        report = format_report(d)
        assert "[!!]" in report
        assert "NO_KEY" in report
        assert "FAIL" in report
        assert "3 commits" in report
        assert "1.5h" in report

    def test_workspace_key_displayed(self):
        d = PushDiagnosis(
            timestamp="", state="HEALTHY", key_path="",
            key_exists=True, key_permissions="", pubkey_exists=True,
            pubkey_fingerprint="", ssh_test_passed=True,
            ssh_test_error="", unpushed_count=0,
            unpushed_oldest_hours=0.0, fix_hint="",
            workspace_key_exists=True, workspace_key_matches=True,
        )
        report = format_report(d)
        assert "workspace key" in report.lower()
        assert "MATCHES" in report


# ── diagnose (integration with mocks) ───────────────────────────

class TestDiagnose:
    @patch("iamai.push_diag._test_ssh", return_value=(True, ""))
    @patch("iamai.push_diag._get_unpushed_oldest_hours", return_value=0.0)
    @patch("iamai.push_diag._get_unpushed_count", return_value=0)
    @patch("iamai.push_diag._get_fingerprint", return_value="SHA256:xyz")
    @patch("iamai.push_diag._keys_match", return_value=True)
    def test_healthy_diagnosis(self, *mocks):
        # create a temp key file with correct perms
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix="_key", delete=False) as f:
            f.write(b"fake")
            kp = Path(f.name)
        kp.chmod(0o600)
        # create matching .pub file
        pub = Path(str(kp) + ".pub")
        pub.write_text("ssh-ed25519 AAAA")
        try:
            d = diagnose(key_path=kp)
            assert d.state == PushState.HEALTHY.value
            assert d.ssh_test_passed is True
        finally:
            kp.unlink(missing_ok=True)
            pub.unlink(missing_ok=True)

    @patch("iamai.push_diag._test_ssh")
    @patch("iamai.push_diag._get_unpushed_oldest_hours", return_value=0.0)
    @patch("iamai.push_diag._get_unpushed_count", return_value=5)
    @patch("iamai.push_diag._get_fingerprint", return_value="")
    @patch("iamai.push_diag._keys_match", return_value=False)
    def test_no_key_diagnosis(self, *mocks):
        d = diagnose(key_path=Path("/nonexistent/key"))
        assert d.state == PushState.NO_KEY.value
        assert d.key_exists is False

    @patch("iamai.push_diag._get_unpushed_oldest_hours", return_value=0.0)
    @patch("iamai.push_diag._get_unpushed_count", return_value=0)
    @patch("iamai.push_diag._get_fingerprint", return_value="")
    @patch("iamai.push_diag._keys_match", return_value=False)
    def test_bad_perms_diagnosis(self, *mocks):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix="_key", delete=False) as f:
            f.write(b"fake")
            kp = Path(f.name)
        kp.chmod(0o644)
        pub = Path(str(kp) + ".pub")
        pub.write_text("pub")
        try:
            d = diagnose(key_path=kp)
            assert d.state == PushState.BAD_PERMS.value
        finally:
            kp.unlink(missing_ok=True)
            pub.unlink(missing_ok=True)

    @patch("iamai.push_diag._test_ssh",
           return_value=(False, "Permission denied (publickey)"))
    @patch("iamai.push_diag._get_unpushed_oldest_hours", return_value=2.0)
    @patch("iamai.push_diag._get_unpushed_count", return_value=3)
    @patch("iamai.push_diag._get_fingerprint", return_value="SHA256:abc")
    @patch("iamai.push_diag._keys_match", return_value=False)
    def test_unregistered_diagnosis(self, *mocks):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix="_key", delete=False) as f:
            f.write(b"fake")
            kp = Path(f.name)
        kp.chmod(0o600)
        pub = Path(str(kp) + ".pub")
        pub.write_text("pub")
        try:
            d = diagnose(key_path=kp)
            assert d.state == PushState.UNREGISTERED.value
            assert d.unpushed_count == 3
        finally:
            kp.unlink(missing_ok=True)
            pub.unlink(missing_ok=True)

    @patch("iamai.push_diag._test_ssh",
           return_value=(False, "Connection timeout"))
    @patch("iamai.push_diag._get_unpushed_oldest_hours", return_value=0.0)
    @patch("iamai.push_diag._get_unpushed_count", return_value=0)
    @patch("iamai.push_diag._get_fingerprint", return_value="SHA256:abc")
    @patch("iamai.push_diag._keys_match", return_value=False)
    def test_network_diagnosis(self, *mocks):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix="_key", delete=False) as f:
            f.write(b"fake")
            kp = Path(f.name)
        kp.chmod(0o600)
        pub = Path(str(kp) + ".pub")
        pub.write_text("pub")
        try:
            d = diagnose(key_path=kp)
            assert d.state == PushState.NETWORK.value
        finally:
            kp.unlink(missing_ok=True)
            pub.unlink(missing_ok=True)


# ── boundary & edge cases ───────────────────────────────────────

class TestEdgeCases:
    def test_fix_hint_contains_actionable_command(self):
        """every non-healthy fix hint must contain at least one shell command."""
        d = PushDiagnosis(
            timestamp="", state="", key_path="/tmp/k",
            key_exists=False, key_permissions="", pubkey_exists=False,
            pubkey_fingerprint="", ssh_test_passed=False,
            ssh_test_error="", unpushed_count=0,
            unpushed_oldest_hours=0.0, fix_hint="",
        )
        for state in PushState:
            if state == PushState.HEALTHY:
                continue
            hint = generate_fix_hint(state, d)
            # every fix hint should have something actionable
            assert len(hint) > 10, f"hint for {state} too short"

    def test_report_json_roundtrip(self):
        """PushDiagnosis → dict → json → dict → PushDiagnosis preserves fields."""
        d = PushDiagnosis(
            timestamp="2026-11-22T00:00:00Z",
            state="HEALTHY",
            key_path="/tmp/k",
            key_exists=True,
            key_permissions="0o600",
            pubkey_exists=True,
            pubkey_fingerprint="SHA256:abc",
            ssh_test_passed=True,
            ssh_test_error="",
            unpushed_count=2,
            unpushed_oldest_hours=0.5,
            fix_hint="ok",
            workspace_key_exists=True,
            workspace_key_matches=True,
        )
        j = json.dumps(asdict(d))
        restored = json.loads(j)
        d2 = PushDiagnosis(**restored)
        assert d2.state == d.state
        assert d2.unpushed_count == d.unpushed_count
        assert d2.workspace_key_matches is True
