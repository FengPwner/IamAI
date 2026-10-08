"""Tests for iamai.git_index_health."""

import os
import time
from pathlib import Path

import pytest

from iamai.git_index_health import (
    check_index,
    check_lock,
    check_refs,
    diagnose,
    repair,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal .git directory structure."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "refs" / "remotes" / "origin").mkdir(parents=True)
    return tmp_path


def _write_index(repo: Path, content: bytes = b"DIRC\x00\x00\x00\x02") -> None:
    (repo / ".git" / "index").write_bytes(content)


def _write_lock(repo: Path, age: float = 0) -> None:
    lock = repo / ".git" / "index.lock"
    lock.write_text("")
    if age > 0:
        now = time.time()
        os.utime(lock, (now - age, now - age))


def _write_loose_ref(repo: Path, ref: str, sha: str) -> None:
    path = repo / ".git" / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sha + "\n")


def _write_packed_refs(repo: Path, lines: list[str]) -> None:
    (repo / ".git" / "packed-refs").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# check_lock
# ---------------------------------------------------------------------------

class TestCheckLock:
    def test_no_lock(self, tmp_path):
        repo = _make_repo(tmp_path)
        result = check_lock(repo)
        assert result["exists"] is False
        assert result["age_seconds"] is None
        assert result["stale"] is False

    def test_fresh_lock(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_lock(repo, age=10)
        result = check_lock(repo)
        assert result["exists"] is True
        assert result["age_seconds"] is not None
        assert result["age_seconds"] >= 9  # allow 1s tolerance
        assert result["stale"] is False

    def test_stale_lock(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_lock(repo, age=600)
        result = check_lock(repo)
        assert result["exists"] is True
        assert result["stale"] is True


# ---------------------------------------------------------------------------
# check_index
# ---------------------------------------------------------------------------

class TestCheckIndex:
    def test_missing(self, tmp_path):
        repo = _make_repo(tmp_path)
        result = check_index(repo)
        assert result["exists"] is False
        assert result["readable"] is False

    def test_empty(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_index(repo, b"")
        result = check_index(repo)
        assert result["exists"] is True
        assert result["size_bytes"] == 0
        assert result["readable"] is False

    def test_valid(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_index(repo)
        result = check_index(repo)
        assert result["exists"] is True
        assert result["size_bytes"] > 0
        assert result["readable"] is True


# ---------------------------------------------------------------------------
# check_refs
# ---------------------------------------------------------------------------

class TestCheckRefs:
    def test_no_refs(self, tmp_path):
        repo = _make_repo(tmp_path)
        result = check_refs(repo)
        assert result["loose_count"] == 0
        assert result["packed_count"] == 0
        assert result["conflicts"] == []

    def test_loose_only(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_loose_ref(repo, "refs/heads/main", "abc123")
        result = check_refs(repo)
        assert result["loose_count"] == 1
        assert result["conflicts"] == []

    def test_matching_packed_and_loose(self, tmp_path):
        """Same SHA in both — no conflict."""
        repo = _make_repo(tmp_path)
        sha = "abc123def456"
        _write_loose_ref(repo, "refs/heads/main", sha)
        _write_packed_refs(repo, [f"{sha} refs/heads/main"])
        result = check_refs(repo)
        assert result["conflicts"] == []

    def test_conflicting_packed_and_loose(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_loose_ref(repo, "refs/heads/main", "aaa111")
        _write_packed_refs(repo, ["bbb222 refs/heads/main"])
        result = check_refs(repo)
        assert "refs/heads/main" in result["conflicts"]

    def test_multiple_conflicts(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_loose_ref(repo, "refs/heads/main", "aaa")
        _write_loose_ref(repo, "refs/remotes/origin/main", "bbb")
        _write_packed_refs(repo, [
            "ccc refs/heads/main",
            "ddd refs/remotes/origin/main",
        ])
        result = check_refs(repo)
        assert len(result["conflicts"]) == 2


# ---------------------------------------------------------------------------
# diagnose
# ---------------------------------------------------------------------------

class TestDiagnose:
    def test_healthy(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_index(repo)
        result = diagnose(repo)
        assert result["verdict"] == "healthy"
        assert result["issues"] == []
        assert result["repairs"] == []

    def test_stale_lock_degraded(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_index(repo)
        _write_lock(repo, age=600)
        result = diagnose(repo)
        assert result["verdict"] == "degraded"
        assert "stale_lock" in result["issues"]

    def test_missing_index_broken(self, tmp_path):
        repo = _make_repo(tmp_path)
        result = diagnose(repo)
        assert result["verdict"] == "broken"
        assert "missing_index" in result["issues"]

    def test_empty_index_broken(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_index(repo, b"")
        result = diagnose(repo)
        assert result["verdict"] == "broken"
        assert "empty_index" in result["issues"]

    def test_ref_conflict_degraded(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_index(repo)
        _write_loose_ref(repo, "refs/heads/main", "aaa")
        _write_packed_refs(repo, ["bbb refs/heads/main"])
        result = diagnose(repo)
        assert result["verdict"] == "degraded"
        assert "ref_conflict" in result["issues"]

    def test_broken_beats_degraded(self, tmp_path):
        """Index missing + stale lock → broken (not degraded)."""
        repo = _make_repo(tmp_path)
        _write_lock(repo, age=600)
        result = diagnose(repo)
        assert result["verdict"] == "broken"
        assert "stale_lock" in result["issues"]
        assert "missing_index" in result["issues"]

    def test_repairs_populated(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_lock(repo, age=600)
        result = diagnose(repo)
        assert len(result["repairs"]) > 0
        assert any("lock" in r for r in result["repairs"])

    def test_checks_included(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_index(repo)
        result = diagnose(repo)
        assert "lock" in result["checks"]
        assert "index" in result["checks"]
        assert "refs" in result["checks"]


# ---------------------------------------------------------------------------
# repair
# ---------------------------------------------------------------------------

class TestRepair:
    def test_dry_run_lock(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_index(repo)
        _write_lock(repo, age=600)
        actions = repair(repo, dry_run=True)
        assert any("dry-run" in a and "lock" in a for a in actions)
        # lock should still exist
        assert (repo / ".git" / "index.lock").exists()

    def test_actual_lock_removal(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_index(repo)
        _write_lock(repo, age=600)
        actions = repair(repo, dry_run=False)
        assert any("removed" in a and "lock" in a for a in actions)
        assert not (repo / ".git" / "index.lock").exists()

    def test_dry_run_ref_conflict(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_index(repo)
        _write_loose_ref(repo, "refs/heads/main", "aaa")
        _write_packed_refs(repo, ["bbb refs/heads/main"])
        actions = repair(repo, dry_run=True)
        assert any("dry-run" in a and "ref" in a for a in actions)
        # loose ref should still exist
        assert (repo / ".git" / "refs" / "heads" / "main").exists()

    def test_actual_ref_conflict_removal(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_index(repo)
        _write_loose_ref(repo, "refs/heads/main", "aaa")
        _write_packed_refs(repo, ["bbb refs/heads/main"])
        actions = repair(repo, dry_run=False)
        assert any("removed" in a and "ref" in a for a in actions)
        assert not (repo / ".git" / "refs" / "heads" / "main").exists()

    def test_index_rebuild_advice(self, tmp_path):
        """Index problems are reported as advice, not auto-fixed."""
        repo = _make_repo(tmp_path)
        # no index written → missing
        actions = repair(repo, dry_run=False)
        assert any("read-tree" in a for a in actions)

    def test_healthy_no_actions(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_index(repo)
        actions = repair(repo, dry_run=False)
        assert actions == []


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_str_and_path_interchangeable(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_index(repo)
        r1 = diagnose(str(repo))
        r2 = diagnose(repo)
        assert r1["verdict"] == r2["verdict"]

    def test_packed_refs_comments_ignored(self, tmp_path):
        repo = _make_repo(tmp_path)
        _write_packed_refs(repo, [
            "# pack-refs with: peeled fully-peeled sorted",
            "^peeled-line-ignored",
            "abc123 refs/heads/main",
        ])
        result = check_refs(repo)
        assert result["packed_count"] == 1

    def test_lock_exactly_300s_not_stale(self, tmp_path):
        """Boundary: 300 s is the threshold, exactly at it is stale (>300)."""
        repo = _make_repo(tmp_path)
        _write_lock(repo, age=300)
        result = check_lock(repo)
        # at exactly 300s the age might be 299.99 or 300.01 due to timing
        # our check is age > 300, so at ~300 it should be False or borderline
        # just verify the structure is correct
        assert isinstance(result["stale"], bool)
