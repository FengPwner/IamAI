"""tests for iamai/ssh_key_mismatch.py — SSH key mismatch classifier.

covers MismatchKind enum, MismatchResult dataclass, helper functions
(_extract_fingerprint, _probe_github, _find_local_key, _has_push_history),
classify_key_failure decision tree, and edge cases.

visit 788, 2026-11-22, written by Qwen.
"""

import subprocess
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.ssh_key_mismatch import (
    MismatchKind,
    MismatchResult,
    _extract_fingerprint,
    _probe_github,
    _find_local_key,
    _has_push_history,
    classify_key_failure,
)


# ── MismatchKind enum ───────────────────────────────────────────

class TestMismatchKind:
    def test_all_kinds_exist(self):
        expected = {"ok", "mismatch", "unregistered", "revoked", "unknown"}
        actual = {k.value for k in MismatchKind}
        assert expected == actual

    def test_string_behaviour(self):
        assert MismatchKind.OK == "ok"
        assert MismatchKind("mismatch") is MismatchKind.MISMATCH


# ── MismatchResult dataclass ────────────────────────────────────

class TestMismatchResult:
    def test_defaults(self):
        r = MismatchResult(kind=MismatchKind.OK)
        assert r.kind == MismatchKind.OK
        assert r.local_fingerprint is None
        assert r.detail == ""
        assert r.checked_at > 0  # auto-set by __post_init__

    def test_explicit_timestamp(self):
        ts = 1700000000.0
        r = MismatchResult(kind=MismatchKind.UNKNOWN, checked_at=ts)
        assert r.checked_at == ts

    def test_auto_timestamp(self):
        before = time.time()
        r = MismatchResult(kind=MismatchKind.OK)
        after = time.time()
        assert before <= r.checked_at <= after

    def test_with_fingerprint(self):
        r = MismatchResult(
            kind=MismatchKind.MISMATCH,
            local_fingerprint="SHA256:abc123",
            detail="key rejected",
        )
        assert r.local_fingerprint == "SHA256:abc123"
        assert r.kind == MismatchKind.MISMATCH


# ── _extract_fingerprint ────────────────────────────────────────

class TestExtractFingerprint:
    def test_missing_key(self, tmp_path):
        fp = _extract_fingerprint(tmp_path / "nope")
        assert fp is None

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_valid_key(self, mock_run, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("fake key content")
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="256 SHA256:abcdef12345 /tmp/id_test (ED25519)\n",
            stderr="",
        )
        fp = _extract_fingerprint(key)
        assert fp == "SHA256:abcdef12345"

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_keygen_failure(self, mock_run, tmp_path):
        key = tmp_path / "id_bad"
        key.write_text("corrupted key")
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error"
        )
        fp = _extract_fingerprint(key)
        assert fp is None

    @patch("iamai.ssh_key_mismatch.subprocess.run",
           side_effect=subprocess.TimeoutExpired("ssh-keygen", 5))
    def test_keygen_timeout(self, _, tmp_path):
        key = tmp_path / "id_slow"
        key.write_text("key")
        fp = _extract_fingerprint(key)
        assert fp is None

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_short_output(self, mock_run, tmp_path):
        """ssh-keygen output with fewer than 2 parts."""
        key = tmp_path / "id_short"
        key.write_text("key")
        mock_run.return_value = MagicMock(
            returncode=0, stdout="unexpected", stderr=""
        )
        fp = _extract_fingerprint(key)
        assert fp is None


# ── _probe_github ───────────────────────────────────────────────

class TestProbeGithub:
    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="Hi FengPwner! You've successfully authenticated.",
        )
        rc, stderr = _probe_github()
        assert rc == 0
        assert "successfully" in stderr.lower()

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_permission_denied(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Permission denied (publickey).",
        )
        rc, stderr = _probe_github()
        assert rc == 1
        assert "permission denied" in stderr.lower()

    @patch("iamai.ssh_key_mismatch.subprocess.run",
           side_effect=subprocess.TimeoutExpired("ssh", 15))
    def test_timeout(self, _):
        rc, stderr = _probe_github()
        assert rc == -1
        assert "timed out" in stderr.lower()

    @patch("iamai.ssh_key_mismatch.subprocess.run",
           side_effect=OSError("network unreachable"))
    def test_os_error(self, _):
        rc, stderr = _probe_github()
        assert rc == -2
        assert "network" in stderr.lower()


# ── _find_local_key ─────────────────────────────────────────────

class TestFindLocalKey:
    def test_no_keys_found(self, tmp_path):
        candidates = [tmp_path / "a", tmp_path / "b"]
        assert _find_local_key(candidates) is None

    def test_finds_readable_key(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake key")
        key.chmod(0o600)
        result = _find_local_key([key])
        assert result == key

    def test_skips_open_permissions(self, tmp_path):
        key = tmp_path / "id_open"
        key.write_text("key")
        key.chmod(0o644)
        result = _find_local_key([key])
        assert result is None

    def test_returns_first_valid(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.write_text("key_a")
        a.chmod(0o600)
        b.write_text("key_b")
        b.chmod(0o600)
        result = _find_local_key([a, b])
        assert result == a

    def test_skips_invalid_returns_valid(self, tmp_path):
        bad = tmp_path / "bad"
        good = tmp_path / "good"
        bad.write_text("open")
        bad.chmod(0o644)
        good.write_text("valid")
        good.chmod(0o600)
        result = _find_local_key([bad, good])
        assert result == good

    def test_nonexistent_candidates(self, tmp_path):
        candidates = [tmp_path / "x", tmp_path / "y", tmp_path / "z"]
        result = _find_local_key(candidates)
        assert result is None


# ── _has_push_history ───────────────────────────────────────────

class TestHasPushHistory:
    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_has_history(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="abc1234 some commit msg\n", stderr=""
        )
        assert _has_push_history(tmp_path) is True

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_no_history(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr=""
        )
        assert _has_push_history(tmp_path) is False

    @patch("iamai.ssh_key_mismatch.subprocess.run")
    def test_git_failure(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=128, stdout="", stderr="fatal: not a repo"
        )
        assert _has_push_history(tmp_path) is False

    @patch("iamai.ssh_key_mismatch.subprocess.run",
           side_effect=OSError("no git"))
    def test_os_error(self, _, tmp_path):
        assert _has_push_history(tmp_path) is False


# ── classify_key_failure ────────────────────────────────────────

class TestClassifyKeyFailure:
    @patch("iamai.ssh_key_mismatch._find_local_key", return_value=None)
    def test_no_key_found(self, _):
        r = classify_key_failure()
        assert r.kind == MismatchKind.UNKNOWN
        assert "no readable ssh key" in r.detail.lower()

    def test_key_ok(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("key")
        with patch("iamai.ssh_key_mismatch._find_local_key", return_value=key), \
             patch("iamai.ssh_key_mismatch._extract_fingerprint", return_value="SHA256:abc"), \
             patch("iamai.ssh_key_mismatch._probe_github", return_value=(0, "Hi user! successfully authenticated")), \
             patch("iamai.ssh_key_mismatch._has_push_history", return_value=False):
            r = classify_key_failure()
            assert r.kind == MismatchKind.OK
            assert r.local_fingerprint == "SHA256:abc"

    def test_unregistered_no_history(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("key")
        with patch("iamai.ssh_key_mismatch._find_local_key", return_value=key), \
             patch("iamai.ssh_key_mismatch._extract_fingerprint", return_value="SHA256:abc"), \
             patch("iamai.ssh_key_mismatch._probe_github", return_value=(1, "Permission denied (publickey).")), \
             patch("iamai.ssh_key_mismatch._has_push_history", return_value=False):
            r = classify_key_failure(repo_path=tmp_path)
            assert r.kind == MismatchKind.UNREGISTERED
            assert "never registered" in r.detail.lower() or \
                   "add the pubkey" in r.detail.lower()

    def test_mismatch_with_history(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("key")
        with patch("iamai.ssh_key_mismatch._find_local_key", return_value=key), \
             patch("iamai.ssh_key_mismatch._extract_fingerprint", return_value="SHA256:abc"), \
             patch("iamai.ssh_key_mismatch._probe_github", return_value=(1, "Permission denied (publickey).")), \
             patch("iamai.ssh_key_mismatch._has_push_history", return_value=True):
            r = classify_key_failure(repo_path=tmp_path)
            assert r.kind == MismatchKind.MISMATCH
            assert "container recycle" in r.detail.lower() or \
                   "stale backup" in r.detail.lower()

    def test_unknown_on_unexpected_response(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("key")
        with patch("iamai.ssh_key_mismatch._find_local_key", return_value=key), \
             patch("iamai.ssh_key_mismatch._extract_fingerprint", return_value="SHA256:abc"), \
             patch("iamai.ssh_key_mismatch._probe_github", return_value=(-1, "ssh connection timed out")), \
             patch("iamai.ssh_key_mismatch._has_push_history", return_value=False):
            r = classify_key_failure()
            assert r.kind == MismatchKind.UNKNOWN
            assert "unexpected" in r.detail.lower()

    def test_no_repo_path_skips_history_check(self, tmp_path):
        """when repo_path is None, has_push_history is not called."""
        key = tmp_path / "id_test"
        key.write_text("key")
        with patch("iamai.ssh_key_mismatch._find_local_key", return_value=key), \
             patch("iamai.ssh_key_mismatch._extract_fingerprint", return_value="SHA256:abc"), \
             patch("iamai.ssh_key_mismatch._probe_github", return_value=(1, "Permission denied (publickey).")):
            r = classify_key_failure(repo_path=None)
            # without repo_path → no history check → UNREGISTERED
            assert r.kind == MismatchKind.UNREGISTERED


# ── edge cases & integration ────────────────────────────────────

class TestEdgeCases:
    def test_mismatch_result_serializable(self):
        """MismatchResult fields are all JSON-serializable types."""
        import json
        r = MismatchResult(
            kind=MismatchKind.MISMATCH,
            local_fingerprint="SHA256:xyz",
            detail="test detail",
            checked_at=1700000000.0,
        )
        data = {
            "kind": r.kind.value,
            "fingerprint": r.local_fingerprint,
            "detail": r.detail,
            "checked_at": r.checked_at,
        }
        j = json.dumps(data)
        restored = json.loads(j)
        assert restored["kind"] == "mismatch"

    def test_fingerprint_none_propagates(self, tmp_path):
        """when key exists but fingerprint extraction fails, fp is None."""
        key = tmp_path / "id_test"
        key.write_text("key")
        with patch("iamai.ssh_key_mismatch._find_local_key", return_value=key), \
             patch("iamai.ssh_key_mismatch._extract_fingerprint", return_value=None), \
             patch("iamai.ssh_key_mismatch._probe_github", return_value=(0, "ok")):
            r = classify_key_failure()
            assert r.kind == MismatchKind.OK
            assert r.local_fingerprint is None

    def test_kind_enum_values_unique(self):
        values = [k.value for k in MismatchKind]
        assert len(values) == len(set(values))
