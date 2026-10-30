"""Tests for iamai.stash_hygiene — stash accumulation health checker."""

import pytest

from iamai.stash_hygiene import (
    analyze_stash,
    classify_entry,
    count_entries,
    drop_candidates,
)


# ---------------------------------------------------------------------------
# classify_entry
# ---------------------------------------------------------------------------

class TestClassifyEntry:
    def test_wip_entry(self):
        line = "stash@{0}: WIP on main: abc1234 some commit message"
        assert classify_entry(line) == "wip"

    def test_named_entry(self):
        line = "stash@{5}: On main: pre-rebase stash"
        assert classify_entry(line) == "named"

    def test_autostash_entry(self):
        line = "stash@{3}: autostash"
        assert classify_entry(line) == "autostash"

    def test_empty_line(self):
        assert classify_entry("") == "unknown"

    def test_whitespace_only(self):
        assert classify_entry("   ") == "unknown"

    def test_wip_with_branch(self):
        line = "stash@{10}: WIP on feature-branch: def5678 added tests"
        assert classify_entry(line) == "wip"

    def test_named_custom_message(self):
        line = "stash@{2}: On main: writer-strokes-pre-rebase"
        assert classify_entry(line) == "named"

    def test_bare_autostash(self):
        assert classify_entry("autostash") == "autostash"

    def test_unknown_fallback(self):
        assert classify_entry("something completely different") == "wip"


# ---------------------------------------------------------------------------
# count_entries
# ---------------------------------------------------------------------------

class TestCountEntries:
    def test_empty_list(self):
        assert count_entries([]) == 0

    def test_blank_lines_ignored(self):
        assert count_entries(["", "  ", "stash@{0}: WIP on main: abc1234 msg"]) == 1

    def test_multiple_entries(self):
        lines = [
            "stash@{0}: WIP on main: abc1234 msg",
            "stash@{1}: On main: named stash",
            "stash@{2}: autostash",
        ]
        assert count_entries(lines) == 3


# ---------------------------------------------------------------------------
# analyze_stash
# ---------------------------------------------------------------------------

class TestAnalyzeStash:
    def test_clean_zero_entries(self):
        report = analyze_stash([])
        assert report["count"] == 0
        assert report["verdict"] == "clean"
        assert "no action" in report["recommend"]

    def test_clean_two_entries(self):
        lines = [
            "stash@{0}: WIP on main: abc msg",
            "stash@{1}: autostash",
        ]
        report = analyze_stash(lines)
        assert report["count"] == 2
        assert report["verdict"] == "clean"

    def test_mild(self):
        lines = [f"stash@{{{i}}}: WIP on main: abc msg{i}" for i in range(5)]
        report = analyze_stash(lines)
        assert report["count"] == 5
        assert report["verdict"] == "mild"

    def test_moderate(self):
        lines = [f"stash@{{{i}}}: WIP on main: abc msg{i}" for i in range(20)]
        report = analyze_stash(lines)
        assert report["count"] == 20
        assert report["verdict"] == "moderate"

    def test_critical(self):
        lines = [f"stash@{{{i}}}: WIP on main: abc msg{i}" for i in range(50)]
        report = analyze_stash(lines)
        assert report["count"] == 50
        assert report["verdict"] == "critical"
        assert "graveyard" in report["recommend"]

    def test_mixed_types(self):
        lines = [
            "stash@{0}: WIP on main: abc msg",
            "stash@{1}: autostash",
            "stash@{2}: On main: named stash",
            "stash@{3}: WIP on main: def msg",
            "stash@{4}: autostash",
        ]
        report = analyze_stash(lines)
        assert report["count"] == 5
        assert report["wip"] == 2
        assert report["autostash"] == 2
        assert report["named"] == 1

    def test_blank_lines_not_counted(self):
        lines = [
            "stash@{0}: WIP on main: abc msg",
            "",
            "  ",
            "stash@{1}: autostash",
        ]
        report = analyze_stash(lines)
        assert report["count"] == 2

    def test_boundary_clean_at_2(self):
        lines = [
            "stash@{0}: WIP on main: a b",
            "stash@{1}: WIP on main: c d",
        ]
        assert analyze_stash(lines)["verdict"] == "clean"

    def test_boundary_mild_at_3(self):
        lines = [f"stash@{{{i}}}: WIP on main: msg{i}" for i in range(3)]
        assert analyze_stash(lines)["verdict"] == "mild"

    def test_boundary_mild_at_10(self):
        lines = [f"stash@{{{i}}}: WIP on main: msg{i}" for i in range(10)]
        assert analyze_stash(lines)["verdict"] == "mild"

    def test_boundary_moderate_at_11(self):
        lines = [f"stash@{{{i}}}: WIP on main: msg{i}" for i in range(11)]
        assert analyze_stash(lines)["verdict"] == "moderate"

    def test_boundary_moderate_at_30(self):
        lines = [f"stash@{{{i}}}: WIP on main: msg{i}" for i in range(30)]
        assert analyze_stash(lines)["verdict"] == "moderate"

    def test_boundary_critical_at_31(self):
        lines = [f"stash@{{{i}}}: WIP on main: msg{i}" for i in range(31)]
        assert analyze_stash(lines)["verdict"] == "critical"

    def test_report_keys(self):
        report = analyze_stash([])
        expected_keys = {"count", "autostash", "wip", "named", "verdict", "recommend"}
        assert set(report.keys()) == expected_keys


# ---------------------------------------------------------------------------
# drop_candidates
# ---------------------------------------------------------------------------

class TestDropCandidates:
    def test_empty_list(self):
        assert drop_candidates([]) == []

    def test_keep_default_three(self):
        lines = [f"stash@{{{i}}}: WIP on main: msg{i}" for i in range(10)]
        candidates = drop_candidates(lines, keep_recent=3)
        # keep stash@{0}, stash@{1}, stash@{2}; drop 3..9
        assert candidates == [3, 4, 5, 6, 7, 8, 9]

    def test_keep_all_when_fewer_than_keep(self):
        lines = [
            "stash@{0}: WIP on main: msg0",
            "stash@{1}: WIP on main: msg1",
        ]
        assert drop_candidates(lines, keep_recent=5) == []

    def test_keep_one(self):
        lines = [f"stash@{{{i}}}: WIP on main: msg{i}" for i in range(5)]
        candidates = drop_candidates(lines, keep_recent=1)
        assert candidates == [1, 2, 3, 4]

    def test_skip_blank_lines(self):
        lines = [
            "stash@{0}: WIP on main: msg0",
            "",
            "stash@{1}: WIP on main: msg1",
            "  ",
            "stash@{2}: WIP on main: msg2",
        ]
        candidates = drop_candidates(lines, keep_recent=1)
        assert candidates == [1, 2]

    def test_unparseable_lines_ignored(self):
        lines = [
            "stash@{0}: WIP on main: msg0",
            "not a stash line",
            "stash@{1}: WIP on main: msg1",
        ]
        candidates = drop_candidates(lines, keep_recent=1)
        assert candidates == [1]

    def test_large_stash(self):
        lines = [f"stash@{{{i}}}: WIP on main: msg{i}" for i in range(95)]
        candidates = drop_candidates(lines, keep_recent=3)
        assert len(candidates) == 92
        assert candidates[0] == 3
        assert candidates[-1] == 94

    def test_drop_order_ascending(self):
        """Candidates should be sorted ascending for safe reverse-order dropping."""
        lines = [f"stash@{{{i}}}: WIP on main: msg{i}" for i in range(10)]
        candidates = drop_candidates(lines, keep_recent=2)
        assert candidates == sorted(candidates)
