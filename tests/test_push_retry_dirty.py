"""Test push_with_retry end-to-end with dirty working tree scenarios.

Exercises the full stash → rebase → pop → push cycle that commit_batch.py
will rely on once it switches from push.push_with_rebase to push_retry.
"""

from __future__ import annotations

from unittest.mock import patch, call

from iamai.push_retry import push_with_retry


def _completed(returncode=0, stdout="", stderr=""):
    from subprocess import CompletedProcess
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestDirtyTreeRetry:
    """When the writer leaves uncommitted changes mid-push, the retry must
    stash before rebase and restore after. A failed stash must abort."""

    @patch("iamai.push_retry._push")
    @patch("iamai.push_retry._pull_rebase")
    @patch("iamai.push_retry._stash_pop")
    @patch("iamai.push_retry._stash")
    @patch("iamai.push_retry._is_dirty")
    def test_dirty_rebase_succeeds(
        self, mock_dirty, mock_stash, mock_pop, mock_rebase, mock_push
    ):
        # First push rejected, retry succeeds
        mock_push.side_effect = [(False, "rejected"), (True, "ok")]
        mock_dirty.return_value = True
        mock_stash.return_value = True
        mock_rebase.return_value = (True, "rebased")
        mock_pop.return_value = True

        ok, msg = push_with_retry("/repo", sleep_fn=lambda _: None)

        assert ok is True
        assert "rebase-retry" in msg
        mock_stash.assert_called_once_with("/repo")
        mock_pop.assert_called_once_with("/repo")
        mock_rebase.assert_called_once_with("/repo")

    @patch("iamai.push_retry._push")
    @patch("iamai.push_retry._stash")
    @patch("iamai.push_retry._is_dirty")
    def test_stash_failure_aborts(self, mock_dirty, mock_stash, mock_push):
        """If git stash fails, we must not attempt rebase — the tree is in
        an unknown state and pushing could lose work."""
        mock_push.return_value = (False, "rejected")
        mock_dirty.return_value = True
        mock_stash.return_value = False

        ok, msg = push_with_retry("/repo", sleep_fn=lambda _: None)

        assert ok is False
        assert "stash failed" in msg

    @patch("iamai.push_retry._push")
    @patch("iamai.push_retry._pull_rebase")
    @patch("iamai.push_retry._stash_pop")
    @patch("iamai.push_retry._stash")
    @patch("iamai.push_retry._is_dirty")
    def test_stash_pop_failure_reports_stash_ref(
        self, mock_dirty, mock_stash, mock_pop, mock_rebase, mock_push
    ):
        """If stash pop fails after rebase, the message must tell the caller
        where the stashed changes are so they can recover manually."""
        mock_push.return_value = (False, "rejected")
        mock_dirty.return_value = True
        mock_stash.return_value = True
        mock_rebase.return_value = (True, "rebased")
        mock_pop.return_value = False

        ok, msg = push_with_retry("/repo", sleep_fn=lambda _: None)

        assert ok is False
        assert "stash@{0}" in msg

    @patch("iamai.push_retry._push")
    @patch("iamai.push_retry._pull_rebase")
    @patch("iamai.push_retry._stash_pop")
    @patch("iamai.push_retry._stash")
    @patch("iamai.push_retry._is_dirty")
    def test_clean_tree_skips_stash(
        self, mock_dirty, mock_stash, mock_pop, mock_rebase, mock_push
    ):
        """When the tree is clean, stash/pop should not be called at all."""
        mock_push.side_effect = [(False, "rejected"), (True, "ok")]
        mock_dirty.return_value = False
        mock_rebase.return_value = (True, "rebased")

        ok, msg = push_with_retry("/repo", sleep_fn=lambda _: None)

        assert ok is True
        mock_stash.assert_not_called()
        mock_pop.assert_not_called()

    @patch("iamai.push_retry._push")
    @patch("iamai.push_retry._pull_rebase")
    @patch("iamai.push_retry._stash_pop")
    @patch("iamai.push_retry._stash")
    @patch("iamai.push_retry._is_dirty")
    def test_exhausted_retries(
        self, mock_dirty, mock_stash, mock_pop, mock_rebase, mock_push
    ):
        """After max_retries, give up and report the last error."""
        mock_push.return_value = (False, "rejected")
        mock_dirty.return_value = False
        mock_rebase.return_value = (True, "rebased")

        ok, msg = push_with_retry(
            "/repo", max_retries=2, sleep_fn=lambda _: None
        )

        assert ok is False
        assert "2 retries" in msg
        # rebase called twice (once per retry), push called 3 times (initial + 2 retries)
        assert mock_rebase.call_count == 2
        assert mock_push.call_count == 3
