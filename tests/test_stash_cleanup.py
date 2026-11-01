"""Tests for tools.stash_cleanup — orphaned stash entry dropper."""

import json
import subprocess
from unittest.mock import patch, MagicMock

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from stash_cleanup import classify, list_stashes, drop, main


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_wip_entry(self):
        line = "stash@{0}: WIP on main: abc1234 some commit message"
        assert classify(line) == "wip"

    def test_autostash_entry(self):
        line = "stash@{3}: autostash"
        assert classify(line) == "autostash"

    def test_named_entry(self):
        line = "stash@{5}: On main: pre-rebase-stash"
        assert classify(line) == "named"

    def test_named_entry_custom(self):
        line = "stash@{7}: On feature-branch: push-sync-test"
        assert classify(line) == "named"

    def test_empty_line(self):
        assert classify("") == "unknown"

    def test_whitespace_only(self):
        assert classify("   ") == "unknown"

    def test_wip_with_date_in_message(self):
        line = "stash@{8}: WIP on main: 9c53b51 catch-up: commit pending"
        assert classify(line) == "wip"

    def test_bare_autostash(self):
        assert classify("autostash") == "autostash"


# ---------------------------------------------------------------------------
# main — dry run
# ---------------------------------------------------------------------------

class TestMainDryRun:
    @patch("stash_cleanup.drop")
    @patch("stash_cleanup.list_stashes")
    def test_dry_run_does_not_drop(self, mock_list, mock_drop, capsys):
        mock_list.return_value = [
            "stash@{0}: WIP on main: aaa1111 fresh work",
            "stash@{1}: WIP on main: bbb2222 older work",
            "stash@{2}: WIP on main: ccc3333 ancient work",
            "stash@{3}: On main: named-entry",
            "stash@{4}: WIP on main: ddd4444 very old",
        ]
        sys.argv = ["stash_cleanup.py", "--keep", "2", "--dry-run"]
        main()
        mock_drop.assert_not_called()
        output = json.loads(capsys.readouterr().out)
        assert output["dropped"] == 2  # indices 2 and 4 (3 is named, preserved)
        assert output["dry_run"] is True

    @patch("stash_cleanup.drop")
    @patch("stash_cleanup.list_stashes")
    def test_nothing_to_clean_when_below_keep(self, mock_list, mock_drop, capsys):
        mock_list.return_value = [
            "stash@{0}: WIP on main: aaa1111 fresh",
            "stash@{1}: WIP on main: bbb2222 also fresh",
        ]
        sys.argv = ["stash_cleanup.py", "--keep", "3"]
        main()
        mock_drop.assert_not_called()
        output = json.loads(capsys.readouterr().out)
        assert output["dropped"] == 0
        assert output["kept"] == 2

    @patch("stash_cleanup.drop")
    @patch("stash_cleanup.list_stashes")
    def test_named_entries_preserved(self, mock_list, mock_drop, capsys):
        mock_list.return_value = [
            "stash@{0}: WIP on main: aaa1111 keep this",
            "stash@{1}: WIP on main: bbb2222 keep this too",
            "stash@{2}: On main: user-named-stash",
            "stash@{3}: On main: another-named",
        ]
        sys.argv = ["stash_cleanup.py", "--keep", "2"]
        main()
        mock_drop.assert_not_called()  # all entries beyond keep are named
        output = json.loads(capsys.readouterr().out)
        assert output["dropped"] == 0

    @patch("stash_cleanup.drop")
    @patch("stash_cleanup.list_stashes")
    def test_drops_oldest_first(self, mock_list, mock_drop, capsys):
        mock_list.return_value = [
            "stash@{0}: WIP on main: aaa1111 fresh",
            "stash@{1}: WIP on main: bbb2222 keep",
            "stash@{2}: WIP on main: ccc3333 old",
            "stash@{3}: WIP on main: ddd4444 older",
            "stash@{4}: autostash",
        ]
        mock_drop.return_value = MagicMock(returncode=0)
        sys.argv = ["stash_cleanup.py", "--keep", "2"]
        main()
        # Should drop indices 2, 3, 4 in reverse order
        assert mock_drop.call_count == 3
        calls = [c.args[0] for c in mock_drop.call_args_list]
        assert calls == ["stash@{4}", "stash@{3}", "stash@{2}"]
        output = json.loads(capsys.readouterr().out)
        assert output["dropped"] == 3

    @patch("stash_cleanup.drop")
    @patch("stash_cleanup.list_stashes")
    def test_empty_stash(self, mock_list, mock_drop, capsys):
        mock_list.return_value = []
        sys.argv = ["stash_cleanup.py"]
        main()
        mock_drop.assert_not_called()
        output = json.loads(capsys.readouterr().out)
        assert output["total"] == 0
        assert output["dropped"] == 0
