#!/usr/bin/env python3
"""Tests for iamai.divergence_preempt — pre-push divergence check and auto-recovery."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.divergence_preempt import (
    _run,
    _do_recover,
    preempt_push,
)


# ---------------------------------------------------------------------------
# _run helper
# ---------------------------------------------------------------------------


class TestRunHelper:
    """Tests for the _run subprocess wrapper."""

    @patch("iamai.divergence_preempt._git")
    def test_success(self, mock_git):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "output line"
        proc.stderr = ""
        mock_git.return_value = proc
        rc, out = _run(Path("/fake"), "status")
        assert rc == 0
        assert "output line" in out

    @patch("iamai.divergence_preempt._git")
    def test_failure(self, mock_git):
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = ""
        proc.stderr = "fatal: something"
        mock_git.return_value = proc
        rc, out = _run(Path("/fake"), "push")
        assert rc == 1
        assert "fatal" in out

    @patch("iamai.divergence_preempt._git")
    def test_timeout(self, mock_git):
        import subprocess
        mock_git.side_effect = subprocess.TimeoutExpired("git", 30)
        rc, out = _run(Path("/fake"), "fetch", timeout=30)
        assert rc == 124
        assert "timed out" in out


# ---------------------------------------------------------------------------
# preempt_push — main entry point
# ---------------------------------------------------------------------------


class TestPreemptPush:
    """Tests for preempt_push."""

    def test_not_a_repo(self, tmp_path):
        result = preempt_push(str(tmp_path))
        assert result["ok"] is False
        assert result["action"] == "failed"
        assert "not a git repository" in result["detail"]

    @patch("iamai.divergence_preempt.divergence")
    @patch("iamai.divergence_preempt._run")
    def test_nothing_to_push(self, mock_run, mock_div):
        """ahead=0, behind=0 → skip."""
        mock_run.return_value = (0, "")
        mock_div.return_value = {"ahead": 0, "behind": 0, "dirty": False}

        # need a .git dir
        fake = Path("/fake")
        with patch("iamai.divergence_preempt.Path") as mock_path:
            mock_p = MagicMock()
            mock_p.__truediv__ = MagicMock(return_value=MagicMock(is_dir=MagicMock(return_value=True)))
            mock_path.return_value = mock_p
            result = preempt_push("/fake")

        assert result["ok"] is True
        assert result["action"] == "skipped"
        assert "nothing to push" in result["detail"]

    @patch("iamai.divergence_preempt.divergence")
    @patch("iamai.divergence_preempt._run")
    def test_clear_to_push(self, mock_run, mock_div):
        """ahead=3, behind=0 → clear, safe to push."""
        mock_run.return_value = (0, "")
        mock_div.return_value = {"ahead": 3, "behind": 0, "dirty": False}

        with patch("iamai.divergence_preempt.Path") as mock_path:
            mock_p = MagicMock()
            mock_p.__truediv__ = MagicMock(return_value=MagicMock(is_dir=MagicMock(return_value=True)))
            mock_path.return_value = mock_p
            result = preempt_push("/fake")

        assert result["ok"] is True
        assert result["action"] == "clear"
        assert result["ahead"] == 3
        assert "no divergence" in result["detail"]

    @patch("iamai.divergence_preempt._do_recover")
    @patch("iamai.divergence_preempt.divergence")
    @patch("iamai.divergence_preempt._run")
    def test_divergence_triggers_recovery(self, mock_run, mock_div, mock_recover):
        """ahead=2, behind=1 → triggers _do_recover."""
        mock_run.return_value = (0, "")
        mock_div.return_value = {"ahead": 2, "behind": 1, "dirty": True}
        mock_recover.return_value = {
            "ok": True,
            "action": "recovered",
            "ahead": 2,
            "behind": 1,
            "dirty": True,
            "detail": "recovered from 1-commit divergence via rebase",
        }

        with patch("iamai.divergence_preempt.Path") as mock_path:
            mock_p = MagicMock()
            mock_p.__truediv__ = MagicMock(return_value=MagicMock(is_dir=MagicMock(return_value=True)))
            mock_path.return_value = mock_p
            result = preempt_push("/fake")

        assert result["ok"] is True
        assert result["action"] == "recovered"
        mock_recover.assert_called_once()

    @patch("iamai.divergence_preempt.divergence")
    @patch("iamai.divergence_preempt._run")
    def test_divergence_no_auto_recover(self, mock_run, mock_div):
        """ahead=2, behind=1, auto_recover=False → report only."""
        mock_run.return_value = (0, "")
        mock_div.return_value = {"ahead": 2, "behind": 1, "dirty": False}

        with patch("iamai.divergence_preempt.Path") as mock_path:
            mock_p = MagicMock()
            mock_p.__truediv__ = MagicMock(return_value=MagicMock(is_dir=MagicMock(return_value=True)))
            mock_path.return_value = mock_p
            result = preempt_push("/fake", auto_recover=False)

        assert result["ok"] is False
        assert result["action"] == "skipped"
        assert "auto_recover=False" in result["detail"]

    @patch("iamai.divergence_preempt.divergence")
    @patch("iamai.divergence_preempt._run")
    def test_fetch_failure_non_fatal(self, mock_run, mock_div):
        """Fetch failure should not prevent divergence check."""
        mock_run.return_value = (128, "fatal: Could not resolve host")
        mock_div.return_value = {"ahead": 5, "behind": 0, "dirty": False}

        with patch("iamai.divergence_preempt.Path") as mock_path:
            mock_p = MagicMock()
            mock_p.__truediv__ = MagicMock(return_value=MagicMock(is_dir=MagicMock(return_value=True)))
            mock_path.return_value = mock_p
            result = preempt_push("/fake")

        assert result["ok"] is True
        assert result["action"] == "clear"


# ---------------------------------------------------------------------------
# _do_recover — the stash/rebase/pop cycle
# ---------------------------------------------------------------------------


class TestDoRecover:
    """Tests for _do_recover."""

    @patch("iamai.divergence_preempt.divergence")
    @patch("iamai.divergence_preempt._run")
    def test_clean_rebase_dirty(self, mock_run, mock_div):
        """Dirty tree: stash → rebase → pop → clean."""
        # stash push, rebase, stash pop all succeed; post-check behind=0
        mock_run.side_effect = [
            (0, "Saved working directory"),   # stash push
            (0, "Successfully rebased"),       # rebase
            (0, "Dropped refs/stash@{0}"),     # stash pop
        ]
        mock_div.return_value = {"ahead": 3, "behind": 0, "dirty": False}

        result = _do_recover(Path("/fake"), "main", "origin", 3, 2, dirty=True)
        assert result["ok"] is True
        assert result["action"] == "recovered"
        assert "recovered from 2-commit" in result["detail"]
        assert mock_run.call_count == 3

    @patch("iamai.divergence_preempt.divergence")
    @patch("iamai.divergence_preempt._run")
    def test_clean_rebase_clean_tree(self, mock_run, mock_div):
        """Clean tree: rebase only (no stash/pop)."""
        mock_run.return_value = (0, "Successfully rebased")
        mock_div.return_value = {"ahead": 2, "behind": 0, "dirty": False}

        result = _do_recover(Path("/fake"), "main", "origin", 2, 1, dirty=False)
        assert result["ok"] is True
        assert result["action"] == "recovered"
        assert mock_run.call_count == 1  # only rebase, no stash

    @patch("iamai.divergence_preempt._run")
    def test_stash_failure(self, mock_run):
        """Stash fails → abort immediately."""
        mock_run.return_value = (1, "fatal: stash failed")

        result = _do_recover(Path("/fake"), "main", "origin", 2, 1, dirty=True)
        assert result["ok"] is False
        assert "stash failed" in result["detail"]

    @patch("iamai.divergence_preempt._run")
    def test_rebase_conflict(self, mock_run):
        """Rebase conflict → abort rebase and pop stash."""
        mock_run.side_effect = [
            (0, "Saved working directory"),          # stash push
            (1, "CONFLICT (content): merge conflict"),  # rebase fails
            (0, ""),                                    # rebase --abort
            (0, "Dropped refs/stash@{0}"),              # stash pop
        ]

        result = _do_recover(Path("/fake"), "main", "origin", 2, 1, dirty=True)
        assert result["ok"] is False
        assert "rebase conflict" in result["detail"]
        assert mock_run.call_count == 4

    @patch("iamai.divergence_preempt.divergence")
    @patch("iamai.divergence_preempt._run")
    def test_stash_pop_conflict_non_fatal(self, mock_run, mock_div):
        """Stash pop conflicts but rebase succeeded → still ok."""
        mock_run.side_effect = [
            (0, "Saved working directory"),   # stash push
            (0, "Successfully rebased"),       # rebase
            (1, "CONFLICT (content): stash pop conflict"),  # stash pop fails
        ]

        result = _do_recover(Path("/fake"), "main", "origin", 3, 1, dirty=True)
        assert result["ok"] is True
        assert "stash pop conflicted" in result["detail"]

    @patch("iamai.divergence_preempt.divergence")
    @patch("iamai.divergence_preempt._run")
    def test_still_behind_after_rebase(self, mock_run, mock_div):
        """Remote advanced during recovery → still behind."""
        mock_run.side_effect = [
            (0, "Successfully rebased"),  # rebase
        ]
        # post-rebase check shows behind > 0
        mock_div.return_value = {"ahead": 3, "behind": 2, "dirty": False}

        result = _do_recover(Path("/fake"), "main", "origin", 3, 2, dirty=False)
        assert result["ok"] is False
        assert "still behind" in result["detail"]

    @patch("iamai.divergence_preempt.divergence")
    @patch("iamai.divergence_preempt._run")
    def test_rebase_clean_no_stash_needed(self, mock_run, mock_div):
        """Clean tree + clean rebase + clean post-check."""
        mock_run.return_value = (0, "Successfully rebased")
        mock_div.return_value = {"ahead": 4, "behind": 0, "dirty": False}

        result = _do_recover(Path("/fake"), "main", "origin", 4, 3, dirty=False)
        assert result["ok"] is True
        assert result["action"] == "recovered"
        # Only one _run call (rebase), no stash operations
        assert mock_run.call_count == 1


# ---------------------------------------------------------------------------
# Integration-style tests (mocked git, real logic flow)
# ---------------------------------------------------------------------------


class TestPreemptPushFlow:
    """End-to-end flow tests with mocked subprocess."""

    @patch("iamai.divergence_preempt.divergence")
    @patch("iamai.divergence_preempt._run")
    def test_full_cycle_dirty_tree(self, mock_run, mock_div):
        """Simulate: divergence detected, dirty tree, successful recovery."""
        # divergence check
        mock_div.side_effect = [
            {"ahead": 3, "behind": 2, "dirty": True},   # initial check
            {"ahead": 5, "behind": 0, "dirty": True},    # post-rebase check
        ]
        # fetch, stash, rebase, stash pop
        mock_run.side_effect = [
            (0, "From github.com:FengPwner/IamAI"),       # fetch
            (0, "Saved working directory"),                # stash push
            (0, "Successfully rebased"),                   # rebase
            (0, "Dropped refs/stash@{0}"),                 # stash pop
        ]

        with patch("iamai.divergence_preempt.Path") as mock_path:
            mock_p = MagicMock()
            mock_p.__truediv__ = MagicMock(return_value=MagicMock(is_dir=MagicMock(return_value=True)))
            mock_path.return_value = mock_p
            result = preempt_push("/fake")

        assert result["ok"] is True
        assert result["action"] == "recovered"
        assert result["behind"] == 2

    @patch("iamai.divergence_preempt.divergence")
    @patch("iamai.divergence_preempt._run")
    def test_idempotent_second_call(self, mock_run, mock_div):
        """Second call after recovery: no divergence → clear."""
        mock_run.return_value = (0, "")
        mock_div.return_value = {"ahead": 5, "behind": 0, "dirty": False}

        with patch("iamai.divergence_preempt.Path") as mock_path:
            mock_p = MagicMock()
            mock_p.__truediv__ = MagicMock(return_value=MagicMock(is_dir=MagicMock(return_value=True)))
            mock_path.return_value = mock_p
            result = preempt_push("/fake")

        assert result["ok"] is True
        assert result["action"] == "clear"
        # No stash/rebase calls — just fetch + divergence check
        assert mock_run.call_count == 1  # only fetch
