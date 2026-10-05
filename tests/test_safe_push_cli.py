"""Tests for iamai.push.safe_push_cli."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.push import safe_push_cli


def _make_repo(tmp: Path) -> Path:
    """Create a minimal git repo with one commit."""
    repo = tmp / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def test_not_a_repo(tmp_path):
    """Returns 1 and prints JSON error for a non-repo path."""
    fake = tmp_path / "nope"
    fake.mkdir()
    rc = safe_push_cli(fake)
    assert rc == 1


def test_returns_int(tmp_path):
    """Return value is always an int (exit code)."""
    repo = _make_repo(tmp_path)
    # No remote configured — push_with_rebase will fail gracefully.
    rc = safe_push_cli(repo)
    assert isinstance(rc, int)


def test_json_output(tmp_path, capsys):
    """Prints valid JSON to stdout."""
    repo = _make_repo(tmp_path)
    safe_push_cli(repo)
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert "ok" in data
    assert "detail" in data


def test_stashes_dirty_tree(tmp_path):
    """Uncommitted changes survive the push attempt."""
    repo = _make_repo(tmp_path)
    (repo / "dirty.txt").write_text("uncommitted\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    # Do not commit — tree is dirty.
    safe_push_cli(repo)
    # The dirty file should still be there (stash was popped).
    assert (repo / "dirty.txt").exists()
    assert (repo / "dirty.txt").read_text() == "uncommitted\n"


def test_remote_arg(tmp_path, capsys):
    """Accepts a custom remote name without crashing."""
    repo = _make_repo(tmp_path)
    rc = safe_push_cli(repo, remote="upstream")
    assert isinstance(rc, int)
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert isinstance(data, dict)


def test_branch_arg(tmp_path, capsys):
    """Accepts a custom branch name without crashing."""
    repo = _make_repo(tmp_path)
    rc = safe_push_cli(repo, branch="develop")
    assert isinstance(rc, int)
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert isinstance(data, dict)
