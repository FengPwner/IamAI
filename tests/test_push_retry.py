"""Tests for iamai.push_retry — push with automatic pull-rebase retry."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from iamai.push_retry import (
    _is_dirty,
    _push,
    _pull_rebase,
    _stash,
    _stash_pop,
    push_with_retry,
)


def _completed(stdout="", stderr="", returncode=0):
    """Helper to build a CompletedProcess-like object."""
    from subprocess import CompletedProcess
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestIsDirty:
    @patch("iamai.push_retry._git")
    def test_clean(self, mock_git):
        mock_git.return_value = _completed(stdout="")
        assert _is_dirty("/repo") is False

    @patch("iamai.push_retry._git")
    def test_dirty(self, mock_git):
        mock_git.return_value = _completed(stdout=" M file.txt\n")
        assert _is_dirty("/repo") is True


class TestStash:
    @patch("iamai.push_retry._git")
    def test_success(self, mock_git):
        mock_git.return_value = _completed()
        assert _stash("/repo") is True

    @patch("iamai.push_retry._git")
    def test_failure(self, mock_git):
        mock_git.return_value = _completed(returncode=1, stderr="error")
        assert _stash("/repo") is False


class TestStashPop:
    @patch("iamai.push_retry._git")
    def test_success(self, mock_git):
        mock_git.return_value = _completed()
        assert _stash_pop("/repo") is True

    @patch("iamai.push_retry._git")
    def test_conflict(self, mock_git):
        mock_git.return_value = _completed(returncode=1, stderr="CONFLICT")
        assert _stash_pop("/repo") is False


class TestPullRebase:
    @patch("iamai.push_retry._git")
    def test_success(self, mock_git):
        mock_git.return_value = _completed(stdout="Successfully rebased")
        ok, msg = _pull_rebase("/repo")
        assert ok is True
        assert "rebase" in msg.lower()

    @patch("iamai.push_retry._git")
    def test_failure(self, mock_git):
        mock_git.return_value = _completed(
            returncode=1, stderr="error: could not apply..."
        )
        ok, msg = _pull_rebase("/repo")
        assert ok is False


class TestPush:
    @patch("iamai.push_retry._git")
    def test_success(self, mock_git):
        mock_git.return_value = _completed(stdout="done")
        ok, msg = _push("/repo")
        assert ok is True

    @patch("iamai.push_retry._git")
    def test_non_fast_forward(self, mock_git):
        mock_git.return_value = _completed(
            returncode=1,
            stderr="! [rejected] main -> main (fetch first)\n"
                     "error: failed to push some refs",
        )
        ok, msg = _push("/repo")
        assert ok is False
        assert "non-fast-forward" in msg

    @patch("iamai.push_retry._git")
    def test_other_failure(self, mock_git):
        mock_git.return_value = _completed(
            returncode=1, stderr="fatal: could not read Username"
        )
        ok, msg = _push("/repo")
        assert ok is False
        assert "Username" in msg


class TestPushWithRetry:
    @patch("iamai.push_retry._push")
    def test_first_attempt_succeeds(self, mock_push):
        mock_push.return_value = (True, "push succeeded")
        ok, msg = push_with_retry("/repo", max_retries=3)
        assert ok is True
        assert mock_push.call_count == 1

    @patch("iamai.push_retry._is_dirty", return_value=False)
    @patch("iamai.push_retry._pull_rebase", return_value=(True, "rebased"))
    @patch("iamai.push_retry._push")
    def test_retry_after_rejection(self, mock_push, mock_rebase, mock_dirty):
        mock_push.side_effect = [
            (False, "non-fast-forward: remote has diverged"),
            (True, "push succeeded"),
        ]
        sleep_fn = MagicMock()
        ok, msg = push_with_retry("/repo", max_retries=3, sleep_fn=sleep_fn)
        assert ok is True
        assert "1 rebase-retry" in msg
        assert sleep_fn.call_count == 0  # succeeded on first retry, no backoff needed

    @patch("iamai.push_retry._is_dirty", return_value=False)
    @patch("iamai.push_retry._pull_rebase", return_value=(True, "rebased"))
    @patch("iamai.push_retry._push")
    def test_all_retries_exhausted(self, mock_push, mock_rebase, mock_dirty):
        mock_push.return_value = (False, "non-fast-forward: remote has diverged")
        sleep_fn = MagicMock()
        ok, msg = push_with_retry("/repo", max_retries=2, sleep_fn=sleep_fn)
        assert ok is False
        assert "2 retries" in msg
        assert mock_push.call_count == 3  # initial + 2 retries

    @patch("iamai.push_retry._stash", return_value=False)
    @patch("iamai.push_retry._is_dirty", return_value=True)
    @patch("iamai.push_retry._push")
    def test_stash_failure_aborts(self, mock_push, mock_dirty, mock_stash):
        mock_push.return_value = (False, "non-fast-forward: remote has diverged")
        sleep_fn = MagicMock()
        ok, msg = push_with_retry("/repo", max_retries=2, sleep_fn=sleep_fn)
        assert ok is False
        assert "stash failed" in msg

    @patch("iamai.push_retry._stash_pop", return_value=True)
    @patch("iamai.push_retry._stash", return_value=True)
    @patch("iamai.push_retry._pull_rebase", return_value=(True, "rebased"))
    @patch("iamai.push_retry._is_dirty", return_value=True)
    @patch("iamai.push_retry._push")
    def test_dirty_tree_stash_restore(
        self, mock_push, mock_dirty, mock_rebase, mock_stash, mock_pop
    ):
        mock_push.side_effect = [
            (False, "non-fast-forward: remote has diverged"),
            (True, "push succeeded"),
        ]
        sleep_fn = MagicMock()
        ok, msg = push_with_retry("/repo", max_retries=2, sleep_fn=sleep_fn)
        assert ok is True
        mock_stash.assert_called_once()
        mock_pop.assert_called_once()

    @patch("iamai.push_retry._is_dirty", return_value=False)
    @patch("iamai.push_retry._pull_rebase", return_value=(False, "CONFLICT"))
    @patch("iamai.push_retry._push")
    def test_rebase_failure_aborts(self, mock_push, mock_rebase, mock_dirty):
        mock_push.return_value = (False, "non-fast-forward: remote has diverged")
        sleep_fn = MagicMock()
        ok, msg = push_with_retry("/repo", max_retries=2, sleep_fn=sleep_fn)
        assert ok is False
        assert "rebase failed" in msg

    @patch("iamai.push_retry._is_dirty", return_value=False)
    @patch("iamai.push_retry._pull_rebase", return_value=(True, "rebased"))
    @patch("iamai.push_retry._push")
    def test_exponential_backoff(self, mock_push, mock_rebase, mock_dirty):
        mock_push.return_value = (False, "non-fast-forward: remote has diverged")
        sleep_fn = MagicMock()
        push_with_retry("/repo", max_retries=3, base_delay=1.0, sleep_fn=sleep_fn)
        # Should sleep with delays: 1.0, 2.0 (not after last attempt)
        assert sleep_fn.call_args_list == [call(1.0), call(2.0)]
