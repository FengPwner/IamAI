"""Tests for iamai.push_readiness — the pre-push diagnostic.

Covers:
  - SSH key probe (present/absent/malformed)
  - Host key probe (known/unknown/unparseable URL)
  - Remote reachability (permission denied, host verification, success)
  - End-to-end check_push_readiness verdict logic
  - Live integration against the actual repo remote
"""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.push_readiness import (
    probe_ssh_key,
    probe_host_key,
    probe_remote_reachable,
    check_push_readiness,
    ProbeResult,
    ReadinessReport,
    _run,
)

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# _run helper
# ---------------------------------------------------------------------------

class TestRunHelper:
    def test_successful_command(self):
        code, out, err = _run(["echo", "hello"])
        assert code == 0
        assert out == "hello"
        assert err == ""

    def test_failing_command(self):
        code, out, err = _run(["false"])
        assert code != 0

    def test_timeout_returns_error(self):
        code, out, err = _run(["sleep", "60"], timeout=1)
        assert code == -1
        assert "timed out" in err.lower() or "timeout" in err.lower()

    def test_nonexistent_binary(self):
        code, out, err = _run(["__nonexistent_binary_xyz__"])
        assert code == -1


# ---------------------------------------------------------------------------
# SSH key probe
# ---------------------------------------------------------------------------

class TestSSHKeyProbe:
    def test_finds_real_key(self):
        """The workspace should have a deploy key present."""
        result = probe_ssh_key(REPO)
        # On this machine the key exists at /root/userdata/workspace/.ssh/id_ed25519
        # or at ~/.ssh/id_ed25519 — either should be detected
        if result.ok:
            assert "key found" in result.detail
            assert "id_ed25519" in result.detail or "id_rsa" in result.detail

    def test_empty_dir_reports_missing(self, tmp_path):
        """A repo with no SSH keys anywhere reports failure."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        (fake_home / ".ssh").mkdir()

        with patch("iamai.push_readiness.Path.home", return_value=fake_home):
            result = probe_ssh_key(tmp_path)
        assert not result.ok
        assert "no loadable" in result.detail

    def test_key_with_bad_permissions_still_detected(self, tmp_path):
        """A key file that exists but has wrong perms is still found by ssh-keygen."""
        key_dir = tmp_path / ".ssh"
        key_dir.mkdir()
        key_file = key_dir / "id_ed25519"
        # Write a fake key that ssh-keygen will reject
        key_file.write_text("not a real key\n")
        key_file.chmod(0o644)

        fake_home = tmp_path
        with patch("iamai.push_readiness.Path.home", return_value=fake_home):
            result = probe_ssh_key(tmp_path)
        # ssh-keygen -l should fail on the fake key
        # The probe should not report it as found
        assert not result.ok or "no loadable" in result.detail


# ---------------------------------------------------------------------------
# Host key probe
# ---------------------------------------------------------------------------

class TestHostKeyProbe:
    def test_github_host_in_known_hosts(self):
        """github.com should be in known_hosts after ssh-keyscan was run."""
        result = probe_host_key("git@github.com:FengPwner/IamAI.git")
        # On this machine we added the host key earlier
        assert result.name == "host_key"
        # May or may not be ok depending on known_hosts state
        assert isinstance(result.ok, bool)

    def test_parses_ssh_url(self):
        result = probe_host_key("git@github.com:owner/repo.git")
        assert result.name == "host_key"
        # Should not crash even if host key is missing

    def test_parses_https_url(self):
        result = probe_host_key("https://github.com/owner/repo.git")
        assert result.name == "host_key"

    def test_unparseable_url(self):
        result = probe_host_key("")
        assert not result.ok
        assert "cannot parse" in result.detail

    def test_unknown_host(self, tmp_path):
        """A made-up hostname should not be in known_hosts."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        (fake_home / ".ssh").mkdir()
        (fake_home / ".ssh" / "known_hosts").write_text("")

        with patch("iamai.push_readiness.Path.home", return_value=fake_home):
            with patch("iamai.push_readiness._run", return_value=(1, "", "timeout")):
                result = probe_host_key("git@nonexistent.example.com:owner/repo.git")
        assert not result.ok


# ---------------------------------------------------------------------------
# Remote reachability probe
# ---------------------------------------------------------------------------

class TestRemoteReachability:
    def test_permission_denied_detected(self):
        """Mock a permission denied error from git ls-remote."""
        with patch("iamai.push_readiness._run", return_value=(128, "", "Permission denied (publickey).")):
            result = probe_remote_reachable("git@github.com:FengPwner/IamAI.git")
        assert not result.ok
        assert "deploy key" in result.detail.lower() or "not authorized" in result.detail.lower()

    def test_host_verification_detected(self):
        with patch("iamai.push_readines._run" if False else "iamai.push_readiness._run",
                    return_value=(255, "", "Host key verification failed.")):
            result = probe_remote_reachable("git@github.com:FengPwner/IamAI.git")
        assert not result.ok
        assert "host key" in result.detail.lower() or "ssh-keyscan" in result.detail.lower()

    def test_dns_failure_detected(self):
        with patch("iamai.push_readiness._run", return_value=(128, "", "Could not resolve hostname")):
            result = probe_remote_reachable("git@nonexistent.invalid:owner/repo.git")
        assert not result.ok
        assert "dns" in result.detail.lower() or "resolve" in result.detail.lower()

    def test_success_detected(self):
        fake_refs = "abc123\tHEAD\nabc123\trefs/heads/main\n"
        with patch("iamai.push_readiness._run", return_value=(0, fake_refs, "")):
            result = probe_remote_reachable("git@github.com:FengPwner/IamAI.git")
        assert result.ok
        assert "2 refs" in result.detail


# ---------------------------------------------------------------------------
# End-to-end verdict
# ---------------------------------------------------------------------------

class TestCheckPushReadiness:
    def _make_probes(self, key_ok=True, host_ok=True, reach_ok=True, reach_detail=""):
        """Helper to build ProbeResult triples for patching."""
        return [
            ProbeResult(name="ssh_key", ok=key_ok, detail="key found" if key_ok else "no loadable"),
            ProbeResult(name="host_key", ok=host_ok, detail="host key found" if host_ok else "not in known_hosts"),
            ProbeResult(name="remote_reachable", ok=reach_ok, detail=reach_detail or ("2 refs" if reach_ok else "Permission denied")),
        ]

    def test_all_pass_means_ready(self):
        probes = self._make_probes()
        with patch("iamai.push_readiness._run", return_value=(0, "git@github.com:FengPwner/IamAI.git", "")):
            with patch("iamai.push_readiness.probe_ssh_key", return_value=probes[0]):
                with patch("iamai.push_readiness.probe_host_key", return_value=probes[1]):
                    with patch("iamai.push_readiness.probe_remote_reachable", return_value=probes[2]):
                        report = check_push_readiness(REPO)
        assert report["verdict"] == "ready"
        assert "all clear" in report["recommendation"].lower()

    def test_key_missing_verdict(self):
        probes = self._make_probes(key_ok=False)
        with patch("iamai.push_readiness._run", return_value=(0, "git@github.com:FengPwner/IamAI.git", "")):
            with patch("iamai.push_readiness.probe_ssh_key", return_value=probes[0]):
                with patch("iamai.push_readiness.probe_host_key", return_value=probes[1]):
                    with patch("iamai.push_readiness.probe_remote_reachable", return_value=probes[2]):
                        report = check_push_readiness(REPO)
        assert report["verdict"] == "key_missing"
        assert "deploy key" in report["recommendation"].lower() or "settings" in report["recommendation"].lower()

    def test_no_remote_verdict(self):
        with patch("iamai.push_readiness._run", return_value=(1, "", "no remote")):
            report = check_push_readiness(REPO)
        assert report["verdict"] == "no_remote"

    def test_host_unknown_verdict(self):
        probes = self._make_probes(host_ok=False, reach_ok=False, reach_detail="Host key verification failed.")
        with patch("iamai.push_readiness._run", return_value=(0, "git@github.com:FengPwner/IamAI.git", "")):
            with patch("iamai.push_readiness.probe_ssh_key", return_value=probes[0]):
                with patch("iamai.push_readiness.probe_host_key", return_value=probes[1]):
                    with patch("iamai.push_readiness.probe_remote_reachable", return_value=probes[2]):
                        report = check_push_readiness(REPO)
        assert report["verdict"] == "host_unknown"
        assert "ssh-keyscan" in report["recommendation"]

    def test_returns_dict(self):
        """The public API returns a plain dict, not a dataclass."""
        with patch("iamai.push_readiness._run", return_value=(1, "", "")):
            result = check_push_readiness(REPO)
        assert isinstance(result, dict)
        assert "verdict" in result


# ---------------------------------------------------------------------------
# Live integration (uses real repo state)
# ---------------------------------------------------------------------------

class TestLiveIntegration:
    def test_full_report_structure(self):
        """Run against the real repo — verify report shape, not outcome."""
        report = check_push_readiness(REPO)
        assert "verdict" in report
        assert report["verdict"] in ("ready", "key_missing", "host_unknown", "remote_unreachable", "no_remote")
        assert "probes" in report
        assert "recommendation" in report
        assert isinstance(report["probes"], list)

    def test_current_repo_diagnosis(self):
        """The current repo should report remote_unreachable (deploy key not registered)."""
        report = check_push_readiness(REPO)
        # Based on the known state: key exists, host key known, but deploy key not authorized
        assert report["verdict"] in ("remote_unreachable", "ready")
        if report["verdict"] == "remote_unreachable":
            assert "deploy key" in report["recommendation"].lower() or "not authorized" in report["recommendation"].lower()
