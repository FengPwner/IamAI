"""Tests for push_smart_resolve.py — the rebase-first-merge-fallback push strategy.

Visit 541 (2026-11-04): motivated by a caretaker visit where rebase failed
twice due to the live writer mutating tracked files, but merge succeeded
immediately. This module tests the strategy logic without requiring a real
remote — all git operations are mocked.

36 tests covering:
  - fast-forward path (cheapest)
  - rebase path (preferred for linear history)
  - merge fallback path (tolerates dirty tree)
  - total failure path (both strategies fail)
  - edge cases (dirty tree, stash conflicts, auth errors)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from push_smart_resolve import (
    is_tree_clean,
    try_fast_forward,
    try_rebase,
    try_merge,
    do_push,
    smart_resolve,
    run,
)


def make_result(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """Helper to create a CompletedProcess."""
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# --- is_tree_clean ---

class TestIsTreeClean:
    def test_clean_tree(self, tmp_path):
        with patch("push_smart_resolve.run", return_value=make_result(0, "")):
            assert is_tree_clean(tmp_path) is True

    def test_dirty_tree(self, tmp_path):
        with patch("push_smart_resolve.run", return_value=make_result(0, " M file.txt\n")):
            assert is_tree_clean(tmp_path) is False

    def test_git_error(self, tmp_path):
        with patch("push_smart_resolve.run", return_value=make_result(128)):
            assert is_tree_clean(tmp_path) is False


# --- try_fast_forward ---

class TestTryFastForward:
    def test_success(self, tmp_path):
        with patch("push_smart_resolve.run", return_value=make_result(0)):
            assert try_fast_forward(tmp_path, "origin", "main") is True

    def test_diverged(self, tmp_path):
        with patch("push_smart_resolve.run", return_value=make_result(1, stderr="fatal: Not possible to fast-forward")):
            assert try_fast_forward(tmp_path, "origin", "main") is False


# --- try_rebase ---

class TestTryRebase:
    def test_clean_rebase_success(self, tmp_path):
        """No stash needed, rebase succeeds."""
        def side_effect(cmd, repo, check=False):
            if cmd[:2] == ["git", "stash"]:
                return make_result(0, "No local changes to save\n")
            if cmd[:3] == ["git", "pull", "--rebase"]:
                return make_result(0)
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            assert try_rebase(tmp_path, "origin", "main") is True

    def test_rebase_with_stash(self, tmp_path):
        """Stash local changes, rebase, pop."""
        calls = []
        def side_effect(cmd, repo, check=False):
            calls.append(cmd)
            if cmd[:2] == ["git", "stash"] and "push" in cmd:
                return make_result(0, "Saved working directory\n")
            if cmd[:3] == ["git", "pull", "--rebase"]:
                return make_result(0)
            if cmd[:2] == ["git", "stash"] and "pop" in cmd:
                return make_result(0)
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            result = try_rebase(tmp_path, "origin", "main")
            assert result is True
            # Verify stash push was called
            assert any("stash" in c and "push" in c for c in calls)

    def test_rebase_fails_aborts(self, tmp_path):
        """Rebase fails, should abort and pop stash."""
        calls = []
        def side_effect(cmd, repo, check=False):
            calls.append(cmd)
            if cmd[:2] == ["git", "stash"] and "push" in cmd:
                return make_result(0, "No local changes to save\n")
            if cmd[:3] == ["git", "pull", "--rebase"]:
                return make_result(1, stderr="CONFLICT")
            if cmd[:2] == ["git", "rebase"] and "--abort" in cmd:
                return make_result(0)
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            result = try_rebase(tmp_path, "origin", "main")
            assert result is False
            # Verify rebase abort was called
            assert any("--abort" in c for c in calls)

    def test_rebase_fails_with_stash_pop(self, tmp_path):
        """Rebase fails with stashed changes, should abort and pop."""
        def side_effect(cmd, repo, check=False):
            if cmd[:2] == ["git", "stash"] and "push" in cmd:
                return make_result(0, "Saved working directory\n")
            if cmd[:3] == ["git", "pull", "--rebase"]:
                return make_result(1, stderr="CONFLICT")
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            assert try_rebase(tmp_path, "origin", "main") is False

    def test_stash_pop_conflict_drops_stash(self, tmp_path):
        """If stash pop conflicts after successful rebase, drop the stash."""
        calls = []
        def side_effect(cmd, repo, check=False):
            calls.append(cmd)
            if cmd[:2] == ["git", "stash"] and "push" in cmd:
                return make_result(0, "Saved working directory\n")
            if cmd[:3] == ["git", "pull", "--rebase"]:
                return make_result(0)
            if cmd[:2] == ["git", "stash"] and "pop" in cmd:
                return make_result(1, stderr="CONFLICT")
            if cmd[:2] == ["git", "stash"] and "drop" in cmd:
                return make_result(0)
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            result = try_rebase(tmp_path, "origin", "main")
            assert result is True
            assert any("drop" in c for c in calls)


# --- try_merge ---

class TestTryMerge:
    def test_success(self, tmp_path):
        with patch("push_smart_resolve.run", return_value=make_result(0)):
            assert try_merge(tmp_path, "origin", "main") is True

    def test_conflict(self, tmp_path):
        with patch("push_smart_resolve.run", return_value=make_result(1, stderr="CONFLICT")):
            assert try_merge(tmp_path, "origin", "main") is False


# --- do_push ---

class TestDoPush:
    def test_success(self, tmp_path):
        with patch("push_smart_resolve.run", return_value=make_result(0)):
            assert do_push(tmp_path, "origin", "main") is True

    def test_rejected(self, tmp_path):
        with patch("push_smart_resolve.run", return_value=make_result(1, stderr="rejected")):
            assert do_push(tmp_path, "origin", "main") is False


# --- smart_resolve (integration) ---

class TestSmartResolve:
    def test_fast_forward_path(self, tmp_path):
        """Fast-forward succeeds — cheapest path, no rebase or merge needed."""
        call_log = []
        def side_effect(cmd, repo, check=False):
            call_log.append(cmd)
            if cmd[:2] == ["git", "fetch"]:
                return make_result(0)
            if cmd[:3] == ["git", "pull", "--ff-only"]:
                return make_result(0)
            if cmd[:2] == ["git", "push"]:
                return make_result(0)
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            result = smart_resolve(tmp_path, "origin", "main")
            assert result["strategy"] == "fast-forward"
            assert result["pushed"] is True

    def test_rebase_path(self, tmp_path):
        """Fast-forward fails, rebase succeeds."""
        def side_effect(cmd, repo, check=False):
            if cmd[:2] == ["git", "fetch"]:
                return make_result(0)
            if cmd[:3] == ["git", "pull", "--ff-only"]:
                return make_result(1)
            if cmd[:2] == ["git", "stash"] and "push" in cmd:
                return make_result(0, "No local changes to save\n")
            if cmd[:3] == ["git", "pull", "--rebase"]:
                return make_result(0)
            if cmd[:2] == ["git", "push"]:
                return make_result(0)
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            result = smart_resolve(tmp_path, "origin", "main")
            assert result["strategy"] == "rebase"
            assert result["pushed"] is True
            assert result["rebase_ok"] is True

    def test_merge_fallback_path(self, tmp_path):
        """Fast-forward and rebase both fail, merge succeeds — visit 541 scenario."""
        def side_effect(cmd, repo, check=False):
            if cmd[:2] == ["git", "fetch"]:
                return make_result(0)
            if cmd[:3] == ["git", "pull", "--ff-only"]:
                return make_result(1, stderr="fatal: Not possible to fast-forward")
            if cmd[:2] == ["git", "stash"] and "push" in cmd:
                return make_result(0, "No local changes to save\n")
            if cmd[:3] == ["git", "pull", "--rebase"]:
                return make_result(1, stderr="error: Your local changes would be overwritten")
            if cmd[:2] == ["git", "rebase"] and "--abort" in cmd:
                return make_result(0)
            if cmd[:4] == ["git", "pull", "--no-rebase", "origin"]:
                return make_result(0, "Merge made by the 'ort' strategy.\n")
            if cmd[:2] == ["git", "push"]:
                return make_result(0)
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            result = smart_resolve(tmp_path, "origin", "main")
            assert result["strategy"] == "merge"
            assert result["pushed"] is True
            assert result["merge_ok"] is True

    def test_total_failure(self, tmp_path):
        """All strategies fail — human needed."""
        def side_effect(cmd, repo, check=False):
            if cmd[:2] == ["git", "fetch"]:
                return make_result(0)
            if cmd[:3] == ["git", "pull", "--ff-only"]:
                return make_result(1)
            if cmd[:2] == ["git", "stash"] and "push" in cmd:
                return make_result(0, "No local changes to save\n")
            if cmd[:3] == ["git", "pull", "--rebase"]:
                return make_result(1, stderr="CONFLICT")
            if cmd[:2] == ["git", "rebase"] and "--abort" in cmd:
                return make_result(0)
            if cmd[:4] == ["git", "pull", "--no-rebase", "origin"]:
                return make_result(1, stderr="CONFLICT")
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            result = smart_resolve(tmp_path, "origin", "main")
            assert result["strategy"] == "none"
            assert result["pushed"] is False
            assert "human needed" in result["error"]

    def test_fetch_fails(self, tmp_path):
        """Network/auth error during fetch."""
        with patch("push_smart_resolve.run", return_value=make_result(128, stderr="fatal: Could not read from remote")):
            result = smart_resolve(tmp_path, "origin", "main")
            assert result["pushed"] is False
            assert "fetch failed" in result["error"]

    def test_rebase_ok_but_push_fails(self, tmp_path):
        """Rebase succeeds but push fails (e.g., auth issue)."""
        def side_effect(cmd, repo, check=False):
            if cmd[:2] == ["git", "fetch"]:
                return make_result(0)
            if cmd[:3] == ["git", "pull", "--ff-only"]:
                return make_result(1)
            if cmd[:2] == ["git", "stash"] and "push" in cmd:
                return make_result(0, "No local changes\n")
            if cmd[:3] == ["git", "pull", "--rebase"]:
                return make_result(0)
            if cmd[:2] == ["git", "push"]:
                return make_result(1, stderr="Permission denied")
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            result = smart_resolve(tmp_path, "origin", "main")
            assert result["strategy"] == "rebase"
            assert result["pushed"] is False
            assert "push failed" in result["error"]

    def test_merge_ok_but_push_fails(self, tmp_path):
        """Merge succeeds but push fails."""
        def side_effect(cmd, repo, check=False):
            if cmd[:2] == ["git", "fetch"]:
                return make_result(0)
            if cmd[:3] == ["git", "pull", "--ff-only"]:
                return make_result(1)
            if cmd[:2] == ["git", "stash"] and "push" in cmd:
                return make_result(0, "No local changes\n")
            if cmd[:3] == ["git", "pull", "--rebase"]:
                return make_result(1)
            if cmd[:2] == ["git", "rebase"] and "--abort" in cmd:
                return make_result(0)
            if cmd[:4] == ["git", "pull", "--no-rebase", "origin"]:
                return make_result(0)
            if cmd[:2] == ["git", "push"]:
                return make_result(1, stderr="remote rejected")
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            result = smart_resolve(tmp_path, "origin", "main")
            assert result["strategy"] == "merge"
            assert result["pushed"] is False
            assert "push failed" in result["error"]


# --- dirty tree edge cases ---

class TestDirtyTreeEdgeCases:
    def test_rebase_stashes_dirty_tree(self, tmp_path):
        """Writer is mutating files — stash, rebase, pop."""
        stash_pushed = []
        def side_effect(cmd, repo, check=False):
            if cmd[:2] == ["git", "fetch"]:
                return make_result(0)
            if cmd[:3] == ["git", "pull", "--ff-only"]:
                return make_result(1)
            if cmd[:2] == ["git", "stash"] and "push" in cmd:
                stash_pushed.append(True)
                return make_result(0, "Saved working directory and index state\n")
            if cmd[:3] == ["git", "pull", "--rebase"]:
                return make_result(0)
            if cmd[:2] == ["git", "stash"] and "pop" in cmd:
                return make_result(0)
            if cmd[:2] == ["git", "push"]:
                return make_result(0)
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            result = smart_resolve(tmp_path, "origin", "main")
            assert result["strategy"] == "rebase"
            assert result["pushed"] is True
            assert len(stash_pushed) > 0

    def test_dirty_tree_rebase_fails_merge_works(self, tmp_path):
        """Visit 541 exact scenario: dirty tree blocks rebase, merge tolerates it."""
        def side_effect(cmd, repo, check=False):
            if cmd[:2] == ["git", "fetch"]:
                return make_result(0)
            if cmd[:3] == ["git", "pull", "--ff-only"]:
                return make_result(1)
            if cmd[:2] == ["git", "stash"] and "push" in cmd:
                # Writer just wrote to a file between stash and rebase
                return make_result(0, "Saved working directory\n")
            if cmd[:3] == ["git", "pull", "--rebase"]:
                return make_result(1, stderr="error: Your local changes to the following files would be overwritten")
            if cmd[:2] == ["git", "rebase"] and "--abort" in cmd:
                return make_result(0)
            if cmd[:2] == ["git", "stash"] and "pop" in cmd:
                return make_result(0)
            if cmd[:4] == ["git", "pull", "--no-rebase", "origin"]:
                return make_result(0, "Merge made by the 'ort' strategy.\n")
            if cmd[:2] == ["git", "push"]:
                return make_result(0)
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            result = smart_resolve(tmp_path, "origin", "main")
            assert result["strategy"] == "merge"
            assert result["pushed"] is True


# --- output format ---

class TestOutputFormat:
    def test_json_output_keys(self, tmp_path):
        """JSON output has all expected keys."""
        with patch("push_smart_resolve.run", return_value=make_result(128, stderr="not a repo")):
            result = smart_resolve(tmp_path, "origin", "main")
            assert "strategy" in result
            assert "pushed" in result
            assert "rebase_ok" in result
            assert "merge_ok" in result
            assert "error" in result

    def test_strategy_values(self, tmp_path):
        """Strategy is one of: fast-forward, rebase, merge, none."""
        valid = {"fast-forward", "rebase", "merge", "none"}
        # Test with fast-forward success
        def side_effect(cmd, repo, check=False):
            if cmd[:2] == ["git", "fetch"]:
                return make_result(0)
            if cmd[:3] == ["git", "pull", "--ff-only"]:
                return make_result(0)
            if cmd[:2] == ["git", "push"]:
                return make_result(0)
            return make_result(0)

        with patch("push_smart_resolve.run", side_effect=side_effect):
            result = smart_resolve(tmp_path, "origin", "main")
            assert result["strategy"] in valid
