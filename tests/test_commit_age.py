"""tests for iamai.commit_age"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from iamai.commit_age import (
    TIER_MODERATE,
    TIER_HIGH,
    TIER_CRITICAL,
    _classify_risk,
    commit_age,
    commit_age_summary,
)


# ---------------------------------------------------------------------------
# _classify_risk()
# ---------------------------------------------------------------------------
class TestClassifyRisk:
    def test_low_at_zero(self):
        assert _classify_risk(0) == "low"

    def test_low_just_under_moderate(self):
        assert _classify_risk(TIER_MODERATE - 1) == "low"

    def test_moderate_at_boundary(self):
        assert _classify_risk(TIER_MODERATE) == "moderate"

    def test_moderate_mid_range(self):
        assert _classify_risk(7200) == "moderate"

    def test_moderate_just_under_high(self):
        assert _classify_risk(TIER_HIGH - 1) == "moderate"

    def test_high_at_boundary(self):
        assert _classify_risk(TIER_HIGH) == "high"

    def test_high_mid_range(self):
        assert _classify_risk(43200) == "high"

    def test_high_just_under_critical(self):
        assert _classify_risk(TIER_CRITICAL - 1) == "high"

    def test_critical_at_boundary(self):
        assert _classify_risk(TIER_CRITICAL) == "critical"

    def test_critical_beyond(self):
        assert _classify_risk(TIER_CRITICAL * 10) == "critical"

    def test_negative_treated_as_low(self):
        # Negative seconds shouldn't happen, but be safe
        assert _classify_risk(-100) == "low"


# ---------------------------------------------------------------------------
# commit_age() — no unpushed commits
# ---------------------------------------------------------------------------
class TestCommitAgeClean:
    @patch("iamai.commit_age._git_unpushed_shas", return_value=[])
    def test_no_unpushed(self, mock_shas):
        result = commit_age()
        assert result["unpushed_count"] == 0
        assert result["oldest_unpushed_seconds"] == 0
        assert result["risk"] == "low"

    @patch("iamai.commit_age._git_unpushed_shas", return_value=[])
    def test_summary_all_pushed(self, mock_shas):
        summary = commit_age_summary()
        assert "all commits pushed" in summary
        assert "low risk" in summary


# ---------------------------------------------------------------------------
# commit_age() — with unpushed commits
# ---------------------------------------------------------------------------
class TestCommitAgeWithBacklog:
    @patch("iamai.commit_age._git_oldest_unpushed_ts")
    @patch("iamai.commit_age._git_unpushed_shas")
    def test_recent_backlog_low_risk(self, mock_shas, mock_ts):
        mock_shas.return_value = ["aaa", "bbb", "ccc"]
        mock_ts.return_value = datetime.now(timezone.utc) - timedelta(minutes=30)
        result = commit_age()
        assert result["unpushed_count"] == 3
        assert result["risk"] == "low"
        assert 1700 < result["oldest_unpushed_seconds"] < 1900

    @patch("iamai.commit_age._git_oldest_unpushed_ts")
    @patch("iamai.commit_age._git_unpushed_shas")
    def test_stale_backlog_moderate_risk(self, mock_shas, mock_ts):
        mock_shas.return_value = ["aaa", "bbb"]
        mock_ts.return_value = datetime.now(timezone.utc) - timedelta(hours=3)
        result = commit_age()
        assert result["unpushed_count"] == 2
        assert result["risk"] == "moderate"

    @patch("iamai.commit_age._git_oldest_unpushed_ts")
    @patch("iamai.commit_age._git_unpushed_shas")
    def test_old_backlog_high_risk(self, mock_shas, mock_ts):
        mock_shas.return_value = ["aaa"]
        mock_ts.return_value = datetime.now(timezone.utc) - timedelta(hours=12)
        result = commit_age()
        assert result["risk"] == "high"

    @patch("iamai.commit_age._git_oldest_unpushed_ts")
    @patch("iamai.commit_age._git_unpushed_shas")
    def test_ancient_backlog_critical_risk(self, mock_shas, mock_ts):
        mock_shas.return_value = ["aaa", "bbb", "ccc", "ddd"]
        mock_ts.return_value = datetime.now(timezone.utc) - timedelta(days=2)
        result = commit_age()
        assert result["risk"] == "critical"
        assert result["unpushed_count"] == 4


# ---------------------------------------------------------------------------
# commit_age() — edge case: can't determine timestamp
# ---------------------------------------------------------------------------
class TestCommitAgeUnknownTimestamp:
    @patch("iamai.commit_age._git_oldest_unpushed_ts", return_value=None)
    @patch("iamai.commit_age._git_unpushed_shas", return_value=["aaa", "bbb"])
    def test_unknown_ts_high_risk(self, mock_shas, mock_ts):
        result = commit_age()
        assert result["unpushed_count"] == 2
        assert result["oldest_unpushed_seconds"] == -1
        assert result["risk"] == "high"

    @patch("iamai.commit_age._git_oldest_unpushed_ts", return_value=None)
    @patch("iamai.commit_age._git_unpushed_shas", return_value=["aaa"])
    def test_summary_unknown_age(self, mock_shas, mock_ts):
        summary = commit_age_summary()
        assert "age unknown" in summary
        assert "high risk" in summary


# ---------------------------------------------------------------------------
# commit_age_summary() — formatting
# ---------------------------------------------------------------------------
class TestCommitAgeSummaryFormatting:
    @patch("iamai.commit_age._git_oldest_unpushed_ts")
    @patch("iamai.commit_age._git_unpushed_shas")
    def test_summary_minutes_only(self, mock_shas, mock_ts):
        mock_shas.return_value = ["aaa"]
        mock_ts.return_value = datetime.now(timezone.utc) - timedelta(minutes=45)
        summary = commit_age_summary()
        assert "1 unpushed commits" in summary
        assert "45m" in summary
        assert "low risk" in summary

    @patch("iamai.commit_age._git_oldest_unpushed_ts")
    @patch("iamai.commit_age._git_unpushed_shas")
    def test_summary_hours_and_minutes(self, mock_shas, mock_ts):
        mock_shas.return_value = ["aaa", "bbb"]
        mock_ts.return_value = datetime.now(timezone.utc) - timedelta(hours=8, minutes=15)
        summary = commit_age_summary()
        assert "2 unpushed commits" in summary
        assert "8h15m" in summary
        assert "high risk" in summary

    @patch("iamai.commit_age._git_oldest_unpushed_ts")
    @patch("iamai.commit_age._git_unpushed_shas")
    def test_summary_exact_hour(self, mock_shas, mock_ts):
        mock_shas.return_value = ["aaa"]
        mock_ts.return_value = datetime.now(timezone.utc) - timedelta(hours=2)
        summary = commit_age_summary()
        assert "2h0m" in summary


# ---------------------------------------------------------------------------
# Threshold constants sanity
# ---------------------------------------------------------------------------
class TestThresholds:
    def test_tiers_are_ascending(self):
        assert TIER_MODERATE < TIER_HIGH < TIER_CRITICAL

    def test_moderate_is_one_hour(self):
        assert TIER_MODERATE == 3600

    def test_high_is_six_hours(self):
        assert TIER_HIGH == 21600

    def test_critical_is_one_day(self):
        assert TIER_CRITICAL == 86400
