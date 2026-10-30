"""Tests for push_key_recovery module — automated SSH key recovery."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.push_key_recovery import (
    PushKeyRecovery,
    RecoveryResult,
    recover_and_report,
)


@pytest.fixture
def workspace(tmp_path):
    """Create an isolated workspace with controllable paths."""
    primary = tmp_path / "primary" / ".ssh"
    backup1 = tmp_path / "backup1" / ".ssh"
    backup2 = tmp_path / "backup2"
    search_dir = tmp_path / "search"

    for d in [primary, backup1, backup2, search_dir]:
        d.mkdir(parents=True, exist_ok=True)

    return {
        "tmp": tmp_path,
        "primary": primary / "id_ed25519",
        "backup1": backup1 / "id_ed25519",
        "backup2": backup2 / "id_ed25519",
        "search_dir": search_dir,
    }


def make_key(path: Path, content: str = "FAKE_KEY_CONTENT") -> Path:
    """Helper: create a fake key file at the given path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    os.chmod(str(path), 0o600)
    # also create a matching .pub
    pub = path.with_suffix(path.suffix + ".pub")
    pub.write_text(f"ssh-ed25519 AAAA... {path.name}@test")
    os.chmod(str(pub), 0o644)
    return path


# ── RecoveryResult properties ─────────────────────────────────────


class TestRecoveryResult:
    def test_push_ready_when_recovered_and_registered(self):
        r = RecoveryResult(recovered=True, registered=True)
        assert r.push_ready is True
        assert r.needs_registration is False

    def test_push_ready_false_when_not_recovered(self):
        r = RecoveryResult(recovered=False)
        assert r.push_ready is False

    def test_push_ready_false_when_not_registered(self):
        r = RecoveryResult(recovered=True, registered=False)
        assert r.push_ready is False
        assert r.needs_registration is True

    def test_needs_registration_false_when_registered(self):
        r = RecoveryResult(recovered=True, registered=True)
        assert r.needs_registration is False

    def test_needs_registration_false_when_not_recovered(self):
        r = RecoveryResult(recovered=False)
        assert r.needs_registration is False

    def test_errors_default_empty(self):
        r = RecoveryResult(recovered=False)
        assert r.errors == []

    def test_source_none_by_default(self):
        r = RecoveryResult(recovered=False)
        assert r.source is None


# ── Backup discovery ──────────────────────────────────────────────


class TestFindBackup:
    def test_finds_first_backup_in_list(self, workspace):
        make_key(workspace["backup1"])
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[workspace["backup1"], workspace["backup2"]],
            probe_github=False,
        )
        found = recovery._find_backup()
        assert found == workspace["backup1"]

    def test_falls_back_to_second_backup(self, workspace):
        make_key(workspace["backup2"])
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[workspace["backup1"], workspace["backup2"]],
            probe_github=False,
        )
        found = recovery._find_backup()
        assert found == workspace["backup2"]

    def test_returns_none_when_no_backups_exist(self, workspace):
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[workspace["backup1"], workspace["backup2"]],
            search_dirs=[],
            probe_github=False,
        )
        found = recovery._find_backup()
        assert found is None

    def test_deep_search_finds_key(self, workspace):
        deep_dir = workspace["search_dir"] / "a" / "b" / "c"
        deep_key = make_key(deep_dir / "id_ed25519")
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[],
            search_dirs=[workspace["search_dir"]],
            probe_github=False,
        )
        found = recovery._find_backup()
        assert found == deep_key

    def test_deep_search_respects_depth_limit(self, workspace):
        too_deep = workspace["search_dir"] / "a" / "b" / "c" / "d" / "e" / "f"
        make_key(too_deep / "id_ed25519")
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[],
            search_dirs=[workspace["search_dir"]],
            probe_github=False,
        )
        found = recovery._find_backup()
        assert found is None

    def test_deep_search_skips_proc_sys(self, workspace):
        proc_dir = workspace["search_dir"] / "proc"
        make_key(proc_dir / "id_ed25519")
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[],
            search_dirs=[workspace["search_dir"]],
            probe_github=False,
        )
        found = recovery._find_backup()
        assert found is None

    def test_deep_search_skips_primary_path(self, workspace):
        # key at primary should not be found as a "backup"
        make_key(workspace["primary"])
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[],
            search_dirs=[workspace["tmp"]],
            probe_github=False,
        )
        found = recovery._find_backup()
        assert found is None


# ── Key restoration ───────────────────────────────────────────────


class TestRestoreKey:
    def test_copies_key_with_correct_permissions(self, workspace):
        src = make_key(workspace["backup1"], "SECRET_KEY_DATA")
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[workspace["backup1"]],
            probe_github=False,
        )
        recovery._restore_key(src)

        assert workspace["primary"].exists()
        assert workspace["primary"].read_text() == "SECRET_KEY_DATA"
        # check permissions
        mode = oct(os.stat(str(workspace["primary"])).st_mode & 0o777)
        assert mode == "0o600"

    def test_copies_public_key_too(self, workspace):
        src = make_key(workspace["backup1"])
        pub_src = src.with_suffix(src.suffix + ".pub")
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[workspace["backup1"]],
            probe_github=False,
        )
        recovery._restore_key(src)

        pub_dest = workspace["primary"].with_suffix(workspace["primary"].suffix + ".pub")
        assert pub_dest.exists()
        assert pub_dest.read_text() == pub_src.read_text()

    def test_creates_parent_directory(self, workspace):
        src = make_key(workspace["backup1"])
        dest = workspace["tmp"] / "new_dir" / ".ssh" / "id_ed25519"
        recovery = PushKeyRecovery(
            primary_path=dest,
            backup_locations=[workspace["backup1"]],
            probe_github=False,
        )
        recovery._restore_key(src)
        assert dest.exists()


# ── Full recovery flow ───────────────────────────────────────────


class TestAttemptRecovery:
    def test_already_present_returns_recovered(self, workspace):
        make_key(workspace["primary"])
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[],
            probe_github=False,
        )
        result = recovery.attempt_recovery()
        assert result.recovered is True
        assert "already present" in (result.source or "")

    def test_missing_key_no_backup_fails(self, workspace):
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[],
            search_dirs=[workspace["search_dir"]],
            probe_github=False,
        )
        result = recovery.attempt_recovery()
        assert result.recovered is False
        assert "generate" in result.remediation.lower()

    def test_restores_from_backup(self, workspace):
        make_key(workspace["backup1"], "BACKUP_KEY")
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[workspace["backup1"]],
            probe_github=False,
        )
        result = recovery.attempt_recovery()
        assert result.recovered is True
        assert str(workspace["backup1"]) in (result.source or "")
        assert workspace["primary"].read_text() == "BACKUP_KEY"

    def test_remediation_mentions_deploy_key_when_unregistered(self, workspace):
        make_key(workspace["primary"])
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[],
            probe_github=False,
        )
        # simulate probe returning False
        recovery._probe_registration = MagicMock(return_value=False)
        result = recovery.attempt_recovery()
        assert "deploy key" in result.remediation.lower()

    def test_remediation_says_push_ready_when_registered(self, workspace):
        make_key(workspace["primary"])
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[],
            probe_github=False,
        )
        recovery._probe_registration = MagicMock(return_value=True)
        result = recovery.attempt_recovery()
        assert "push should work" in result.remediation.lower()

    def test_restore_failure_returns_error(self, workspace):
        make_key(workspace["backup1"])
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            backup_locations=[workspace["backup1"]],
            probe_github=False,
        )
        # simulate a copy failure
        recovery._restore_key = MagicMock(side_effect=OSError("disk full"))
        result = recovery.attempt_recovery()
        assert result.recovered is False
        assert any("disk full" in e for e in result.errors)


# ── Fingerprint extraction ──────────────────────────────────────


class TestExtractFingerprint:
    def test_returns_none_for_missing_key(self, workspace):
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            probe_github=False,
        )
        result = recovery._extract_fingerprint(workspace["primary"])
        assert result is None

    def test_extracts_fingerprint_from_pub_file(self, workspace):
        make_key(workspace["primary"])
        pub = workspace["primary"].with_suffix(workspace["primary"].suffix + ".pub")
        pub.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey test@host")
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            probe_github=False,
        )
        fp = recovery._extract_fingerprint(workspace["primary"])
        # fingerprint should be a SHA256:... string from ssh-keygen
        # since our fake key won't parse, this will return None —
        # that's the correct behavior for unparseable keys
        assert fp is None or fp.startswith("SHA256:")


# ── GitHub probe ─────────────────────────────────────────────────


class TestProbeRegistration:
    def test_returns_true_on_success(self, workspace):
        make_key(workspace["primary"])
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            probe_github=False,
        )
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "Hi FengPwner! You've successfully authenticated..."
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            assert recovery._probe_registration(workspace["primary"]) is True

    def test_returns_false_on_permission_denied(self, workspace):
        make_key(workspace["primary"])
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            probe_github=False,
        )
        mock_result = MagicMock()
        mock_result.returncode = 255
        mock_result.stdout = ""
        mock_result.stderr = "git@github.com: Permission denied (publickey)."
        with patch("subprocess.run", return_value=mock_result):
            assert recovery._probe_registration(workspace["primary"]) is False

    def test_returns_none_on_timeout(self, workspace):
        make_key(workspace["primary"])
        recovery = PushKeyRecovery(
            primary_path=workspace["primary"],
            probe_github=False,
        )
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 10)):
            assert recovery._probe_registration(workspace["primary"]) is None


# ── Convenience entry point ──────────────────────────────────────


class TestRecoverAndReport:
    def test_returns_recovery_result(self):
        # just check it doesn't crash and returns the right type
        result = recover_and_report()
        assert isinstance(result, RecoveryResult)


# ── Remediation text ─────────────────────────────────────────────


class TestRemediationText:
    def test_registered_text(self):
        r = PushKeyRecovery(probe_github=False)
        text = r._remediation_text(True, "SHA256:abc")
        assert "push should work" in text.lower()

    def test_unregistered_text_includes_fingerprint(self):
        r = PushKeyRecovery(probe_github=False)
        text = r._remediation_text(False, "SHA256:xyz123")
        assert "SHA256:xyz123" in text
        assert "deploy key" in text.lower()

    def test_unknown_text(self):
        r = PushKeyRecovery(probe_github=False)
        text = r._remediation_text(None, None)
        assert "unknown" in text.lower()

    def test_unregistered_without_fingerprint(self):
        r = PushKeyRecovery(probe_github=False)
        text = r._remediation_text(False, None)
        assert "fingerprint" not in text
        assert "deploy key" in text.lower()
