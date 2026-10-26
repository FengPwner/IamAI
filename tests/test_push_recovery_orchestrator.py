"""Tests for iamai.push_recovery_orchestrator — push recovery pipeline."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from iamai.push_recovery_orchestrator import (
    RecoveryReport,
    PushOutcome,
    PipelineStep,
    orchestrate,
    _count_unpushed,
    _key_fingerprint,
    _probe_github,
    _attempt_push,
    _try_restore_key,
)


# ---------------------------------------------------------------------------
# RecoveryReport dataclass
# ---------------------------------------------------------------------------

class TestRecoveryReport:
    """Verify report properties and serialization."""

    def test_push_succeeded_on_success(self):
        r = RecoveryReport(
            outcome=PushOutcome.SUCCESS,
            reached_step=PipelineStep.DONE,
        )
        assert r.push_succeeded is True
        assert r.needs_human_action is False

    def test_push_succeeded_false_on_failure(self):
        r = RecoveryReport(
            outcome=PushOutcome.KEY_UNREGISTERED,
            reached_step=PipelineStep.PROBE,
        )
        assert r.push_succeeded is False

    def test_backlog_drained_when_zero(self):
        r = RecoveryReport(
            outcome=PushOutcome.SUCCESS,
            reached_step=PipelineStep.DONE,
            unpushed_after=0,
        )
        assert r.backlog_drained is True

    def test_backlog_not_drained_when_nonzero(self):
        r = RecoveryReport(
            outcome=PushOutcome.SUCCESS,
            reached_step=PipelineStep.DONE,
            unpushed_after=5,
        )
        assert r.backlog_drained is False

    def test_needs_human_action_key_missing(self):
        r = RecoveryReport(
            outcome=PushOutcome.KEY_MISSING,
            reached_step=PipelineStep.RECOVERY,
        )
        assert r.needs_human_action is True

    def test_needs_human_action_key_unregistered(self):
        r = RecoveryReport(
            outcome=PushOutcome.KEY_UNREGISTERED,
            reached_step=PipelineStep.PROBE,
        )
        assert r.needs_human_action is True

    def test_needs_human_action_false_on_push_failed(self):
        """push_failed means key works but something else broke — not a registration issue."""
        r = RecoveryReport(
            outcome=PushOutcome.PUSH_FAILED,
            reached_step=PipelineStep.PUSH,
        )
        assert r.needs_human_action is False

    def test_needs_human_action_false_on_network_error(self):
        r = RecoveryReport(
            outcome=PushOutcome.NETWORK_ERROR,
            reached_step=PipelineStep.PUSH,
        )
        assert r.needs_human_action is False

    def test_as_dict_round_trip(self):
        r = RecoveryReport(
            outcome=PushOutcome.SUCCESS,
            reached_step=PipelineStep.DONE,
            key_present=True,
            key_source="/root/.ssh/id_ed25519",
            key_fingerprint="SHA256:abc123",
            github_accepts_key=True,
            push_exit_code=0,
            unpushed_before=42,
            unpushed_after=0,
            remediation="all good",
            errors=[],
            elapsed_s=1.234,
        )
        d = r.as_dict()
        assert d["outcome"] == "success"
        assert d["reached_step"] == "done"
        assert d["key_present"] is True
        assert d["unpushed_before"] == 42
        assert d["unpushed_after"] == 0
        assert d["elapsed_s"] == 1.23  # rounded to 2 decimals

    def test_as_dict_preserves_errors(self):
        r = RecoveryReport(
            outcome=PushOutcome.PUSH_FAILED,
            reached_step=PipelineStep.PUSH,
            errors=["err1", "err2"],
        )
        d = r.as_dict()
        assert d["errors"] == ["err1", "err2"]

    def test_default_values(self):
        r = RecoveryReport(
            outcome=PushOutcome.PUSH_FAILED,
            reached_step=PipelineStep.PREFLIGHT,
        )
        assert r.key_present is False
        assert r.key_source is None
        assert r.github_accepts_key is None
        assert r.push_exit_code is None
        assert r.unpushed_before == 0
        assert r.unpushed_after == 0
        assert r.remediation == ""
        assert r.errors == []
        assert r.elapsed_s == 0.0


# ---------------------------------------------------------------------------
# _count_unpushed
# ---------------------------------------------------------------------------

class TestCountUnpushed:
    """Verify git rev-list counting logic."""

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_returns_count_on_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="42\n"
        )
        assert _count_unpushed() == 42

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_returns_zero_on_git_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout=""
        )
        assert _count_unpushed() == 0

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_returns_zero_on_invalid_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="not_a_number\n"
        )
        assert _count_unpushed() == 0

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_returns_zero_on_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=10)
        assert _count_unpushed() == 0


# ---------------------------------------------------------------------------
# _key_fingerprint
# ---------------------------------------------------------------------------

class TestKeyFingerprint:
    """Verify SSH key fingerprint extraction."""

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_extracts_fingerprint(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="256 SHA256:abc123xyz user@host (ED25519)\n",
        )
        result = _key_fingerprint(Path("/fake/key"))
        assert result == "SHA256:abc123xyz"

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_returns_none_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert _key_fingerprint(Path("/fake/key")) is None

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_returns_none_on_bad_format(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="unexpected format\n"
        )
        assert _key_fingerprint(Path("/fake/key")) is None

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_returns_none_on_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ssh-keygen", timeout=5)
        assert _key_fingerprint(Path("/fake/key")) is None


# ---------------------------------------------------------------------------
# _probe_github
# ---------------------------------------------------------------------------

class TestProbeGithub:
    """Verify GitHub SSH probe logic."""

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_success_detection(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,  # github always returns 1
            stderr="Hi FengPwner! You've successfully authenticated, but GitHub does not provide shell access.\n",
        )
        accepted, stderr = _probe_github()
        assert accepted is True
        assert "successfully authenticated" in stderr.lower()

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_key_rejected(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=255,
            stderr="git@github.com: Permission denied (publickey).\n",
        )
        accepted, stderr = _probe_github()
        assert accepted is False
        assert "permission denied" in stderr.lower()

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_timeout_returns_false(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=10)
        accepted, msg = _probe_github()
        assert accepted is False
        assert "timed out" in msg.lower()

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_generic_exception(self, mock_run):
        mock_run.side_effect = OSError("connection refused")
        accepted, msg = _probe_github()
        assert accepted is False
        assert "connection refused" in msg


# ---------------------------------------------------------------------------
# _attempt_push
# ---------------------------------------------------------------------------

class TestAttemptPush:
    """Verify git push wrapper."""

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="To github.com:user/repo.git\n   abc..def  main -> main\n",
            stderr="",
        )
        code, output = _attempt_push()
        assert code == 0
        assert "main" in output

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_push_rejected(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="! [rejected] main -> main (non-fast-forward)\n",
        )
        code, output = _attempt_push()
        assert code == 1
        assert "rejected" in output

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=60)
        code, msg = _attempt_push()
        assert code == -1
        assert "timed out" in msg.lower()

    @patch("iamai.push_recovery_orchestrator.subprocess.run")
    def test_generic_exception(self, mock_run):
        mock_run.side_effect = OSError("no such file")
        code, msg = _attempt_push()
        assert code == -2
        assert "no such file" in msg


# ---------------------------------------------------------------------------
# _try_restore_key
# ---------------------------------------------------------------------------

class TestTryRestoreKey:
    """Verify key restoration from backup locations."""

    def test_no_backups_returns_false(self, tmp_path):
        primary = tmp_path / ".ssh" / "id_ed25519"
        result, source = _try_restore_key(
            primary=primary,
            backups=[tmp_path / "nonexistent1", tmp_path / "nonexistent2"],
            search_dirs=[],
        )
        assert result is False
        assert source is None

    def test_restores_from_backup(self, tmp_path):
        # create backup
        backup = tmp_path / "backup" / "id_ed25519"
        backup.parent.mkdir(parents=True)
        backup.write_text("fake-private-key")
        pub_backup = backup.with_suffix(".pub")
        pub_backup.write_text("fake-public-key")

        primary = tmp_path / ".ssh" / "id_ed25519"
        result, source = _try_restore_key(
            primary=primary,
            backups=[backup],
            search_dirs=[],
        )
        assert result is True
        assert source == str(backup)
        assert primary.exists()
        assert primary.read_text() == "fake-private-key"
        # check public key was also copied
        pub_primary = primary.with_suffix(".pub")
        assert pub_primary.exists()
        assert pub_primary.read_text() == "fake-public-key"

    def test_restores_without_public_key(self, tmp_path):
        """recovery succeeds even if .pub file is missing."""
        backup = tmp_path / "backup" / "id_ed25519"
        backup.parent.mkdir(parents=True)
        backup.write_text("fake-private-key")

        primary = tmp_path / ".ssh" / "id_ed25519"
        result, source = _try_restore_key(
            primary=primary,
            backups=[backup],
            search_dirs=[],
        )
        assert result is True
        assert primary.exists()

    def test_search_dir_finds_key(self, tmp_path):
        """recursive search under known dirs finds a key."""
        deep = tmp_path / "root" / "some" / "deep" / "id_ed25519"
        deep.parent.mkdir(parents=True)
        deep.write_text("found-key")

        primary = tmp_path / ".ssh" / "id_ed25519"
        result, source = _try_restore_key(
            primary=primary,
            backups=[],
            search_dirs=[tmp_path / "root"],
            depth=5,
        )
        assert result is True
        assert "found-key" in primary.read_text()

    def test_depth_limit_prevents_deep_search(self, tmp_path):
        """keys beyond depth limit are not found."""
        deep = tmp_path / "root" / "a" / "b" / "c" / "d" / "e" / "id_ed25519"
        deep.parent.mkdir(parents=True)
        deep.write_text("too-deep-key")

        primary = tmp_path / ".ssh" / "id_ed25519"
        result, source = _try_restore_key(
            primary=primary,
            backups=[],
            search_dirs=[tmp_path / "root"],
            depth=3,
        )
        assert result is False


# ---------------------------------------------------------------------------
# orchestrate — integration tests (all subprocess calls mocked)
# ---------------------------------------------------------------------------

class TestOrchestrateSuccess:
    """Full pipeline: key exists, github accepts, push works."""

    @patch("iamai.push_recovery_orchestrator._attempt_push")
    @patch("iamai.push_recovery_orchestrator._probe_github")
    @patch("iamai.push_recovery_orchestrator._key_fingerprint")
    @patch("iamai.push_recovery_orchestrator._count_unpushed")
    def test_full_success(self, mock_count, mock_fp, mock_probe, mock_push, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake")

        mock_count.side_effect = [62, 0]  # before, after
        mock_fp.return_value = "SHA256:testfp"
        mock_probe.return_value = (True, "Hi user! You've successfully authenticated")
        mock_push.return_value = (0, "main -> main")

        report = orchestrate(
            repo=str(tmp_path),
            primary_key=key,
        )
        assert report.push_succeeded is True
        assert report.outcome == PushOutcome.SUCCESS
        assert report.backlog_drained is True
        assert report.unpushed_before == 62
        assert report.unpushed_after == 0
        assert report.reached_step == PipelineStep.DONE


class TestOrchestrateKeyMissing:
    """Full pipeline: key missing, no backup found."""

    @patch("iamai.push_recovery_orchestrator._count_unpushed")
    def test_key_missing_no_backup(self, mock_count, tmp_path):
        mock_count.return_value = 0
        primary = tmp_path / "nonexistent" / "id_ed25519"

        report = orchestrate(
            repo=str(tmp_path),
            primary_key=primary,
            backup_locations=[],
            search_dirs=[],
        )
        assert report.outcome == PushOutcome.KEY_MISSING
        assert report.needs_human_action is True
        assert report.reached_step == PipelineStep.RECOVERY
        assert "generate a new key" in report.remediation

    @patch("iamai.push_recovery_orchestrator._count_unpushed")
    def test_key_missing_recovery_disabled(self, mock_count, tmp_path):
        mock_count.return_value = 0
        primary = tmp_path / "nonexistent" / "id_ed25519"

        report = orchestrate(
            repo=str(tmp_path),
            primary_key=primary,
            attempt_recovery=False,
        )
        assert report.outcome == PushOutcome.KEY_MISSING
        assert "recovery was disabled" in report.remediation


class TestOrchestrateKeyUnregistered:
    """Full pipeline: key exists but github rejects it."""

    @patch("iamai.push_recovery_orchestrator._probe_github")
    @patch("iamai.push_recovery_orchestrator._key_fingerprint")
    @patch("iamai.push_recovery_orchestrator._count_unpushed")
    def test_key_unregistered(self, mock_count, mock_fp, mock_probe, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake")

        mock_count.return_value = 42
        mock_fp.return_value = "SHA256:umMVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk"
        mock_probe.return_value = (False, "Permission denied (publickey)")

        report = orchestrate(
            repo=str(tmp_path),
            primary_key=key,
        )
        assert report.outcome == PushOutcome.KEY_UNREGISTERED
        assert report.needs_human_action is True
        assert report.reached_step == PipelineStep.PROBE
        assert "deploy key" in report.remediation
        assert "SHA256:" in report.remediation


class TestOrchestratePushFailed:
    """Full pipeline: key works but push itself fails."""

    @patch("iamai.push_recovery_orchestrator._attempt_push")
    @patch("iamai.push_recovery_orchestrator._probe_github")
    @patch("iamai.push_recovery_orchestrator._key_fingerprint")
    @patch("iamai.push_recovery_orchestrator._count_unpushed")
    def test_push_rejected(self, mock_count, mock_fp, mock_probe, mock_push, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake")

        mock_count.side_effect = [10, 10]
        mock_fp.return_value = "SHA256:test"
        mock_probe.return_value = (True, "successfully authenticated")
        mock_push.return_value = (1, "! [rejected] non-fast-forward")

        report = orchestrate(
            repo=str(tmp_path),
            primary_key=key,
        )
        assert report.outcome == PushOutcome.PUSH_FAILED
        assert report.push_exit_code == 1
        assert report.reached_step == PipelineStep.PUSH


class TestOrchestrateNetworkError:
    """Full pipeline: key works but network is down."""

    @patch("iamai.push_recovery_orchestrator._attempt_push")
    @patch("iamai.push_recovery_orchestrator._probe_github")
    @patch("iamai.push_recovery_orchestrator._key_fingerprint")
    @patch("iamai.push_recovery_orchestrator._count_unpushed")
    def test_network_error(self, mock_count, mock_fp, mock_probe, mock_push, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake")

        mock_count.side_effect = [5, 5]
        mock_fp.return_value = "SHA256:test"
        mock_probe.return_value = (True, "successfully authenticated")
        mock_push.return_value = (128, "fatal: Could not resolve host: github.com")

        report = orchestrate(
            repo=str(tmp_path),
            primary_key=key,
        )
        assert report.outcome == PushOutcome.NETWORK_ERROR
        assert "transient" in report.remediation


class TestOrchestrateWithRecovery:
    """Full pipeline: key missing at primary, found in backup."""

    @patch("iamai.push_recovery_orchestrator._attempt_push")
    @patch("iamai.push_recovery_orchestrator._probe_github")
    @patch("iamai.push_recovery_orchestrator._key_fingerprint")
    @patch("iamai.push_recovery_orchestrator._count_unpushed")
    def test_recovery_then_success(self, mock_count, mock_fp, mock_probe, mock_push, tmp_path):
        primary = tmp_path / ".ssh" / "id_ed25519"
        backup = tmp_path / "backup" / "id_ed25519"
        backup.parent.mkdir(parents=True)
        backup.write_text("restored-key")

        mock_count.side_effect = [20, 0]
        mock_fp.return_value = "SHA256:restored"
        mock_probe.return_value = (True, "successfully authenticated")
        mock_push.return_value = (0, "done")

        report = orchestrate(
            repo=str(tmp_path),
            primary_key=primary,
            backup_locations=[backup],
            search_dirs=[],
        )
        assert report.push_succeeded is True
        assert report.key_source == str(backup)
        assert report.reached_step == PipelineStep.DONE


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Boundary and edge-case behavior."""

    @patch("iamai.push_recovery_orchestrator._attempt_push")
    @patch("iamai.push_recovery_orchestrator._probe_github")
    @patch("iamai.push_recovery_orchestrator._key_fingerprint")
    @patch("iamai.push_recovery_orchestrator._count_unpushed")
    def test_elapsed_time_is_recorded(self, mock_count, mock_fp, mock_probe, mock_push, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_text("fake")
        mock_count.return_value = 0
        mock_fp.return_value = "SHA256:test"
        mock_probe.return_value = (True, "ok")
        mock_push.return_value = (0, "ok")

        report = orchestrate(repo=str(tmp_path), primary_key=key)
        assert report.elapsed_s >= 0

    def test_enum_string_values(self):
        assert PushOutcome.SUCCESS.value == "success"
        assert PushOutcome.KEY_MISSING.value == "key_missing"
        assert PushOutcome.KEY_UNREGISTERED.value == "key_unregistered"
        assert PipelineStep.PREFLIGHT.value == "preflight"
        assert PipelineStep.DONE.value == "done"

    @patch("iamai.push_recovery_orchestrator._count_unpushed")
    def test_report_errors_accumulate(self, mock_count, tmp_path):
        mock_count.return_value = 0
        primary = tmp_path / "missing" / "key"

        report = orchestrate(
            repo=str(tmp_path),
            primary_key=primary,
            backup_locations=[],
            search_dirs=[],
        )
        assert len(report.errors) > 0
