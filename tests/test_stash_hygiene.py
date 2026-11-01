#!/usr/bin/env python3
"""Tests for stash_hygiene.py — stale stash audit and pruning."""

import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stash_hygiene import (
    StashEntry,
    StashAudit,
    _parse_stash_list,
    audit,
    prune,
)


# ---------------------------------------------------------------------------
# StashEntry
# ---------------------------------------------------------------------------

class TestStashEntry:
    def test_age_hours(self):
        e = StashEntry(index=0, name="test", age_seconds=7200, branch="main")
        assert e.age_hours == 2.0

    def test_age_days(self):
        e = StashEntry(index=0, name="test", age_seconds=172800, branch="main")
        assert e.age_days == 2.0

    def test_frozen(self):
        e = StashEntry(index=0, name="test", age_seconds=100, branch="main")
        with pytest.raises(AttributeError):
            e.name = "changed"


# ---------------------------------------------------------------------------
# StashAudit
# ---------------------------------------------------------------------------

class TestStashAudit:
    def test_empty(self):
        a = StashAudit()
        assert a.total == 0
        assert a.stale_count == 0
        assert a.fresh_count == 0
        assert a.oldest_age_seconds == 0.0
        assert "no stashes" in a.recommendation

    def test_all_fresh(self):
        entries = [
            StashEntry(0, "recent", 3600, "main"),      # 1 hour
            StashEntry(1, "also recent", 7200, "main"), # 2 hours
        ]
        a = StashAudit(entries=entries, max_age_hours=24)
        assert a.total == 2
        assert a.fresh_count == 2
        assert a.stale_count == 0
        assert "fresh" in a.recommendation

    def test_all_stale(self):
        entries = [
            StashEntry(0, "old", 172800, "main"),    # 2 days
            StashEntry(1, "older", 259200, "main"),  # 3 days
        ]
        a = StashAudit(entries=entries, max_age_hours=24)
        assert a.total == 2
        assert a.stale_count == 2
        assert a.fresh_count == 0
        assert "safe to drop all" in a.recommendation

    def test_mixed(self):
        entries = [
            StashEntry(0, "fresh", 3600, "main"),
            StashEntry(1, "stale", 172800, "main"),
        ]
        a = StashAudit(entries=entries, max_age_hours=24)
        assert a.stale_count == 1
        assert a.fresh_count == 1
        assert "1/2 stale" in a.recommendation

    def test_oldest_age(self):
        entries = [
            StashEntry(0, "a", 1000, "main"),
            StashEntry(1, "b", 5000, "main"),
            StashEntry(2, "c", 3000, "main"),
        ]
        a = StashAudit(entries=entries)
        assert a.oldest_age_seconds == 5000.0


# ---------------------------------------------------------------------------
# _parse_stash_list
# ---------------------------------------------------------------------------

class TestParseStashList:
    def test_empty_input(self):
        assert _parse_stash_list("", time.time()) == []

    def test_single_entry(self):
        now = time.time()
        raw = "stash@{0}|1730000000|WIP on main: abc1234 some commit"
        entries = _parse_stash_list(raw, now)
        assert len(entries) == 1
        assert entries[0].index == 0
        assert entries[0].branch == "main"
        assert entries[0].age_seconds >= 0

    def test_multiple_entries(self):
        now = 1730100000
        raw = (
            "stash@{0}|1730099000|On main: recent\n"
            "stash@{1}|1730000000|WIP on feature: old stuff\n"
            "stash@{2}|1729900000|On main: oldest\n"
        )
        entries = _parse_stash_list(raw, now)
        assert len(entries) == 3
        assert entries[0].index == 0
        assert entries[1].index == 1
        assert entries[2].index == 2
        # oldest should have largest age
        assert entries[2].age_seconds > entries[1].age_seconds > entries[0].age_seconds

    def test_malformed_lines_skipped(self):
        now = time.time()
        raw = "bad line\nstash@{0}|1730000000|good\n|incomplete|"
        entries = _parse_stash_list(raw, now)
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# audit (integration-style, mocked subprocess)
# ---------------------------------------------------------------------------

class TestAudit:
    def test_audit_with_mocked_git(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "stash@{0}|1730000000|WIP on main: abc old commit\n"
            "stash@{1}|1730099999|On main: very recent\n"
        )
        with patch("iamai.stash_hygiene._run", return_value=mock_result):
            report = audit("/fake/repo", max_age_hours=1)
        assert report.total == 2
        # both will be very old relative to now
        assert report.stale_count >= 1

    def test_audit_git_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        with patch("iamai.stash_hygiene._run", return_value=mock_result):
            report = audit("/fake/repo")
        assert report.total == 0


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------

class TestPrune:
    def test_dry_run_does_not_drop(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "stash@{0}|1700000000|old stash"
        calls = []
        def mock_run(cmd, cwd):
            calls.append(cmd)
            return mock_result
        with patch("iamai.stash_hygiene._run", side_effect=mock_run):
            dropped = prune("/fake/repo", max_age_hours=1, dry_run=True)
        assert len(dropped) == 1
        # only the list call, no drop call
        assert len(calls) == 1
        assert calls[0][2] == "list"

    def test_actual_prune_drops(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "stash@{0}|1700000000|old stash"
        calls = []
        def mock_run(cmd, cwd):
            calls.append(cmd)
            return mock_result
        with patch("iamai.stash_hygiene._run", side_effect=mock_run):
            dropped = prune("/fake/repo", max_age_hours=1, dry_run=False)
        assert len(dropped) == 1
        assert dropped[0] == 0
        # list + drop
        assert len(calls) == 2
        assert calls[0][2] == "list"
        assert calls[1][2] == "drop"

    def test_no_stale_no_drop(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = f"stash@{{0}}|{int(time.time())}|brand new"
        with patch("iamai.stash_hygiene._run", return_value=mock_result):
            dropped = prune("/fake/repo", max_age_hours=24, dry_run=False)
        assert dropped == []
