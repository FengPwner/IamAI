"""Tests for iamai.caretaker_push_cycle — the push divergence recovery orchestrator."""

from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from iamai.caretaker_push_cycle import (
    PushCycleResult,
    run_push_cycle,
    _has_unstaged,
    _has_unpushed,
    _is_diverged,
    _pause_writer,
    _resume_writer,
    _git,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_repo(tmp_path):
    """Create a minimal git repo with one commit, return its path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.local"],
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        capture_output=True,
    )
    (repo / "README.md").write_text("# test\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        capture_output=True,
    )
    return str(repo)


@pytest.fixture
def pause_file(tmp_path):
    """Return a path for the pause gate file."""
    return str(tmp_path / "pause-gate")


# ---------------------------------------------------------------------------
# PushCycleResult dataclass
# ---------------------------------------------------------------------------


class TestPushCycleResult:
    def test_default_values(self):
        r = PushCycleResult()
        assert r.success is False
        assert r.steps_taken == []
        assert r.error is None
        assert r.divergence_detected is False
        assert r.stash_used is False
        assert r.commits_pushed == 0

    def test_to_dict(self):
        r = PushCycleResult(
            success=True,
            steps_taken=["fetch", "push"],
            error=None,
            divergence_detected=False,
            stash_used=False,
            commits_pushed=2,
        )
        d = r.to_dict()
        assert d["success"] is True
        assert d["steps_taken"] == ["fetch", "push"]
        assert d["commits_pushed"] == 2
        assert "error" in d

    def test_to_dict_with_error(self):
        r = PushCycleResult(success=False, error="push failed: rejected")
        d = r.to_dict()
        assert d["success"] is False
        assert "rejected" in d["error"]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHasUnstaged:
    def test_clean_tree(self, clean_repo):
        assert _has_unstaged(clean_repo) is False

    def test_modified_file(self, clean_repo):
        (Path(clean_repo) / "README.md").write_text("# modified\n")
        assert _has_unstaged(clean_repo) is True

    def test_untracked_file(self, clean_repo):
        (Path(clean_repo) / "new.txt").write_text("hello\n")
        assert _has_unstaged(clean_repo) is True


class TestHasUnpushed:
    def test_no_remote(self, clean_repo):
        """Without a remote, rev-list fails → returns 0."""
        count = _has_unpushed(clean_repo, "origin", "main")
        assert count == 0  # no origin configured, so git fails → 0

    def test_local_ahead(self, clean_repo, tmp_path):
        """Set up a bare remote, push, then add a local commit."""
        bare = tmp_path / "bare.git"
        subprocess.run(
            ["git", "init", "--bare", str(bare)], capture_output=True
        )
        subprocess.run(
            ["git", "-C", clean_repo, "remote", "add", "origin", str(bare)],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", clean_repo, "push", "-u", "origin", "master"],
            capture_output=True,
        )
        # create a new local commit
        (Path(clean_repo) / "extra.txt").write_text("more\n")
        subprocess.run(["git", "-C", clean_repo, "add", "-A"], capture_output=True)
        subprocess.run(
            ["git", "-C", clean_repo, "commit", "-m", "extra"],
            capture_output=True,
        )
        count = _has_unpushed(clean_repo, "origin", "master")
        assert count == 1


class TestIsDiverged:
    def test_not_diverged_no_remote(self, clean_repo):
        assert _is_diverged(clean_repo, "origin", "main") is False

    def test_diverged(self, clean_repo, tmp_path):
        """Create divergence: local and remote both advance independently."""
        bare = tmp_path / "bare.git"
        subprocess.run(
            ["git", "init", "--bare", str(bare)], capture_output=True
        )
        subprocess.run(
            ["git", "-C", clean_repo, "remote", "add", "origin", str(bare)],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", clean_repo, "push", "-u", "origin", "master"],
            capture_output=True,
        )

        # clone to a second repo, make a commit there, push
        clone = tmp_path / "clone"
        subprocess.run(
            ["git", "clone", str(bare), str(clone)], capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(clone), "config", "user.email", "c@c.local"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(clone), "config", "user.name", "Clone"],
            capture_output=True,
        )
        (clone / "remote_change.txt").write_text("from clone\n")
        subprocess.run(
            ["git", "-C", str(clone), "add", "-A"], capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(clone), "commit", "-m", "remote work"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(clone), "push"], capture_output=True
        )

        # now make a local commit in the original repo
        (Path(clean_repo) / "local_change.txt").write_text("from local\n")
        subprocess.run(
            ["git", "-C", clean_repo, "add", "-A"], capture_output=True
        )
        subprocess.run(
            ["git", "-C", clean_repo, "commit", "-m", "local work"],
            capture_output=True,
        )

        # fetch to learn about remote
        subprocess.run(
            ["git", "-C", clean_repo, "fetch", "origin"], capture_output=True
        )

        assert _is_diverged(clean_repo, "origin", "master") is True


# ---------------------------------------------------------------------------
# Pause / resume writer
# ---------------------------------------------------------------------------


class TestPauseResume:
    def test_pause_creates_file(self, pause_file):
        _pause_writer(pause_file)
        assert Path(pause_file).exists()
        # cleanup
        _resume_writer(pause_file)

    def test_resume_removes_file(self, pause_file):
        Path(pause_file).touch()
        _resume_writer(pause_file)
        assert not Path(pause_file).exists()

    def test_resume_missing_file_no_error(self, pause_file):
        # should not raise even if file doesn't exist
        _resume_writer(pause_file)


# ---------------------------------------------------------------------------
# run_push_cycle — dry_run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_returns_plan(self, clean_repo, pause_file):
        result = run_push_cycle(
            repo_path=clean_repo,
            remote="origin",
            branch="main",
            pause_file=pause_file,
            dry_run=True,
        )
        assert result.success is True
        assert "fetch" in result.steps_taken
        assert "push" in result.steps_taken
        assert "resume_writer" in result.steps_taken
        # dry run should NOT create the pause file
        assert not Path(pause_file).exists()

    def test_dry_run_with_commit_message(self, clean_repo, pause_file):
        result = run_push_cycle(
            repo_path=clean_repo,
            remote="origin",
            branch="main",
            pause_file=pause_file,
            dry_run=True,
            commit_message="test commit",
        )
        assert "commit_pending" in result.steps_taken


# ---------------------------------------------------------------------------
# run_push_cycle — integration (uses local bare repo as remote)
# ---------------------------------------------------------------------------


class TestIntegration:
    @pytest.fixture
    def paired_repos(self, tmp_path):
        """Create a local repo + bare remote, push initial commit."""
        bare = tmp_path / "bare.git"
        subprocess.run(
            ["git", "init", "--bare", str(bare)], capture_output=True
        )

        repo = tmp_path / "work"
        repo.mkdir()
        subprocess.run(
            ["git", "init", str(repo)], capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "t@t.local"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test"],
            capture_output=True,
        )
        (repo / "README.md").write_text("# paired\n")
        subprocess.run(
            ["git", "-C", str(repo), "add", "-A"], capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "init"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", str(bare)],
            capture_output=True,
        )
        # detect default branch name
        r = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True,
        )
        branch = r.stdout.strip()
        subprocess.run(
            ["git", "-C", str(repo), "push", "-u", "origin", branch],
            capture_output=True,
        )
        return {"repo": str(repo), "bare": str(bare), "branch": branch}

    def test_push_ahead_clean(self, paired_repos, pause_file):
        """Local adds a commit, remote unchanged → push should succeed."""
        repo = paired_repos["repo"]
        branch = paired_repos["branch"]

        (Path(repo) / "new.txt").write_text("new content\n")
        subprocess.run(["git", "-C", repo, "add", "-A"], capture_output=True)
        subprocess.run(
            ["git", "-C", repo, "commit", "-m", "new content"],
            capture_output=True,
        )

        result = run_push_cycle(
            repo_path=repo,
            remote="origin",
            branch=branch,
            pause_file=pause_file,
        )
        assert result.success is True
        assert result.commits_pushed >= 1
        # pause file must be cleaned up
        assert not Path(pause_file).exists()

    def test_push_with_stash_needed(self, paired_repos, pause_file):
        """Local has unstaged changes + new commit → stash then push."""
        repo = paired_repos["repo"]
        branch = paired_repos["branch"]

        # commit something
        (Path(repo) / "feature.txt").write_text("feature\n")
        subprocess.run(["git", "-C", repo, "add", "-A"], capture_output=True)
        subprocess.run(
            ["git", "-C", repo, "commit", "-m", "feature"],
            capture_output=True,
        )
        # also leave an unstaged change
        (Path(repo) / "README.md").write_text("# modified during push\n")

        result = run_push_cycle(
            repo_path=repo,
            remote="origin",
            branch=branch,
            pause_file=pause_file,
        )
        assert result.success is True
        assert result.stash_used is True
        # the unstaged change should be restored
        assert "modified during push" in (Path(repo) / "README.md").read_text()

    def test_writer_resumed_on_failure(self, paired_repos, pause_file):
        """Even if push fails, the writer must be resumed."""
        repo = paired_repos["repo"]

        # push to a non-existent branch to force failure
        result = run_push_cycle(
            repo_path=repo,
            remote="origin",
            branch="nonexistent-branch-xyz",
            pause_file=pause_file,
        )
        # whether it succeeds or fails, pause file must be gone
        assert not Path(pause_file).exists()

    def test_divergence_detected(self, paired_repos, pause_file, tmp_path):
        """When remote and local diverge, divergence_detected should be True."""
        repo = paired_repos["repo"]
        bare = paired_repos["bare"]
        branch = paired_repos["branch"]

        # create divergence via a clone
        clone = tmp_path / "clone2"
        subprocess.run(
            ["git", "clone", str(bare), str(clone)], capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(clone), "config", "user.email", "c@c.local"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(clone), "config", "user.name", "Clone"],
            capture_output=True,
        )
        (clone / "remote.txt").write_text("remote work\n")
        subprocess.run(
            ["git", "-C", str(clone), "add", "-A"], capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(clone), "commit", "-m", "remote work"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(clone), "push"], capture_output=True
        )

        # local commit
        (Path(repo) / "local.txt").write_text("local work\n")
        subprocess.run(["git", "-C", repo, "add", "-A"], capture_output=True)
        subprocess.run(
            ["git", "-C", repo, "commit", "-m", "local work"],
            capture_output=True,
        )

        # run push cycle — should handle divergence via rebase
        result = run_push_cycle(
            repo_path=repo,
            remote="origin",
            branch=branch,
            pause_file=pause_file,
        )
        assert result.divergence_detected is True
        # rebase should resolve it (different files touched)
        assert result.success is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_result_to_dict_roundtrip(self):
        r = PushCycleResult(
            success=True,
            steps_taken=["fetch", "push", "resume_writer"],
            divergence_detected=True,
            stash_used=True,
            commits_pushed=3,
        )
        d = r.to_dict()
        r2 = PushCycleResult(**d)
        assert r2.success == r.success
        assert r2.steps_taken == r.steps_taken
        assert r2.commits_pushed == r.commits_pushed

    def test_pause_resume_idempotent(self, pause_file):
        """Pausing twice or resuming twice should not raise."""
        _pause_writer(pause_file)
        _pause_writer(pause_file)  # no error
        assert Path(pause_file).exists()
        _resume_writer(pause_file)
        _resume_writer(pause_file)  # no error
        assert not Path(pause_file).exists()
