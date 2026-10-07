"""Tests for the rebase strategy in pre_push_sync.py.

Visit 66 added sync with merge-only strategy. Visit 67 adds a rebase
strategy option so the sync path can match the push_with_rebase path,
producing linear history instead of merge commits.

These tests verify:
- rebase strategy calls git pull --rebase
- rebase failure triggers rebase --abort and stash pop
- unknown strategy returns a clean error
- default strategy remains "merge" (backward compat)
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from pre_push_sync import sync, SyncResult


def _ok(rc=0, stdout="", stderr=""):
    r = MagicMock()
    r.returncode = rc
    r.stdout = stdout
    r.stderr = stderr
    return r


def _make_run_mock(sequence):
    """Build a run() side_effect that returns preset results in order.

    sequence: list of (returncode, stdout, stderr) tuples, one per run() call.
    If more calls are made than entries, the last entry is repeated.
    """
    idx = [0]

    def side_effect(cmd, cwd=None):
        i = min(idx[0], len(sequence) - 1)
        idx[0] += 1
        rc, out, err = sequence[i]
        return _ok(rc, out, err)

    return side_effect


class TestRebaseStrategy:
    """Verify the rebase strategy path in sync()."""

    @patch("pre_push_sync.run")
    def test_rebase_strategy_calls_pull_rebase(self, mock_run):
        """When strategy='rebase', sync must call git pull --rebase."""
        # Sequence: fetch, rev-parse main, rev-parse origin/main,
        #           merge-base, status --porcelain, pull --rebase
        mock_run.side_effect = _make_run_mock([
            (0, "", ""),          # fetch
            (0, "aaa\n", ""),     # rev-parse main
            (0, "bbb\n", ""),     # rev-parse origin/main
            (0, "ccc\n", ""),     # merge-base (diverged: ccc != aaa)
            (1, "", ""),          # status (clean)
            (0, "", ""),          # pull --rebase
        ])

        repo = Path("/tmp/fake-repo")
        result = sync(repo, strategy="rebase")

        # Verify --rebase was used
        pull_calls = [c for c in mock_run.call_args_list
                      if len(c[0]) > 0 and len(c[0][0]) > 1 and c[0][0][1] == "pull"]
        assert len(pull_calls) == 1
        pull_cmd = pull_calls[0][0][0]
        assert "--rebase" in pull_cmd
        assert "--no-rebase" not in pull_cmd
        assert result.ready is True

    @patch("pre_push_sync.run")
    def test_rebase_failure_aborts_and_restores(self, mock_run):
        """When rebase fails, must call rebase --abort and pop stash."""
        mock_run.side_effect = _make_run_mock([
            (0, "", ""),                          # fetch
            (0, "aaa\n", ""),                     # rev-parse main
            (0, "bbb\n", ""),                     # rev-parse origin/main
            (0, "ccc\n", ""),                     # merge-base (diverged)
            (0, " M file.txt\n", ""),             # status (dirty)
            (0, "", ""),                          # stash
            (1, "", "CONFLICT (content)"),        # pull --rebase FAILS
            (0, "", ""),                          # rebase --abort
            (0, "", ""),                          # stash pop
        ])

        repo = Path("/tmp/fake-repo")
        result = sync(repo, strategy="rebase")

        assert result.ready is False
        assert result.diverged is True
        assert "rebase failed" in result.message
        # Verify rebase --abort was called (not merge --abort)
        abort_calls = [c for c in mock_run.call_args_list
                       if len(c[0]) > 0 and len(c[0][0]) > 2 and c[0][0][-1] == "--abort"]
        assert len(abort_calls) == 1
        assert abort_calls[0][0][0][1] == "rebase"

    @patch("pre_push_sync.run")
    def test_unknown_strategy_rejected(self, mock_run):
        """An invalid strategy must return an error without touching git."""
        repo = Path("/tmp/fake-repo")
        result = sync(repo, strategy="squash")

        assert result.ready is False
        assert "unknown strategy" in result.message
        mock_run.assert_not_called()

    @patch("pre_push_sync.run")
    def test_default_strategy_is_merge(self, mock_run):
        """Calling sync() without strategy must use merge (backward compat)."""
        mock_run.side_effect = _make_run_mock([
            (0, "", ""),          # fetch
            (0, "aaa\n", ""),     # rev-parse main
            (0, "bbb\n", ""),     # rev-parse origin/main
            (0, "ccc\n", ""),     # merge-base (diverged)
            (1, "", ""),          # status (clean)
            (0, "", ""),          # pull --no-rebase
        ])

        repo = Path("/tmp/fake-repo")
        result = sync(repo)  # no strategy arg

        pull_calls = [c for c in mock_run.call_args_list
                      if len(c[0]) > 0 and len(c[0][0]) > 1 and c[0][0][1] == "pull"]
        assert len(pull_calls) == 1
        pull_cmd = pull_calls[0][0][0]
        assert "--no-rebase" in pull_cmd

    @patch("pre_push_sync.run")
    def test_rebase_success_message_includes_strategy(self, mock_run):
        """Successful rebase sync message should mention 'rebase'."""
        mock_run.side_effect = _make_run_mock([
            (0, "", ""),          # fetch
            (0, "aaa\n", ""),     # rev-parse main
            (0, "bbb\n", ""),     # rev-parse origin/main
            (0, "ccc\n", ""),     # merge-base (diverged)
            (1, "", ""),          # status (clean)
            (0, "", ""),          # pull --rebase
        ])

        repo = Path("/tmp/fake-repo")
        result = sync(repo, strategy="rebase")

        assert result.ready is True
        assert "rebase" in result.message

    @patch("pre_push_sync.run")
    def test_rebase_with_dirty_files(self, mock_run):
        """Rebase strategy must stash dirty files, rebase, then pop."""
        mock_run.side_effect = _make_run_mock([
            (0, "", ""),              # fetch
            (0, "aaa\n", ""),         # rev-parse main
            (0, "bbb\n", ""),         # rev-parse origin/main
            (0, "ccc\n", ""),         # merge-base (diverged)
            (0, " M notes/x.md\n", ""),  # status (dirty)
            (0, "", ""),              # stash
            (0, "", ""),              # pull --rebase
            (0, "", ""),              # stash pop
        ])

        repo = Path("/tmp/fake-repo")
        result = sync(repo, strategy="rebase")

        assert result.ready is True
        assert result.stashed is True
        assert result.stash_popped is True
