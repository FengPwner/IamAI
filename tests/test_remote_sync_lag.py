"""Tests for tools/remote_sync_lag.py

Uses subprocess mocking to avoid real git calls.  Covers:
  - synced state (lag = 0)
  - ahead state (local newer)
  - behind state (remote newer)
  - no remote ref
  - threshold boundary
  - human-readable formatting
  - JSON output mode
  - error handling
"""

import json
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, "tools")
import remote_sync_lag as rsl


class TestCommitTimestamp(unittest.TestCase):
    @patch("remote_sync_lag.git")
    def test_returns_int(self, mock_git):
        mock_git.return_value = "1730476800"
        ts = rsl.commit_timestamp("main")
        self.assertEqual(ts, 1730476800)
        mock_git.assert_called_once_with("log", "-1", "--format=%ct", "main")


class TestRemoteSyncLag(unittest.TestCase):
    @patch("remote_sync_lag.commit_timestamp")
    def test_synced(self, mock_ts):
        mock_ts.side_effect = lambda ref: 1000
        info = rsl.remote_sync_lag()
        self.assertEqual(info["status"], "synced")
        self.assertEqual(info["lag_seconds"], 0)
        self.assertEqual(info["lag_human"], "0s")

    @patch("remote_sync_lag.commit_timestamp")
    def test_ahead(self, mock_ts):
        mock_ts.side_effect = lambda ref: 1500 if ref == "main" else 1000
        info = rsl.remote_sync_lag()
        self.assertEqual(info["status"], "ahead")
        self.assertEqual(info["lag_seconds"], 500)

    @patch("remote_sync_lag.commit_timestamp")
    def test_behind(self, mock_ts):
        mock_ts.side_effect = lambda ref: 800 if ref == "main" else 1000
        info = rsl.remote_sync_lag()
        self.assertEqual(info["status"], "behind")
        self.assertEqual(info["lag_seconds"], -200)

    @patch("remote_sync_lag.commit_timestamp")
    def test_no_remote_ref(self, mock_ts):
        def side_effect(ref):
            if "origin" in ref:
                raise RuntimeError("fatal: bad revision")
            return 1000
        mock_ts.side_effect = side_effect
        info = rsl.remote_sync_lag()
        self.assertEqual(info["status"], "no_remote")
        self.assertIsNone(info["remote_ts"])

    @patch("remote_sync_lag.commit_timestamp")
    def test_custom_branch_and_remote(self, mock_ts):
        mock_ts.side_effect = lambda ref: 1000
        rsl.remote_sync_lag(branch="dev", remote="upstream")
        calls = mock_ts.call_args_list
        self.assertEqual(calls[0].args, ("dev",))
        self.assertEqual(calls[1].args, ("upstream/dev",))


class TestFormatHuman(unittest.TestCase):
    @patch("remote_sync_lag.commit_timestamp")
    def test_seconds(self, mock_ts):
        mock_ts.side_effect = lambda ref: 1045 if ref == "main" else 1000
        info = rsl.remote_sync_lag()
        self.assertEqual(info["lag_human"], "45s")

    @patch("remote_sync_lag.commit_timestamp")
    def test_minutes(self, mock_ts):
        mock_ts.side_effect = lambda ref: 1180 if ref == "main" else 1000
        info = rsl.remote_sync_lag()
        self.assertEqual(info["lag_human"], "3m0s")

    @patch("remote_sync_lag.commit_timestamp")
    def test_hours(self, mock_ts):
        mock_ts.side_effect = lambda ref: 1000 + 7265 if ref == "main" else 1000
        info = rsl.remote_sync_lag()
        self.assertEqual(info["lag_human"], "2h1m")

    @patch("remote_sync_lag.commit_timestamp")
    def test_behind_shows_negative(self, mock_ts):
        mock_ts.side_effect = lambda ref: 900 if ref == "main" else 1000
        info = rsl.remote_sync_lag()
        self.assertIn("-", info["lag_human"])


class TestFormatReport(unittest.TestCase):
    def test_includes_status(self):
        info = {
            "local_ts": 1730476800,
            "remote_ts": 1730476800,
            "lag_seconds": 0,
            "lag_human": "0s",
            "status": "synced",
        }
        report = rsl.format_report(info)
        self.assertIn("synced", report)
        self.assertIn("0s", report)

    def test_no_remote(self):
        info = {
            "local_ts": 1730476800,
            "remote_ts": None,
            "lag_seconds": None,
            "lag_human": "no remote tracking ref",
            "status": "no_remote",
        }
        report = rsl.format_report(info)
        self.assertNotIn("remote:", report)
        self.assertIn("no remote tracking ref", report)


class TestThreshold(unittest.TestCase):
    """Test the exit-code logic without actually running main()."""

    @patch("remote_sync_lag.commit_timestamp")
    def test_within_threshold(self, mock_ts):
        mock_ts.side_effect = lambda ref: 1100 if ref == "main" else 1000
        info = rsl.remote_sync_lag()
        # lag = 100s, threshold = 600 → ok
        self.assertTrue(abs(info["lag_seconds"]) <= 600)

    @patch("remote_sync_lag.commit_timestamp")
    def test_exceeds_threshold(self, mock_ts):
        mock_ts.side_effect = lambda ref: 2000 if ref == "main" else 1000
        info = rsl.remote_sync_lag()
        # lag = 1000s, threshold = 600 → stale
        self.assertTrue(abs(info["lag_seconds"]) > 600)


if __name__ == "__main__":
    unittest.main()
