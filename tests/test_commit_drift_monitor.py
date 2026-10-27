#!/usr/bin/bin/env python3
"""Tests for commit_drift_monitor.py"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from commit_drift_monitor import (
    DriftSnapshot,
    classify_drift,
    count_unpushed,
    get_remote_name,
    get_current_branch,
    get_oldest_unpushed_age_hours,
    get_newest_unpushed_age_hours,
    get_recent_rate,
    measure,
    format_human,
    run_cmd,
    TRIVIAL_THRESHOLD,
    EASY_THRESHOLD,
    MODERATE_THRESHOLD,
    HARD_THRESHOLD,
    TRIVIAL_HOURS,
    EASY_HOURS,
    MODERATE_HOURS,
    HARD_HOURS,
    DRIFT_WINDOW_HOURS,
)


# --- DriftSnapshot ---

class TestDriftSnapshot:
    def test_basic_creation(self):
        s = DriftSnapshot(
            unpushed_count=10,
            oldest_unpushed_age_hours=5.0,
            newest_unpushed_age_hours=1.0,
            divergence_span_hours=4.0,
            recent_rate_per_hour=3.5,
            severity="easy",
            suggested_action="just push",
            remote_name="origin",
            branch="main",
            timestamp="2026-10-27T11:00:00+00:00",
        )
        assert s.unpushed_count == 10
        assert s.severity == "easy"
        assert s.remote_name == "origin"

    def test_to_dict(self):
        s = DriftSnapshot(
            unpushed_count=0,
            oldest_unpushed_age_hours=None,
            newest_unpushed_age_hours=None,
            divergence_span_hours=None,
            recent_rate_per_hour=0.0,
            severity="none",
            suggested_action="nothing to do",
            remote_name="origin",
            branch="main",
            timestamp="2026-10-27T11:00:00+00:00",
        )
        d = s.to_dict()
        assert d["unpushed_count"] == 0
        assert d["severity"] == "none"
        assert d["oldest_unpushed_age_hours"] is None
        assert isinstance(d, dict)

    def test_to_dict_round_trip(self):
        s = DriftSnapshot(
            unpushed_count=50,
            oldest_unpushed_age_hours=48.5,
            newest_unpushed_age_hours=0.25,
            divergence_span_hours=48.25,
            recent_rate_per_hour=12.0,
            severity="hard",
            suggested_action="create a PR branch",
            remote_name="upstream",
            branch="dev",
            timestamp="2026-10-27T11:00:00+00:00",
        )
        d = s.to_dict()
        assert d["unpushed_count"] == 50
        assert d["branch"] == "dev"
        # all fields present
        for key in [
            "unpushed_count", "oldest_unpushed_age_hours",
            "newest_unpushed_age_hours", "divergence_span_hours",
            "recent_rate_per_hour", "severity", "suggested_action",
            "remote_name", "branch", "timestamp",
        ]:
            assert key in d


# --- classify_drift ---

class TestClassifyDrift:
    def test_none_when_zero(self):
        sev, act = classify_drift(0, None)
        assert sev == "none"
        assert "nothing" in act.lower()

    def test_trivial_few_commits(self):
        sev, act = classify_drift(3, 0.5)
        assert sev == "trivial"
        assert "push" in act.lower()

    def test_trivial_at_boundary(self):
        sev, act = classify_drift(TRIVIAL_THRESHOLD - 1, TRIVIAL_HOURS - 0.5)
        assert sev == "trivial"

    def test_easy_by_count(self):
        sev, act = classify_drift(EASY_THRESHOLD - 1, 0.5)
        assert sev == "easy"

    def test_easy_by_age(self):
        sev, act = classify_drift(3, TRIVIAL_HOURS + 1)
        assert sev == "easy"

    def test_moderate_by_count(self):
        sev, act = classify_drift(EASY_THRESHOLD, 2.0)
        assert sev == "moderate"

    def test_moderate_by_age(self):
        sev, act = classify_drift(10, EASY_HOURS + 1)
        assert sev == "moderate"

    def test_hard_by_count(self):
        sev, act = classify_drift(MODERATE_THRESHOLD, 10.0)
        assert sev == "hard"

    def test_hard_by_age(self):
        sev, act = classify_drift(30, MODERATE_HOURS + 1)
        assert sev == "hard"

    def test_extreme_by_count(self):
        sev, act = classify_drift(HARD_THRESHOLD, 5.0)
        assert sev == "extreme"

    def test_extreme_by_age(self):
        sev, act = classify_drift(60, HARD_HOURS + 1)
        assert sev == "extreme"

    def test_extreme_suggests_rebase(self):
        sev, act = classify_drift(200, 48.0)
        assert sev == "extreme"
        assert "rebase" in act.lower() or "squash" in act.lower()

    def test_none_age_is_zero(self):
        # None age should be treated as 0 — still classified by count alone
        sev, act = classify_drift(10, None)
        assert sev == "easy"

    def test_moderate_suggests_force_with_lease(self):
        sev, act = classify_drift(30, 8.0)
        assert "force-with-lease" in act

    def test_hard_suggests_pr_branch(self):
        sev, act = classify_drift(75, 36.0)
        assert "pr" in act.lower() or "branch" in act.lower()


# --- run_cmd ---

class TestRunCmd:
    def test_returns_completed_process(self):
        result = run_cmd(["echo", "hello"])
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_failure_returns_nonzero(self):
        result = run_cmd(["false"])
        assert result.returncode != 0


# --- get_remote_name ---

class TestGetRemoteName:
    @patch("commit_drift_monitor.run_cmd")
    def test_returns_origin_when_present(self, mock_run):
        mock_run.return_value = MagicMock(stdout="origin\nupstream\n")
        assert get_remote_name() == "origin"

    @patch("commit_drift_monitor.run_cmd")
    def test_returns_first_when_no_origin(self, mock_run):
        mock_run.return_value = MagicMock(stdout="fork\nother\n")
        assert get_remote_name() == "fork"

    @patch("commit_drift_monitor.run_cmd")
    def test_returns_origin_for_empty(self, mock_run):
        mock_run.return_value = MagicMock(stdout="\n")
        assert get_remote_name() == "origin"


# --- get_current_branch ---

class TestGetCurrentBranch:
    @patch("commit_drift_monitor.run_cmd")
    def test_returns_branch(self, mock_run):
        mock_run.return_value = MagicMock(stdout="main\n")
        assert get_current_branch() == "main"

    @patch("commit_drift_monitor.run_cmd")
    def test_returns_main_for_empty(self, mock_run):
        mock_run.return_value = MagicMock(stdout="\n")
        assert get_current_branch() == "main"


# --- count_unpushed ---

class TestCountUnpushed:
    @patch("commit_drift_monitor.run_cmd")
    def test_parses_integer(self, mock_run):
        mock_run.return_value = MagicMock(stdout="42\n")
        assert count_unpushed("origin", "main") == 42

    @patch("commit_drift_monitor.run_cmd")
    def test_zero_on_empty(self, mock_run):
        mock_run.return_value = MagicMock(stdout="0\n")
        assert count_unpushed("origin", "main") == 0

    @patch("commit_drift_monitor.run_cmd")
    def test_zero_on_garbage(self, mock_run):
        mock_run.return_value = MagicMock(stdout="not a number\n")
        assert count_unpushed("origin", "main") == 0

    @patch("commit_drift_monitor.run_cmd")
    def test_zero_on_error(self, mock_run):
        mock_run.return_value = MagicMock(stdout="")
        assert count_unpushed("origin", "main") == 0


# --- get_oldest_unpushed_age_hours ---

class TestGetOldestUnpushedAge:
    @patch("commit_drift_monitor.run_cmd")
    def test_parses_iso_dates(self, mock_run):
        old = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        new = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        mock_run.return_value = MagicMock(stdout=f"{old}\n{new}\n")
        age = get_oldest_unpushed_age_hours("origin", "main")
        assert age is not None
        assert 9.5 < age < 10.5

    @patch("commit_drift_monitor.run_cmd")
    def test_returns_none_when_empty(self, mock_run):
        mock_run.return_value = MagicMock(stdout="\n")
        assert get_oldest_unpushed_age_hours("origin", "main") is None

    @patch("commit_drift_monitor.run_cmd")
    def test_returns_none_on_bad_date(self, mock_run):
        mock_run.return_value = MagicMock(stdout="not-a-date\n")
        assert get_oldest_unpushed_age_hours("origin", "main") is None


# --- get_newest_unpushed_age_hours ---

class TestGetNewestUnpushedAge:
    @patch("commit_drift_monitor.run_cmd")
    def test_parses_recent_date(self, mock_run):
        recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        mock_run.return_value = MagicMock(stdout=f"{recent}\n")
        age = get_newest_unpushed_age_hours("origin", "main")
        assert age is not None
        assert 0.4 < age < 0.6

    @patch("commit_drift_monitor.run_cmd")
    def test_returns_none_when_empty(self, mock_run):
        mock_run.return_value = MagicMock(stdout="")
        assert get_newest_unpushed_age_hours("origin", "main") is None


# --- get_recent_rate ---

class TestGetRecentRate:
    @patch("commit_drift_monitor.run_cmd")
    def test_counts_recent_commits(self, mock_run):
        # 4 commits within window
        now = datetime.now(timezone.utc)
        dates = [
            (now - timedelta(minutes=30)).isoformat(),
            (now - timedelta(minutes=45)).isoformat(),
            (now - timedelta(hours=1)).isoformat(),
            (now - timedelta(hours=1, minutes=30)).isoformat(),
        ]
        mock_run.return_value = MagicMock(stdout="\n".join(dates) + "\n")
        rate = get_recent_rate("origin", "main", window_hours=2.0)
        assert rate == pytest.approx(2.0, abs=0.1)

    @patch("commit_drift_monitor.run_cmd")
    def test_ignores_old_commits(self, mock_run):
        now = datetime.now(timezone.utc)
        dates = [
            (now - timedelta(hours=5)).isoformat(),
            (now - timedelta(hours=10)).isoformat(),
        ]
        mock_run.return_value = MagicMock(stdout="\n".join(dates) + "\n")
        rate = get_recent_rate("origin", "main", window_hours=2.0)
        assert rate == 0.0

    @patch("commit_drift_monitor.run_cmd")
    def test_zero_when_empty(self, mock_run):
        mock_run.return_value = MagicMock(stdout="\n")
        rate = get_recent_rate("origin", "main", window_hours=2.0)
        assert rate == 0.0

    def test_zero_window(self):
        rate = get_recent_rate("origin", "main", window_hours=0)
        assert rate == 0.0


# --- measure ---

class TestMeasure:
    @patch("commit_drift_monitor.get_recent_rate", return_value=5.0)
    @patch("commit_drift_monitor.get_newest_unpushed_age_hours", return_value=0.5)
    @patch("commit_drift_monitor.get_oldest_unpushed_age_hours", return_value=3.0)
    @patch("commit_drift_monitor.count_unpushed", return_value=15)
    @patch("commit_drift_monitor.get_current_branch", return_value="main")
    @patch("commit_drift_monitor.get_remote_name", return_value="origin")
    def test_full_snapshot(self, *mocks):
        snap = measure()
        assert snap.unpushed_count == 15
        assert snap.severity == "easy"
        assert snap.remote_name == "origin"
        assert snap.branch == "main"
        assert snap.divergence_span_hours == pytest.approx(2.5, abs=0.01)
        assert snap.recent_rate_per_hour == 5.0

    @patch("commit_drift_monitor.get_recent_rate", return_value=0.0)
    @patch("commit_drift_monitor.get_newest_unpushed_age_hours", return_value=None)
    @patch("commit_drift_monitor.get_oldest_unpushed_age_hours", return_value=None)
    @patch("commit_drift_monitor.count_unpushed", return_value=0)
    @patch("commit_drift_monitor.get_current_branch", return_value="main")
    @patch("commit_drift_monitor.get_remote_name", return_value="origin")
    def test_no_drift(self, *mocks):
        snap = measure()
        assert snap.unpushed_count == 0
        assert snap.severity == "none"
        assert snap.divergence_span_hours is None


# --- format_human ---

class TestFormatHuman:
    def test_contains_key_fields(self):
        snap = DriftSnapshot(
            unpushed_count=42,
            oldest_unpushed_age_hours=12.5,
            newest_unpushed_age_hours=0.25,
            divergence_span_hours=12.25,
            recent_rate_per_hour=8.0,
            severity="moderate",
            suggested_action="push with --force-with-lease",
            remote_name="origin",
            branch="main",
            timestamp="2026-10-27T11:00:00+00:00",
        )
        out = format_human(snap)
        assert "42" in out
        assert "moderate" in out
        assert "origin" in out
        assert "main" in out
        assert "force-with-lease" in out

    def test_handles_none_values(self):
        snap = DriftSnapshot(
            unpushed_count=0,
            oldest_unpushed_age_hours=None,
            newest_unpushed_age_hours=None,
            divergence_span_hours=None,
            recent_rate_per_hour=0.0,
            severity="none",
            suggested_action="nothing to do",
            remote_name="origin",
            branch="main",
            timestamp="2026-10-27T11:00:00+00:00",
        )
        out = format_human(snap)
        assert "?" in out
        assert "0 commits" in out


# --- threshold constants ---

class TestThresholds:
    def test_thresholds_are_ordered(self):
        assert TRIVIAL_THRESHOLD < EASY_THRESHOLD < MODERATE_THRESHOLD < HARD_THRESHOLD

    def test_hour_thresholds_are_ordered(self):
        assert TRIVIAL_HOURS < EASY_HOURS < MODERATE_HOURS < HARD_HOURS

    def test_drift_window_is_positive(self):
        assert DRIFT_WINDOW_HOURS > 0
