"""tests for credential_gap_monitor — verifying the diagnostic chain.

the monitor composes checks into a single diagnostic. each test isolates
one step in the chain: missing key, unreadable key, local-only diagnosis,
and probe-based classification.

these tests do not require network access — the github probe is mocked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iamai.credential_gap_monitor import (
    CredentialGapMonitor,
    GapReport,
    GapType,
)


# ---------------------------------------------------------------------------
# missing key
# ---------------------------------------------------------------------------


class TestMissingKey:
    """when the key file does not exist, diagnosis returns MISSING."""

    def test_missing_key_detected(self, tmp_path):
        key_path = tmp_path / "id_ed25519"
        monitor = CredentialGapMonitor(key_path=key_path)
        report = monitor.diagnose()
        assert report.gap_type == GapType.MISSING
        assert "missing" in report.remediation.lower()
        assert report.fingerprint is None

    def test_missing_key_summary_mentions_path(self, tmp_path):
        key_path = tmp_path / "id_ed25519"
        monitor = CredentialGapMonitor(key_path=key_path)
        report = monitor.diagnose()
        assert str(key_path) in report.summary

    def test_missing_key_no_probe(self, tmp_path):
        """probe should not be attempted when key is missing."""
        key_path = tmp_path / "id_ed25519"
        monitor = CredentialGapMonitor(key_path=key_path)
        # even with probe=True, missing key short-circuits
        report = monitor.diagnose(probe=True)
        assert report.gap_type == GapType.MISSING
        assert report.probe_performed is False


# ---------------------------------------------------------------------------
# unreadable key
# ---------------------------------------------------------------------------


class TestUnreadableKey:
    """when ssh-keygen cannot read the key, diagnosis returns UNREADABLE."""

    def test_corrupt_key_detected(self, tmp_path):
        key_path = tmp_path / "id_ed25519"
        key_path.write_text("not a valid key")
        monitor = CredentialGapMonitor(key_path=key_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="invalid key format"
            )
            report = monitor.diagnose()

        assert report.gap_type == GapType.UNREADABLE
        assert "unreadable" in report.remediation.lower() or "corrupt" in report.remediation.lower()

    def test_unreadable_key_captures_error(self, tmp_path):
        key_path = tmp_path / "id_ed25519"
        key_path.write_text("garbage")
        monitor = CredentialGapMonitor(key_path=key_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="cannot parse key"
            )
            report = monitor.diagnose()

        assert len(report.errors) > 0
        assert "cannot parse key" in report.errors[0]


# ---------------------------------------------------------------------------
# local-only diagnosis (no probe)
# ---------------------------------------------------------------------------


class TestLocalDiagnosis:
    """when probe=False, diagnosis reports what it can verify locally."""

    def test_key_present_returns_unknown(self, tmp_path):
        key_path = tmp_path / "id_ed25519"
        key_path.write_text("valid key content")
        pubkey_path = tmp_path / "id_ed25519.pub"
        pubkey_path.write_text("ssh-ed25519 AAAA... user@host")

        monitor = CredentialGapMonitor(key_path=key_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout="256 SHA256:testfingerprint user@host (ED25519)\n",
                stderr="",
            )
            report = monitor.diagnose(probe=False)

        assert report.gap_type == GapType.UNKNOWN
        assert report.fingerprint == "SHA256:testfingerprint"
        assert report.probe_performed is False
        assert "registration status unknown" in report.remediation.lower()

    def test_pubkey_content_captured(self, tmp_path):
        key_path = tmp_path / "id_ed25519"
        key_path.write_text("valid key")
        pubkey_content = "ssh-ed25519 AAAA... user@host"
        pubkey_path = tmp_path / "id_ed25519.pub"
        pubkey_path.write_text(pubkey_content)

        monitor = CredentialGapMonitor(key_path=key_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout="256 SHA256:abc123 user@host (ED25519)\n",
                stderr="",
            )
            report = monitor.diagnose()

        assert report.pubkey_content == pubkey_content


# ---------------------------------------------------------------------------
# probe-based classification
# ---------------------------------------------------------------------------


class TestProbeClassification:
    """when probe=True, github's response determines the gap type."""

    def test_ok_when_github_accepts(self, tmp_path):
        key_path = tmp_path / "id_ed25519"
        key_path.write_text("valid key")
        (tmp_path / "id_ed25519.pub").write_text("ssh-ed25519 AAAA...")

        monitor = CredentialGapMonitor(key_path=key_path)

        call_count = {"n": 0}

        def mock_run(cmd, **kwargs):
            call_count["n"] += 1
            # first call: ssh-keygen (fingerprint)
            if call_count["n"] == 1:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0,
                    stdout="256 SHA256:ok123 user@host (ED25519)\n",
                    stderr="",
                )
            # second call: ssh -T git@github.com (success)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0,
                stdout="Hi FengPwner! You've successfully authenticated.",
                stderr="",
            )

        with patch("subprocess.run", side_effect=mock_run):
            report = monitor.diagnose(probe=True)

        assert report.gap_type == GapType.OK
        assert report.probe_performed is True
        assert "healthy" in report.summary.lower()

    def test_unregistered_when_github_rejects(self, tmp_path):
        key_path = tmp_path / "id_ed25519"
        key_path.write_text("valid key")
        (tmp_path / "id_ed25519.pub").write_text("ssh-ed25519 AAAA...")

        monitor = CredentialGapMonitor(key_path=key_path)

        call_count = {"n": 0}

        def mock_run(cmd, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0,
                    stdout="256 SHA256:unknown456 user@host (ED25519)\n",
                    stderr="",
                )
            # github rejects with permission denied
            return subprocess.CompletedProcess(
                args=cmd, returncode=255,
                stdout="",
                stderr="git@github.com: Permission denied (publickey).",
            )

        with patch("subprocess.run", side_effect=mock_run):
            report = monitor.diagnose(probe=True)

        assert report.gap_type == GapType.UNREGISTERED
        assert report.probe_performed is True
        assert "not registered" in report.remediation.lower()
        assert "deploy key" in report.remediation.lower()

    def test_probe_timeout_handled(self, tmp_path):
        key_path = tmp_path / "id_ed25519"
        key_path.write_text("valid key")
        (tmp_path / "id_ed25519.pub").write_text("ssh-ed25519 AAAA...")

        monitor = CredentialGapMonitor(key_path=key_path)

        call_count = {"n": 0}

        def mock_run(cmd, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0,
                    stdout="256 SHA256:timeout789 user@host (ED25519)\n",
                    stderr="",
                )
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=15)

        with patch("subprocess.run", side_effect=mock_run):
            report = monitor.diagnose(probe=True)

        # timeout means we can't classify — fall back to UNKNOWN
        assert report.gap_type == GapType.UNKNOWN
        assert report.probe_performed is True


# ---------------------------------------------------------------------------
# remediation content
# ---------------------------------------------------------------------------


class TestRemediation:
    """remediation messages should be actionable."""

    def test_missing_key_suggests_keygen(self, tmp_path):
        key_path = tmp_path / "id_ed25519"
        monitor = CredentialGapMonitor(key_path=key_path)
        report = monitor.diagnose()
        assert "ssh-keygen" in report.remediation
        assert "deploy key" in report.remediation.lower()

    def test_unregistered_reminds_to_register(self, tmp_path):
        key_path = tmp_path / "id_ed25519"
        key_path.write_text("valid key")
        pubkey = "ssh-ed25519 AAAA... user@host"
        (tmp_path / "id_ed25519.pub").write_text(pubkey)

        monitor = CredentialGapMonitor(key_path=key_path)

        call_count = {"n": 0}

        def mock_run(cmd, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0,
                    stdout="256 SHA256:abc user@host (ED25519)\n", stderr="",
                )
            return subprocess.CompletedProcess(
                args=cmd, returncode=255,
                stdout="", stderr="Permission denied (publickey).",
            )

        with patch("subprocess.run", side_effect=mock_run):
            report = monitor.diagnose(probe=True)

        assert "settings/keys" in report.remediation
        assert pubkey in report.remediation

    def test_revoked_suggests_reregister(self, tmp_path):
        monitor = CredentialGapMonitor(key_path=tmp_path / "x")
        remediation = monitor._remediation_registered(GapType.REVOKED, None)
        assert "re-register" in remediation.lower() or "generate" in remediation.lower()


# ---------------------------------------------------------------------------
# dataclass integrity
# ---------------------------------------------------------------------------


class TestGapReport:
    """GapReport fields are correctly initialized."""

    def test_default_fields(self):
        report = GapReport(gap_type=GapType.OK, key_path=Path("/tmp/x"))
        assert report.fingerprint is None
        assert report.pubkey_content is None
        assert report.errors == []
        assert report.probe_performed is False

    def test_all_fields_populated(self):
        report = GapReport(
            gap_type=GapType.UNREGISTERED,
            key_path=Path("/root/.ssh/id_ed25519"),
            fingerprint="SHA256:test",
            pubkey_content="ssh-ed25519 AAAA...",
            remediation="register the key",
            summary="key not registered",
            errors=["permission denied"],
            probe_performed=True,
            probe_output="Permission denied (publickey).",
        )
        assert report.gap_type == GapType.UNREGISTERED
        assert report.fingerprint == "SHA256:test"
        assert len(report.errors) == 1


# ---------------------------------------------------------------------------
# integration: full diagnostic chain with defaults
# ---------------------------------------------------------------------------


class TestFullChain:
    """end-to-end tests using the default key path."""

    def test_default_key_path(self):
        monitor = CredentialGapMonitor()
        expected = Path.home() / ".ssh" / "id_ed25519"
        assert monitor.key_path == expected

    def test_repo_path_configurable(self, tmp_path):
        monitor = CredentialGapMonitor(repo=tmp_path)
        assert monitor.repo == tmp_path

    def test_diagnose_returns_gap_report(self, tmp_path):
        key_path = tmp_path / "id_ed25519"
        monitor = CredentialGapMonitor(key_path=key_path)
        report = monitor.diagnose()
        assert isinstance(report, GapReport)
