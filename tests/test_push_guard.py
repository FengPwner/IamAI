"""tests for push_guard — divergence detection and resolution."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from iamai.push_guard import (
    PushVerdict,
    assess,
    resolve,
    _count_ahead,
    _local_commit_messages,
    CATCHUP_RE,
)


# --- helpers ---

def _init_repo(tmpdir: str) -> str:
    """Create a minimal git repo with one commit."""
    subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", tmpdir, "config", "user.email", "test@test.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", tmpdir, "config", "user.name", "test"],
        capture_output=True, check=True,
    )
    readme = Path(tmpdir) / "README.md"
    readme.write_text("# test\n")
    subprocess.run(["git", "-C", tmpdir, "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", tmpdir, "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    return tmpdir


def _commit(repo: str, msg: str, filename: str = "file.txt", content: str = "x\n"):
    """Create a commit with the given message."""
    f = Path(repo) / filename
    existing = f.read_text() if f.exists() else ""
    f.write_text(existing + content)
    subprocess.run(["git", "-C", repo, "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", repo, "commit", "-m", msg, "--allow-empty"],
        capture_output=True, check=True,
    )


# --- CATCHUP_RE tests ---

class TestCatchupRegex:
    def test_matches_catchup_prefix(self):
        assert CATCHUP_RE.match("catch-up: commit pending changes")

    def test_matches_case_insensitive(self):
        assert CATCHUP_RE.match("Catch-Up: something")
        assert CATCHUP_RE.match("CATCH-UP: something")

    def test_no_match_regular_commit(self):
        assert not CATCHUP_RE.match("guoban: note (stroke 236)")
        assert not CATCHUP_RE.match("caretaker visit 464")

    def test_no_match_empty(self):
        assert not CATCHUP_RE.match("")


# --- PushVerdict tests ---

class TestPushVerdict:
    def test_frozen_dataclass(self):
        v = PushVerdict(strategy="clean", local_ahead=0, remote_ahead=0, reason="ok")
        with pytest.raises(AttributeError):
            v.strategy = "rebase"

    def test_default_not_executed(self):
        v = PushVerdict(strategy="clean", local_ahead=0, remote_ahead=0, reason="ok")
        assert v.executed is False

    def test_executed_flag(self):
        v = PushVerdict(
            strategy="reset", local_ahead=1, remote_ahead=2,
            reason="diverged", executed=True,
        )
        assert v.executed is True


# --- assess tests (mocked git) ---

class TestAssess:
    """Test assess() with mocked subprocess calls."""

    @patch("iamai.push_guard._run")
    @patch("iamai.push_guard._count_ahead")
    def test_clean_sync(self, mock_count, mock_run):
        """When local and remote are in sync, verdict is clean."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_count.return_value = 0

        verdict = assess("/fake/repo")
        assert verdict.strategy == "clean"
        assert verdict.local_ahead == 0
        assert verdict.remote_ahead == 0

    @patch("iamai.push_guard._run")
    @patch("iamai.push_guard._count_ahead")
    @patch("iamai.push_guard._local_commit_messages")
    def test_all_catchup_commits_gives_reset(self, mock_msgs, mock_count, mock_run):
        """When all local commits are catch-ups, prefer reset."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def count_side_effect(repo, from_ref, to_ref):
            if from_ref == "HEAD":
                return 1  # local ahead
            return 2  # remote ahead

        mock_count.side_effect = count_side_effect
        mock_msgs.return_value = ["catch-up: commit pending changes"]

        verdict = assess("/fake/repo")
        assert verdict.strategy == "reset"
        assert verdict.local_ahead == 1
        assert verdict.remote_ahead == 2

    @patch("iamai.push_guard._run")
    @patch("iamai.push_guard._count_ahead")
    @patch("iamai.push_guard._local_commit_messages")
    def test_unique_work_gives_rebase(self, mock_msgs, mock_count, mock_run):
        """When local commits have unique work, prefer rebase."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def count_side_effect(repo, from_ref, to_ref):
            if from_ref == "HEAD":
                return 2
            return 1

        mock_count.side_effect = count_side_effect
        mock_msgs.return_value = [
            "feat: add push_guard module",
            "catch-up: commit pending changes",
        ]

        verdict = assess("/fake/repo")
        assert verdict.strategy == "rebase"
        assert verdict.local_ahead == 2

    @patch("iamai.push_guard._run")
    @patch("iamai.push_guard._count_ahead")
    def test_fast_forward_needed(self, mock_count, mock_run):
        """When only remote is ahead (no local commits), suggest rebase."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def count_side_effect(repo, from_ref, to_ref):
            if from_ref == "HEAD":
                return 0
            return 3

        mock_count.side_effect = count_side_effect

        verdict = assess("/fake/repo")
        assert verdict.strategy == "rebase"
        assert verdict.local_ahead == 0
        assert verdict.remote_ahead == 3

    @patch("iamai.push_guard._run")
    def test_fetch_failure(self, mock_run):
        """When git fetch fails, verdict is conflict."""
        mock_run.return_value = MagicMock(
            returncode=128, stdout="", stderr="fatal: remote not found",
        )

        verdict = assess("/fake/repo")
        assert verdict.strategy == "conflict"
        assert "fetch failed" in verdict.reason


# --- resolve tests (mocked) ---

class TestResolve:
    """Test resolve() with mocked assess and _run."""

    @patch("iamai.push_guard._run")
    @patch("iamai.push_guard.assess")
    def test_clean_returns_immediately(self, mock_assess, mock_run):
        """Clean verdict needs no action."""
        mock_assess.return_value = PushVerdict(
            strategy="clean", local_ahead=0, remote_ahead=0, reason="sync",
        )

        verdict = resolve("/fake/repo")
        assert verdict.strategy == "clean"
        assert not verdict.executed
        # _run should not be called beyond what assess does
        mock_run.assert_not_called()

    @patch("iamai.push_guard._run")
    @patch("iamai.push_guard.assess")
    def test_dry_run_skips_execution(self, mock_assess, mock_run):
        """dry_run=True returns verdict without executing."""
        mock_assess.return_value = PushVerdict(
            strategy="reset", local_ahead=1, remote_ahead=2,
            reason="diverged",
        )

        verdict = resolve("/fake/repo", dry_run=True)
        assert verdict.strategy == "reset"
        assert not verdict.executed

    @patch("iamai.push_guard._run")
    @patch("iamai.push_guard.assess")
    def test_reset_success(self, mock_assess, mock_run):
        """Reset strategy stashes, resets, and pops."""
        mock_assess.return_value = PushVerdict(
            strategy="reset", local_ahead=1, remote_ahead=2,
            reason="catch-up divergence",
        )
        # Simulate: stash succeeded with content, reset succeeded, pop succeeded
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Saved working directory"),  # stash
            MagicMock(returncode=0, stdout="", stderr=""),               # reset
            MagicMock(returncode=0, stdout="", stderr=""),               # pop
        ]

        verdict = resolve("/fake/repo")
        assert verdict.strategy == "reset"
        assert verdict.executed is True

    @patch("iamai.push_guard._run")
    @patch("iamai.push_guard.assess")
    def test_reset_failure_returns_conflict(self, mock_assess, mock_run):
        """When reset --hard fails, verdict becomes conflict."""
        mock_assess.return_value = PushVerdict(
            strategy="reset", local_ahead=1, remote_ahead=2,
            reason="diverged",
        )
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Saved"),                      # stash
            MagicMock(returncode=1, stdout="", stderr="fatal: cannot"),   # reset fails
        ]

        verdict = resolve("/fake/repo")
        assert verdict.strategy == "conflict"
        assert "reset failed" in verdict.reason

    @patch("iamai.push_guard._run")
    @patch("iamai.push_guard.assess")
    def test_rebase_success(self, mock_assess, mock_run):
        """Rebase strategy uses -X theirs."""
        mock_assess.return_value = PushVerdict(
            strategy="rebase", local_ahead=2, remote_ahead=1,
            reason="unique work divergence",
        )
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        verdict = resolve("/fake/repo")
        assert verdict.strategy == "rebase"
        assert verdict.executed is True

    @patch("iamai.push_guard._run")
    @patch("iamai.push_guard.assess")
    def test_rebase_failure_aborts(self, mock_assess, mock_run):
        """When rebase fails, it's aborted and verdict is conflict."""
        mock_assess.return_value = PushVerdict(
            strategy="rebase", local_ahead=2, remote_ahead=1,
            reason="diverged",
        )
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="CONFLICT in foo.md"),  # rebase fails
            MagicMock(returncode=0, stdout="", stderr=""),                     # abort
        ]

        verdict = resolve("/fake/repo")
        assert verdict.strategy == "conflict"
        assert "rebase failed" in verdict.reason

    @patch("iamai.push_guard._run")
    @patch("iamai.push_guard.assess")
    def test_no_stash_pop_when_nothing_saved(self, mock_assess, mock_run):
        """When stash says 'No local changes', skip pop."""
        mock_assess.return_value = PushVerdict(
            strategy="reset", local_ahead=1, remote_ahead=2,
            reason="diverged",
        )
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="No local changes to save"),  # stash
            MagicMock(returncode=0, stdout="", stderr=""),                # reset
        ]

        verdict = resolve("/fake/repo")
        assert verdict.strategy == "reset"
        assert verdict.executed is True
        # Only 2 calls: stash + reset, no pop
        assert mock_run.call_count == 2


# --- integration test (real git) ---

class TestIntegration:
    """Integration tests using a real temporary git repo."""

    def test_assess_clean_repo(self, tmp_path):
        """A fresh repo with no remote should report conflict on fetch."""
        repo = _init_repo(str(tmp_path / "testrepo"))
        # No remote configured — fetch will fail
        verdict = assess(repo, remote="origin")
        assert verdict.strategy == "conflict"
        assert "fetch failed" in verdict.reason

    def test_count_ahead_same_commit(self, tmp_path):
        """When refs point to the same commit, count is 0."""
        repo = _init_repo(str(tmp_path / "testrepo"))
        count = _count_ahead(repo, "HEAD", "HEAD")
        assert count == 0

    def test_local_commit_messages(self, tmp_path):
        """Can read commit messages from a real repo."""
        repo = _init_repo(str(tmp_path / "testrepo"))
        _commit(repo, "first: add feature", "a.txt", "a\n")
        _commit(repo, "catch-up: batch commit", "b.txt", "b\n")

        msgs = _local_commit_messages(repo, "HEAD", "HEAD~2")
        assert len(msgs) == 2
        assert "catch-up" in msgs[0].lower() or "catch-up" in msgs[1].lower()
