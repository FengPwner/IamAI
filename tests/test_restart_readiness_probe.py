"""Tests for iamai.restart_readiness_probe module."""

import os
import time
from pathlib import Path

import pytest

from iamai.restart_readiness_probe import (
    DEFAULT_HEARTBEAT_MAX_AGE,
    DEFAULT_LOCK_THRESHOLD,
    DEFAULT_MIN_FREE_MB,
    ProbeResult,
    ReadinessReport,
    RestartReadinessProbe,
    _probe_deploy_key,
    _probe_disk_headroom,
    _probe_heartbeat_fresh,
    _probe_index_lock,
)


# ── ProbeResult ───────────────────────────────────────────────


class TestProbeResult:
    def test_pass_str(self):
        r = ProbeResult(name="deploy_key", passed=True, detail="/tmp/key")
        assert "[PASS]" in str(r)
        assert "deploy_key" in str(r)

    def test_fail_str(self):
        r = ProbeResult(name="index_lock", passed=False, detail="stale lock: 300s")
        assert "[FAIL]" in str(r)
        assert "300s" in str(r)

    def test_no_detail(self):
        r = ProbeResult(name="test", passed=True)
        assert str(r) == "[PASS] test"


# ── ReadinessReport ──────────────────────────────────────────


class TestReadinessReport:
    def test_ready_when_all_pass(self):
        results = [
            ProbeResult("a", True),
            ProbeResult("b", True),
        ]
        report = ReadinessReport(results=results)
        assert report.ready is True
        assert report.score == 1.0
        assert report.failures == []

    def test_not_ready_when_any_fail(self):
        results = [
            ProbeResult("a", True),
            ProbeResult("b", False, detail="broken"),
        ]
        report = ReadinessReport(results=results)
        assert report.ready is False
        assert len(report.failures) == 1
        assert "broken" in report.failures[0]

    def test_score_partial(self):
        results = [
            ProbeResult("a", True),
            ProbeResult("b", False),
            ProbeResult("c", True),
            ProbeResult("d", False),
        ]
        report = ReadinessReport(results=results)
        assert report.score == 0.5

    def test_score_empty(self):
        report = ReadinessReport(results=[])
        assert report.score == 0.0
        assert report.ready is True  # vacuous truth: all(zero items) = True

    def test_summary_ready(self):
        results = [ProbeResult("a", True), ProbeResult("b", True)]
        report = ReadinessReport(results=results)
        s = report.summary()
        assert "ready" in s
        assert "2/2" in s

    def test_summary_not_ready(self):
        results = [
            ProbeResult("a", True),
            ProbeResult("b", False, "oops"),
        ]
        report = ReadinessReport(results=results)
        s = report.summary()
        assert "NOT ready" in s
        assert "1/2" in s

    def test_frozen(self):
        report = ReadinessReport(results=[])
        with pytest.raises(AttributeError):
            report.timestamp = 999.0  # type: ignore


# ── deploy_key probe ─────────────────────────────────────────


class TestProbeDeployKey:
    def test_no_path(self):
        r = _probe_deploy_key(None)
        assert r.passed is False
        assert "no ssh key path" in r.detail

    def test_missing_file(self, tmp_path):
        r = _probe_deploy_key(str(tmp_path / "nonexistent"))
        assert r.passed is False
        assert "not found" in r.detail

    def test_directory_not_file(self, tmp_path):
        d = tmp_path / "keydir"
        d.mkdir()
        r = _probe_deploy_key(str(d))
        assert r.passed is False
        assert "not a file" in r.detail

    def test_valid_key(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n")
        r = _probe_deploy_key(str(key))
        assert r.passed is True

    def test_empty_key_file(self, tmp_path):
        key = tmp_path / "id_ed25519"
        key.write_bytes(b"")
        r = _probe_deploy_key(str(key))
        # empty but readable → passes (content validation is not our job)
        assert r.passed is True


# ── index_lock probe ─────────────────────────────────────────


class TestProbeIndexLock:
    def _make_repo(self, tmp_path):
        """Create a minimal .git directory."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        return tmp_path

    def test_no_lock(self, tmp_path):
        repo = self._make_repo(tmp_path)
        now = time.time()
        r = _probe_index_lock(str(repo), DEFAULT_LOCK_THRESHOLD, now)
        assert r.passed is True
        assert "no lock" in r.detail

    def test_stale_lock(self, tmp_path):
        repo = self._make_repo(tmp_path)
        lock = repo / ".git" / "index.lock"
        lock.write_text("pid: 12345\n")
        now = time.time()
        # set mtime to 300 seconds ago
        old = now - 300
        os.utime(str(lock), (old, old))
        r = _probe_index_lock(str(repo), DEFAULT_LOCK_THRESHOLD, now)
        assert r.passed is False
        assert "stale" in r.detail
        assert "300" in r.detail

    def test_fresh_lock(self, tmp_path):
        repo = self._make_repo(tmp_path)
        lock = repo / ".git" / "index.lock"
        lock.write_text("pid: 12345\n")
        now = time.time()
        # lock created 10 seconds ago — active, not stale
        old = now - 10
        os.utime(str(lock), (old, old))
        r = _probe_index_lock(str(repo), DEFAULT_LOCK_THRESHOLD, now)
        assert r.passed is True
        assert "young" in r.detail

    def test_custom_threshold(self, tmp_path):
        repo = self._make_repo(tmp_path)
        lock = repo / ".git" / "index.lock"
        lock.write_text("pid: 12345\n")
        now = time.time()
        old = now - 50
        os.utime(str(lock), (old, old))
        # threshold 30s → 50s old lock is stale
        r = _probe_index_lock(str(repo), 30.0, now)
        assert r.passed is False
        # threshold 120s → 50s old lock is fresh
        r2 = _probe_index_lock(str(repo), 120.0, now)
        assert r2.passed is True

    def test_boundary_exact(self, tmp_path):
        repo = self._make_repo(tmp_path)
        lock = repo / ".git" / "index.lock"
        lock.write_text("")
        now = time.time()
        # exactly at threshold
        os.utime(str(lock), (now - DEFAULT_LOCK_THRESHOLD, now - DEFAULT_LOCK_THRESHOLD))
        r = _probe_index_lock(str(repo), DEFAULT_LOCK_THRESHOLD, now)
        # age == threshold → not greater → passes
        assert r.passed is True


# ── disk_headroom probe ──────────────────────────────────────


class TestProbeDiskHeadroom:
    def test_real_path_passes(self, tmp_path):
        # real tmpfs or disk should have > 50 MB free in test environments
        r = _probe_disk_headroom(str(tmp_path), DEFAULT_MIN_FREE_MB)
        # we cannot assert pass/fail on CI (disk might be full),
        # but the probe should return a valid result
        assert r.name == "disk_headroom"
        assert "MB" in r.detail or "filesystem" in r.detail

    def test_nonexistent_path(self):
        r = _probe_disk_headroom("/nonexistent/path/xyz", DEFAULT_MIN_FREE_MB)
        assert r.passed is False
        assert "cannot stat" in r.detail

    def test_high_threshold(self, tmp_path):
        # ask for 1 PB — should fail
        r = _probe_disk_headroom(str(tmp_path), 1_000_000_000.0)
        assert r.passed is False
        assert "low disk" in r.detail

    def test_zero_threshold(self, tmp_path):
        r = _probe_disk_headroom(str(tmp_path), 0.0)
        assert r.passed is True


# ── heartbeat_fresh probe ────────────────────────────────────


class TestProbeHeartbeatFresh:
    def _make_repo(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)
        return tmp_path

    def test_no_heartbeat(self, tmp_path):
        repo = self._make_repo(tmp_path)
        now = time.time()
        r = _probe_heartbeat_fresh(str(repo), "qwen", DEFAULT_HEARTBEAT_MAX_AGE, now)
        assert r.passed is True
        assert "clean start" in r.detail

    def test_fresh_heartbeat(self, tmp_path):
        repo = self._make_repo(tmp_path)
        hb = repo / "data" / "heartbeat.qwen.json"
        hb.write_text('{"ts": 1234567890}')
        now = time.time()
        # heartbeat 60 seconds old
        os.utime(str(hb), (now - 60, now - 60))
        r = _probe_heartbeat_fresh(str(repo), "qwen", DEFAULT_HEARTBEAT_MAX_AGE, now)
        assert r.passed is True
        assert "60s" in r.detail

    def test_stale_heartbeat(self, tmp_path):
        repo = self._make_repo(tmp_path)
        hb = repo / "data" / "heartbeat.qwen.json"
        hb.write_text('{"ts": 1234567890}')
        now = time.time()
        # heartbeat 2 hours old
        os.utime(str(hb), (now - 7200, now - 7200))
        r = _probe_heartbeat_fresh(str(repo), "qwen", DEFAULT_HEARTBEAT_MAX_AGE, now)
        assert r.passed is False
        assert "stale" in r.detail

    def test_custom_writer_id(self, tmp_path):
        repo = self._make_repo(tmp_path)
        hb = repo / "data" / "heartbeat.kimi.json"
        hb.write_text("{}")
        now = time.time()
        os.utime(str(hb), (now - 10, now - 10))
        # kimi heartbeat exists → should find it
        r = _probe_heartbeat_fresh(str(repo), "kimi", DEFAULT_HEARTBEAT_MAX_AGE, now)
        assert r.passed is True
        # qwen heartbeat does not exist → clean start
        r2 = _probe_heartbeat_fresh(str(repo), "qwen", DEFAULT_HEARTBEAT_MAX_AGE, now)
        assert r2.passed is True
        assert "clean start" in r2.detail

    def test_boundary_exact(self, tmp_path):
        repo = self._make_repo(tmp_path)
        hb = repo / "data" / "heartbeat.qwen.json"
        hb.write_text("{}")
        now = time.time()
        os.utime(str(hb), (now - DEFAULT_HEARTBEAT_MAX_AGE, now - DEFAULT_HEARTBEAT_MAX_AGE))
        r = _probe_heartbeat_fresh(str(repo), "qwen", DEFAULT_HEARTBEAT_MAX_AGE, now)
        # age == threshold → not greater → passes
        assert r.passed is True


# ── RestartReadinessProbe orchestrator ───────────────────────


class TestRestartReadinessProbe:
    def _setup_repo(self, tmp_path, with_key=True, with_lock=False, lock_age=0):
        """Create a minimal repo structure for testing."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        key_path = None
        if with_key:
            key = tmp_path / "id_ed25519"
            key.write_bytes(b"fake-key")
            key_path = str(key)

        if with_lock:
            lock = git_dir / "index.lock"
            lock.write_text("pid: 1\n")
            if lock_age:
                now = time.time()
                os.utime(str(lock), (now - lock_age, now - lock_age))

        return str(tmp_path), key_path

    def test_all_pass(self, tmp_path):
        repo, key = self._setup_repo(tmp_path, with_key=True)
        probe = RestartReadinessProbe(
            repo_root=repo,
            ssh_key_path=key,
            now=time.time(),
        )
        report = probe.check()
        assert report.ready is True
        assert report.score == 1.0
        assert len(report.results) == 4

    def test_no_key_fails(self, tmp_path):
        repo, _ = self._setup_repo(tmp_path, with_key=False)
        probe = RestartReadinessProbe(
            repo_root=repo,
            ssh_key_path=None,
            now=time.time(),
        )
        report = probe.check()
        assert report.ready is False
        assert any("deploy_key" in f for f in report.failures)

    def test_stale_lock_fails(self, tmp_path):
        repo, key = self._setup_repo(
            tmp_path, with_key=True, with_lock=True, lock_age=300
        )
        probe = RestartReadinessProbe(
            repo_root=repo,
            ssh_key_path=key,
            now=time.time(),
        )
        report = probe.check()
        assert report.ready is False
        assert any("index_lock" in f for f in report.failures)

    def test_multiple_failures(self, tmp_path):
        repo, _ = self._setup_repo(
            tmp_path, with_key=False, with_lock=True, lock_age=300
        )
        probe = RestartReadinessProbe(
            repo_root=repo,
            ssh_key_path=None,
            now=time.time(),
        )
        report = probe.check()
        assert report.ready is False
        assert len(report.failures) >= 2

    def test_custom_thresholds(self, tmp_path):
        repo, key = self._setup_repo(
            tmp_path, with_key=True, with_lock=True, lock_age=50
        )
        now = time.time()
        # strict threshold: 30s → lock is stale
        probe_strict = RestartReadinessProbe(
            repo_root=repo,
            ssh_key_path=key,
            lock_threshold=30.0,
            now=now,
        )
        r1 = probe_strict.check()
        assert any("index_lock" in f for f in r1.failures)

        # lenient threshold: 120s → lock is fresh
        probe_lenient = RestartReadinessProbe(
            repo_root=repo,
            ssh_key_path=key,
            lock_threshold=120.0,
            now=now,
        )
        r2 = probe_lenient.check()
        assert not any("index_lock" in f for f in r2.failures)

    def test_default_now(self, tmp_path):
        """Constructor uses time.time() when now is not provided."""
        repo, key = self._setup_repo(tmp_path, with_key=True)
        probe = RestartReadinessProbe(repo_root=repo, ssh_key_path=key)
        report = probe.check()
        # timestamp should be close to now
        assert abs(report.timestamp - time.time()) < 5.0

    def test_four_probes_always(self, tmp_path):
        """Even with failures, all four probes run."""
        repo, _ = self._setup_repo(tmp_path, with_key=False)
        probe = RestartReadinessProbe(
            repo_root=repo,
            ssh_key_path=None,
            now=time.time(),
        )
        report = probe.check()
        names = [r.name for r in report.results]
        assert "deploy_key" in names
        assert "index_lock" in names
        assert "disk_headroom" in names
        assert "heartbeat_fresh" in names
        assert len(report.results) == 4
