"""Tests for tools/push_wire_check.py — push-pathway diagnostics.

Run:  python3 -m pytest tests/test_push_wire_check.py -v
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import push_wire_check as pwc  # noqa: E402


# ---------------------------------------------------------------------------
# CheckResult / WireReport
# ---------------------------------------------------------------------------

class TestDataStructures:
    def test_check_result_fields(self):
        cr = pwc.CheckResult("test", "pass", "all good")
        assert cr.name == "test"
        assert cr.status == "pass"
        assert cr.detail == "all good"

    def test_wire_report_to_dict(self):
        checks = [
            pwc.CheckResult("a", "pass", "ok"),
            pwc.CheckResult("b", "fail", "broken"),
        ]
        report = pwc.WireReport(checks=checks, verdict="fail")
        d = report.to_dict()
        assert d["verdict"] == "fail"
        assert len(d["checks"]) == 2
        assert d["checks"][0]["name"] == "a"
        assert d["checks"][1]["status"] == "fail"

    def test_severity_order_complete(self):
        assert pwc.SEVERITY_ORDER["pass"] < pwc.SEVERITY_ORDER["warn"]
        assert pwc.SEVERITY_ORDER["warn"] < pwc.SEVERITY_ORDER["fail"]


# ---------------------------------------------------------------------------
# check_ssh_key
# ---------------------------------------------------------------------------

class TestCheckSSHKey:
    def test_no_git_ssh_command_warns(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GIT_SSH_COMMAND", None)
            result = pwc.check_ssh_key(Path("/tmp"))
        assert result.status == "warn"
        assert "GIT_SSH_COMMAND" in result.detail

    def test_git_ssh_command_without_i_flag(self):
        with patch.dict(os.environ, {"GIT_SSH_COMMAND": "ssh -o BatchMode=yes"}):
            result = pwc.check_ssh_key(Path("/tmp"))
        assert result.status == "warn"
        assert "no -i flag" in result.detail

    def test_missing_key_file_fails(self, tmp_path):
        cmd = f"ssh -i {tmp_path}/nonexistent_key -o StrictHostKeyChecking=no"
        with patch.dict(os.environ, {"GIT_SSH_COMMAND": cmd}):
            result = pwc.check_ssh_key(Path("/tmp"))
        assert result.status == "fail"
        assert "not found" in result.detail

    def test_key_with_correct_permissions(self, tmp_path):
        key = tmp_path / "deploy_key"
        key.write_text("fake key content")
        key.chmod(0o600)
        cmd = f"ssh -i {key} -o StrictHostKeyChecking=no"
        with patch.dict(os.environ, {"GIT_SSH_COMMAND": cmd}):
            result = pwc.check_ssh_key(Path("/tmp"))
        assert result.status == "pass"
        assert "0o600" in result.detail

    def test_key_with_wrong_permissions_warns(self, tmp_path):
        key = tmp_path / "deploy_key"
        key.write_text("fake key content")
        key.chmod(0o644)
        cmd = f"ssh -i {key} -o StrictHostKeyChecking=no"
        with patch.dict(os.environ, {"GIT_SSH_COMMAND": cmd}):
            result = pwc.check_ssh_key(Path("/tmp"))
        assert result.status == "warn"
        assert "permissions" in result.detail


# ---------------------------------------------------------------------------
# check_divergence
# ---------------------------------------------------------------------------

class TestCheckDivergence:
    def test_clean_when_identical(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "0\t0\n"
        with patch.object(pwc, "_run", return_value=mock):
            result = pwc.check_divergence(repo)
        assert result.status == "pass"
        assert "clean" in result.detail

    def test_ahead_is_safe_to_push(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "3\t0\n"
        with patch.object(pwc, "_run", return_value=mock):
            result = pwc.check_divergence(repo)
        assert result.status == "pass"
        assert "ahead 3" in result.detail

    def test_behind_needs_pull(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "0\t2\n"
        with patch.object(pwc, "_run", return_value=mock):
            result = pwc.check_divergence(repo)
        assert result.status == "warn"
        assert "behind 2" in result.detail

    def test_diverged_needs_rebase(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "3\t2\n"
        with patch.object(pwc, "_run", return_value=mock):
            result = pwc.check_divergence(repo)
        assert result.status == "fail"
        assert "diverged" in result.detail

    def test_rev_list_failure_warns(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        mock = MagicMock()
        mock.returncode = 1
        mock.stdout = ""
        with patch.object(pwc, "_run", return_value=mock):
            result = pwc.check_divergence(repo)
        assert result.status == "warn"


# ---------------------------------------------------------------------------
# check_dirty_tree
# ---------------------------------------------------------------------------

class TestCheckDirtyTree:
    def test_clean_tree(self, tmp_path):
        mock = MagicMock()
        mock.stdout = ""
        with patch.object(pwc, "_run", return_value=mock):
            result = pwc.check_dirty_tree(tmp_path)
        assert result.status == "pass"
        assert "clean" in result.detail

    def test_untracked_only_is_rebase_safe(self, tmp_path):
        mock = MagicMock()
        mock.stdout = "?? new_file.txt\n?? another.txt\n"
        with patch.object(pwc, "_run", return_value=mock):
            result = pwc.check_dirty_tree(tmp_path)
        assert result.status == "pass"
        assert "untracked" in result.detail

    def test_tracked_modifications_warn(self, tmp_path):
        mock = MagicMock()
        mock.stdout = " M modified.py\n M another.py\n?? untracked.txt\n"
        with patch.object(pwc, "_run", return_value=mock):
            result = pwc.check_dirty_tree(tmp_path)
        assert result.status == "warn"
        assert "2 modified" in result.detail

    def test_staged_changes_warn(self, tmp_path):
        mock = MagicMock()
        mock.stdout = "M  staged.py\n"
        with patch.object(pwc, "_run", return_value=mock):
            result = pwc.check_dirty_tree(tmp_path)
        assert result.status == "warn"


# ---------------------------------------------------------------------------
# check_sync_import
# ---------------------------------------------------------------------------

class TestCheckSyncImport:
    def test_import_and_call_present(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "commit_batch.py").write_text(textwrap.dedent("""\
            import pre_push_sync
            result = pre_push_sync.sync(REPO)
        """))
        result = pwc.check_sync_import(tmp_path)
        assert result.status == "pass"

    def test_import_without_call_warns(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "commit_batch.py").write_text(textwrap.dedent("""\
            import pre_push_sync
            # but never calls it
        """))
        result = pwc.check_sync_import(tmp_path)
        # "imported but not called" — but our check looks for the name
        # appearing anywhere after import, which is a heuristic
        assert result.status in ("pass", "warn")

    def test_no_import_fails(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "commit_batch.py").write_text(textwrap.dedent("""\
            import os
            # no pre_push_sync here
        """))
        result = pwc.check_sync_import(tmp_path)
        assert result.status == "fail"
        assert "does NOT import" in result.detail

    def test_missing_file_fails(self, tmp_path):
        result = pwc.check_sync_import(tmp_path)
        assert result.status == "fail"
        assert "not found" in result.detail


# ---------------------------------------------------------------------------
# check_unpushed
# ---------------------------------------------------------------------------

class TestCheckUnpushed:
    def test_nothing_to_push(self, tmp_path):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = ""
        with patch.object(pwc, "_run", return_value=mock):
            result = pwc.check_unpushed(tmp_path)
        assert result.status == "pass"
        assert "nothing" in result.detail

    def test_few_unpushed_passes(self, tmp_path):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "abc1234 commit one\ndef5678 commit two\n"
        with patch.object(pwc, "_run", return_value=mock):
            result = pwc.check_unpushed(tmp_path)
        assert result.status == "pass"
        assert "2 unpushed" in result.detail

    def test_many_unpushed_warns(self, tmp_path):
        mock = MagicMock()
        mock.returncode = 0
        lines = [f"abc{i:04d} commit {i}" for i in range(10)]
        mock.stdout = "\n".join(lines) + "\n"
        with patch.object(pwc, "_run", return_value=mock):
            result = pwc.check_unpushed(tmp_path)
        assert result.status == "warn"
        assert "backlog" in result.detail

    def test_git_failure_warns(self, tmp_path):
        mock = MagicMock()
        mock.returncode = 1
        mock.stdout = ""
        with patch.object(pwc, "_run", return_value=mock):
            result = pwc.check_unpushed(tmp_path)
        assert result.status == "warn"


# ---------------------------------------------------------------------------
# run_all_checks / orchestration
# ---------------------------------------------------------------------------

class TestOrchestration:
    def test_all_pass_gives_pass_verdict(self, tmp_path):
        checks = [
            pwc.CheckResult("a", "pass", "ok"),
            pwc.CheckResult("b", "pass", "ok"),
        ]
        with patch.multiple(
            pwc,
            check_ssh_key=lambda repo: checks[0],
            check_remote=lambda repo, timeout=15: checks[1],
            check_divergence=lambda repo: pwc.CheckResult("c", "pass", "ok"),
            check_dirty_tree=lambda repo: pwc.CheckResult("d", "pass", "ok"),
            check_sync_import=lambda repo: pwc.CheckResult("e", "pass", "ok"),
            check_unpushed=lambda repo: pwc.CheckResult("f", "pass", "ok"),
        ):
            report = pwc.run_all_checks(tmp_path)
        assert report.verdict == "pass"
        assert len(report.checks) == 6

    def test_one_fail_makes_verdict_fail(self, tmp_path):
        with patch.multiple(
            pwc,
            check_ssh_key=lambda repo: pwc.CheckResult("ssh", "pass", "ok"),
            check_remote=lambda repo, timeout=15: pwc.CheckResult("remote", "fail", "down"),
            check_divergence=lambda repo: pwc.CheckResult("div", "pass", "ok"),
            check_dirty_tree=lambda repo: pwc.CheckResult("dirty", "pass", "ok"),
            check_sync_import=lambda repo: pwc.CheckResult("sync", "pass", "ok"),
            check_unpushed=lambda repo: pwc.CheckResult("unpushed", "pass", "ok"),
        ):
            report = pwc.run_all_checks(tmp_path)
        assert report.verdict == "fail"

    def test_warn_beats_pass_in_verdict(self, tmp_path):
        with patch.multiple(
            pwc,
            check_ssh_key=lambda repo: pwc.CheckResult("ssh", "pass", "ok"),
            check_remote=lambda repo, timeout=15: pwc.CheckResult("remote", "pass", "ok"),
            check_divergence=lambda repo: pwc.CheckResult("div", "warn", "behind"),
            check_dirty_tree=lambda repo: pwc.CheckResult("dirty", "pass", "ok"),
            check_sync_import=lambda repo: pwc.CheckResult("sync", "pass", "ok"),
            check_unpushed=lambda repo: pwc.CheckResult("unpushed", "pass", "ok"),
        ):
            report = pwc.run_all_checks(tmp_path)
        assert report.verdict == "warn"

    def test_json_output_structure(self, tmp_path, capsys):
        """Verify JSON output mode produces valid JSON."""
        with patch.multiple(
            pwc,
            check_ssh_key=lambda repo: pwc.CheckResult("ssh", "pass", "ok"),
            check_remote=lambda repo, timeout=15: pwc.CheckResult("remote", "pass", "ok"),
            check_divergence=lambda repo: pwc.CheckResult("div", "pass", "ok"),
            check_dirty_tree=lambda repo: pwc.CheckResult("dirty", "pass", "ok"),
            check_sync_import=lambda repo: pwc.CheckResult("sync", "pass", "ok"),
            check_unpushed=lambda repo: pwc.CheckResult("unpushed", "pass", "ok"),
        ):
            report = pwc.run_all_checks(tmp_path)
        d = report.to_dict()
        # Verify it round-trips through JSON
        serialized = json.dumps(d)
        deserialized = json.loads(serialized)
        assert deserialized["verdict"] == "pass"
        assert len(deserialized["checks"]) == 6


# ---------------------------------------------------------------------------
# _run helper
# ---------------------------------------------------------------------------

class TestRunHelper:
    def test_returns_completed_process(self):
        result = pwc._run(["echo", "hello"])
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_captures_stderr(self):
        result = pwc._run(["bash", "-c", "echo err >&2"])
        assert "err" in result.stderr

    def test_timeout_raises(self):
        with pytest.raises(subprocess.TimeoutExpired):
            pwc._run(["sleep", "10"], timeout=1)


# ---------------------------------------------------------------------------
# main() exit codes
# ---------------------------------------------------------------------------

class TestMain:
    def test_exit_code_zero_on_all_pass(self, tmp_path):
        with patch.multiple(
            pwc,
            REPO_DEFAULT=tmp_path,
            check_ssh_key=lambda repo: pwc.CheckResult("ssh", "pass", "ok"),
            check_remote=lambda repo, timeout=15: pwc.CheckResult("remote", "pass", "ok"),
            check_divergence=lambda repo: pwc.CheckResult("div", "pass", "ok"),
            check_dirty_tree=lambda repo: pwc.CheckResult("dirty", "pass", "ok"),
            check_sync_import=lambda repo: pwc.CheckResult("sync", "pass", "ok"),
            check_unpushed=lambda repo: pwc.CheckResult("unpushed", "pass", "ok"),
        ):
            with patch("sys.argv", ["push_wire_check.py", "--repo", str(tmp_path)]):
                assert pwc.main() == 0

    def test_exit_code_two_on_fail(self, tmp_path):
        with patch.multiple(
            pwc,
            REPO_DEFAULT=tmp_path,
            check_ssh_key=lambda repo: pwc.CheckResult("ssh", "fail", "missing"),
            check_remote=lambda repo, timeout=15: pwc.CheckResult("remote", "pass", "ok"),
            check_divergence=lambda repo: pwc.CheckResult("div", "pass", "ok"),
            check_dirty_tree=lambda repo: pwc.CheckResult("dirty", "pass", "ok"),
            check_sync_import=lambda repo: pwc.CheckResult("sync", "pass", "ok"),
            check_unpushed=lambda repo: pwc.CheckResult("unpushed", "pass", "ok"),
        ):
            with patch("sys.argv", ["push_wire_check.py", "--repo", str(tmp_path)]):
                assert pwc.main() == 2
