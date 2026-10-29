"""Tests for iamai.push_readiness_probe — push connectivity probe.

The probe answers one question: "can we push *right now*?" before the
committer accumulates commits it can't deliver. These tests exercise
every failure mode without touching the network.

Design notes:
    - _check_key is tested with real tempfiles (permissions matter).
    - _classify is tested with stderr snippets from real SSH failures.
    - probe_push is tested via subprocess mock — we don't hit the network.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from iamai.push_readiness_probe import (
    DEFAULT_REMOTE,
    ProbeResult,
    _check_key,
    _classify,
    probe_push,
    probe_summary,
    VALID_STATUSES,
)


# ---------------------------------------------------------------------------
# ProbeResult
# ---------------------------------------------------------------------------

class TestProbeResult:
    def test_ok_when_ready(self):
        r = ProbeResult(status="READY", latency_ms=100)
        assert r.ok is True

    def test_not_ok_for_any_failure(self):
        for s in VALID_STATUSES - {"READY"}:
            r = ProbeResult(status=s)
            assert r.ok is False

    def test_unknown_status_normalised(self):
        r = ProbeResult(status="BOGUS")
        assert r.status == "UNKNOWN"

    def test_summary_ready(self):
        r = ProbeResult(status="READY", latency_ms=312)
        assert r.summary() == "READY in 312ms"

    def test_summary_failure_includes_snippet(self):
        r = ProbeResult(
            status="HOST_KEY",
            latency_ms=50,
            stderr_snippet="Host key verification failed",
        )
        s = r.summary()
        assert "HOST_KEY" in s
        assert "Host key verification" in s

    def test_summary_failure_no_snippet(self):
        r = ProbeResult(status="AUTH", latency_ms=200)
        assert "AUTH" in r.summary()


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    @pytest.mark.parametrize(
        "stderr",
        [
            "Host key verification failed.",
            "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!",
            "Add correct host key in /root/.ssh/known_hosts",
            "Offending key for server in known_hosts:3",
        ],
    )
    def test_host_key(self, stderr):
        assert _classify(stderr) == "HOST_KEY"

    @pytest.mark.parametrize(
        "stderr",
        [
            "Permission denied (publickey).",
            "fatal: Could not read from remote repository.\n\nPlease make sure you have the correct access rights.",
            "Authentication failed.",
        ],
    )
    def test_auth(self, stderr):
        assert _classify(stderr) == "AUTH"

    @pytest.mark.parametrize(
        "stderr",
        [
            "ssh: Could not resolve hostname github.com: Name or service not known",
            "Connection timed out",
            "Network is unreachable",
            "No route to host",
            "Connection refused",
        ],
    )
    def test_unreachable(self, stderr):
        assert _classify(stderr) == "UNREACHABLE"

    def test_unknown_fallback(self):
        assert _classify("something completely unexpected") == "UNKNOWN"

    def test_empty_string(self):
        assert _classify("") == "UNKNOWN"

    def test_case_insensitive(self):
        assert _classify("HOST KEY VERIFICATION FAILED") == "HOST_KEY"
        assert _classify("PERMISSION DENIED") == "AUTH"


# ---------------------------------------------------------------------------
# _check_key
# ---------------------------------------------------------------------------

class TestCheckKey:
    def test_missing_key(self, tmp_path):
        fake = str(tmp_path / "nonexistent_key")
        r = _check_key(fake)
        assert r is not None
        assert r.status == "NO_KEY"
        assert "not found" in r.stderr_snippet

    def test_good_permissions(self, tmp_path):
        key = tmp_path / "good_key"
        key.write_text("fake-key-content")
        key.chmod(0o600)
        assert _check_key(str(key)) is None  # no problem

    def test_world_readable(self, tmp_path):
        key = tmp_path / "open_key"
        key.write_text("fake-key-content")
        key.chmod(0o644)
        r = _check_key(str(key))
        assert r is not None
        assert r.status == "NO_KEY"
        assert "permissions" in r.stderr_snippet

    def test_group_readable(self, tmp_path):
        key = tmp_path / "grp_key"
        key.write_text("fake-key-content")
        key.chmod(0o640)
        r = _check_key(str(key))
        assert r is not None
        assert r.status == "NO_KEY"

    def test_owner_only_rw(self, tmp_path):
        key = tmp_path / "strict_key"
        key.write_text("fake-key-content")
        key.chmod(0o400)
        assert _check_key(str(key)) is None


# ---------------------------------------------------------------------------
# probe_push (mocked subprocess)
# ---------------------------------------------------------------------------

class TestProbePush:
    """Test the full probe_push flow with mocked subprocess."""

    def _mock_run(self, returncode=0, stdout="", stderr="", side_effect=None):
        """Build a patch for subprocess.run."""
        if side_effect:
            return mock.patch(
                "iamai.push_readiness_probe.subprocess.run",
                side_effect=side_effect,
            )
        proc = mock.MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return mock.patch(
            "iamai.push_readiness_probe.subprocess.run",
            return_value=proc,
        )

    def test_ready(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake")
        key.chmod(0o600)
        with self._mock_run(returncode=0, stdout="abc123\trefs/heads/main\n"):
            r = probe_push(remote="git@github.com:test/test.git", ssh_key=str(key))
        assert r.status == "READY"
        assert r.ok is True
        assert r.latency_ms >= 0

    def test_host_key_failure(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake")
        key.chmod(0o600)
        with self._mock_run(
            returncode=255,
            stderr="Host key verification failed.\n",
        ):
            r = probe_push(remote="git@github.com:test/test.git", ssh_key=str(key))
        assert r.status == "HOST_KEY"
        assert r.ok is False

    def test_auth_failure(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake")
        key.chmod(0o600)
        with self._mock_run(
            returncode=128,
            stderr="Permission denied (publickey).\n",
        ):
            r = probe_push(remote="git@github.com:test/test.git", ssh_key=str(key))
        assert r.status == "AUTH"

    def test_timeout(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake")
        key.chmod(0o600)
        with self._mock_run(side_effect=subprocess.TimeoutExpired("git", 15)):
            r = probe_push(
                remote="git@github.com:test/test.git",
                ssh_key=str(key),
                timeout=15,
            )
        assert r.status == "UNREACHABLE"
        assert "timeout" in r.stderr_snippet

    def test_missing_key_short_circuits(self, tmp_path):
        """probe_push should return NO_KEY without calling subprocess."""
        fake_key = str(tmp_path / "missing")
        with self._mock_run() as m:
            r = probe_push(remote="git@github.com:test/test.git", ssh_key=fake_key)
        assert r.status == "NO_KEY"
        m.assert_not_called()  # subprocess.run was never called

    def test_network_error(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake")
        key.chmod(0o600)
        with self._mock_run(
            returncode=255,
            stderr="ssh: Could not resolve hostname github.com\n",
        ):
            r = probe_push(remote="git@github.com:test/test.git", ssh_key=str(key))
        assert r.status == "UNREACHABLE"


# ---------------------------------------------------------------------------
# probe_summary
# ---------------------------------------------------------------------------

class TestProbeSummary:
    def test_returns_string(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake")
        key.chmod(0o600)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = "abc\trefs/heads/main\n"
        proc.stderr = ""
        with mock.patch("iamai.push_readiness_probe.subprocess.run", return_value=proc):
            s = probe_summary(remote="git@github.com:test/test.git", ssh_key=str(key))
        assert "READY" in s
