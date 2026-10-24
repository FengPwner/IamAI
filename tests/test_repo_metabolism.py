"""Tests for iamai.repo_metabolism."""

import pytest
from unittest.mock import patch

from iamai.repo_metabolism import (
    MetabolismReport,
    classify_commit,
    metabolism_report,
    metabolism_summary,
    _compute_efficiency,
    _classify_state,
    _git_log_with_messages,
    _files_added_per_commit,
)


# ---------------------------------------------------------------------------
# classify_commit
# ---------------------------------------------------------------------------

class TestClassifyCommit:
    def test_productive_add(self):
        assert classify_commit("add repo_breath.py (breathing rhythm)") == "productive"

    def test_productive_caretaker_visit(self):
        msg = "caretaker visit 349: add writer_wellness.py"
        assert classify_commit(msg) == "productive"

    def test_productive_new_feature(self):
        assert classify_commit("new stroke novelty detector") == "productive"

    def test_productive_upgrade(self):
        assert classify_commit("upgrade commit_hygiene.py scoring") == "productive"

    def test_productive_test(self):
        assert classify_commit("add test for cadence drift") == "productive"

    def test_productive_improve(self):
        assert classify_commit("improve heartbeat monitoring") == "productive"

    def test_productive_fix(self):
        assert classify_commit("fix deadlock in batch committer") == "productive"

    def test_overhead_catchup(self):
        msg = "catch-up: commit pending changes before process restart"
        assert classify_commit(msg) == "overhead"

    def test_overhead_catch_up_spaced(self):
        msg = "catch up commit for backlog flush"
        assert classify_commit(msg) == "overhead"

    def test_overhead_lock_clean(self):
        assert classify_commit("lock clean after crash recovery") == "overhead"

    def test_overhead_restart(self):
        assert classify_commit("restart writer after stall detected") == "overhead"

    def test_overhead_recovery(self):
        assert classify_commit("recovery from overnight stall") == "overhead"

    def test_overhead_flush(self):
        assert classify_commit("flush pending strokes before shutdown") == "overhead"

    def test_overhead_sync(self):
        assert classify_commit("sync remote branches after conflict") == "overhead"

    def test_overhead_rebase(self):
        assert classify_commit("rebase feature branch onto main") == "overhead"

    def test_neutral_merge(self):
        assert classify_commit("Merge branch 'dev' into main") == "neutral"

    def test_neutral_rename(self):
        assert classify_commit("rename module for clarity") == "neutral"

    def test_neutral_update_readme(self):
        assert classify_commit("updated README with badges") == "neutral"

    def test_overhead_priority_over_productive(self):
        """Overhead keywords take priority when both match."""
        msg = "catch-up: add missing test files"
        # catch-up matches overhead first
        assert classify_commit(msg) == "overhead"

    def test_empty_message(self):
        assert classify_commit("") == "neutral"

    def test_case_insensitive(self):
        assert classify_commit("ADD new feature") == "productive"
        assert classify_commit("CATCH-UP flush") == "overhead"


# ---------------------------------------------------------------------------
# _compute_efficiency
# ---------------------------------------------------------------------------

class TestComputeEfficiency:
    def test_perfect_efficiency(self):
        score = _compute_efficiency(
            productive_ratio=1.0,
            overhead_ratio=0.0,
            anabolic_ratio=0.5,
            metabolic_rate=6.0,
        )
        assert score == 100.0

    def test_all_overhead(self):
        score = _compute_efficiency(
            productive_ratio=0.0,
            overhead_ratio=1.0,
            anabolic_ratio=0.0,
            metabolic_rate=6.0,
        )
        assert score < 20.0

    def test_zero_rate(self):
        score = _compute_efficiency(
            productive_ratio=0.5,
            overhead_ratio=0.1,
            anabolic_ratio=0.3,
            metabolic_rate=0.0,
        )
        # No rate health points
        assert score < 90.0

    def test_very_slow_rate(self):
        score = _compute_efficiency(
            productive_ratio=0.8,
            overhead_ratio=0.1,
            anabolic_ratio=0.3,
            metabolic_rate=0.5,
        )
        assert score > 0.0

    def test_very_fast_rate(self):
        score = _compute_efficiency(
            productive_ratio=0.5,
            overhead_ratio=0.2,
            anabolic_ratio=0.2,
            metabolic_rate=50.0,
        )
        # Penalty for too-fast rate
        assert score < 80.0

    def test_moderate_overhead(self):
        score = _compute_efficiency(
            productive_ratio=0.6,
            overhead_ratio=0.3,
            anabolic_ratio=0.2,
            metabolic_rate=6.0,
        )
        assert 50.0 <= score <= 90.0

    def test_clamped_to_100(self):
        score = _compute_efficiency(
            productive_ratio=1.0,
            overhead_ratio=0.0,
            anabolic_ratio=1.0,
            metabolic_rate=6.0,
        )
        assert score <= 100.0

    def test_clamped_to_zero(self):
        score = _compute_efficiency(
            productive_ratio=0.0,
            overhead_ratio=1.0,
            anabolic_ratio=0.0,
            metabolic_rate=0.0,
        )
        assert score >= 0.0


# ---------------------------------------------------------------------------
# _classify_state
# ---------------------------------------------------------------------------

class TestClassifyState:
    def test_thriving(self):
        assert _classify_state(80.0, 0.8, 0.1, 6.0) == "thriving"

    def test_healthy(self):
        assert _classify_state(60.0, 0.5, 0.2, 6.0) == "healthy"

    def test_stagnant_low_rate(self):
        state = _classify_state(45.0, 0.2, 0.3, 1.0)
        assert state == "stagnant"

    def test_stressed_high_overhead(self):
        state = _classify_state(50.0, 0.2, 0.7, 6.0)
        assert state == "stressed"

    def test_stressed_low_efficiency(self):
        state = _classify_state(35.0, 0.3, 0.4, 5.0)
        assert state == "stressed"

    def test_dormant_zero_rate(self):
        assert _classify_state(50.0, 0.5, 0.1, 0.0) == "dormant"

    def test_healthy_boundary(self):
        state = _classify_state(55.0, 0.5, 0.2, 6.0)
        assert state == "healthy"

    def test_thriving_boundary(self):
        state = _classify_state(75.0, 0.8, 0.1, 6.0)
        assert state == "thriving"


# ---------------------------------------------------------------------------
# metabolism_report (integration with mocked git)
# ---------------------------------------------------------------------------

def _mock_commits():
    """Return a set of mock commits for testing."""
    return [
        {"hash": "a" * 40, "timestamp": 1_700_000_000.0, "message": "add first tool"},
        {"hash": "b" * 40, "timestamp": 1_700_000_600.0, "message": "add second tool"},
        {"hash": "c" * 40, "timestamp": 1_700_001_200.0, "message": "catch-up: flush"},
        {"hash": "d" * 40, "timestamp": 1_700_001_800.0, "message": "caretaker visit 100: add wellness"},
        {"hash": "e" * 40, "timestamp": 1_700_002_400.0, "message": "catch-up: pending changes"},
        {"hash": "f" * 40, "timestamp": 1_700_003_000.0, "message": "add metabolism module"},
        {"hash": "g" * 40, "timestamp": 1_700_003_600.0, "message": "Merge branch feature"},
        {"hash": "h" * 40, "timestamp": 1_700_004_200.0, "message": "upgrade scoring algorithm"},
        {"hash": "i" * 40, "timestamp": 1_700_004_800.0, "message": "catch-up: restart flush"},
        {"hash": "j" * 40, "timestamp": 1_700_005_400.0, "message": "add new test suite"},
    ]


class TestMetabolismReport:
    @patch("iamai.repo_metabolism._files_added_per_commit")
    @patch("iamai.repo_metabolism._git_log_with_messages")
    def test_basic_report(self, mock_log, mock_files):
        mock_log.return_value = _mock_commits()
        mock_files.return_value = {
            "a" * 40: 1, "b" * 40: 1, "c" * 40: 0,
            "d" * 40: 2, "e" * 40: 0, "f" * 40: 1,
            "g" * 40: 0, "h" * 40: 0, "i" * 40: 0, "j" * 40: 1,
        }
        report = metabolism_report(repo_path="/fake", last=10)
        assert report.commit_count == 10
        assert report.metabolic_rate > 0
        assert report.productive_ratio > 0
        assert report.overhead_ratio > 0
        assert report.state in ("thriving", "healthy", "stagnant", "stressed", "dormant")

    @patch("iamai.repo_metabolism._git_log_with_messages")
    def test_insufficient_data(self, mock_log):
        mock_log.return_value = [{"hash": "a" * 40, "timestamp": 1.0, "message": "init"}]
        report = metabolism_report(repo_path="/fake", last=10)
        assert report.commit_count == 0
        assert report.state == "dormant"

    @patch("iamai.repo_metabolism._files_added_per_commit")
    @patch("iamai.repo_metabolism._git_log_with_messages")
    def test_all_overhead(self, mock_log, mock_files):
        mock_log.return_value = [
            {"hash": "a" * 40, "timestamp": 1_700_000_000.0, "message": "catch-up: flush"},
            {"hash": "b" * 40, "timestamp": 1_700_000_600.0, "message": "catch-up: restart"},
            {"hash": "c" * 40, "timestamp": 1_700_001_200.0, "message": "recovery from stall"},
        ]
        mock_files.return_value = {"a" * 40: 0, "b" * 40: 0, "c" * 40: 0}
        report = metabolism_report(repo_path="/fake", last=10)
        assert report.overhead_ratio == 1.0
        assert report.productive_ratio == 0.0
        assert report.anabolic_ratio == 0.0

    @patch("iamai.repo_metabolism._files_added_per_commit")
    @patch("iamai.repo_metabolism._git_log_with_messages")
    def test_all_productive(self, mock_log, mock_files):
        mock_log.return_value = [
            {"hash": "a" * 40, "timestamp": 1_700_000_000.0, "message": "add feature A"},
            {"hash": "b" * 40, "timestamp": 1_700_000_600.0, "message": "add feature B"},
            {"hash": "c" * 40, "timestamp": 1_700_001_200.0, "message": "add test suite C"},
        ]
        mock_files.return_value = {"a" * 40: 2, "b" * 40: 1, "c" * 40: 3}
        report = metabolism_report(repo_path="/fake", last=10)
        assert report.productive_ratio == 1.0
        assert report.overhead_ratio == 0.0
        assert report.anabolic_ratio == 1.0

    @patch("iamai.repo_metabolism._files_added_per_commit")
    @patch("iamai.repo_metabolism._git_log_with_messages")
    def test_metabolic_rate_calculation(self, mock_log, mock_files):
        # 5 commits over 1 hour = 5/hr
        mock_log.return_value = [
            {"hash": f"{c}" * 40, "timestamp": 1_700_000_000.0 + i * 900.0,
             "message": f"add feature {i}"}
            for i, c in enumerate("abcde")
        ]
        mock_files.return_value = {f"{c}" * 40: 1 for c in "abcde"}
        report = metabolism_report(repo_path="/fake", last=10)
        # 5 commits / 1 hour = 5.0
        assert 4.0 <= report.metabolic_rate <= 6.0

    @patch("iamai.repo_metabolism._files_added_per_commit")
    @patch("iamai.repo_metabolism._git_log_with_messages")
    def test_window_seconds(self, mock_log, mock_files):
        # git-log order: newest first
        mock_log.return_value = [
            {"hash": "b" * 40, "timestamp": 4600.0, "message": "add test"},
            {"hash": "a" * 40, "timestamp": 1000.0, "message": "add tool"},
        ]
        mock_files.return_value = {"a" * 40: 1, "b" * 40: 1}
        report = metabolism_report(repo_path="/fake", last=10)
        assert report.window_seconds == 3600.0


# ---------------------------------------------------------------------------
# metabolism_summary
# ---------------------------------------------------------------------------

class TestMetabolismSummary:
    def test_empty_report(self):
        report = MetabolismReport()
        assert "insufficient data" in metabolism_summary(report)

    def test_summary_format(self):
        report = MetabolismReport(
            commit_count=50,
            metabolic_rate=6.5,
            productive_ratio=0.62,
            overhead_ratio=0.28,
            neutral_ratio=0.10,
            anabolic_ratio=0.35,
            efficiency_score=68.5,
            state="healthy",
            window_seconds=28800.0,
        )
        summary = metabolism_summary(report)
        assert "healthy" in summary
        assert "6.5" in summary
        assert "68.5" in summary
        assert "62%" in summary
        assert "28%" in summary

    def test_thriving_summary(self):
        report = MetabolismReport(
            commit_count=100,
            metabolic_rate=8.0,
            productive_ratio=0.80,
            overhead_ratio=0.10,
            neutral_ratio=0.10,
            anabolic_ratio=0.50,
            efficiency_score=85.0,
            state="thriving",
            window_seconds=45000.0,
        )
        summary = metabolism_summary(report)
        assert "thriving" in summary

    def test_stressed_summary(self):
        report = MetabolismReport(
            commit_count=20,
            metabolic_rate=3.0,
            productive_ratio=0.20,
            overhead_ratio=0.70,
            neutral_ratio=0.10,
            anabolic_ratio=0.05,
            efficiency_score=30.0,
            state="stressed",
            window_seconds=24000.0,
        )
        summary = metabolism_summary(report)
        assert "stressed" in summary


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_report_has_classifications(self):
        """Report should include individual commit classifications."""
        report = MetabolismReport(
            commit_count=2,
            classifications=[
                {"hash": "abc12345", "message": "test", "category": "productive"},
                {"hash": "def67890", "message": "flush", "category": "overhead"},
            ],
        )
        assert len(report.classifications) == 2
        assert report.classifications[0]["category"] == "productive"
        assert report.classifications[1]["category"] == "overhead"

    def test_efficiency_boundary_values(self):
        """Test efficiency at exact boundary values."""
        # At productive=0.5, overhead=0.2, anabolic=0.2, rate=6
        # Should be in healthy range
        score = _compute_efficiency(0.5, 0.2, 0.2, 6.0)
        assert 50.0 <= score <= 80.0

    def test_state_transitions(self):
        """Test that state transitions are consistent."""
        # Higher efficiency should yield better states
        states = []
        for eff in [20.0, 40.0, 60.0, 80.0]:
            state = _classify_state(eff, 0.5, 0.2, 6.0)
            states.append(state)
        # Should generally improve
        order = {"dormant": 0, "stressed": 1, "stagnant": 2, "healthy": 3, "thriving": 4}
        assert order.get(states[-1], 0) >= order.get(states[0], 0)

    @patch("iamai.repo_metabolism._files_added_per_commit")
    @patch("iamai.repo_metabolism._git_log_with_messages")
    def test_max_last_capped(self, mock_log, mock_files):
        """last parameter should be capped at 200."""
        mock_log.return_value = [
            {"hash": "a" * 40, "timestamp": 1.0, "message": "add x"},
            {"hash": "b" * 40, "timestamp": 2.0, "message": "add y"},
        ]
        mock_files.return_value = {"a" * 40: 1, "b" * 40: 1}
        # Requesting 500 should be capped to 200
        report = metabolism_report(repo_path="/fake", last=500)
        # Just verify it doesn't crash
        assert report.commit_count == 2

    def test_classify_commit_no_false_positives(self):
        """Common neutral messages should not match productive or overhead."""
        neutral_messages = [
            "update README",
            "chore: bump version",
            "wip",
            ".",
            "save progress",
            "cosmetic changes to docs",
        ]
        for msg in neutral_messages:
            assert classify_commit(msg) == "neutral", f"'{msg}' should be neutral"
