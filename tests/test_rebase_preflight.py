"""tests for rebase_preflight — 25 tests covering all verdicts and edge cases."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from iamai.rebase_preflight import (
    RebasePreflight,
    check_rebase_safety,
    safe_pull_rebase_push,
    _parse_status,
    _check_lock_files,
    _has_binary_changes,
    _run_git,
)


# --- helpers ---

def _init_repo(tmpdir: str) -> str:
    """create a minimal git repo with one commit."""
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


# --- RebasePreflight dataclass ---

def test_default_preflight_is_clean():
    pf = RebasePreflight()
    assert pf.verdict == "clean"
    assert pf.safe_to_rebase is True
    assert pf.has_changes is False
    assert pf.blocked is False


def test_has_changes_with_unstaged():
    pf = RebasePreflight(unstaged_files=["foo.py"])
    assert pf.has_changes is True


def test_has_changes_with_staged():
    pf = RebasePreflight(staged_files=["bar.py"])
    assert pf.has_changes is True


def test_has_changes_with_untracked():
    pf = RebasePreflight(untracked_files=["new.txt"])
    assert pf.has_changes is True


def test_blocked_property():
    pf = RebasePreflight(verdict="blocked")
    assert pf.blocked is True
    assert pf.has_changes is False


def test_to_dict():
    pf = RebasePreflight(
        verdict="needs_stash",
        unstaged_files=["a.py"],
        stash_required=True,
        safe_to_rebase=False,
        recommendation="stash first",
    )
    d = pf.to_dict()
    assert d["verdict"] == "needs_stash"
    assert d["stash_required"] is True
    assert d["safe_to_rebase"] is False
    assert d["unstaged_files"] == ["a.py"]
    assert d["recommendation"] == "stash first"


# --- clean repo ---

def test_clean_repo_verdict_clean(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    pf = check_rebase_safety(repo)
    assert pf.verdict == "clean"
    assert pf.safe_to_rebase is True
    assert pf.stash_required is False


# --- unstaged changes ---

def test_unstaged_changes_verdict_needs_stash(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    readme = Path(repo) / "README.md"
    readme.write_text("# modified\n")
    pf = check_rebase_safety(repo)
    assert pf.verdict == "needs_stash"
    assert pf.stash_required is True
    assert pf.safe_to_rebase is False
    assert "README.md" in pf.unstaged_files


# --- staged changes ---

def test_staged_changes_verdict_needs_stash(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    readme = Path(repo) / "README.md"
    readme.write_text("# staged\n")
    subprocess.run(["git", "-C", repo, "add", "README.md"], capture_output=True)
    pf = check_rebase_safety(repo)
    assert pf.verdict == "needs_stash"
    assert pf.stash_required is True
    assert "README.md" in pf.staged_files


# --- untracked files alone ---

def test_untracked_files_verdict_needs_stash(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    new_file = Path(repo) / "new_note.md"
    new_file.write_text("hello\n")
    pf = check_rebase_safety(repo)
    assert pf.verdict == "needs_stash"
    assert "new_note.md" in pf.untracked_files


# --- lock files ---

def test_merge_head_blocks(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    merge_head = Path(repo) / ".git" / "MERGE_HEAD"
    merge_head.write_text("abc123\n")
    pf = check_rebase_safety(repo)
    assert pf.verdict == "blocked"
    assert pf.safe_to_rebase is False
    assert "merge" in pf.recommendation.lower() or "rebase" in pf.recommendation.lower()


def test_rebase_merge_dir_blocks(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    rebase_dir = Path(repo) / ".git" / "rebase-merge"
    rebase_dir.mkdir()
    pf = check_rebase_safety(repo)
    assert pf.verdict == "blocked"


def test_rebase_apply_dir_blocks(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    rebase_dir = Path(repo) / ".git" / "rebase-apply"
    rebase_dir.mkdir()
    pf = check_rebase_safety(repo)
    assert pf.verdict == "blocked"


def test_cherry_pick_head_blocks(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    cp_head = Path(repo) / ".git" / "CHERRY_PICK_HEAD"
    cp_head.write_text("abc\n")
    pf = check_rebase_safety(repo)
    assert pf.verdict == "blocked"


def test_revert_head_blocks(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    rv_head = Path(repo) / ".git" / "REVERT_HEAD"
    rv_head.write_text("abc\n")
    pf = check_rebase_safety(repo)
    assert pf.verdict == "blocked"


# --- parse_status edge cases ---

def test_parse_status_empty_output():
    with patch("iamai.rebase_preflight._run_git") as mock_git:
        mock_git.return_value = MagicMock(stdout="", stderr="")
        staged, unstaged, untracked = _parse_status("/fake")
        assert staged == []
        assert unstaged == []
        assert untracked == []


def test_parse_status_mixed_changes():
    output = "M  staged.py\n M unstaged.py\n?? new.txt\n"
    with patch("iamai.rebase_preflight._run_git") as mock_git:
        mock_git.return_value = MagicMock(stdout=output, stderr="")
        staged, unstaged, untracked = _parse_status("/fake")
        assert "staged.py" in staged
        assert "unstaged.py" in unstaged
        assert "new.txt" in untracked


def test_parse_status_short_line_skipped():
    output = "AB\nM  good.py\n"
    with patch("iamai.rebase_preflight._run_git") as mock_git:
        mock_git.return_value = MagicMock(stdout=output, stderr="")
        staged, unstaged, untracked = _parse_status("/fake")
        assert "good.py" in staged


# --- lock file checker ---

def test_check_lock_files_no_locks(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    assert _check_lock_files(repo) is False


def test_check_lock_files_with_merge_head(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    (Path(repo) / ".git" / "MERGE_HEAD").write_text("x\n")
    assert _check_lock_files(repo) is True


# --- binary detection ---

def test_has_binary_changes_false_for_text(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    readme = Path(repo) / "README.md"
    readme.write_text("# text change\n")
    assert _has_binary_changes(repo, ["README.md"]) is False


def test_has_binary_changes_no_files():
    assert _has_binary_changes("/fake", []) is False


# --- safe_pull_rebase_push dry_run ---

def test_dry_run_clean_returns_plan(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    result = safe_pull_rebase_push(repo, dry_run=True)
    assert result["executed"] is False
    assert result["result"] == "dry_run"
    assert any("pull --rebase" in step for step in result["plan"])
    assert any("push" in step for step in result["plan"])
    # clean repo should NOT have stash in plan
    assert "git stash" not in result["plan"]


def test_dry_run_dirty_includes_stash(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    readme = Path(repo) / "README.md"
    readme.write_text("# dirty\n")
    result = safe_pull_rebase_push(repo, dry_run=True)
    assert result["executed"] is False
    assert "git stash" in result["plan"]
    assert "git stash pop" in result["plan"]


def test_dry_run_blocked_returns_blocked(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    (Path(repo) / ".git" / "MERGE_HEAD").write_text("x\n")
    result = safe_pull_rebase_push(repo, dry_run=True)
    assert result["executed"] is False
    assert result["result"] == "blocked"


# --- recommendation text ---

def test_clean_recommendation(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    pf = check_rebase_safety(repo)
    assert "safe" in pf.recommendation.lower()


def test_stash_recommendation(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    readme = Path(repo) / "README.md"
    readme.write_text("# mod\n")
    pf = check_rebase_safety(repo)
    assert "stash" in pf.recommendation.lower()


def test_blocked_recommendation(tmp_path):
    repo = _init_repo(str(tmp_path / "repo"))
    (Path(repo) / ".git" / "MERGE_HEAD").write_text("x\n")
    pf = check_rebase_safety(repo)
    assert "resolve" in pf.recommendation.lower() or "progress" in pf.recommendation.lower()
