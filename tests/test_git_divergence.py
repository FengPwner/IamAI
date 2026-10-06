"""Tests for iamai.git_divergence — local/remote divergence measurement."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.git_divergence import (
    count_commits,
    current_branch,
    divergence,
    fetch_remote,
    has_conflict_markers,
    is_dirty,
    is_merging,
    is_rebasing,
    merge_base,
    push_safe,
    remote_for_branch,
    tracking_branch,
    uncommitted_count,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run(cwd: Path, *cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=True)


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """Create a bare git repo to act as the remote."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    # Point HEAD at main so clones check out main by default
    subprocess.run(
        ["git", "-C", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True, capture_output=True,
    )
    return remote


@pytest.fixture
def repo(tmp_path: Path, bare_remote: Path) -> Path:
    """Create a working repo with one commit, linked to bare_remote as origin."""
    work = tmp_path / "work"
    work.mkdir()
    _run(work, "git", "init")
    _run(work, "git", "config", "user.email", "test@test.local")
    _run(work, "git", "config", "user.name", "Test")
    _run(work, "git", "remote", "add", "origin", str(bare_remote))
    # initial commit + push
    (work / "README.md").write_text("# test\n")
    _run(work, "git", "add", ".")
    _run(work, "git", "commit", "-m", "initial commit")
    _run(work, "git", "branch", "-M", "main")
    _run(work, "git", "push", "-u", "origin", "main")
    return work


# ---------------------------------------------------------------------------
# current_branch
# ---------------------------------------------------------------------------

class TestCurrentBranch:
    def test_main(self, repo: Path):
        assert current_branch(repo) == "main"

    def test_feature_branch(self, repo: Path):
        _run(repo, "git", "checkout", "-b", "feature/x")
        assert current_branch(repo) == "feature/x"

    def test_detached_head(self, repo: Path):
        head = _run(repo, "git", "rev-parse", "HEAD").stdout.strip()
        _run(repo, "git", "checkout", head)
        assert current_branch(repo) == "HEAD"


# ---------------------------------------------------------------------------
# remote_for_branch / tracking_branch
# ---------------------------------------------------------------------------

class TestRemoteTracking:
    def test_remote_for_main(self, repo: Path):
        assert remote_for_branch(repo, "main") == "origin"

    def test_remote_for_unknown_branch(self, repo: Path):
        assert remote_for_branch(repo, "nonexistent") == "origin"  # fallback

    def test_tracking_branch(self, repo: Path):
        t = tracking_branch(repo, "main")
        assert t is not None
        assert "origin/main" in t

    def test_no_tracking(self, repo: Path):
        _run(repo, "git", "checkout", "-b", "local-only")
        t = tracking_branch(repo, "local-only")
        assert t is None


# ---------------------------------------------------------------------------
# is_dirty / uncommitted_count
# ---------------------------------------------------------------------------

class TestDirtyTree:
    def test_clean(self, repo: Path):
        assert is_dirty(repo) is False
        assert uncommitted_count(repo) == 0

    def test_modified_file(self, repo: Path):
        (repo / "README.md").write_text("# changed\n")
        assert is_dirty(repo) is True
        assert uncommitted_count(repo) == 1

    def test_new_untracked(self, repo: Path):
        (repo / "new.txt").write_text("hello")
        # untracked files don't show in --porcelain without --untracked-files
        # but our status --porcelain does show them by default
        assert is_dirty(repo) is True

    def test_multiple_changes(self, repo: Path):
        (repo / "README.md").write_text("# changed\n")
        (repo / "a.txt").write_text("a")
        (repo / "b.txt").write_text("b")
        _run(repo, "git", "add", "a.txt", "b.txt")
        assert uncommitted_count(repo) >= 2


# ---------------------------------------------------------------------------
# is_rebasing / is_merging
# ---------------------------------------------------------------------------

class TestInProgress:
    def test_not_rebasing(self, repo: Path):
        assert is_rebasing(repo) is False

    def test_not_merging(self, repo: Path):
        assert is_merging(repo) is False


# ---------------------------------------------------------------------------
# merge_base / count_commits
# ---------------------------------------------------------------------------

class TestCommitCounting:
    def test_merge_base_self(self, repo: Path):
        head = _run(repo, "git", "rev-parse", "HEAD").stdout.strip()
        base = merge_base(repo, "HEAD", "HEAD")
        assert base == head

    def test_count_zero(self, repo: Path):
        assert count_commits(repo, "HEAD", "HEAD") == 0

    def test_count_after_commit(self, repo: Path):
        head_before = _run(repo, "git", "rev-parse", "HEAD").stdout.strip()
        (repo / "x.txt").write_text("x")
        _run(repo, "git", "add", ".")
        _run(repo, "git", "commit", "-m", "add x")
        assert count_commits(repo, head_before, "HEAD") == 1

    def test_count_multiple(self, repo: Path):
        head_before = _run(repo, "git", "rev-parse", "HEAD").stdout.strip()
        for i in range(3):
            (repo / f"f{i}.txt").write_text(str(i))
            _run(repo, "git", "add", ".")
            _run(repo, "git", "commit", "-m", f"commit {i}")
        assert count_commits(repo, head_before, "HEAD") == 3

    def test_no_merge_base(self, repo: Path):
        # Create an orphan branch with no common history
        _run(repo, "git", "checkout", "--orphan", "orphan")
        _run(repo, "git", "rm", "-rf", ".")
        (repo / "orphan.txt").write_text("orphan")
        _run(repo, "git", "add", ".")
        _run(repo, "git", "commit", "-m", "orphan initial")
        base = merge_base(repo, "HEAD", "main")
        assert base is None


# ---------------------------------------------------------------------------
# fetch_remote
# ---------------------------------------------------------------------------

class TestFetch:
    def test_fetch_origin(self, repo: Path):
        assert fetch_remote(repo, "origin") is True

    def test_fetch_bad_remote(self, repo: Path):
        assert fetch_remote(repo, "nonexistent") is False


# ---------------------------------------------------------------------------
# has_conflict_markers
# ---------------------------------------------------------------------------

class TestConflictMarkers:
    def test_clean_repo(self, repo: Path):
        assert has_conflict_markers(repo) == []

    def test_file_with_markers(self, repo: Path):
        conflict_content = (
            "line 1\n"
            "<<<<<<< HEAD\n"
            "our version\n"
            "=======\n"
            "their version\n"
            ">>>>>>> branch\n"
            "line 2\n"
        )
        (repo / "conflicted.txt").write_text(conflict_content)
        _run(repo, "git", "add", "conflicted.txt")
        _run(repo, "git", "commit", "-m", "add file with markers")
        result = has_conflict_markers(repo)
        assert "conflicted.txt" in result


# ---------------------------------------------------------------------------
# divergence (integration)
# ---------------------------------------------------------------------------

class TestDivergence:
    def test_in_sync(self, repo: Path):
        d = divergence(repo, do_fetch=True)
        assert d["branch"] == "main"
        assert d["ahead"] == 0
        assert d["behind"] == 0
        assert d["dirty"] is False
        assert d["fetch_ok"] is True

    def test_ahead(self, repo: Path):
        (repo / "ahead.txt").write_text("ahead")
        _run(repo, "git", "add", ".")
        _run(repo, "git", "commit", "-m", "ahead commit")
        d = divergence(repo, do_fetch=True)
        assert d["ahead"] == 1
        assert d["behind"] == 0

    def test_behind(self, repo: Path, bare_remote: Path):
        # Push a commit to the bare remote from a clone
        clone = repo.parent / "clone"
        subprocess.run(["git", "clone", str(bare_remote), str(clone)],
                       capture_output=True, check=True)
        _run(clone, "git", "config", "user.email", "test@test.local")
        _run(clone, "git", "config", "user.name", "Test")
        (clone / "remote_commit.txt").write_text("from clone")
        _run(clone, "git", "add", ".")
        _run(clone, "git", "commit", "-m", "commit from clone")
        _run(clone, "git", "push", "origin", "main")

        d = divergence(repo, do_fetch=True)
        assert d["behind"] == 1
        assert d["ahead"] == 0

    def test_diverged(self, repo: Path, bare_remote: Path):
        # Local commit
        (repo / "local.txt").write_text("local")
        _run(repo, "git", "add", ".")
        _run(repo, "git", "commit", "-m", "local commit")

        # Remote commit from clone
        clone = repo.parent / "clone2"
        subprocess.run(["git", "clone", str(bare_remote), str(clone)],
                       capture_output=True, check=True)
        _run(clone, "git", "config", "user.email", "test@test.local")
        _run(clone, "git", "config", "user.name", "Test")
        (clone / "remote.txt").write_text("remote")
        _run(clone, "git", "add", ".")
        _run(clone, "git", "commit", "-m", "remote commit")
        _run(clone, "git", "push", "origin", "main")

        d = divergence(repo, do_fetch=True)
        assert d["ahead"] == 1
        assert d["behind"] == 1

    def test_dirty_flag(self, repo: Path):
        (repo / "README.md").write_text("# dirty\n")
        d = divergence(repo, do_fetch=True)
        assert d["dirty"] is True
        assert d["uncommitted"] >= 1

    def test_no_fetch(self, repo: Path):
        (repo / "x.txt").write_text("x")
        _run(repo, "git", "add", ".")
        _run(repo, "git", "commit", "-m", "x")
        d = divergence(repo, do_fetch=False)
        assert d["fetch_ok"] is True  # skipped, assumed fresh
        assert d["ahead"] >= 1


# ---------------------------------------------------------------------------
# push_safe
# ---------------------------------------------------------------------------

class TestPushSafe:
    def test_safe_when_ahead(self, repo: Path):
        (repo / "push.txt").write_text("push me")
        _run(repo, "git", "add", ".")
        _run(repo, "git", "commit", "-m", "ready to push")
        safe, reason = push_safe(repo, do_fetch=True)
        assert safe is True
        assert "1 commit(s)" in reason

    def test_unsafe_when_behind(self, repo: Path, bare_remote: Path):
        # Push from clone to make local behind
        clone = repo.parent / "clone3"
        subprocess.run(["git", "clone", str(bare_remote), str(clone)],
                       capture_output=True, check=True)
        _run(clone, "git", "config", "user.email", "test@test.local")
        _run(clone, "git", "config", "user.name", "Test")
        (clone / "ahead.txt").write_text("remote ahead")
        _run(clone, "git", "add", ".")
        _run(clone, "git", "commit", "-m", "remote ahead")
        _run(clone, "git", "push", "origin", "main")

        safe, reason = push_safe(repo, do_fetch=True)
        assert safe is False
        assert "behind" in reason

    def test_unsafe_when_nothing(self, repo: Path):
        safe, reason = push_safe(repo, do_fetch=True)
        assert safe is False
        assert "nothing" in reason
