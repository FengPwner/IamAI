"""Tests for push_divergence_checker.py — divergence detection and edge cases."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from push_divergence_checker import (
    check_divergence,
    get_local_head,
    get_remote_head,
    get_merge_base,
    count_commits,
    DivergenceReport,
)


# --- helpers ---

def _init_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit on main."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def _create_remote(tmp_path: Path, repo: Path) -> Path:
    """Create a bare repo to act as remote and configure it."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)],
                   check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)],
                   cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "main"],
                   cwd=repo, check=True, capture_output=True)
    return bare


# --- DivergenceReport dataclass ---

def test_report_fields():
    r = DivergenceReport(
        local_head="abc123",
        remote_head="def456",
        merge_base="000111",
        ahead=2,
        behind=0,
        verdict="ahead_only",
        push_safe=True,
        message="test",
    )
    assert r.ahead == 2
    assert r.push_safe is True
    assert r.verdict == "ahead_only"


# --- get_local_head ---

def test_get_local_head_returns_sha(tmp_path):
    repo = _init_repo(tmp_path)
    head = get_local_head(repo)
    assert len(head) == 40
    assert all(c in "0123456789abcdef" for c in head)


def test_get_local_head_empty_repo(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    with pytest.raises(RuntimeError, match="rev-parse HEAD"):
        get_local_head(repo)


# --- get_remote_head ---

def test_get_remote_head(tmp_path):
    repo = _init_repo(tmp_path)
    _create_remote(tmp_path, repo)
    remote_sha = get_remote_head(repo)
    local_sha = get_local_head(repo)
    assert remote_sha == local_sha


def test_get_remote_head_no_remote(tmp_path):
    repo = _init_repo(tmp_path)
    with pytest.raises(RuntimeError, match="Have you fetched recently"):
        get_remote_head(repo)


# --- count_commits ---

def test_count_commits_zero(tmp_path):
    repo = _init_repo(tmp_path)
    head = get_local_head(repo)
    assert count_commits(repo, head, head) == 0


def test_count_commits_ahead(tmp_path):
    repo = _init_repo(tmp_path)
    base = get_local_head(repo)
    # Add 3 more commits
    for i in range(3):
        (repo / f"file_{i}.txt").write_text(f"content {i}")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"commit {i}"],
                       cwd=repo, check=True, capture_output=True)
    head = get_local_head(repo)
    assert count_commits(repo, base, head) == 3


# --- check_divergence ---

def test_up_to_date(tmp_path):
    repo = _init_repo(tmp_path)
    _create_remote(tmp_path, repo)
    report = check_divergence(repo=repo)
    assert report.verdict == "up_to_date"
    assert report.push_safe is True
    assert report.ahead == 0
    assert report.behind == 0


def test_ahead_only(tmp_path):
    repo = _init_repo(tmp_path)
    _create_remote(tmp_path, repo)
    # Add a local commit without pushing
    (repo / "new.txt").write_text("new content")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "local change"],
                   cwd=repo, check=True, capture_output=True)
    report = check_divergence(repo=repo)
    assert report.verdict == "ahead_only"
    assert report.push_safe is True
    assert report.ahead == 1
    assert report.behind == 0


def test_behind_only(tmp_path):
    repo = _init_repo(tmp_path)
    bare = _create_remote(tmp_path, repo)
    # Create a second clone and push from it
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(bare), str(clone)],
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "other"],
                   cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "other@other"],
                   cwd=clone, check=True, capture_output=True)
    (clone / "remote_change.txt").write_text("from remote")
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "remote change"],
                   cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "push"], cwd=clone, check=True, capture_output=True)
    # Fetch in original repo (so remote tracking ref updates)
    subprocess.run(["git", "fetch", "origin"],
                   cwd=repo, check=True, capture_output=True)
    report = check_divergence(repo=repo)
    assert report.verdict == "behind_only"
    assert report.push_safe is False
    assert report.behind == 1
    assert report.ahead == 0


def test_diverged(tmp_path):
    repo = _init_repo(tmp_path)
    bare = _create_remote(tmp_path, repo)
    # Push a remote-only commit from a clone
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(bare), str(clone)],
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "other"],
                   cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "other@other"],
                   cwd=clone, check=True, capture_output=True)
    (clone / "remote.txt").write_text("remote side")
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "remote only"],
                   cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "push"], cwd=clone, check=True, capture_output=True)
    # Add a local commit in original repo
    (repo / "local.txt").write_text("local side")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "local only"],
                   cwd=repo, check=True, capture_output=True)
    # Fetch to update tracking ref
    subprocess.run(["git", "fetch", "origin"],
                   cwd=repo, check=True, capture_output=True)
    report = check_divergence(repo=repo)
    assert report.verdict == "diverged"
    assert report.push_safe is False
    assert report.ahead >= 1
    assert report.behind >= 1


# --- CLI ---

def test_cli_json_output(tmp_path):
    repo = _init_repo(tmp_path)
    _create_remote(tmp_path, repo)
    result = subprocess.run(
        [sys.executable, "-m", "push_divergence_checker",
         "--repo", str(repo), "--json"],
        cwd=str(Path(__file__).resolve().parent.parent / "tools"),
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["verdict"] == "up_to_date"
    assert data["push_safe"] is True


def test_cli_text_output(tmp_path):
    repo = _init_repo(tmp_path)
    _create_remote(tmp_path, repo)
    result = subprocess.run(
        [sys.executable, "-m", "push_divergence_checker",
         "--repo", str(repo)],
        cwd=str(Path(__file__).resolve().parent.parent / "tools"),
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "verdict:" in result.stdout
    assert "up_to_date" in result.stdout
