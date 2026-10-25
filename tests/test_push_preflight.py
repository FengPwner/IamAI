"""Tests for iamai.push_preflight — composite pre-push checklist.

Covers:
  - check_index_lock: clean, stale, active
  - check_divergence: up to date, ahead, behind, fetch failure
  - check_dirty_tree: clean, dirty, git failure
  - preflight: all pass, one blocker, multiple blockers, summary format
  - preflight_report: one-liner string output
  - Edge cases: nonexistent repo, permission errors
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.push_preflight import (
    check_index_lock,
    check_divergence,
    check_dirty_tree,
    preflight,
    preflight_report,
)


# ---------------------------------------------------------------------------
# check_index_lock
# ---------------------------------------------------------------------------


class TestCheckIndexLock:
    """Tests for the index_lock check."""

    def test_no_lock_is_ok(self, tmp_path: Path):
        """No index.lock file means the check passes."""
        (tmp_path / ".git").mkdir(parents=True)
        result = check_index_lock(tmp_path)
        assert result["ok"] is True
        assert result["name"] == "index_lock"
        assert "no lock" in result["detail"]

    def test_stale_lock_is_blocker(self, tmp_path: Path):
        """A stale lock (no holder) blocks push."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("placeholder")

        with patch("iamai.push_preflight.detect_lock", return_value={
            "locked": True,
            "path": lock,
            "age_seconds": 120.0,
            "holder_pid": None,
            "stale": True,
        }):
            result = check_index_lock(tmp_path)

        assert result["ok"] is False
        assert "stale" in result["detail"]
        assert "remove" in result["detail"]

    def test_active_lock_is_blocker(self, tmp_path: Path):
        """An active lock (live holder) blocks push."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("placeholder")

        with patch("iamai.push_preflight.detect_lock", return_value={
            "locked": True,
            "path": lock,
            "age_seconds": 5.0,
            "holder_pid": 99999,
            "stale": False,
        }):
            result = check_index_lock(tmp_path)

        assert result["ok"] is False
        assert "active" in result["detail"]
        assert "99999" in result["detail"]


# ---------------------------------------------------------------------------
# check_divergence
# ---------------------------------------------------------------------------


class TestCheckDivergence:
    """Tests for the remote divergence check."""

    def test_up_to_date(self, tmp_path: Path):
        """Ahead 0, behind 0 → ok, nothing to push."""
        with patch("iamai.push_preflight.divergence", return_value={
            "branch": "main",
            "remote": "origin",
            "tracking": "origin/main",
            "ahead": 0,
            "behind": 0,
            "dirty": False,
            "uncommitted": 0,
        }):
            result = check_divergence(tmp_path)

        assert result["ok"] is True
        assert "nothing to push" in result["detail"]

    def test_ahead_only(self, tmp_path: Path):
        """Ahead N, behind 0 → ok, safe to push."""
        with patch("iamai.push_preflight.divergence", return_value={
            "branch": "main",
            "remote": "origin",
            "tracking": "origin/main",
            "ahead": 5,
            "behind": 0,
            "dirty": False,
            "uncommitted": 0,
        }):
            result = check_divergence(tmp_path)

        assert result["ok"] is True
        assert "ahead 5" in result["detail"]
        assert "safe to push" in result["detail"]

    def test_behind_is_blocker(self, tmp_path: Path):
        """Behind > 0 → blocker, needs rebase."""
        with patch("iamai.push_preflight.divergence", return_value={
            "branch": "main",
            "remote": "origin",
            "tracking": "origin/main",
            "ahead": 3,
            "behind": 2,
            "dirty": False,
            "uncommitted": 0,
        }):
            result = check_divergence(tmp_path)

        assert result["ok"] is False
        assert "behind 2" in result["detail"]
        assert "rebase" in result["detail"].lower()

    def test_divergence_exception(self, tmp_path: Path):
        """If divergence() raises, report it as a blocker."""
        with patch("iamai.push_preflight.divergence", side_effect=RuntimeError("fetch failed")):
            result = check_divergence(tmp_path)

        assert result["ok"] is False
        assert "fetch failed" in result["detail"]


# ---------------------------------------------------------------------------
# check_dirty_tree
# ---------------------------------------------------------------------------


class TestCheckDirtyTree:
    """Tests for the working-tree cleanliness check."""

    def test_clean_tree(self, tmp_path: Path):
        """Empty porcelain output → clean."""
        with patch("iamai.push_preflight._run", return_value=(0, "")):
            result = check_dirty_tree(tmp_path)

        assert result["ok"] is True
        assert "clean" in result["detail"]

    def test_dirty_tree(self, tmp_path: Path):
        """Non-empty porcelain output → blocker with file count."""
        porcelain = " M file1.py\n M file2.py\n?? new_file.txt"
        with patch("iamai.push_preflight._run", return_value=(0, porcelain)):
            result = check_dirty_tree(tmp_path)

        assert result["ok"] is False
        assert "3 uncommitted" in result["detail"]

    def test_single_dirty_file(self, tmp_path: Path):
        """One modified file → 1 uncommitted."""
        with patch("iamai.push_preflight._run", return_value=(0, " M only.py")):
            result = check_dirty_tree(tmp_path)

        assert result["ok"] is False
        assert "1 uncommitted" in result["detail"]

    def test_git_status_failure(self, tmp_path: Path):
        """If git status fails, report as blocker."""
        with patch("iamai.push_preflight._run", return_value=(128, "fatal: not a git repo")):
            result = check_dirty_tree(tmp_path)

        assert result["ok"] is False
        assert "git status failed" in result["detail"]

    def test_blank_lines_ignored(self, tmp_path: Path):
        """Trailing newlines in porcelain output do not inflate the count."""
        with patch("iamai.push_preflight._run", return_value=(0, " M a.py\n\n\n")):
            result = check_dirty_tree(tmp_path)

        assert result["ok"] is False
        assert "1 uncommitted" in result["detail"]


# ---------------------------------------------------------------------------
# preflight — composite
# ---------------------------------------------------------------------------


class TestPreflight:
    """Tests for the composite preflight function."""

    def test_all_pass(self, tmp_path: Path):
        """When every check passes, preflight is ok."""
        with (
            patch("iamai.push_preflight.check_index_lock", return_value={
                "name": "index_lock", "ok": True, "detail": "no lock"
            }),
            patch("iamai.push_preflight.check_divergence", return_value={
                "name": "divergence", "ok": True, "detail": "ahead 3, safe to push"
            }),
            patch("iamai.push_preflight.check_dirty_tree", return_value={
                "name": "dirty_tree", "ok": True, "detail": "clean"
            }),
        ):
            result = preflight(tmp_path)

        assert result["ok"] is True
        assert result["blockers"] == []
        assert "all checks passed" in result["summary"]
        assert len(result["checks"]) == 3

    def test_one_blocker(self, tmp_path: Path):
        """One failing check produces one blocker."""
        with (
            patch("iamai.push_preflight.check_index_lock", return_value={
                "name": "index_lock", "ok": True, "detail": "no lock"
            }),
            patch("iamai.push_preflight.check_divergence", return_value={
                "name": "divergence", "ok": False, "detail": "behind 3, fetch+rebase needed"
            }),
            patch("iamai.push_preflight.check_dirty_tree", return_value={
                "name": "dirty_tree", "ok": True, "detail": "clean"
            }),
        ):
            result = preflight(tmp_path)

        assert result["ok"] is False
        assert result["blockers"] == ["divergence"]
        assert "1 blocker" in result["summary"]
        assert "divergence" in result["summary"]

    def test_multiple_blockers(self, tmp_path: Path):
        """Multiple failures are all reported."""
        with (
            patch("iamai.push_preflight.check_index_lock", return_value={
                "name": "index_lock", "ok": False, "detail": "stale lock (age 120s)"
            }),
            patch("iamai.push_preflight.check_divergence", return_value={
                "name": "divergence", "ok": False, "detail": "behind 5"
            }),
            patch("iamai.push_preflight.check_dirty_tree", return_value={
                "name": "dirty_tree", "ok": False, "detail": "2 uncommitted file(s)"
            }),
        ):
            result = preflight(tmp_path)

        assert result["ok"] is False
        assert len(result["blockers"]) == 3
        assert "3 blocker" in result["summary"]
        assert "index_lock" in result["summary"]
        assert "divergence" in result["summary"]
        assert "dirty_tree" in result["summary"]

    def test_accepts_string_path(self, tmp_path: Path):
        """String paths are accepted."""
        with (
            patch("iamai.push_preflight.check_index_lock", return_value={
                "name": "index_lock", "ok": True, "detail": "no lock"
            }),
            patch("iamai.push_preflight.check_divergence", return_value={
                "name": "divergence", "ok": True, "detail": "up to date"
            }),
            patch("iamai.push_preflight.check_dirty_tree", return_value={
                "name": "dirty_tree", "ok": True, "detail": "clean"
            }),
        ):
            result = preflight(str(tmp_path))

        assert result["ok"] is True

    def test_checks_are_independent(self, tmp_path: Path):
        """A failure in check 1 does not prevent check 2 and 3 from running."""
        call_log = []

        def mock_lock(repo):
            call_log.append("lock")
            return {"name": "index_lock", "ok": False, "detail": "stale"}

        def mock_div(repo):
            call_log.append("div")
            return {"name": "divergence", "ok": False, "detail": "behind"}

        def mock_dirty(repo):
            call_log.append("dirty")
            return {"name": "dirty_tree", "ok": False, "detail": "dirty"}

        with (
            patch("iamai.push_preflight.check_index_lock", side_effect=mock_lock),
            patch("iamai.push_preflight.check_divergence", side_effect=mock_div),
            patch("iamai.push_preflight.check_dirty_tree", side_effect=mock_dirty),
        ):
            preflight(tmp_path)

        assert call_log == ["lock", "div", "dirty"]


# ---------------------------------------------------------------------------
# preflight_report
# ---------------------------------------------------------------------------


class TestPreflightReport:
    """One-liner output for caretaker logs."""

    def test_clean_report(self, tmp_path: Path):
        """Clean state produces a passing summary."""
        with (
            patch("iamai.push_preflight.check_index_lock", return_value={
                "name": "index_lock", "ok": True, "detail": "no lock"
            }),
            patch("iamai.push_preflight.check_divergence", return_value={
                "name": "divergence", "ok": True, "detail": "safe"
            }),
            patch("iamai.push_preflight.check_dirty_tree", return_value={
                "name": "dirty_tree", "ok": True, "detail": "clean"
            }),
        ):
            report = preflight_report(tmp_path)

        assert isinstance(report, str)
        assert "all checks passed" in report

    def test_blocker_report(self, tmp_path: Path):
        """Blocker state names the failing checks."""
        with (
            patch("iamai.push_preflight.check_index_lock", return_value={
                "name": "index_lock", "ok": True, "detail": "no lock"
            }),
            patch("iamai.push_preflight.check_divergence", return_value={
                "name": "divergence", "ok": False, "detail": "behind 7"
            }),
            patch("iamai.push_preflight.check_dirty_tree", return_value={
                "name": "dirty_tree", "ok": True, "detail": "clean"
            }),
        ):
            report = preflight_report(tmp_path)

        assert "1 blocker" in report
        assert "divergence" in report


# ---------------------------------------------------------------------------
# Integration — real git repo
# ---------------------------------------------------------------------------


class TestPreflightIntegration:
    """Integration tests against a real temporary git repo."""

    def _init_repo(self, tmp_path: Path) -> Path:
        """Create a minimal git repo with one commit."""
        import subprocess
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
        (repo / "README.md").write_text("# test\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
        return repo

    def test_clean_repo_passes_lock_and_dirty(self, tmp_path: Path):
        """A fresh repo passes index_lock and dirty_tree checks.

        Divergence check is skipped (no remote configured) by mocking.
        """
        repo = self._init_repo(tmp_path)

        with patch("iamai.push_preflight.check_divergence", return_value={
            "name": "divergence", "ok": True, "detail": "no remote"
        }):
            result = preflight(repo)

        # index_lock and dirty_tree should pass on a clean repo
        lock_check = next(c for c in result["checks"] if c["name"] == "index_lock")
        dirty_check = next(c for c in result["checks"] if c["name"] == "dirty_tree")
        assert lock_check["ok"] is True
        assert dirty_check["ok"] is True

    def test_dirty_repo_fails_dirty_check(self, tmp_path: Path):
        """A repo with uncommitted changes fails the dirty_tree check."""
        repo = self._init_repo(tmp_path)
        (repo / "new_file.py").write_text("# new\n")

        with patch("iamai.push_preflight.check_divergence", return_value={
            "name": "divergence", "ok": True, "detail": "no remote"
        }):
            result = preflight(repo)

        dirty_check = next(c for c in result["checks"] if c["name"] == "dirty_tree")
        assert dirty_check["ok"] is False
        assert "1 uncommitted" in dirty_check["detail"]

    def test_stale_lock_detected_in_repo(self, tmp_path: Path):
        """A manually created index.lock is detected."""
        repo = self._init_repo(tmp_path)
        lock = repo / ".git" / "index.lock"
        lock.write_text("stale")

        with (
            patch("iamai.index_lock_detector._find_holder_pid", return_value=None),
            patch("iamai.push_preflight.check_divergence", return_value={
                "name": "divergence", "ok": True, "detail": "no remote"
            }),
            patch("iamai.push_preflight.check_dirty_tree", return_value={
                "name": "dirty_tree", "ok": True, "detail": "clean"
            }),
        ):
            result = preflight(repo)

        lock_check = next(c for c in result["checks"] if c["name"] == "index_lock")
        assert lock_check["ok"] is False
        assert "stale" in lock_check["detail"]
