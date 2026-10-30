"""Tests for iamai.commit_blockage — why can't this repo commit?

Covers:
  - check_blockage returns empty list for a clean repo
  - stale index.lock detected as blocking
  - active index.lock (with holder) detected as warning
  - rebase-merge directory detected as blocking
  - MERGE_HEAD detected as blocking
  - summary() one-liner for each state
  - findings sorted by severity (blocking before warning before info)
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.commit_blockage import check_blockage, summary


@pytest.fixture
def clean_repo(tmp_path):
    """Create a minimal git repo structure with no blockers."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    return tmp_path


@pytest.fixture
def locked_repo(tmp_path):
    """Create a repo with a stale index.lock."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    lock = git_dir / "index.lock"
    lock.write_text("")
    # Set mtime to 1 hour ago
    old_time = time.time() - 3600
    import os
    os.utime(lock, (old_time, old_time))
    return tmp_path


@pytest.fixture
def rebasing_repo(tmp_path):
    """Create a repo with an ongoing rebase."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    (git_dir / "rebase-merge").mkdir()
    return tmp_path


# --- clean repo -----------------------------------------------------------


def test_clean_repo_has_no_blockers(clean_repo):
    findings = check_blockage(clean_repo)
    # Should have no blocking findings (info notes are ok)
    blocking = [f for f in findings if f["severity"] == "blocking"]
    assert len(blocking) == 0


def test_clean_repo_summary_says_clear(clean_repo):
    result = summary(clean_repo)
    assert "BLOCKED" not in result


# --- stale index.lock -----------------------------------------------------


@patch("iamai.commit_blockage._find_holder", return_value=None)
def test_stale_lock_is_blocking(mock_holder, locked_repo):
    findings = check_blockage(locked_repo)
    blocking = [f for f in findings if f["severity"] == "blocking"]
    assert len(blocking) >= 1
    lock_finding = [f for f in blocking if f["cause"] == "stale_index_lock"]
    assert len(lock_finding) == 1
    assert "remove" in lock_finding[0]["fix"].lower()


@patch("iamai.commit_blockage._find_holder", return_value=None)
def test_stale_lock_summary_says_blocked(mock_holder, locked_repo):
    result = summary(locked_repo)
    assert "BLOCKED" in result
    assert "stale_index_lock" in result


# --- active index.lock (held by live process) ----------------------------


@patch("iamai.commit_blockage._find_holder", return_value=12345)
def test_active_lock_is_warning(mock_holder, locked_repo):
    findings = check_blockage(locked_repo)
    # Should be warning, not blocking
    blocking = [f for f in findings if f["severity"] == "blocking"]
    lock_blocking = [f for f in blocking if "index_lock" in f["cause"]]
    assert len(lock_blocking) == 0

    warnings = [f for f in findings if f["severity"] == "warning"]
    lock_warnings = [f for f in warnings if f["cause"] == "active_index_lock"]
    assert len(lock_warnings) == 1
    assert "12345" in lock_warnings[0]["detail"]


# --- rebase in progress ---------------------------------------------------


def test_rebase_merge_is_blocking(rebasing_repo):
    findings = check_blockage(rebasing_repo)
    blocking = [f for f in findings if f["severity"] == "blocking"]
    assert any(f["cause"] == "interactive rebase_in_progress" for f in blocking)


def test_merge_head_is_blocking(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    (git_dir / "MERGE_HEAD").write_text("abc123\n")

    findings = check_blockage(tmp_path)
    blocking = [f for f in findings if f["severity"] == "blocking"]
    assert any("merge" in f["cause"] for f in blocking)


# --- severity sorting -----------------------------------------------------


@patch("iamai.commit_blockage._find_holder", return_value=None)
def test_findings_sorted_blocking_first(mock_holder, locked_repo):
    """Blocking findings should appear before warnings and info."""
    # Add a stash (info) alongside the lock (blocking)
    stash_dir = locked_repo / ".git" / "refs"
    stash_dir.mkdir(parents=True)
    (stash_dir / "stash").write_text("abc\n")

    findings = check_blockage(locked_repo)
    severities = [f["severity"] for f in findings]

    # blocking should come before info
    if "blocking" in severities and "info" in severities:
        assert severities.index("blocking") < severities.index("info")


# --- summary format -------------------------------------------------------


def test_summary_no_git_dir(tmp_path):
    """Repo without .git should not crash."""
    result = summary(tmp_path)
    assert "no commit blockers" in result


def test_findings_have_required_keys(clean_repo):
    """Every finding dict must have severity, cause, detail, fix."""
    # Force at least one finding by creating a rebase marker
    git_dir = clean_repo / ".git"
    (git_dir / "CHERRY_PICK_HEAD").write_text("abc\n")

    findings = check_blockage(clean_repo)
    for f in findings:
        assert "severity" in f
        assert "cause" in f
        assert "detail" in f
        assert "fix" in f
