#!/usr/bin/env python3
"""Tests for push_recovery_eta.py — push recovery time estimation."""

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import push_recovery_eta as pre


# ---------------------------------------------------------------------------
# classify_blockage
# ---------------------------------------------------------------------------

class TestClassifyBlockage:
    def test_auth_failure(self):
        """Permission denied in stderr -> auth blockage."""
        mock = MagicMock()
        mock.returncode = 255
        mock.stderr = "git@github.com: Permission denied (publickey)."
        with patch("push_recovery_eta.subprocess.run", return_value=mock):
            assert pre.classify_blockage() == "auth"

    def test_network_timeout(self):
        """TimeoutExpired -> network blockage."""
        import subprocess
        with patch("push_recovery_eta.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("ssh", 10)):
            assert pre.classify_blockage() == "network"

    def test_network_dns_failure(self):
        """DNS resolution failure -> network blockage."""
        mock = MagicMock()
        mock.returncode = 255
        mock.stderr = "ssh: Could not resolve hostname github.com"
        with patch("push_recovery_eta.subprocess.run", return_value=mock):
            assert pre.classify_blockage() == "network"

    def test_success(self):
        """Successful authentication -> no blockage."""
        mock = MagicMock()
        mock.returncode = 1  # GitHub returns 1 even on success with -T
        mock.stderr = "Hi FengPwner! You've successfully authenticated"
        with patch("push_recovery_eta.subprocess.run", return_value=mock):
            assert pre.classify_blockage() == "none"

    def test_unknown_error(self):
        """Unrecognized error -> unknown."""
        mock = MagicMock()
        mock.returncode = 255
        mock.stderr = "something weird happened"
        with patch("push_recovery_eta.subprocess.run", return_value=mock):
            assert pre.classify_blockage() == "unknown"

    def test_generic_exception(self):
        """Any exception -> unknown."""
        with patch("push_recovery_eta.subprocess.run",
                    side_effect=OSError("broken")):
            assert pre.classify_blockage() == "unknown"


# ---------------------------------------------------------------------------
# count_unpushed
# ---------------------------------------------------------------------------

class TestCountUnpushed:
    def test_normal_count(self):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "42\n"
        with patch("push_recovery_eta.subprocess.run", return_value=mock):
            assert pre.count_unpushed() == 42

    def test_zero(self):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "0\n"
        with patch("push_recovery_eta.subprocess.run", return_value=mock):
            assert pre.count_unpushed() == 0

    def test_git_failure(self):
        """git command fails -> returns 0 (safe default)."""
        mock = MagicMock()
        mock.returncode = 128
        mock.stdout = ""
        with patch("push_recovery_eta.subprocess.run", return_value=mock):
            assert pre.count_unpushed() == 0

    def test_timeout(self):
        import subprocess
        with patch("push_recovery_eta.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("git", 10)):
            assert pre.count_unpushed() == 0

    def test_bad_output(self):
        """Non-numeric output -> 0."""
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "not a number\n"
        with patch("push_recovery_eta.subprocess.run", return_value=mock):
            assert pre.count_unpushed() == 0


# ---------------------------------------------------------------------------
# commits_in_window
# ---------------------------------------------------------------------------

class TestCommitsInWindow:
    def test_counts_lines(self):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "abc1234 first commit\ndef5678 second commit\n"
        with patch("push_recovery_eta.subprocess.run", return_value=mock):
            assert pre.commits_in_window(24.0) == 2

    def test_empty_log(self):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "\n"
        with patch("push_recovery_eta.subprocess.run", return_value=mock):
            assert pre.commits_in_window(24.0) == 0

    def test_git_failure(self):
        mock = MagicMock()
        mock.returncode = 128
        mock.stdout = ""
        with patch("push_recovery_eta.subprocess.run", return_value=mock):
            assert pre.commits_in_window(24.0) == 0


# ---------------------------------------------------------------------------
# RecoveryEstimate
# ---------------------------------------------------------------------------

class TestRecoveryEstimate:
    def test_to_dict_rounds(self):
        est = pre.RecoveryEstimate(
            unpushed_count=100,
            blockage_type="auth",
            push_rate_cph=3.456789,
            commit_rate_cph=5.123456,
            drain_eta_hours=None,
            sustainable=False,
            recommendation="fix auth",
        )
        d = est.to_dict()
        assert d["push_rate_cph"] == 3.46
        assert d["commit_rate_cph"] == 5.12
        assert d["drain_eta_hours"] is None

    def test_to_dict_with_eta(self):
        est = pre.RecoveryEstimate(
            unpushed_count=50,
            blockage_type="none",
            push_rate_cph=10.0,
            commit_rate_cph=5.0,
            drain_eta_hours=10.123456,
            sustainable=True,
            recommendation="draining",
        )
        d = est.to_dict()
        assert d["drain_eta_hours"] == 10.12
        assert d["sustainable"] is True


# ---------------------------------------------------------------------------
# estimate_recovery
# ---------------------------------------------------------------------------

class TestEstimateRecovery:
    def test_no_debt(self):
        """Zero unpushed commits -> all clear."""
        with patch.object(pre, "count_unpushed", return_value=0), \
             patch.object(pre, "classify_blockage", return_value="none"), \
             patch.object(pre, "commits_in_window", return_value=100):
            est = pre.estimate_recovery(24.0)
            assert est.unpushed_count == 0
            assert est.sustainable is True
            assert est.drain_eta_hours == 0.0
            assert "all clear" in est.recommendation

    def test_blocked_auth(self):
        """Auth blocked with debt -> infeasible."""
        with patch.object(pre, "count_unpushed", return_value=114), \
             patch.object(pre, "classify_blockage", return_value="auth"), \
             patch.object(pre, "commits_in_window", return_value=50):
            est = pre.estimate_recovery(24.0)
            assert est.unpushed_count == 114
            assert est.blockage_type == "auth"
            assert est.push_rate_cph == 0.0
            assert est.drain_eta_hours is None
            assert est.sustainable is False
            assert "auth" in est.recommendation

    def test_blocked_network(self):
        """Network blocked with debt -> infeasible."""
        with patch.object(pre, "count_unpushed", return_value=30), \
             patch.object(pre, "classify_blockage", return_value="network"), \
             patch.object(pre, "commits_in_window", return_value=20):
            est = pre.estimate_recovery(24.0)
            assert est.blockage_type == "network"
            assert est.sustainable is False

    def test_draining(self):
        """Push working, push rate > commit rate -> draining."""
        with patch.object(pre, "count_unpushed", return_value=50), \
             patch.object(pre, "classify_blockage", return_value="none"), \
             patch.object(pre, "commits_in_window", return_value=120):
            # push_rate = commit_rate when unblocked, so they're equal
            # This tests the unsustainable branch
            est = pre.estimate_recovery(24.0)
            assert est.unpushed_count == 50
            # When blockage is none, push_rate = commit_rate, so not draining
            assert est.sustainable is False

    def test_unsustainable_rate(self):
        """Push working but rates equal -> unsustainable."""
        with patch.object(pre, "count_unpushed", return_value=20), \
             patch.object(pre, "classify_blockage", return_value="none"), \
             patch.object(pre, "commits_in_window", return_value=48):
            est = pre.estimate_recovery(24.0)
            # push_rate == commit_rate -> unsustainable
            assert est.sustainable is False
            assert "unsustainable" in est.recommendation or "unsustainable" in est.recommendation.lower()

    def test_zero_window(self):
        """Zero window avoids division by zero."""
        with patch.object(pre, "count_unpushed", return_value=0), \
             patch.object(pre, "classify_blockage", return_value="none"), \
             patch.object(pre, "commits_in_window", return_value=0):
            est = pre.estimate_recovery(0.0)
            assert est.commit_rate_cph == 0.0
            assert est.sustainable is True


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_blocked_report(self):
        est = pre.RecoveryEstimate(
            unpushed_count=114,
            blockage_type="auth",
            push_rate_cph=0.0,
            commit_rate_cph=5.2,
            drain_eta_hours=None,
            sustainable=False,
            recommendation="push blocked (auth): fix blockage first, then drain",
        )
        report = pre.format_report(est)
        assert "114 commits" in report
        assert "auth" in report
        assert "inf" in report
        assert "NO" in report

    def test_healthy_report(self):
        est = pre.RecoveryEstimate(
            unpushed_count=0,
            blockage_type="none",
            push_rate_cph=5.0,
            commit_rate_cph=5.0,
            drain_eta_hours=0.0,
            sustainable=True,
            recommendation="all clear — no push debt",
        )
        report = pre.format_report(est)
        assert "0 commits" in report
        assert "yes" in report
        assert "all clear" in report

    def test_draining_report(self):
        est = pre.RecoveryEstimate(
            unpushed_count=25,
            blockage_type="none",
            push_rate_cph=10.0,
            commit_rate_cph=5.0,
            drain_eta_hours=5.0,
            sustainable=True,
            recommendation="draining at 5.0 commits/hour",
        )
        report = pre.format_report(est)
        assert "25 commits" in report
        assert "5.0 hours" in report
        assert "yes" in report


# ---------------------------------------------------------------------------
# pushed_in_window
# ---------------------------------------------------------------------------

class TestPushedInWindow:
    def test_blocked_returns_zero(self):
        with patch.object(pre, "classify_blockage", return_value="auth"):
            assert pre.pushed_in_window(24.0) == 0

    def test_healthy_delegates(self):
        with patch.object(pre, "classify_blockage", return_value="none"), \
             patch.object(pre, "commits_in_window", return_value=30):
            assert pre.pushed_in_window(24.0) == 30
