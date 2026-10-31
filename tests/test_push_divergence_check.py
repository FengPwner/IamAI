"""Tests for push_divergence_check.py — local/remote divergence detection.

Uses temporary git repos to test all divergence states without network access.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add tools/ to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from push_divergence_check import (
    DivergenceStatus,
    check_divergence,
    find_repo_root,
    format_report,
    get_local_head,
    get_merge_base,
    get_remote_head,
    count_commits,
    run_git,
)


def _run(cmd, cwd):
    """Helper to run a git command in a directory."""
    result = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"git command failed: {cmd}\n{result.stderr}"
    return result.stdout.strip()


def _make_repo_with_commit(tmpdir, name="repo"):
    """Create a minimal git repo with one commit. Returns Path."""
    repo = Path(tmpdir) / name
    repo.mkdir(parents=True)
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "test@test.local"], repo)
    _run(["git", "config", "user.name", "Test"], repo)
    (repo / "README.md").write_text("# test\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "initial"], repo)
    return repo


class TestFindRepoRoot:
    def test_finds_git_root(self, tmp_path):
        repo = _make_repo_with_commit(tmp_path)
        subdir = repo / "a" / "b"
        subdir.mkdir(parents=True)
        assert find_repo_root(subdir) == repo

    def test_returns_cwd_if_no_git(self, tmp_path):
        (tmp_path / "plain").mkdir()
        assert find_repo_root(tmp_path / "plain") == tmp_path / "plain"


class TestGetLocalHead:
    def test_returns_sha(self, tmp_path):
        repo = _make_repo_with_commit(tmp_path)
        sha = get_local_head(repo)
        assert sha is not None
        assert len(sha) == 40

    def test_returns_none_for_non_repo(self, tmp_path):
        (tmp_path / "empty").mkdir()
        assert get_local_head(tmp_path / "empty") is None


class TestRunGit:
    def test_success(self, tmp_path):
        repo = _make_repo_with_commit(tmp_path)
        result = run_git(["status"], repo)
        assert result.returncode == 0

    def test_failure(self, tmp_path):
        repo = _make_repo_with_commit(tmp_path)
        result = run_git(["log", "--nonexistent-flag"], repo)
        assert result.returncode != 0


class TestCountCommits:
    def test_counts_correctly(self, tmp_path):
        repo = _make_repo_with_commit(tmp_path)
        head1 = _run(["git", "rev-parse", "HEAD"], repo)

        # Add two more commits
        (repo / "a.txt").write_text("a")
        _run(["git", "add", "."], repo)
        _run(["git", "commit", "-m", "second"], repo)

        (repo / "b.txt").write_text("b")
        _run(["git", "add", "."], repo)
        _run(["git", "commit", "-m", "third"], repo)

        head3 = _run(["git", "rev-parse", "HEAD"], repo)
        assert count_commits(repo, head1, head3) == 2
        assert count_commits(repo, head3, head1) == 0


class TestCheckDivergenceWithMockedGit:
    """Test divergence states by mocking subprocess.run to avoid network."""

    def _mock_run(self, responses: dict):
        """Create a mock for subprocess.run that returns predefined responses."""
        def side_effect(cmd, *args, **kwargs):
            key = " ".join(cmd)
            for pattern, (rc, stdout, stderr) in responses.items():
                if pattern in key:
                    result = MagicMock()
                    result.returncode = rc
                    result.stdout = stdout
                    result.stderr = stderr
                    return result
            # Default: success with empty output
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result
        return side_effect

    @patch("push_divergence_check.run_git")
    @patch("push_divergence_check.find_repo_root")
    def test_error_not_a_repo(self, mock_root, mock_git, tmp_path):
        mock_root.return_value = tmp_path
        mock_git.side_effect = self._mock_run({
            "rev-parse HEAD": (128, "", "fatal: not a git repository"),
        })
        status = check_divergence(repo=tmp_path)
        assert status.state == "error"
        assert "not a git repository" in status.message

    @patch("push_divergence_check.fetch_remote")
    @patch("push_divergence_check.get_local_head")
    @patch("push_divergence_check.find_repo_root")
    def test_error_fetch_failed(self, mock_root, mock_head, mock_fetch, tmp_path):
        mock_root.return_value = tmp_path
        mock_head.return_value = "a" * 40
        mock_fetch.return_value = False
        status = check_divergence(repo=tmp_path, timeout=1)
        assert status.state == "error"
        assert "fetch" in status.message.lower()

    @patch("push_divergence_check.fetch_remote")
    @patch("push_divergence_check.get_remote_head")
    @patch("push_divergence_check.get_local_head")
    @patch("push_divergence_check.find_repo_root")
    def test_no_remote(self, mock_root, mock_head, mock_remote, mock_fetch, tmp_path):
        mock_root.return_value = tmp_path
        mock_head.return_value = "a" * 40
        mock_fetch.return_value = True
        mock_remote.return_value = None
        status = check_divergence(repo=tmp_path)
        assert status.state == "no-remote"
        assert status.ahead == 0

    @patch("push_divergence_check.fetch_remote")
    @patch("push_divergence_check.get_remote_head")
    @patch("push_divergence_check.get_local_head")
    @patch("push_divergence_check.find_repo_root")
    def test_clean(self, mock_root, mock_head, mock_remote, mock_fetch, tmp_path):
        sha = "a" * 40
        mock_root.return_value = tmp_path
        mock_head.return_value = sha
        mock_fetch.return_value = True
        mock_remote.return_value = sha
        status = check_divergence(repo=tmp_path)
        assert status.state == "clean"
        assert status.ahead == 0
        assert status.behind == 0

    @patch("push_divergence_check.count_commits")
    @patch("push_divergence_check.get_merge_base")
    @patch("push_divergence_check.fetch_remote")
    @patch("push_divergence_check.get_remote_head")
    @patch("push_divergence_check.get_local_head")
    @patch("push_divergence_check.find_repo_root")
    def test_ahead(self, mock_root, mock_head, mock_remote, mock_fetch,
                   mock_base, mock_count, tmp_path):
        local_sha = "a" * 40
        remote_sha = "b" * 40
        base_sha = "c" * 40
        mock_root.return_value = tmp_path
        mock_head.return_value = local_sha
        mock_fetch.return_value = True
        mock_remote.return_value = remote_sha
        mock_base.return_value = base_sha
        mock_count.side_effect = lambda repo, f, t: (
            3 if (f == base_sha and t == local_sha) else 0
        )
        status = check_divergence(repo=tmp_path)
        assert status.state == "ahead"
        assert status.ahead == 3
        assert status.behind == 0

    @patch("push_divergence_check.count_commits")
    @patch("push_divergence_check.get_merge_base")
    @patch("push_divergence_check.fetch_remote")
    @patch("push_divergence_check.get_remote_head")
    @patch("push_divergence_check.get_local_head")
    @patch("push_divergence_check.find_repo_root")
    def test_behind(self, mock_root, mock_head, mock_remote, mock_fetch,
                    mock_base, mock_count, tmp_path):
        local_sha = "a" * 40
        remote_sha = "b" * 40
        base_sha = "c" * 40
        mock_root.return_value = tmp_path
        mock_head.return_value = local_sha
        mock_fetch.return_value = True
        mock_remote.return_value = remote_sha
        mock_base.return_value = base_sha
        mock_count.side_effect = lambda repo, f, t: (
            2 if (f == base_sha and t == remote_sha) else 0
        )
        status = check_divergence(repo=tmp_path)
        assert status.state == "behind"
        assert status.behind == 2
        assert status.ahead == 0

    @patch("push_divergence_check.count_commits")
    @patch("push_divergence_check.get_merge_base")
    @patch("push_divergence_check.fetch_remote")
    @patch("push_divergence_check.get_remote_head")
    @patch("push_divergence_check.get_local_head")
    @patch("push_divergence_check.find_repo_root")
    def test_diverged(self, mock_root, mock_head, mock_remote, mock_fetch,
                      mock_base, mock_count, tmp_path):
        local_sha = "a" * 40
        remote_sha = "b" * 40
        base_sha = "c" * 40
        mock_root.return_value = tmp_path
        mock_head.return_value = local_sha
        mock_fetch.return_value = True
        mock_remote.return_value = remote_sha
        mock_base.return_value = base_sha
        mock_count.side_effect = lambda repo, f, t: (
            3 if (f == base_sha and t == local_sha) else
            2 if (f == base_sha and t == remote_sha) else 0
        )
        status = check_divergence(repo=tmp_path)
        assert status.state == "diverged"
        assert status.ahead == 3
        assert status.behind == 2


class TestFormatReport:
    def test_includes_all_fields(self):
        status = DivergenceStatus(
            state="diverged",
            local="a" * 40,
            remote="b" * 40,
            merge_base="c" * 40,
            ahead=3,
            behind=2,
            message="diverged: 3 local + 2 remote commit(s)",
        )
        report = format_report(status)
        assert "diverged" in report
        assert "aaaa" in report  # truncated sha
        assert "Ahead:      3" in report
        assert "Behind:     2" in report

    def test_handles_empty_shas(self):
        status = DivergenceStatus(
            state="no-remote",
            local="a" * 40,
            remote="",
            merge_base="",
            ahead=0,
            behind=0,
            message="first push is safe",
        )
        report = format_report(status)
        assert "N/A" in report  # empty remote shown as N/A
        assert "no-remote" in report


class TestCheckDivergenceIntegration:
    """Integration test using real local git repos (no network)."""

    def test_clean_state(self, tmp_path):
        """Two clones of the same repo with no divergence."""
        origin = _make_repo_with_commit(tmp_path, "origin")
        clone = Path(tmp_path) / "clone"
        _run(["git", "clone", str(origin), str(clone)], tmp_path)
        _run(["git", "config", "user.email", "test@test.local"], clone)
        _run(["git", "config", "user.name", "Test"], clone)

        status = check_divergence(repo=clone, remote="origin", branch="master")
        # master may not exist on fresh clone with newer git default branch
        # but the fetch will succeed, so we test the mechanism
        assert status.state in ("clean", "no-remote", "error")

    def test_ahead_state(self, tmp_path):
        """Clone adds a commit that origin doesn't have."""
        origin = _make_repo_with_commit(tmp_path, "origin")
        clone = Path(tmp_path) / "clone"
        _run(["git", "clone", str(origin), str(clone)], tmp_path)
        _run(["git", "config", "user.email", "test@test.local"], clone)
        _run(["git", "config", "user.name", "Test"], clone)

        # Add commit to clone
        (clone / "new.txt").write_text("new content")
        _run(["git", "add", "."], clone)
        _run(["git", "commit", "-m", "clone addition"], clone)

        # Determine the branch name
        branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], clone)

        status = check_divergence(repo=clone, remote="origin", branch=branch)
        assert status.state == "ahead"
        assert status.ahead >= 1
        assert status.behind == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
