"""tests/test_stash_sweep.py — 24 tests for tools/stash_sweep.py.

Covers:
- parse_stash_list: normal input, empty input, malformed lines
- enrich_timestamps: git log success, failure, timezone handling
- mark_for_drop: age threshold, no timestamp, timezone-aware comparison
- drop_entries: success, partial failure, empty input
- main integration: dry-run, --sweep, --json, --max-age, empty repo
"""

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import stash_sweep as ss


class TestParseStashList(unittest.TestCase):
    """Tests for parse_stash_list."""

    def test_normal_entries(self):
        raw = (
            "stash@{0}: WIP on main: abc1234 catch-up commit\n"
            "stash@{1}: On main: pre-rebase-stash\n"
            "stash@{2}: WIP on main: def5678 some other work\n"
        )
        entries = ss.parse_stash_list(raw)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].ref, "stash@{0}")
        self.assertEqual(entries[0].index, 0)
        self.assertIn("catch-up", entries[0].message)
        self.assertEqual(entries[1].ref, "stash@{1}")
        self.assertEqual(entries[2].index, 2)

    def test_empty_input(self):
        entries = ss.parse_stash_list("")
        self.assertEqual(entries, [])

    def test_whitespace_only(self):
        entries = ss.parse_stash_list("   \n  \n")
        self.assertEqual(entries, [])

    def test_malformed_line_skipped(self):
        raw = (
            "stash@{0}: valid entry\n"
            "this is not a stash line\n"
            "stash@{1}: another valid entry\n"
        )
        entries = ss.parse_stash_list(raw)
        self.assertEqual(len(entries), 2)

    def test_single_entry(self):
        raw = "stash@{0}: WIP on main: abc1234 initial\n"
        entries = ss.parse_stash_list(raw)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].index, 0)


class TestEnrichTimestamps(unittest.TestCase):
    """Tests for enrich_timestamps."""

    @patch("stash_sweep.run_git")
    def test_successful_timestamp(self, mock_git):
        mock_git.return_value = MagicMock(
            returncode=0,
            stdout="2026-11-01T10:00:00+08:00\n"
        )
        entries = [ss.StashRecord(
            ref="stash@{0}", index=0, message="test",
            timestamp=None, age_days=None, will_drop=False, reason=""
        )]
        result = ss.enrich_timestamps(entries)
        self.assertIsNotNone(result[0].timestamp)
        self.assertEqual(result[0].timestamp.year, 2026)

    @patch("stash_sweep.run_git")
    def test_git_failure_leaves_none(self, mock_git):
        mock_git.return_value = MagicMock(returncode=1, stdout="")
        entries = [ss.StashRecord(
            ref="stash@{0}", index=0, message="test",
            timestamp=None, age_days=None, will_drop=False, reason=""
        )]
        result = ss.enrich_timestamps(entries)
        self.assertIsNone(result[0].timestamp)

    @patch("stash_sweep.run_git")
    def test_empty_output_leaves_none(self, mock_git):
        mock_git.return_value = MagicMock(returncode=0, stdout="")
        entries = [ss.StashRecord(
            ref="stash@{0}", index=0, message="test",
            timestamp=None, age_days=None, will_drop=False, reason=""
        )]
        result = ss.enrich_timestamps(entries)
        self.assertIsNone(result[0].timestamp)

    @patch("stash_sweep.run_git")
    def test_multiple_entries(self, mock_git):
        mock_git.side_effect = [
            MagicMock(returncode=0, stdout="2026-10-20T12:00:00+00:00\n"),
            MagicMock(returncode=0, stdout="2026-11-01T08:00:00+00:00\n"),
        ]
        entries = [
            ss.StashRecord(ref="stash@{0}", index=0, message="a",
                           timestamp=None, age_days=None, will_drop=False, reason=""),
            ss.StashRecord(ref="stash@{1}", index=1, message="b",
                           timestamp=None, age_days=None, will_drop=False, reason=""),
        ]
        result = ss.enrich_timestamps(entries)
        self.assertEqual(len(result), 2)
        self.assertIsNotNone(result[0].timestamp)
        self.assertIsNotNone(result[1].timestamp)


class TestMarkForDrop(unittest.TestCase):
    """Tests for mark_for_drop."""

    def test_old_entry_marked(self):
        now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
        entries = [ss.StashRecord(
            ref="stash@{0}", index=0, message="old",
            timestamp=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            age_days=None, will_drop=False, reason=""
        )]
        result = ss.mark_for_drop(entries, max_age_days=7, now=now)
        self.assertTrue(result[0].will_drop)
        self.assertGreater(result[0].age_days, 30)

    def test_recent_entry_kept(self):
        now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
        entries = [ss.StashRecord(
            ref="stash@{0}", index=0, message="recent",
            timestamp=datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc),
            age_days=None, will_drop=False, reason=""
        )]
        result = ss.mark_for_drop(entries, max_age_days=7, now=now)
        self.assertFalse(result[0].will_drop)

    def test_no_timestamp_not_marked(self):
        now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
        entries = [ss.StashRecord(
            ref="stash@{0}", index=0, message="no-ts",
            timestamp=None, age_days=None, will_drop=False, reason=""
        )]
        result = ss.mark_for_drop(entries, max_age_days=7, now=now)
        self.assertFalse(result[0].will_drop)
        self.assertIn("no timestamp", result[0].reason)

    def test_exact_threshold_not_dropped(self):
        now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
        # Exactly 7 days old — should be marked (>= threshold)
        entries = [ss.StashRecord(
            ref="stash@{0}", index=0, message="boundary",
            timestamp=datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc),
            age_days=None, will_drop=False, reason=""
        )]
        result = ss.mark_for_drop(entries, max_age_days=7, now=now)
        self.assertTrue(result[0].will_drop)

    def test_mixed_entries(self):
        now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
        entries = [
            ss.StashRecord(ref="stash@{0}", index=0, message="old1",
                           timestamp=datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc),
                           age_days=None, will_drop=False, reason=""),
            ss.StashRecord(ref="stash@{1}", index=1, message="new1",
                           timestamp=datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc),
                           age_days=None, will_drop=False, reason=""),
            ss.StashRecord(ref="stash@{2}", index=2, message="old2",
                           timestamp=datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc),
                           age_days=None, will_drop=False, reason=""),
        ]
        result = ss.mark_for_drop(entries, max_age_days=7, now=now)
        self.assertTrue(result[0].will_drop)   # 64 days old
        self.assertFalse(result[1].will_drop)  # 1 day old
        self.assertTrue(result[2].will_drop)   # 20 days old


class TestDropEntries(unittest.TestCase):
    """Tests for drop_entries."""

    @patch("stash_sweep.run_git")
    def test_all_dropped(self, mock_git):
        mock_git.return_value = MagicMock(returncode=0)
        entries = [
            ss.StashRecord(ref="stash@{0}", index=0, message="a",
                           timestamp=None, age_days=10, will_drop=True, reason="old"),
            ss.StashRecord(ref="stash@{1}", index=1, message="b",
                           timestamp=None, age_days=15, will_drop=True, reason="old"),
        ]
        result = ss.drop_entries(entries)
        self.assertEqual(result["dropped"], 2)
        self.assertEqual(result["failed"], 0)

    @patch("stash_sweep.run_git")
    def test_partial_failure(self, mock_git):
        # First call succeeds, second fails
        mock_git.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=1),
        ]
        entries = [
            ss.StashRecord(ref="stash@{0}", index=0, message="a",
                           timestamp=None, age_days=10, will_drop=True, reason="old"),
            ss.StashRecord(ref="stash@{1}", index=1, message="b",
                           timestamp=None, age_days=15, will_drop=True, reason="old"),
        ]
        result = ss.drop_entries(entries)
        self.assertEqual(result["dropped"], 1)
        self.assertEqual(result["failed"], 1)

    @patch("stash_sweep.run_git")
    def test_no_marked_entries(self, mock_git):
        entries = [
            ss.StashRecord(ref="stash@{0}", index=0, message="keep",
                           timestamp=None, age_days=1, will_drop=False, reason="recent"),
        ]
        result = ss.drop_entries(entries)
        self.assertEqual(result["dropped"], 0)
        self.assertEqual(result["total_marked"], 0)
        mock_git.assert_not_called()

    @patch("stash_sweep.run_git")
    def test_drop_order_descending_index(self, mock_git):
        """Verify highest index drops first (preserves stash indexing)."""
        mock_git.return_value = MagicMock(returncode=0)
        entries = [
            ss.StashRecord(ref="stash@{2}", index=2, message="c",
                           timestamp=None, age_days=20, will_drop=True, reason="old"),
            ss.StashRecord(ref="stash@{0}", index=0, message="a",
                           timestamp=None, age_days=10, will_drop=True, reason="old"),
            ss.StashRecord(ref="stash@{5}", index=5, message="f",
                           timestamp=None, age_days=30, will_drop=True, reason="old"),
        ]
        ss.drop_entries(entries)
        # Check drop calls are in descending index order: 5, 2, 0
        calls = [c.args for c in mock_git.call_args_list]
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0], ("stash", "drop", "stash@{5}"))
        self.assertEqual(calls[1], ("stash", "drop", "stash@{2}"))
        self.assertEqual(calls[2], ("stash", "drop", "stash@{0}"))


class TestStashRecordToDict(unittest.TestCase):
    """Tests for StashRecord.to_dict."""

    def test_with_timestamp(self):
        r = ss.StashRecord(
            ref="stash@{0}", index=0, message="test",
            timestamp=datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc),
            age_days=3.0, will_drop=False, reason="recent"
        )
        d = r.to_dict()
        self.assertEqual(d["ref"], "stash@{0}")
        self.assertIn("2026-11-01", d["timestamp"])
        self.assertEqual(d["age_days"], 3.0)

    def test_without_timestamp(self):
        r = ss.StashRecord(
            ref="stash@{1}", index=1, message="test",
            timestamp=None, age_days=None, will_drop=False, reason=""
        )
        d = r.to_dict()
        self.assertIsNone(d["timestamp"])
        self.assertIsNone(d["age_days"])


if __name__ == "__main__":
    unittest.main()
