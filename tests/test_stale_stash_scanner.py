#!/usr/bin/env python3
"""Tests for stale_stash_scanner.py — 15 tests covering scan, classify, drop.

Uses temporary git repos with artificially dated stashes to verify
classification logic without depending on the real IamAI repo.
"""

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from stale_stash_scanner import (
    StashEntry,
    StashReport,
    find_repo_root,
    parse_stash_list,
    scan_stashes,
    drop_stash,
    DEFAULT_FRESH_DAYS,
    DEFAULT_MAX_AGE_DAYS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd, cwd, env=None):
    merged = {**os.environ, **(env or {})}
    result = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, env=merged
    )
    assert result.returncode == 0, f"Command failed: {cmd}\n{result.stderr}"
    return result


def _init_repo(path):
    """Create a git repo with an initial commit."""
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], cwd=path)
    _run(["git", "config", "user.email", "test@test.local"], cwd=path)
    _run(["git", "config", "user.name", "Test"], cwd=path)
    (path / "README.md").write_text("# test\n")
    _run(["git", "add", "."], cwd=path)
    _run(["git", "commit", "-m", "init"], cwd=path)
    return path


def _create_stash(path, message="test stash", date_offset_days=0):
    """Create a stash entry, optionally backdating it."""
    (path / "temp.txt").write_text(f"stash-{message}\n")
    _run(["git", "add", "."], cwd=path)

    # Use GIT_COMMITTER_DATE and --date to backdate the stash commit
    if date_offset_days > 0:
        target = datetime.now(timezone.utc) - timedelta(days=date_offset_days)
        date_str = target.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        env = {
            "GIT_COMMITTER_DATE": date_str,
            "GIT_AUTHOR_DATE": date_str,
        }
        _run(
            ["git", "stash", "push", "-m", message],
            cwd=path, env=env,
        )
    else:
        _run(["git", "stash", "push", "-m", message], cwd=path)


# ---------------------------------------------------------------------------
# Tests — find_repo_root
# ---------------------------------------------------------------------------

class TestFindRepoRoot:
    def test_finds_repo(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        assert find_repo_root(str(repo)) == str(repo)

    def test_not_a_repo(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            find_repo_root(str(tmp_path / "nope"))


# ---------------------------------------------------------------------------
# Tests — parse_stash_list
# ---------------------------------------------------------------------------

class TestParseStashList:
    def test_empty_repo(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        entries = parse_stash_list(str(repo))
        assert entries == []

    def test_single_stash(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _create_stash(repo, "first stash")
        entries = parse_stash_list(str(repo))
        assert len(entries) == 1
        assert "first stash" in entries[0]["message"]
        assert entries[0]["index"] == 0

    def test_multiple_stashes(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        for i in range(3):
            _create_stash(repo, f"stash-{i}")
        entries = parse_stash_list(str(repo))
        assert len(entries) == 3


# ---------------------------------------------------------------------------
# Tests — scan_stashes classification
# ---------------------------------------------------------------------------

class TestScanStashes:
    def test_no_stashes(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        report = scan_stashes(repo=str(repo))
        assert report.total == 0
        assert report.fresh == 0

    def test_fresh_stash(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _create_stash(repo, "just now")
        report = scan_stashes(repo=str(repo))
        assert report.total == 1
        assert report.fresh == 1
        assert report.entries[0].classification == "fresh"

    def test_aging_stash(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _create_stash(repo, "five days old", date_offset_days=5)
        report = scan_stashes(repo=str(repo))
        assert report.total == 1
        assert report.aging == 1
        assert report.entries[0].classification == "aging"

    def test_stale_stash(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _create_stash(repo, "old one", date_offset_days=10)
        report = scan_stashes(repo=str(repo))
        assert report.total == 1
        assert report.stale == 1
        assert report.entries[0].classification == "stale"

    def test_mixed_ages(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _create_stash(repo, "fresh", date_offset_days=0)
        _create_stash(repo, "aging", date_offset_days=5)
        _create_stash(repo, "stale", date_offset_days=14)
        report = scan_stashes(repo=str(repo))
        assert report.total == 3
        assert report.fresh >= 1
        # At least one should be stale
        stale_entries = [e for e in report.entries if e.classification == "stale"]
        assert len(stale_entries) >= 1

    def test_custom_thresholds(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _create_stash(repo, "two days", date_offset_days=2)
        # With default thresholds, 2 days is "fresh"
        report = scan_stashes(repo=str(repo))
        assert report.entries[0].classification == "fresh"
        # With fresh_days=1, 2 days should be "aging"
        report2 = scan_stashes(repo=str(repo), fresh_days=1, max_age_days=3)
        assert report2.entries[0].classification == "aging"


# ---------------------------------------------------------------------------
# Tests — drop_stash
# ---------------------------------------------------------------------------

class TestDropStash:
    def test_drop_single(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _create_stash(repo, "to drop")
        entries_before = parse_stash_list(str(repo))
        assert len(entries_before) == 1
        ok = drop_stash(0, str(repo))
        assert ok is True
        entries_after = parse_stash_list(str(repo))
        assert len(entries_after) == 0

    def test_drop_stale_only(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _create_stash(repo, "keep this", date_offset_days=0)
        _create_stash(repo, "drop this", date_offset_days=10)
        report = scan_stashes(repo=str(repo), drop_stale=True)
        assert len(report.dropped) >= 1
        # Fresh stash should still exist
        remaining = parse_stash_list(str(repo))
        messages = [e["message"] for e in remaining]
        assert any("keep this" in m for m in messages)


# ---------------------------------------------------------------------------
# Tests — report structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_report_has_scanned_at(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _create_stash(repo, "test")
        report = scan_stashes(repo=str(repo))
        assert report.scanned_at is not None
        assert len(report.scanned_at) > 10  # ISO timestamp

    def test_report_repo_path(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        report = scan_stashes(repo=str(repo))
        assert report.repo == str(repo)

    def test_entry_age_is_number(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _create_stash(repo, "aged", date_offset_days=5)
        report = scan_stashes(repo=str(repo))
        for entry in report.entries:
            assert isinstance(entry.age_days, float)
            assert entry.age_days >= 0
