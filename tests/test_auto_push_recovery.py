#!/usr/bin/env python3
"""Tests for iamai.auto_push_recovery — push divergence recovery orchestration."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.auto_push_recovery import (
    _stash_dirty,
    _pop_stash,
    _rebase_on_remote,
    _push,
    _has_stash,
    recover,
    needs_recovery,
)


def _mock_run(returncode: int, output: str):
    """Create a mock for _run that returns (returncode, output)."""
    return (returncode, output)


class TestStashDirty:
    """Tests for _stash_dirty."""

    @patch("iamai.auto_push_recovery._run")
    def test_stash_created(self, mock_run):
        mock_run.return_value = (0, "Saved working directory and index state WIP on main")
        assert _stash_dirty(Path("/fake")) is True
        mock_run.assert_called_once_with(Path("/fake"), "stash", "push", "-m", "auto_push_recovery")

    @patch("iamai.auto_push_recovery._run")
    def test_nothing_to_stash(self, mock_run):
        mock_run.return_value = (0, "No local changes to save")
        assert _stash_dirty(Path("/fake")) is False

    @patch("iamai.auto_push_recovery._run")
    def test_stash_failure(self, mock_run):
        mock_run.return_value = (1, "fatal: error")
        assert _stash_dirty(Path("/fake")) is False


class TestPopStash:
    """Tests for _pop_stash."""

    @patch("iamai.auto_push_recovery._run")
    def test_clean_pop(self, mock_run):
        mock_run.return_value = (0, "On branch main\nDropped refs/stash@{0}")
        ok, detail = _pop_stash(Path("/fake"))
        assert ok is True
        assert "cleanly" in detail

    @patch("iamai.auto_push_recovery._run")
    def test_conflict_pop(self, mock_run):
        mock_run.return_value = (1, "CONFLICT (content): Merge conflict in data/strokes.jsonl")
        ok, detail = _pop_stash(Path("/fake"))
        assert ok is False
        assert "conflict" in detail.lower()

    @patch("iamai.auto_push_recovery._run")
    def test_generic_failure(self, mock_run):
        mock_run.return_value = (1, "fatal: no stash entries found")
        ok, detail = _pop_stash(Path("/fake"))
        assert ok is False
        assert "failed" in detail


class TestRebaseOnRemote:
    """Tests for _rebase_on_remote."""

    @patch("iamai.auto_push_recovery._run")
    def test_clean_rebase(self, mock_run):
        mock_run.side_effect = [
            (0, ""),  # fetch
            (0, "Successfully rebased and updated refs/heads/main"),  # rebase
        ]
        ok, detail = _rebase_on_remote(Path("/fake"), "origin", "main")
        assert ok is True
        assert mock_run.call_count == 2

    @patch("iamai.auto_push_recovery._run")
    def test_fetch_failure(self, mock_run):
        mock_run.return_value = (1, "fatal: Could not read from remote")
        ok, detail = _rebase_on_remote(Path("/fake"), "origin", "main")
        assert ok is False
        assert "fetch failed" in detail

    @patch("iamai.auto_push_recovery._run")
    def test_rebase_conflict_aborts(self, mock_run):
        mock_run.side_effect = [
            (0, ""),  # fetch
            (1, "CONFLICT (content): Merge conflict in notes/foo.md"),  # rebase
            (0, ""),  # rebase --abort
        ]
        ok, detail = _rebase_on_remote(Path("/fake"), "origin", "main")
        assert ok is False
        assert "conflicted" in detail.lower()
        assert mock_run.call_count == 3  # fetch + rebase + abort


class TestPush:
    """Tests for _push."""

    @patch("iamai.auto_push_recovery._run")
    def test_push_success(self, mock_run):
        mock_run.return_value = (0, "To github.com:...\n   abc..def  HEAD -> main")
        ok, detail = _push(Path("/fake"), "origin", "main")
        assert ok is True

    @patch("iamai.auto_push_recovery._run")
    def test_push_rejected(self, mock_run):
        mock_run.return_value = (1, "! [rejected]  HEAD -> main (fetch first)")
        ok, detail = _push(Path("/fake"), "origin", "main")
        assert ok is False
        assert "rejected" in detail


class TestHasStash:
    """Tests for _has_stash."""

    @patch("iamai.auto_push_recovery._run")
    def test_stash_exists(self, mock_run):
        mock_run.return_value = (0, "stash@{0}: WIP on main: abc1234 message")
        assert _has_stash(Path("/fake")) is True

    @patch("iamai.auto_push_recovery._run")
    def test_no_stash(self, mock_run):
        mock_run.return_value = (0, "")
        assert _has_stash(Path("/fake")) is False


class TestRecover:
    """Tests for the full recover() orchestration."""

    @patch("iamai.auto_push_recovery._push")
    @patch("iamai.auto_push_recovery._pop_stash")
    @patch("iamai.auto_push_recovery._rebase_on_remote")
    @patch("iamai.auto_push_recovery._stash_dirty")
    def test_happy_path_no_dirty(self, mock_stash, mock_rebase, mock_pop, mock_push):
        mock_stash.return_value = False
        mock_rebase.return_value = (True, "rebased cleanly")
        mock_push.return_value = (True, "pushed")

        result = recover(Path("/fake"))
        assert result["ok"] is True
        assert result["stashed"] is False
        assert result["rebased"] is True
        assert result["pushed"] is True
        mock_pop.assert_not_called()

    @patch("iamai.auto_push_recovery._push")
    @patch("iamai.auto_push_recovery._pop_stash")
    @patch("iamai.auto_push_recovery._rebase_on_remote")
    @patch("iamai.auto_push_recovery._stash_dirty")
    def test_happy_path_with_stash(self, mock_stash, mock_rebase, mock_pop, mock_push):
        mock_stash.return_value = True
        mock_rebase.return_value = (True, "rebased cleanly")
        mock_pop.return_value = (True, "stash popped cleanly")
        mock_push.return_value = (True, "pushed")

        result = recover(Path("/fake"))
        assert result["ok"] is True
        assert result["stashed"] is True
        assert result["pushed"] is True
        assert "stashed+popped" in result["detail"]

    @patch("iamai.auto_push_recovery._pop_stash")
    @patch("iamai.auto_push_recovery._rebase_on_remote")
    @patch("iamai.auto_push_recovery._stash_dirty")
    def test_rebase_failure_pops_stash(self, mock_stash, mock_rebase, mock_pop):
        mock_stash.return_value = True
        mock_rebase.return_value = (False, "rebase conflicted (aborted)")
        mock_pop.return_value = (True, "stash popped")

        result = recover(Path("/fake"))
        assert result["ok"] is False
        assert result["rebased"] is False
        mock_pop.assert_called_once()

    @patch("iamai.auto_push_recovery._push")
    @patch("iamai.auto_push_recovery._pop_stash")
    @patch("iamai.auto_push_recovery._rebase_on_remote")
    @patch("iamai.auto_push_recovery._stash_dirty")
    def test_push_failure_after_rebase(self, mock_stash, mock_rebase, mock_pop, mock_push):
        mock_stash.return_value = False
        mock_rebase.return_value = (True, "rebased cleanly")
        mock_push.return_value = (False, "still rejected")

        result = recover(Path("/fake"))
        assert result["ok"] is False
        assert result["rebased"] is True
        assert result["pushed"] is False

    @patch("iamai.auto_push_recovery._push")
    @patch("iamai.auto_push_recovery._pop_stash")
    @patch("iamai.auto_push_recovery._rebase_on_remote")
    @patch("iamai.auto_push_recovery._stash_dirty")
    def test_stash_pop_conflict_still_tries_push(self, mock_stash, mock_rebase, mock_pop, mock_push):
        mock_stash.return_value = True
        mock_rebase.return_value = (True, "rebased cleanly")
        mock_pop.return_value = (False, "stash pop conflicted")
        mock_push.return_value = (True, "pushed")

        result = recover(Path("/fake"))
        assert result["pushed"] is True
        mock_push.assert_called_once()

    @patch("iamai.auto_push_recovery._push")
    @patch("iamai.auto_push_recovery._rebase_on_remote")
    @patch("iamai.auto_push_recovery._stash_dirty")
    def test_steps_recorded(self, mock_stash, mock_rebase, mock_push):
        mock_stash.return_value = False
        mock_rebase.return_value = (True, "ok")
        mock_push.return_value = (True, "pushed")

        result = recover(Path("/fake"))
        assert len(result["steps"]) >= 3  # stash, rebase, push (at minimum)


class TestNeedsRecovery:
    """Tests for needs_recovery."""

    @patch("iamai.auto_push_recovery._run")
    def test_behind_remote(self, mock_run):
        mock_run.side_effect = [
            (0, "1"),   # ahead count
            (0, "3"),   # behind count
        ]
        assert needs_recovery(Path("/fake")) is True

    @patch("iamai.auto_push_recovery._run")
    def test_up_to_date(self, mock_run):
        mock_run.side_effect = [
            (0, "0"),   # ahead
            (0, "0"),   # behind
        ]
        assert needs_recovery(Path("/fake")) is False

    @patch("iamai.auto_push_recovery._run")
    def test_ahead_only(self, mock_run):
        mock_run.side_effect = [
            (0, "5"),   # ahead
            (0, "0"),   # behind
        ]
        assert needs_recovery(Path("/fake")) is False

    @patch("iamai.auto_push_recovery._run")
    def test_command_failure(self, mock_run):
        mock_run.return_value = (1, "fatal: bad revision")
        assert needs_recovery(Path("/fake")) is False
