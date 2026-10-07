"""Tests for pre-push sync integration in commit_batch.py.

Visit 65 added tools/pre_push_sync.py as a standalone utility and noted that
the next step was wiring it into commit_batch.py's hot path. Visit 66 did
the wiring. These tests verify the integration: that sync is called before
push, that sync results are logged appropriately, and that sync failures
do not block the fallback push_with_rebase path.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from pre_push_sync import SyncResult


def _make_state():
    """Minimal state stub for run_once."""
    state = MagicMock()
    state.last_commit = None
    state.history = []
    return state


def _git_with_pending():
    """Return a git mock that simulates pending changes (diff --cached --quiet → 1)."""
    def side_effect(*args, **kwargs):
        if args and "diff" in args[0]:
            return (1, "")  # has pending changes
        return (0, "")
    return side_effect


class TestSyncIntegration:
    """Verify the sync-before-push wiring in run_once."""

    def test_sync_called_before_push(self):
        """sync() must be invoked with the correct repo, remote and branch."""
        from tools import commit_batch as cb

        state = _make_state()
        with patch.object(cb, "guards", return_value=True), \
             patch.object(cb, "gate", return_value=(True, "42 passed")), \
             patch.object(cb, "git", side_effect=_git_with_pending()), \
             patch.object(cb, "writer_alive", return_value=True), \
             patch.object(cb, "batch"), \
             patch.object(cb, "heartbeat"), \
             patch.object(cb, "PAUSE", MagicMock()), \
             patch.object(cb, "pre_push_sync") as mock_sync_mod, \
             patch.object(cb, "push") as mock_push:
            mock_sync_mod.sync.return_value = SyncResult(
                diverged=False, stashed=False, merged=False,
                stash_popped=False, ready=True,
                message="no divergence — ready to push",
            )
            mock_push.push_with_rebase.return_value = {
                "ok": True, "strategy": "push", "detail": "pushed",
            }
            cb.run_once(state, 600)
            mock_sync_mod.sync.assert_called_once_with(
                cb.REPO, remote="origin", branch="main"
            )

    def test_sync_merged_then_push_succeeds(self):
        """When sync resolves divergence, push should still be called and succeed."""
        from tools import commit_batch as cb

        state = _make_state()
        with patch.object(cb, "guards", return_value=True), \
             patch.object(cb, "gate", return_value=(True, "42 passed")), \
             patch.object(cb, "git", side_effect=_git_with_pending()), \
             patch.object(cb, "writer_alive", return_value=True), \
             patch.object(cb, "batch"), \
             patch.object(cb, "heartbeat"), \
             patch.object(cb, "PAUSE", MagicMock()), \
             patch.object(cb, "pre_push_sync") as mock_sync_mod, \
             patch.object(cb, "push") as mock_push:
            mock_sync_mod.sync.return_value = SyncResult(
                diverged=True, stashed=False, merged=True,
                stash_popped=False, ready=True,
                message="synced — ready to push",
            )
            mock_push.push_with_rebase.return_value = {
                "ok": True, "strategy": "push", "detail": "pushed",
            }
            result = cb.run_once(state, 600)
            assert result == 0
            mock_push.push_with_rebase.assert_called_once()

    def test_sync_failure_does_not_block_push(self):
        """If sync fails, push_with_rebase must still be attempted (original behavior)."""
        from tools import commit_batch as cb

        state = _make_state()
        with patch.object(cb, "guards", return_value=True), \
             patch.object(cb, "gate", return_value=(True, "42 passed")), \
             patch.object(cb, "git", side_effect=_git_with_pending()), \
             patch.object(cb, "writer_alive", return_value=True), \
             patch.object(cb, "batch"), \
             patch.object(cb, "heartbeat"), \
             patch.object(cb, "PAUSE", MagicMock()), \
             patch.object(cb, "pre_push_sync") as mock_sync_mod, \
             patch.object(cb, "push") as mock_push:
            mock_sync_mod.sync.return_value = SyncResult(
                diverged=True, stashed=False, merged=False,
                stash_popped=False, ready=False,
                message="fetch failed: could not resolve host",
            )
            mock_push.push_with_rebase.return_value = {
                "ok": True, "strategy": "rebase", "detail": "rebased and pushed",
            }
            result = cb.run_once(state, 600)
            assert result == 0
            mock_push.push_with_rebase.assert_called_once()

    def test_sync_exception_does_not_crash(self):
        """If sync raises, run_once must catch it and fall through to push."""
        from tools import commit_batch as cb

        state = _make_state()
        with patch.object(cb, "guards", return_value=True), \
             patch.object(cb, "gate", return_value=(True, "42 passed")), \
             patch.object(cb, "git", side_effect=_git_with_pending()), \
             patch.object(cb, "writer_alive", return_value=True), \
             patch.object(cb, "batch"), \
             patch.object(cb, "heartbeat"), \
             patch.object(cb, "PAUSE", MagicMock()), \
             patch.object(cb, "pre_push_sync") as mock_sync_mod, \
             patch.object(cb, "push") as mock_push:
            mock_sync_mod.sync.side_effect = RuntimeError("network timeout")
            mock_push.push_with_rebase.return_value = {
                "ok": True, "strategy": "push", "detail": "pushed",
            }
            result = cb.run_once(state, 600)
            assert result == 0
            mock_push.push_with_rebase.assert_called_once()

    def test_sync_no_divergence_push_succeeds(self):
        """Happy path: no divergence, push goes through cleanly."""
        from tools import commit_batch as cb

        state = _make_state()
        with patch.object(cb, "guards", return_value=True), \
             patch.object(cb, "gate", return_value=(True, "42 passed")), \
             patch.object(cb, "git", side_effect=_git_with_pending()), \
             patch.object(cb, "writer_alive", return_value=True), \
             patch.object(cb, "batch"), \
             patch.object(cb, "heartbeat"), \
             patch.object(cb, "PAUSE", MagicMock()), \
             patch.object(cb, "pre_push_sync") as mock_sync_mod, \
             patch.object(cb, "push") as mock_push:
            mock_sync_mod.sync.return_value = SyncResult(
                diverged=False, stashed=False, merged=False,
                stash_popped=False, ready=True,
                message="no divergence — ready to push",
            )
            mock_push.push_with_rebase.return_value = {
                "ok": True, "strategy": "push", "detail": "pushed",
            }
            result = cb.run_once(state, 600)
            assert result == 0
