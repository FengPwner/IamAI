"""Tests for iamai.last_sync_age — last sync age measurement.

These tests exercise the pure logic (formatting, classification) without
touching git, and also test the full integration path against the real
repo state.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.last_sync_age import (  # noqa: E402
    _format_age,
    _classify_health,
    last_sync_age,
    last_sync_summary,
)


# ---------------------------------------------------------------------------
# _format_age — pure formatting
# ---------------------------------------------------------------------------

class TestFormatAge:
    def test_zero(self):
        assert _format_age(0) == "0m"

    def test_negative(self):
        assert _format_age(-1) == "unknown"

    def test_minutes_only(self):
        assert _format_age(1500) == "25m"

    def test_hours_and_minutes(self):
        assert _format_age(5400) == "1h 30m"

    def test_days_hours_minutes(self):
        # 314520s = 3d + 55320s → 55320/3600 = 15h rem 1320s → 22m
        assert _format_age(314520) == "3d 15h 22m"

    def test_exactly_one_day(self):
        # zero-valued hours skipped → "1d 0m"
        assert _format_age(86400) == "1d 0m"

    def test_seven_days(self):
        assert _format_age(604800) == "7d 0m"

    def test_large_value(self):
        assert _format_age(2592000) == "30d 0m"

    def test_fractional_seconds_ignored(self):
        assert _format_age(61.7) == "1m"

    def test_one_hour_exactly(self):
        assert _format_age(3600) == "1h 0m"

    def test_two_days_three_hours(self):
        # 2*86400 + 3*3600 = 183600
        assert _format_age(183600) == "2d 3h 0m"


# ---------------------------------------------------------------------------
# _classify_health — tier mapping
# ---------------------------------------------------------------------------

class TestClassifyHealth:
    def test_fresh_at_zero(self):
        assert _classify_health(0) == "fresh"

    def test_fresh_at_59_minutes(self):
        assert _classify_health(3599) == "fresh"

    def test_stale_at_1_hour(self):
        assert _classify_health(3600) == "stale"

    def test_stale_at_23_hours(self):
        assert _classify_health(82800) == "stale"

    def test_cold_at_1_day(self):
        assert _classify_health(86400) == "cold"

    def test_cold_at_6_days(self):
        assert _classify_health(518400) == "cold"

    def test_frozen_at_7_days(self):
        assert _classify_health(604800) == "frozen"

    def test_frozen_at_30_days(self):
        assert _classify_health(2592000) == "frozen"

    def test_negative_is_frozen(self):
        assert _classify_health(-1) == "frozen"


# ---------------------------------------------------------------------------
# last_sync_age — integration with mocked internals
# ---------------------------------------------------------------------------

class TestLastSyncAgeMocked:
    """Test last_sync_age() by patching internal helper functions."""

    @patch("iamai.last_sync_age._origin_head_sha", return_value=None)
    @patch("iamai.last_sync_age._local_ahead_count", return_value=50)
    def test_origin_not_found(self, *_):
        """When origin/main doesn't exist → frozen."""
        info = last_sync_age()
        assert info["sync_health"] == "frozen"
        assert info["sync_age_seconds"] == -1
        assert info["last_synced_sha"] is None
        assert info["local_ahead"] == 50

    @patch("iamai.last_sync_age._local_ahead_count", return_value=5)
    def test_fresh_sync(self, _):
        """Sync 30 minutes ago → fresh."""
        sha = "abc1234"
        ts = datetime.now(timezone.utc) - timedelta(minutes=30)

        with patch("iamai.last_sync_age._origin_head_sha", return_value=sha), \
             patch("iamai.last_sync_age._origin_head_ts", return_value=ts):
            info = last_sync_age()

        assert info["sync_health"] == "fresh"
        assert info["last_synced_sha"] == sha
        assert info["local_ahead"] == 5
        assert 1700 < info["sync_age_seconds"] < 1900

    @patch("iamai.last_sync_age._local_ahead_count", return_value=126)
    def test_cold_sync(self, _):
        """Sync 3 days ago → cold."""
        sha = "def5678"
        ts = datetime.now(timezone.utc) - timedelta(days=3)

        with patch("iamai.last_sync_age._origin_head_sha", return_value=sha), \
             patch("iamai.last_sync_age._origin_head_ts", return_value=ts):
            info = last_sync_age()

        assert info["sync_health"] == "cold"
        assert info["local_ahead"] == 126
        assert info["sync_age_seconds"] > 250000

    @patch("iamai.last_sync_age._local_ahead_count", return_value=200)
    def test_frozen_sync(self, _):
        """Sync 10 days ago → frozen."""
        sha = "ghi9012"
        ts = datetime.now(timezone.utc) - timedelta(days=10)

        with patch("iamai.last_sync_age._origin_head_sha", return_value=sha), \
             patch("iamai.last_sync_age._origin_head_ts", return_value=ts):
            info = last_sync_age()

        assert info["sync_health"] == "frozen"
        assert info["local_ahead"] == 200

    @patch("iamai.last_sync_age._origin_head_sha", return_value="jkl3456")
    @patch("iamai.last_sync_age._origin_head_ts", return_value=None)
    @patch("iamai.last_sync_age._local_ahead_count", return_value=10)
    def test_timestamp_unparseable(self, *_):
        """When timestamp can't be parsed → frozen."""
        info = last_sync_age()
        assert info["sync_health"] == "frozen"
        assert info["sync_age_seconds"] == -1
        assert info["last_synced_sha"] == "jkl3456"

    @patch("iamai.last_sync_age._local_ahead_count", return_value=0)
    def test_stale_sync(self, _):
        """Sync 5 hours ago → stale."""
        sha = "mno5678"
        ts = datetime.now(timezone.utc) - timedelta(hours=5)

        with patch("iamai.last_sync_age._origin_head_sha", return_value=sha), \
             patch("iamai.last_sync_age._origin_head_ts", return_value=ts):
            info = last_sync_age()

        assert info["sync_health"] == "stale"
        assert info["local_ahead"] == 0
        assert 17000 < info["sync_age_seconds"] < 19000


# ---------------------------------------------------------------------------
# last_sync_summary — string formatting
# ---------------------------------------------------------------------------

class TestLastSyncSummary:
    @patch("iamai.last_sync_age.last_sync_age")
    def test_summary_fresh(self, mock_fn):
        mock_fn.return_value = {
            "sync_age_seconds": 1800,
            "sync_age_human": "30m",
            "local_ahead": 3,
            "last_synced_sha": "abc1234",
            "last_synced_ts": "2026-10-27T18:30:00+00:00",
            "sync_health": "fresh",
        }
        s = last_sync_summary()
        assert "30m" in s
        assert "fresh" in s
        assert "abc1234" in s
        assert "3 commits ahead" in s

    @patch("iamai.last_sync_age.last_sync_age")
    def test_summary_frozen_unknown(self, mock_fn):
        mock_fn.return_value = {
            "sync_age_seconds": -1,
            "sync_age_human": "unknown",
            "local_ahead": -1,
            "last_synced_sha": None,
            "last_synced_ts": None,
            "sync_health": "frozen",
        }
        s = last_sync_summary()
        assert "unknown" in s
        assert "frozen" in s
        assert "none" in s

    @patch("iamai.last_sync_age.last_sync_age")
    def test_summary_cold_days(self, mock_fn):
        mock_fn.return_value = {
            "sync_age_seconds": 314520,
            "sync_age_human": "3d 15h 22m",
            "local_ahead": 126,
            "last_synced_sha": "xyz7890",
            "last_synced_ts": "2026-10-24T03:38:00+00:00",
            "sync_health": "cold",
        }
        s = last_sync_summary()
        assert "3d15h" in s
        assert "cold" in s
        assert "126 commits ahead" in s

    @patch("iamai.last_sync_age.last_sync_age")
    def test_summary_stale_hours(self, mock_fn):
        mock_fn.return_value = {
            "sync_age_seconds": 14400,
            "sync_age_human": "4h 0m",
            "local_ahead": 20,
            "last_synced_sha": "mn1234",
            "last_synced_ts": "2026-10-27T15:00:00+00:00",
            "sync_health": "stale",
        }
        s = last_sync_summary()
        assert "4h0m" in s
        assert "stale" in s
        assert "20 commits ahead" in s

    @patch("iamai.last_sync_age.last_sync_age")
    def test_summary_zero_ahead(self, mock_fn):
        mock_fn.return_value = {
            "sync_age_seconds": 600,
            "sync_age_human": "10m",
            "local_ahead": 0,
            "last_synced_sha": "allgood",
            "last_synced_ts": "2026-10-27T18:50:00+00:00",
            "sync_health": "fresh",
        }
        s = last_sync_summary()
        assert "0 commits ahead" in s


# ---------------------------------------------------------------------------
# Integration: real repo (validates structure, not exact values)
# ---------------------------------------------------------------------------

class TestIntegration:
    """Run against the real repo — only validates structure."""

    def test_real_repo_returns_dict(self):
        info = last_sync_age()
        assert isinstance(info, dict)
        assert "sync_health" in info
        assert info["sync_health"] in ("fresh", "stale", "cold", "frozen")
        assert "sync_age_seconds" in info
        assert "sync_age_human" in info
        assert "local_ahead" in info

    def test_real_summary_is_string(self):
        s = last_sync_summary()
        assert isinstance(s, str)
        assert "last sync" in s
        assert any(tag in s for tag in ("fresh", "stale", "cold", "frozen"))

    def test_real_sync_health_fields(self):
        info = last_sync_age()
        # If sync_age_seconds is known (>= 0), ts should be set too
        if info["sync_age_seconds"] >= 0:
            assert info["last_synced_sha"] is not None
            assert info["last_synced_ts"] is not None
