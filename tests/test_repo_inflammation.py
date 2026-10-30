"""Tests for repo_inflammation module."""

import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.repo_inflammation import (
    InflammationSignal,
    InflammationReport,
    analyze_inflammation,
    inflammation_summary,
    detect_restart_density,
    detect_push_failures,
    detect_backlog_growth,
    detect_catch_up_mass,
    detect_stall_frequency,
    detect_stash_accumulation,
    _classify_state,
    _make_recommendation,
    _parse_git_log,
    _run,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_git_repo(tmp_path):
    """Create a temporary git repository for testing."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init"], cwd=str(repo), capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo), capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo), capture_output=True,
    )
    # Create initial commit
    readme = repo / "README.md"
    readme.write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(repo), capture_output=True,
    )
    return repo


@pytest.fixture
def repo_with_history(tmp_git_repo):
    """Create a repo with multiple commits simulating stress patterns."""
    repo = tmp_git_repo
    for i in range(10):
        f = repo / f"file_{i}.txt"
        f.write_text(f"content {i}\n")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        msg = "caretaker visit {}: restart and recovery".format(i) if i % 3 == 0 else f"stroke: feature {i}"
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=str(repo), capture_output=True,
        )
    return repo


# ---------------------------------------------------------------------------
# Signal tests
# ---------------------------------------------------------------------------


class TestRestartDensity:
    def test_no_restarts(self):
        commits = [
            {"hash": "a", "subject": "stroke: add feature", "date": ""},
            {"hash": "b", "subject": "feat: new module", "date": ""},
        ]
        signal = detect_restart_density(commits, hours=24)
        assert signal.name == "restart_density"
        assert signal.score == 0.0
        assert signal.weight == 0.25

    def test_many_restarts(self):
        commits = [
            {"hash": f"h{i}", "subject": "catch-up: restart process", "date": ""}
            for i in range(20)
        ]
        signal = detect_restart_density(commits, hours=24)
        assert signal.score > 50

    def test_mixed_commits(self):
        commits = [
            {"hash": "a", "subject": "caretaker visit 100: restart", "date": ""},
            {"hash": "b", "subject": "stroke: garden update", "date": ""},
            {"hash": "c", "subject": "recovery: process restart", "date": ""},
            {"hash": "d", "subject": "feat: new module", "date": ""},
        ]
        signal = detect_restart_density(commits, hours=24)
        assert 0 < signal.score < 100

    def test_evidence_contains_count(self):
        commits = [
            {"hash": "a", "subject": "restart process", "date": ""},
        ]
        signal = detect_restart_density(commits, hours=12)
        assert "restart" in signal.evidence.lower()

    def test_weighted_property(self):
        signal = InflammationSignal(
            name="test", score=80, weight=0.25, evidence="test"
        )
        assert signal.weighted == 20.0


class TestPushFailures:
    def test_clean_repo(self, tmp_git_repo):
        signal = detect_push_failures(str(tmp_git_repo), hours=24)
        assert signal.name == "push_failure_rate"
        assert signal.score == 0.0
        assert signal.weight == 0.15

    def test_score_scaling(self):
        """Verify score caps at 100."""
        with patch("iamai.repo_inflammation._run") as mock_run:
            # Simulate 10 push failures in reflog
            mock_run.return_value = "\n".join(
                [f"rejected push {i}" for i in range(10)]
            )
            signal = detect_push_failures("/fake", hours=24)
            assert signal.score == 100


class TestBacklogGrowth:
    def test_clean_working_tree(self, tmp_git_repo):
        signal = detect_backlog_growth(str(tmp_git_repo))
        assert signal.name == "backlog_growth"
        assert signal.score == 0.0

    def test_dirty_working_tree(self, tmp_git_repo):
        # Create uncommitted files
        for i in range(5):
            (tmp_git_repo / f"new_{i}.txt").write_text(f"data {i}")
        signal = detect_backlog_growth(str(tmp_git_repo))
        assert signal.score > 0
        assert "5 uncommitted" in signal.evidence

    def test_score_scaling_with_many_files(self, tmp_git_repo):
        for i in range(25):
            (tmp_git_repo / f"file_{i}.txt").write_text("x")
        signal = detect_backlog_growth(str(tmp_git_repo))
        assert signal.score >= 100  # 25 * 5 = 125, capped at 100


class TestCatchUpMass:
    def test_no_catch_up_commits(self, repo_with_history):
        commits = [
            {"hash": "abc", "subject": "feat: something", "date": ""},
        ]
        signal = detect_catch_up_mass(commits, str(repo_with_history), hours=24)
        assert signal.score == 0.0
        assert "no catch-up" in signal.evidence

    def test_with_catch_up_commits(self, tmp_git_repo):
        repo = tmp_git_repo
        # Create a small normal commit
        (repo / "normal.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feat: small change"],
            cwd=str(repo), capture_output=True,
        )
        # Create a large catch-up commit
        for i in range(10):
            (repo / f"catchup_{i}.txt").write_text(f"catchup {i}")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "catch-up: big batch"],
            cwd=str(repo), capture_output=True,
        )
        commits = _parse_git_log(str(repo), hours=24)
        signal = detect_catch_up_mass(commits, str(repo), hours=24)
        assert signal.weight == 0.15


class TestStallFrequency:
    def test_no_stalls(self, tmp_git_repo):
        signal = detect_stall_frequency(str(tmp_git_repo), hours=24)
        assert signal.name == "stall_frequency"
        assert signal.weight == 0.20

    def test_with_writer_state(self, tmp_git_repo):
        # Create writer state file with a large gap
        data_dir = tmp_git_repo / "data"
        data_dir.mkdir()
        state_file = data_dir / "writer_state.test.json"
        state_file.write_text(json.dumps({
            "longest_gap_seconds": 3600,
            "writer": "test",
        }))
        signal = detect_stall_frequency(str(tmp_git_repo), hours=24)
        assert "3600s" in signal.evidence

    def test_malformed_state_file(self, tmp_git_repo):
        data_dir = tmp_git_repo / "data"
        data_dir.mkdir()
        state_file = data_dir / "writer_state.bad.json"
        state_file.write_text("not json")
        signal = detect_stall_frequency(str(tmp_git_repo), hours=24)
        assert signal.score >= 0  # Should not crash


class TestStashAccumulation:
    def test_no_stashes(self, tmp_git_repo):
        signal = detect_stash_accumulation(str(tmp_git_repo))
        assert signal.name == "stash_accumulation"
        assert signal.score == 0.0
        assert signal.weight == 0.10

    def test_with_stashes(self, tmp_git_repo):
        # Create a few stashes
        for i in range(3):
            (tmp_git_repo / f"stash_{i}.txt").write_text(f"stash {i}")
            subprocess.run(
                ["git", "add", "."], cwd=str(tmp_git_repo), capture_output=True
            )
            subprocess.run(
                ["git", "stash", "-m", f"stash {i}"],
                cwd=str(tmp_git_repo), capture_output=True,
            )
        signal = detect_stash_accumulation(str(tmp_git_repo))
        assert signal.score > 0
        assert "3 stash" in signal.evidence


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------


class TestClassification:
    def test_calm(self):
        assert _classify_state(0) == "calm"
        assert _classify_state(15) == "calm"
        assert _classify_state(20) == "calm"

    def test_mild(self):
        assert _classify_state(21) == "mild"
        assert _classify_state(35) == "mild"
        assert _classify_state(40) == "mild"

    def test_moderate(self):
        assert _classify_state(41) == "moderate"
        assert _classify_state(55) == "moderate"
        assert _classify_state(60) == "moderate"

    def test_severe(self):
        assert _classify_state(61) == "severe"
        assert _classify_state(75) == "severe"
        assert _classify_state(80) == "severe"

    def test_critical(self):
        assert _classify_state(81) == "critical"
        assert _classify_state(100) == "critical"
        assert _classify_state(150) == "critical"


class TestRecommendations:
    def test_calm_recommendation(self):
        rec = _make_recommendation("calm", "", False)
        assert "healthy" in rec.lower()

    def test_mild_recommendation(self):
        rec = _make_recommendation("mild", "restart_density", False)
        assert "monitor" in rec.lower()

    def test_moderate_acute(self):
        rec = _make_recommendation("moderate", "stall_frequency", False)
        assert "pause" in rec.lower() or "consolidate" in rec.lower()

    def test_moderate_chronic(self):
        rec = _make_recommendation("moderate", "restart_density", True)
        assert "chronic" in rec.lower()

    def test_severe_recommendation(self):
        rec = _make_recommendation("severe", "push_failure_rate", False)
        assert "reduce" in rec.lower() or "stabilize" in rec.lower()

    def test_critical_recommendation(self):
        rec = _make_recommendation("critical", "stash_accumulation", False)
        assert "halt" in rec.lower() or "critical" in rec.lower()


# ---------------------------------------------------------------------------
# Report tests
# ---------------------------------------------------------------------------


class TestInflammationReport:
    def test_empty_report(self):
        report = InflammationReport()
        assert report.inflammation_score == 0.0
        assert report.inflammation_state == "calm"
        assert not report.chronic

    def test_chronic_detection(self):
        signals = [
            InflammationSignal(name="a", score=60, weight=0.3, evidence="high"),
            InflammationSignal(name="b", score=70, weight=0.3, evidence="high"),
            InflammationSignal(name="c", score=55, weight=0.4, evidence="high"),
        ]
        report = InflammationReport(
            signals=signals,
            inflammation_score=62,
            inflammation_state="severe",
        )
        assert report.chronic

    def test_not_chronic_low_score(self):
        signals = [
            InflammationSignal(name="a", score=60, weight=0.5, evidence="high"),
            InflammationSignal(name="b", score=60, weight=0.5, evidence="high"),
        ]
        report = InflammationReport(
            signals=signals,
            inflammation_score=30,
            inflammation_state="mild",
        )
        assert not report.chronic

    def test_not_chronic_few_elevated(self):
        signals = [
            InflammationSignal(name="a", score=80, weight=0.5, evidence="high"),
            InflammationSignal(name="b", score=20, weight=0.5, evidence="low"),
        ]
        report = InflammationReport(
            signals=signals,
            inflammation_score=50,
            inflammation_state="moderate",
        )
        assert not report.chronic  # only 1 signal > 50, need >= 3


class TestSummary:
    def test_calm_summary(self):
        report = InflammationReport(
            inflammation_score=5.0,
            inflammation_state="calm",
        )
        summary = inflammation_summary(report)
        assert "calm" in summary
        assert "5.0" in summary

    def test_stressed_summary(self):
        report = InflammationReport(
            inflammation_score=65.0,
            inflammation_state="severe",
            primary_stressor="restart_density",
            recovery_hours=2.5,
            window_commits=20,
            window_hours=24.0,
        )
        summary = inflammation_summary(report)
        assert "severe" in summary
        assert "restart_density" in summary

    def test_chronic_summary(self):
        signals = [
            InflammationSignal(name="a", score=60, weight=0.3, evidence=""),
            InflammationSignal(name="b", score=70, weight=0.3, evidence=""),
            InflammationSignal(name="c", score=55, weight=0.4, evidence=""),
        ]
        report = InflammationReport(
            signals=signals,
            inflammation_score=62,
            inflammation_state="severe",
            primary_stressor="a",
        )
        summary = inflammation_summary(report)
        assert "chronic" in summary


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


class TestAnalyzeInflammation:
    def test_analyze_clean_repo(self, tmp_git_repo):
        report = analyze_inflammation(str(tmp_git_repo), hours=24)
        assert isinstance(report, InflammationReport)
        assert report.inflammation_state in (
            "calm", "mild", "moderate", "severe", "critical"
        )
        assert len(report.signals) == 6
        assert report.window_hours == 24.0

    def test_analyze_with_activity(self, repo_with_history):
        report = analyze_inflammation(str(repo_with_history), hours=24)
        assert report.window_commits >= 10
        # Should detect restart patterns
        restart_signal = next(
            s for s in report.signals if s.name == "restart_density"
        )
        assert restart_signal.score > 0

    def test_analyze_custom_window(self, tmp_git_repo):
        report = analyze_inflammation(str(tmp_git_repo), hours=48)
        assert report.window_hours == 48.0

    def test_all_signals_present(self, tmp_git_repo):
        report = analyze_inflammation(str(tmp_git_repo))
        names = {s.name for s in report.signals}
        expected = {
            "restart_density",
            "push_failure_rate",
            "backlog_growth",
            "catch_up_mass",
            "stall_frequency",
            "stash_accumulation",
        }
        assert names == expected

    def test_weights_sum_correctly(self, tmp_git_repo):
        report = analyze_inflammation(str(tmp_git_repo))
        total_weight = sum(s.weight for s in report.signals)
        assert abs(total_weight - 1.0) < 0.01

    def test_score_bounded(self, tmp_git_repo):
        report = analyze_inflammation(str(tmp_git_repo))
        assert 0 <= report.inflammation_score <= 100


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------


class TestUtilities:
    def test_run_success(self):
        result = _run("echo hello")
        assert result == "hello"

    def test_run_failure(self):
        result = _run("false")
        assert result == ""

    def test_run_timeout(self):
        result = _run("sleep 60")
        # Should not hang; returns empty on timeout
        assert isinstance(result, str)

    def test_parse_git_log_empty(self, tmp_git_repo):
        commits = _parse_git_log(str(tmp_git_repo), hours=0)
        assert isinstance(commits, list)

    def test_parse_git_log_with_commits(self, repo_with_history):
        commits = _parse_git_log(str(repo_with_history), hours=24)
        assert len(commits) >= 10
        for c in commits:
            assert "hash" in c
            assert "subject" in c
            assert "date" in c


class TestSignalDataclass:
    def test_weighted_calculation(self):
        s = InflammationSignal(
            name="test", score=50, weight=0.2, evidence="test evidence"
        )
        assert s.weighted == 10.0

    def test_zero_score(self):
        s = InflammationSignal(
            name="test", score=0, weight=0.5, evidence="none"
        )
        assert s.weighted == 0.0

    def test_max_score(self):
        s = InflammationSignal(
            name="test", score=100, weight=1.0, evidence="max"
        )
        assert s.weighted == 100.0

    def test_with_timestamp(self):
        now = datetime.now()
        s = InflammationSignal(
            name="test", score=30, weight=0.1, evidence="x", timestamp=now
        )
        assert s.timestamp == now
