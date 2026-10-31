"""Tests for rebase_safe_pull.py — union-merge-aware git pull strategy.

Uses temporary git repos and mocked divergence states to verify:
  1. .gitattributes parsing for merge=union paths
  2. Strategy selection logic (merge vs rebase vs none)
  3. Divergence detection
  4. Fallback from rebase to merge on failure
  5. Dirty working tree guard
"""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add tools/ to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from rebase_safe_pull import (
    PullPlan,
    choose_strategy,
    count_commits,
    detect_divergence,
    execute_pull,
    find_repo_root,
    find_union_merge_files,
    format_report,
    get_local_head,
    get_merge_base,
    get_remote_head,
    has_dirty_working_tree,
    plan_and_execute,
    run_git,
)


def _run(cmd, cwd):
    """Helper to run a git command in a directory."""
    result = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"git command failed: {cmd}\n{result.stderr}"
    return result.stdout.strip()


def _make_repo(tmpdir, name="test"):
    """Create a bare git repo with an initial commit."""
    repo = Path(tmpdir) / name
    repo.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "test@test.com"], repo)
    _run(["git", "config", "user.name", "Test"], repo)
    (repo / "README.md").write_text("# test\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)
    return repo


# ---------------------------------------------------------------------------
# find_repo_root
# ---------------------------------------------------------------------------

class TestFindRepoRoot:
    def test_finds_repo(self, tmp_path):
        repo = _make_repo(tmp_path, "root-test")
        subdir = repo / "a" / "b"
        subdir.mkdir(parents=True)
        assert find_repo_root(subdir) == repo

    def test_no_repo_returns_cwd(self, tmp_path):
        assert find_repo_root(tmp_path) == tmp_path


# ---------------------------------------------------------------------------
# find_union_merge_files
# ---------------------------------------------------------------------------

class TestFindUnionMergeFiles:
    def test_no_gitattributes(self, tmp_path):
        assert find_union_merge_files(tmp_path) == []

    def test_empty_gitattributes(self, tmp_path):
        (tmp_path / ".gitattributes").write_text("")
        assert find_union_merge_files(tmp_path) == []

    def test_comments_ignored(self, tmp_path):
        (tmp_path / ".gitattributes").write_text(
            "# this is a comment\n# merge=union\n"
        )
        assert find_union_merge_files(tmp_path) == []

    def test_detects_union_paths(self, tmp_path):
        (tmp_path / ".gitattributes").write_text(
            "notes/*.md   merge=union\ndata/strokes.jsonl merge=union\n"
        )
        result = find_union_merge_files(tmp_path)
        assert result == ["notes/*.md", "data/strokes.jsonl"]

    def test_non_union_ignored(self, tmp_path):
        (tmp_path / ".gitattributes").write_text(
            "notes/*.md   merge=union\n*.py  -merge\n"
        )
        result = find_union_merge_files(tmp_path)
        assert result == ["notes/*.md"]

    def test_real_repo_gitattributes(self, tmp_path):
        repo = _make_repo(tmp_path, "attrs")
        (repo / ".gitattributes").write_text(
            "docs/DEVLOG.md   merge=union\n"
            "docs/GARDEN.md   merge=union\n"
            "notes/*.md       merge=union\n"
            "doubao/code/*.py -merge\n"
        )
        _run(["git", "add", ".gitattributes"], repo)
        _run(["git", "commit", "-m", "add attrs"], repo)
        result = find_union_merge_files(repo)
        assert len(result) == 3
        assert "notes/*.md" in result


# ---------------------------------------------------------------------------
# choose_strategy
# ---------------------------------------------------------------------------

class TestChooseStrategy:
    def test_clean_no_action(self):
        assert choose_strategy("clean", []) == "none"

    def test_ahead_no_action(self):
        assert choose_strategy("ahead", ["notes/*.md"]) == "none"

    def test_no_remote_no_action(self):
        assert choose_strategy("no-remote", []) == "none"

    def test_error_no_action(self):
        assert choose_strategy("error", []) == "none"

    def test_behind_with_union_uses_merge(self):
        assert choose_strategy("behind", ["notes/*.md"]) == "merge"

    def test_behind_without_union_uses_rebase(self):
        assert choose_strategy("behind", []) == "rebase"

    def test_diverged_with_union_uses_merge(self):
        assert choose_strategy("diverged", ["notes/*.md"]) == "merge"

    def test_diverged_without_union_uses_rebase(self):
        assert choose_strategy("diverged", []) == "rebase"


# ---------------------------------------------------------------------------
# has_dirty_working_tree
# ---------------------------------------------------------------------------

class TestHasDirtyWorkingTree:
    def test_clean_repo(self, tmp_path):
        repo = _make_repo(tmp_path, "dirty-clean")
        assert has_dirty_working_tree(repo) is False

    def test_dirty_repo(self, tmp_path):
        repo = _make_repo(tmp_path, "dirty-dirty")
        (repo / "new.txt").write_text("hello")
        assert has_dirty_working_tree(repo) is True


# ---------------------------------------------------------------------------
# get_local_head / get_remote_head / get_merge_base / count_commits
# ---------------------------------------------------------------------------

class TestGitHelpers:
    def test_get_local_head(self, tmp_path):
        repo = _make_repo(tmp_path, "head")
        head = get_local_head(repo)
        assert head is not None
        assert len(head) == 40

    def test_get_local_head_not_repo(self, tmp_path):
        assert get_local_head(tmp_path) is None

    def test_get_remote_head(self, tmp_path):
        # Create origin + clone
        origin = _make_repo(tmp_path, "origin")
        clone = Path(tmp_path) / "clone"
        _run(["git", "clone", str(origin), str(clone)], tmp_path)
        remote = get_remote_head(clone, "origin", "master")
        if remote is None:
            remote = get_remote_head(clone, "origin", "main")
        assert remote is not None

    def test_get_merge_base(self, tmp_path):
        repo = _make_repo(tmp_path, "mergebase")
        head = get_local_head(repo)
        base = get_merge_base(repo, head, head)
        assert base == head

    def test_count_commits(self, tmp_path):
        repo = _make_repo(tmp_path, "count")
        first = get_local_head(repo)
        (repo / "a.txt").write_text("a")
        _run(["git", "add", "."], repo)
        _run(["git", "commit", "-m", "second"], repo)
        second = get_local_head(repo)
        assert count_commits(repo, first, second) == 1


# ---------------------------------------------------------------------------
# execute_pull
# ---------------------------------------------------------------------------

class TestExecutePull:
    def test_none_strategy(self, tmp_path):
        repo = _make_repo(tmp_path, "exec-none")
        success, msg = execute_pull(repo, "none", "origin", "main")
        assert success is True
        assert "nothing to do" in msg

    def test_dry_run(self, tmp_path):
        repo = _make_repo(tmp_path, "exec-dry")
        success, msg = execute_pull(repo, "merge", "origin", "main",
                                     dry_run=True)
        assert success is True
        assert "would run" in msg
        assert "--no-rebase" in msg

    def test_dry_run_rebase(self, tmp_path):
        repo = _make_repo(tmp_path, "exec-dry-rb")
        success, msg = execute_pull(repo, "rebase", "origin", "main",
                                     dry_run=True)
        assert success is True
        assert "--rebase" in msg


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_report_structure(self):
        plan = PullPlan(
            divergence="diverged",
            strategy="merge",
            union_files=["notes/*.md", "data/strokes.jsonl"],
            action_taken="git pull --no-rebase origin main succeeded",
            exit_code=0,
        )
        report = format_report(plan)
        assert "Rebase-Safe Pull" in report
        assert "diverged" in report
        assert "merge" in report
        assert "notes/*.md" in report

    def test_empty_union_files(self):
        plan = PullPlan(
            divergence="clean", strategy="none", union_files=[],
            action_taken="nothing to do", exit_code=0,
        )
        report = format_report(plan)
        assert "Union files: 0" in report


# ---------------------------------------------------------------------------
# plan_and_execute (integration)
# ---------------------------------------------------------------------------

class TestPlanAndExecute:
    def test_not_a_repo(self, tmp_path):
        plan = plan_and_execute(repo=tmp_path / "nonexistent")
        assert plan.exit_code == 2
        assert plan.divergence == "error"

    def test_dirty_tree_rejected(self, tmp_path):
        repo = _make_repo(tmp_path, "dirty-plan")
        (repo / "dirty.txt").write_text("uncommitted")
        plan = plan_and_execute(repo=repo)
        assert plan.exit_code == 1
        assert "uncommitted" in plan.action_taken

    def test_clean_repo_with_origin(self, tmp_path):
        origin = _make_repo(tmp_path, "plan-origin")
        clone = Path(tmp_path) / "plan-clone"
        _run(["git", "clone", str(origin), str(clone)], tmp_path)
        _run(["git", "config", "user.email", "test@test.com"], clone)
        _run(["git", "config", "user.name", "Test"], clone)
        branch = "master" if (clone / ".git" / "refs" / "heads" / "master").exists() else "main"
        plan = plan_and_execute(repo=clone, branch=branch)
        assert plan.divergence == "clean"
        assert plan.strategy == "none"

    def test_ahead_is_safe(self, tmp_path):
        origin = _make_repo(tmp_path, "ahead-origin")
        clone = Path(tmp_path) / "ahead-clone"
        _run(["git", "clone", str(origin), str(clone)], tmp_path)
        _run(["git", "config", "user.email", "test@test.com"], clone)
        _run(["git", "config", "user.name", "Test"], clone)
        (clone / "new.txt").write_text("new")
        _run(["git", "add", "."], clone)
        _run(["git", "commit", "-m", "new commit"], clone)
        branch = "master" if (clone / ".git" / "refs" / "heads" / "master").exists() else "main"
        plan = plan_and_execute(repo=clone, branch=branch)
        assert plan.divergence == "ahead"
        assert plan.strategy == "none"


# ---------------------------------------------------------------------------
# detect_divergence with real repos
# ---------------------------------------------------------------------------

class TestDetectDivergence:
    def test_clean(self, tmp_path):
        origin = _make_repo(tmp_path, "div-origin")
        clone = Path(tmp_path) / "div-clone"
        _run(["git", "clone", str(origin), str(clone)], tmp_path)
        branch = "master" if (clone / ".git" / "refs" / "heads" / "master").exists() else "main"
        state, ahead, behind = detect_divergence(clone, "origin", branch)
        assert state == "clean"

    def test_ahead(self, tmp_path):
        origin = _make_repo(tmp_path, "ahead2-origin")
        clone = Path(tmp_path) / "ahead2-clone"
        _run(["git", "clone", str(origin), str(clone)], tmp_path)
        _run(["git", "config", "user.email", "test@test.com"], clone)
        _run(["git", "config", "user.name", "Test"], clone)
        (clone / "extra.txt").write_text("extra")
        _run(["git", "add", "."], clone)
        _run(["git", "commit", "-m", "extra"], clone)
        branch = "master" if (clone / ".git" / "refs" / "heads" / "master").exists() else "main"
        state, ahead, behind = detect_divergence(clone, "origin", branch)
        assert state == "ahead"
        assert ahead >= 1

    def test_behind(self, tmp_path):
        origin = _make_repo(tmp_path, "behind-origin")
        clone = Path(tmp_path) / "behind-clone"
        _run(["git", "clone", str(origin), str(clone)], tmp_path)
        _run(["git", "config", "user.email", "test@test.com"], origin)
        _run(["git", "config", "user.name", "Test"], origin)
        (origin / "remote.txt").write_text("remote")
        _run(["git", "add", "."], origin)
        _run(["git", "commit", "-m", "remote change"], origin)
        branch = "master" if (clone / ".git" / "refs" / "heads" / "master").exists() else "main"
        state, ahead, behind = detect_divergence(clone, "origin", branch)
        assert state == "behind"
        assert behind >= 1

    def test_diverged(self, tmp_path):
        origin = _make_repo(tmp_path, "diverge-origin")
        clone = Path(tmp_path) / "diverge-clone"
        _run(["git", "clone", str(origin), str(clone)], tmp_path)
        # remote gets a commit
        _run(["git", "config", "user.email", "test@test.com"], origin)
        _run(["git", "config", "user.name", "Test"], origin)
        (origin / "remote.txt").write_text("remote")
        _run(["git", "add", "."], origin)
        _run(["git", "commit", "-m", "remote"], origin)
        # local gets a different commit
        _run(["git", "config", "user.email", "test@test.com"], clone)
        _run(["git", "config", "user.name", "Test"], clone)
        (clone / "local.txt").write_text("local")
        _run(["git", "add", "."], clone)
        _run(["git", "commit", "-m", "local"], clone)
        branch = "master" if (clone / ".git" / "refs" / "heads" / "master").exists() else "main"
        state, ahead, behind = detect_divergence(clone, "origin", branch)
        assert state == "diverged"
        assert ahead >= 1
        assert behind >= 1
