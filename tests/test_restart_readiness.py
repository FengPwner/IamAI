"""Tests for iamai.restart_readiness — pre-restart environment readiness."""

import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.restart_readiness import (
    CheckResult,
    ReadinessReport,
    RestartReadinessChecker,
    DEFAULT_MIN_FREE_MB,
    DEFAULT_MAX_DIRTY_FILES,
    DEFAULT_MAX_DIRTY_FAIL,
    DEFAULT_SSH_KEY_PATH,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _init_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo in tmp_path and return it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init"], cwd=str(repo),
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo), capture_output=True, check=True,
    )
    # create initial commit
    readme = repo / "README.md"
    readme.write_text("# Test Repo\n")
    subprocess.run(
        ["git", "add", "."], cwd=str(repo),
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(repo), capture_output=True, check=True,
    )
    return repo


def _make_checker(
    repo: Path,
    **kwargs,
) -> RestartReadinessChecker:
    """Create a checker with defaults suitable for tests."""
    defaults = {
        "repo_root": str(repo),
        "ssh_key_path": str(repo / ".deploy_key"),
        "cooldown_log_path": str(repo / "data" / "restart_cooldown.jsonl"),
    }
    defaults.update(kwargs)
    return RestartReadinessChecker(**defaults)


# ---------------------------------------------------------------------------
# CheckResult dataclass
# ---------------------------------------------------------------------------

class TestCheckResult:
    def test_fields(self):
        r = CheckResult(name="test", status="pass", detail="all good")
        assert r.name == "test"
        assert r.status == "pass"
        assert r.detail == "all good"

    def test_frozen(self):
        r = CheckResult(name="test", status="pass")
        with pytest.raises(AttributeError):
            r.status = "fail"

    def test_to_dict(self):
        r = CheckResult(name="disk_space", status="warn", detail="low")
        d = r.to_dict()
        assert d == {"name": "disk_space", "status": "warn", "detail": "low"}

    def test_default_detail(self):
        r = CheckResult(name="x", status="pass")
        assert r.detail == ""


# ---------------------------------------------------------------------------
# ReadinessReport dataclass
# ---------------------------------------------------------------------------

class TestReadinessReport:
    def test_verdict_ready(self):
        checks = [
            CheckResult(name="a", status="pass"),
            CheckResult(name="b", status="warn", detail="meh"),
        ]
        r = ReadinessReport(verdict="ready", checks=checks, elapsed_ms=10, repo_root="/tmp")
        assert r.verdict == "ready"
        assert len(r.failures) == 0
        assert len(r.warnings) == 1
        assert len(r.passes) == 1

    def test_verdict_blocked(self):
        checks = [
            CheckResult(name="a", status="pass"),
            CheckResult(name="b", status="fail", detail="broken"),
        ]
        r = ReadinessReport(verdict="blocked", checks=checks, elapsed_ms=5, repo_root="/tmp")
        assert r.verdict == "blocked"
        assert len(r.failures) == 1
        assert r.failures[0].name == "b"

    def test_summary_text(self):
        checks = [
            CheckResult(name="a", status="fail", detail="x"),
            CheckResult(name="b", status="warn", detail="y"),
        ]
        r = ReadinessReport(verdict="blocked", checks=checks, elapsed_ms=42, repo_root="/tmp")
        s = r.summary_text()
        assert "blocked" in s
        assert "a" in s
        assert "warnings" in s
        assert "42ms" in s

    def test_to_dict(self):
        checks = [CheckResult(name="a", status="pass")]
        r = ReadinessReport(verdict="ready", checks=checks, elapsed_ms=1.5, repo_root="/tmp")
        d = r.to_dict()
        assert d["verdict"] == "ready"
        assert d["elapsed_ms"] == 1.5
        assert len(d["checks"]) == 1
        assert "summary" in d


# ---------------------------------------------------------------------------
# RestartReadinessChecker — initialization
# ---------------------------------------------------------------------------

class TestInit:
    def test_accepts_string_path(self, tmp_path):
        c = RestartReadinessChecker(repo_root=str(tmp_path))
        assert c.repo_root == tmp_path.resolve()

    def test_accepts_path_object(self, tmp_path):
        c = RestartReadinessChecker(repo_root=tmp_path)
        assert c.repo_root == tmp_path.resolve()

    def test_default_values(self, tmp_path):
        c = RestartReadinessChecker(repo_root=tmp_path)
        assert c.min_free_mb == DEFAULT_MIN_FREE_MB
        assert c.max_dirty_files == DEFAULT_MAX_DIRTY_FILES
        assert c.max_dirty_fail == DEFAULT_MAX_DIRTY_FAIL
        assert c.max_restarts_per_hour == 3

    def test_custom_values(self, tmp_path):
        c = RestartReadinessChecker(
            repo_root=tmp_path,
            min_free_mb=500,
            max_dirty_files=10,
            max_restarts_per_hour=5,
        )
        assert c.min_free_mb == 500
        assert c.max_dirty_files == 10
        assert c.max_restarts_per_hour == 5

    def test_check_names(self, tmp_path):
        c = RestartReadinessChecker(repo_root=tmp_path)
        assert len(c.check_names) == 6
        assert "git_index_clean" in c.check_names
        assert "disk_space" in c.check_names


# ---------------------------------------------------------------------------
# git_index_clean check
# ---------------------------------------------------------------------------

class TestGitIndexClean:
    def test_clean_repo(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        c = _make_checker(repo)
        r = c.check_one("git_index_clean")
        assert r.status == "pass"

    def test_lock_file_detected(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        lock = repo / ".git" / "index.lock"
        lock.write_text("locked")
        c = _make_checker(repo)
        r = c.check_one("git_index_clean")
        assert r.status == "fail"
        assert "lock" in r.detail.lower()

    def test_merge_head_detected(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        merge_head = repo / ".git" / "MERGE_HEAD"
        merge_head.write_text("abc123\n")
        c = _make_checker(repo)
        r = c.check_one("git_index_clean")
        assert r.status == "fail"
        assert "merge" in r.detail.lower()

    def test_dirty_tree_still_passes(self, tmp_path):
        """Dirty files are not a git index problem — they're a working tree check."""
        repo = _init_git_repo(tmp_path)
        (repo / "new_file.txt").write_text("dirty")
        c = _make_checker(repo)
        r = c.check_one("git_index_clean")
        assert r.status == "pass"


# ---------------------------------------------------------------------------
# disk_space check
# ---------------------------------------------------------------------------

class TestDiskSpace:
    def test_normal_pass(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        c = _make_checker(repo, min_free_mb=1)  # 1 MB — always passes on modern systems
        r = c.check_one("disk_space")
        assert r.status == "pass"
        assert "GB free" in r.detail or "MB free" in r.detail

    def test_impossible_threshold_fails(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        c = _make_checker(repo, min_free_mb=999_999_999)  # ~1 PB
        r = c.check_one("disk_space")
        assert r.status == "fail"
        assert "need" in r.detail

    def test_warn_threshold(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        # set min_free_mb high enough to trigger warn (10x min) but not fail
        usage = __import__("shutil").disk_usage(str(repo))
        free_mb = usage.free / (1024 * 1024)
        # set min so that free is between min and min*10
        target_min = int(free_mb / 5)
        c = _make_checker(repo, min_free_mb=target_min)
        r = c.check_one("disk_space")
        assert r.status == "warn"
        assert "approaching" in r.detail


# ---------------------------------------------------------------------------
# credential_ready check
# ---------------------------------------------------------------------------

class TestCredentialReady:
    def test_key_present_and_readable(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        key = repo / ".deploy_key"
        key.write_text("ssh-ed25519 AAAA...")
        c = _make_checker(repo, ssh_key_path=str(key))
        r = c.check_one("credential_ready")
        assert r.status == "pass"
        assert "ready" in r.detail

    def test_key_missing_no_alts(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        c = _make_checker(repo, ssh_key_path=str(repo / "nonexistent_key"))
        # mock Path.home() so ~/.ssh/id_ed25519 is not found
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        with patch("iamai.restart_readiness.Path.home", return_value=fake_home):
            r = c.check_one("credential_ready")
        assert r.status == "fail"
        assert "not found" in r.detail

    def test_key_empty(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        key = repo / ".deploy_key"
        key.write_text("")
        c = _make_checker(repo, ssh_key_path=str(key))
        r = c.check_one("credential_ready")
        assert r.status == "fail"
        assert "empty" in r.detail

    def test_key_unreadable(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        key = repo / ".deploy_key"
        key.write_text("secret")
        c = _make_checker(repo, ssh_key_path=str(key))
        # mock os.access to deny read (root bypasses real permissions)
        with patch("iamai.restart_readiness.os.access", return_value=False):
            r = c.check_one("credential_ready")
        assert r.status == "fail"
        assert "not readable" in r.detail

    def test_alt_path_found(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        alt = repo / ".deploy_key"
        alt.write_text("ssh-ed25519 AAAA...")
        # primary path does not exist
        c = _make_checker(repo, ssh_key_path=str(repo / "nonexistent"))
        r = c.check_one("credential_ready")
        # should be warn (primary missing but alt found)
        assert r.status == "warn"
        assert "found at" in r.detail


# ---------------------------------------------------------------------------
# no_stale_pids check
# ---------------------------------------------------------------------------

class TestNoStalePids:
    def test_no_stale_processes(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        c = _make_checker(repo)
        r = c.check_one("no_stale_pids")
        assert r.status == "pass"
        assert "no zombie" in r.detail

    def test_detects_zombie(self, tmp_path):
        """Mock a zombie process detection."""
        repo = _init_git_repo(tmp_path)
        c = _make_checker(repo)

        mock_result = MagicMock()
        mock_result.stdout = "12345 python3 tools/writer_loop.py --writer qwen"

        with patch("subprocess.run", return_value=mock_result):
            with patch("pathlib.Path.exists", return_value=True):
                with patch(
                    "pathlib.Path.read_text",
                    return_value="State:\tZ (zombie)\n",
                ):
                    r = c.check_one("no_stale_pids")
                    assert r.status == "warn"
                    assert "zombie" in r.detail


# ---------------------------------------------------------------------------
# working_tree_manageable check
# ---------------------------------------------------------------------------

class TestWorkingTreeManageable:
    def test_clean_tree(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        c = _make_checker(repo)
        r = c.check_one("working_tree_manageable")
        assert r.status == "pass"
        assert "0 dirty" in r.detail

    def test_few_dirty_files(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        for i in range(3):
            (repo / f"file_{i}.txt").write_text(f"content {i}")
        c = _make_checker(repo)
        r = c.check_one("working_tree_manageable")
        assert r.status == "pass"

    def test_warn_threshold(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        c = _make_checker(repo, max_dirty_files=2, max_dirty_fail=100)
        for i in range(5):
            (repo / f"file_{i}.txt").write_text(f"content {i}")
        r = c.check_one("working_tree_manageable")
        assert r.status == "warn"

    def test_fail_threshold(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        c = _make_checker(repo, max_dirty_files=2, max_dirty_fail=3)
        for i in range(5):
            (repo / f"file_{i}.txt").write_text(f"content {i}")
        r = c.check_one("working_tree_manageable")
        assert r.status == "fail"


# ---------------------------------------------------------------------------
# cooldown_respected check
# ---------------------------------------------------------------------------

class TestCooldownRespected:
    def test_no_log_file(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        c = _make_checker(repo, cooldown_log_path=str(repo / "nonexistent.jsonl"))
        r = c.check_one("cooldown_respected")
        assert r.status == "pass"
        assert "first restart" in r.detail

    def test_empty_log(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        log = repo / "data" / "restart_cooldown.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("")
        c = _make_checker(repo)
        r = c.check_one("cooldown_respected")
        assert r.status == "pass"

    def test_within_limit(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        log = repo / "data" / "restart_cooldown.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        entries = [
            json.dumps({"ts": now - 600, "decision": "allowed"}),
        ]
        log.write_text("\n".join(entries) + "\n")
        c = _make_checker(repo, max_restarts_per_hour=3)
        r = c.check_one("cooldown_respected")
        assert r.status == "pass"

    def test_at_limit_warns(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        log = repo / "data" / "restart_cooldown.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        entries = [
            json.dumps({"ts": now - 600, "decision": "allowed"}),
            json.dumps({"ts": now - 300, "decision": "allowed"}),
        ]
        log.write_text("\n".join(entries) + "\n")
        c = _make_checker(repo, max_restarts_per_hour=3)
        r = c.check_one("cooldown_respected")
        assert r.status == "warn"
        assert "2/3" in r.detail

    def test_exceeds_limit_fails(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        log = repo / "data" / "restart_cooldown.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        entries = [
            json.dumps({"ts": now - 600, "decision": "allowed"}),
            json.dumps({"ts": now - 300, "decision": "allowed"}),
            json.dumps({"ts": now - 100, "decision": "allowed"}),
        ]
        log.write_text("\n".join(entries) + "\n")
        c = _make_checker(repo, max_restarts_per_hour=3)
        r = c.check_one("cooldown_respected")
        assert r.status == "fail"
        assert "3 restarts" in r.detail

    def test_old_entries_ignored(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        log = repo / "data" / "restart_cooldown.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        entries = [
            json.dumps({"ts": now - 7200, "decision": "allowed"}),
            json.dumps({"ts": now - 5400, "decision": "allowed"}),
            json.dumps({"ts": now - 3600 - 100, "decision": "allowed"}),
        ]
        log.write_text("\n".join(entries) + "\n")
        c = _make_checker(repo, max_restarts_per_hour=3)
        r = c.check_one("cooldown_respected")
        assert r.status == "pass"
        assert "0/3" in r.detail

    def test_denied_entries_not_counted(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        log = repo / "data" / "restart_cooldown.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        entries = [
            json.dumps({"ts": now - 600, "decision": "allowed"}),
            json.dumps({"ts": now - 300, "decision": "denied"}),
            json.dumps({"ts": now - 100, "decision": "denied"}),
        ]
        log.write_text("\n".join(entries) + "\n")
        c = _make_checker(repo, max_restarts_per_hour=3)
        r = c.check_one("cooldown_respected")
        assert r.status == "pass"
        assert "1/3" in r.detail


# ---------------------------------------------------------------------------
# check_all — integration
# ---------------------------------------------------------------------------

class TestCheckAll:
    def test_clean_repo_all_pass(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        key = repo / ".deploy_key"
        key.write_text("ssh-ed25519 AAAA...")
        c = _make_checker(repo, ssh_key_path=str(key))
        report = c.check_all()
        assert report.verdict == "ready"
        assert len(report.checks) == 6
        assert report.elapsed_ms > 0

    def test_blocked_by_lock(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        key = repo / ".deploy_key"
        key.write_text("ssh-ed25519 AAAA...")
        (repo / ".git" / "index.lock").write_text("locked")
        c = _make_checker(repo, ssh_key_path=str(key))
        report = c.check_all()
        assert report.verdict == "blocked"
        assert any(f.name == "git_index_clean" for f in report.failures)

    def test_all_checks_run_despite_failures(self, tmp_path):
        """One check failing should not prevent others from running."""
        repo = _init_git_repo(tmp_path)
        # no deploy key, lock file → two failures
        (repo / ".git" / "index.lock").write_text("locked")
        c = _make_checker(repo, ssh_key_path=str(repo / "missing_key"))
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        with patch("iamai.restart_readiness.Path.home", return_value=fake_home):
            report = c.check_all()
        assert len(report.checks) == 6
        assert report.verdict == "blocked"
        # multiple failures should be reported
        assert len(report.failures) >= 2

    def test_unknown_check_raises(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        c = _make_checker(repo)
        with pytest.raises(ValueError, match="unknown check"):
            c.check_one("nonexistent_check")


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_malformed_cooldown_json(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        log = repo / "data" / "restart_cooldown.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("not json\n{broken\n\n")
        c = _make_checker(repo)
        r = c.check_one("cooldown_respected")
        # should not crash, treat as 0 restarts
        assert r.status == "pass"

    def test_cooldown_with_string_timestamps(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        log = repo / "data" / "restart_cooldown.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        entries = [
            json.dumps({"ts": "2026-01-01T00:00:00", "decision": "allowed"}),
        ]
        log.write_text("\n".join(entries) + "\n")
        c = _make_checker(repo)
        r = c.check_one("cooldown_respected")
        # string timestamps are skipped
        assert r.status == "pass"

    def test_report_summary_contains_all_sections(self, tmp_path):
        checks = [
            CheckResult(name="a", status="pass"),
            CheckResult(name="b", status="fail", detail="broken"),
            CheckResult(name="c", status="warn", detail="iffy"),
        ]
        r = ReadinessReport(
            verdict="blocked", checks=checks, elapsed_ms=99, repo_root="/tmp"
        )
        s = r.summary_text()
        assert "blocked" in s
        assert "b" in s
        assert "warnings" in s
        assert "99ms" in s
