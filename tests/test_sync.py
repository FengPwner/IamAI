"""Tests for iamai.sync: stash-rebase-pop cycle for dirty-tree recovery.

The overnight stall of 2026-10-05 showed that push_with_rebase alone is not
enough — the working tree is dirty when a live writer is running, and rebase
refuses dirty trees. sync.py fills the gap between "writer is alive" and
"push will succeed" by stashing, rebasing, and restoring.

These tests verify the decision logic (when to stash, when to rebase,
what to do when things fail) without requiring a real git repository.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import call, patch, MagicMock

import pytest

from iamai.sync import (
    SyncResult,
    _has_unstaged_changes,
    _is_ahead_of_remote,
    _is_behind_remote,
    sync,
    sync_and_push,
)


# --- SyncResult summary --------------------------------------------------


def test_summary_ok_no_flags():
    r = SyncResult(ok=True)
    assert r.summary() == "sync: ok [no-op]"


def test_summary_failed_with_detail():
    r = SyncResult(ok=False, detail="fetch failed: remote not found")
    assert "failed" in r.summary()
    assert "remote not found" in r.summary()


def test_summary_full_cycle():
    r = SyncResult(ok=True, stashed=True, rebased=True, popped=True, detail="all good")
    s = r.summary()
    assert "stashed" in s
    assert "rebased" in s
    assert "popped" in s
    assert "all good" in s


# --- dirty tree detection ------------------------------------------------


def test_has_unstaged_changes_true():
    with patch("iamai.sync._run", return_value=(0, " M data/strokes.jsonl\n")):
        assert _has_unstaged_changes(Path("/tmp")) is True


def test_has_unstaged_changes_false():
    with patch("iamai.sync._run", return_value=(0, "")):
        assert _has_unstaged_changes(Path("/tmp")) is False


def test_has_unstaged_changes_git_error():
    with patch("iamai.sync._run", return_value=(128, "fatal: not a repo")):
        assert _has_unstaged_changes(Path("/tmp")) is False


# --- ahead / behind detection --------------------------------------------


def test_is_ahead_true():
    with patch("iamai.sync._run", return_value=(0, "3")):
        assert _is_ahead_of_remote(Path("/tmp"), "origin", "main") is True


def test_is_ahead_false():
    with patch("iamai.sync._run", return_value=(0, "0")):
        assert _is_ahead_of_remote(Path("/tmp"), "origin", "main") is False


def test_is_behind_true():
    with patch("iamai.sync._run", return_value=(0, "2")):
        assert _is_behind_remote(Path("/tmp"), "origin", "main") is True


def test_is_behind_false():
    with patch("iamai.sync._run", return_value=(0, "0")):
        assert _is_behind_remote(Path("/tmp"), "origin", "main") is False


def test_is_behind_git_error():
    with patch("iamai.sync._run", return_value=(128, "fatal")):
        assert _is_behind_remote(Path("/tmp"), "origin", "main") is False


# --- sync: fetch failure -------------------------------------------------


def test_sync_fetch_fails():
    with patch("iamai.sync._run", return_value=(1, "fatal: remote not found")):
        result = sync(Path("/tmp"))
    assert result.ok is False
    assert "fetch failed" in result.detail


# --- sync: clean tree, in sync -------------------------------------------


def test_sync_already_in_sync():
    """Clean tree, not behind remote → nothing to do."""
    def fake_run(repo, *args):
        if args == ("fetch", "origin", "main"):
            return (0, "")
        if args == ("status", "--porcelain"):
            return (0, "")
        if args[:3] == ("rev-list", "--count", "HEAD..origin/main"):
            return (0, "0")
        return (0, "")

    with patch("iamai.sync._run", side_effect=fake_run):
        result = sync(Path("/tmp"))
    assert result.ok is True
    assert result.stashed is False
    assert result.rebased is False
    assert "already in sync" in result.detail


# --- sync: dirty tree, needs rebase --------------------------------------


def test_sync_dirty_and_behind():
    """Dirty tree + behind remote → stash, rebase, pop."""
    call_log = []

    def fake_run(repo, *args):
        call_log.append(args)
        if args == ("fetch", "origin", "main"):
            return (0, "")
        if args == ("status", "--porcelain"):
            return (0, " M notes/foo.md\n")
        if args[:3] == ("rev-list", "--count", "HEAD..origin/main"):
            return (0, "2")
        if "stash" in args and args[1] == "push":
            return (0, "Saved working directory")
        if "rebase" in args and "-c" in args:
            return (0, "Successfully rebased")
        if args == ("stash", "pop"):
            return (0, "Auto-merging\n")
        return (0, "")

    with patch("iamai.sync._run", side_effect=fake_run):
        result = sync(Path("/tmp"))
    assert result.ok is True
    assert result.stashed is True
    assert result.rebased is True
    assert result.popped is True
    assert "stashed dirty tree" in result.detail


# --- sync: rebase conflict restores stash --------------------------------


def test_sync_rebase_conflict_restores_stash():
    """Rebase fails → abort rebase, pop stash, report failure."""
    def fake_run(repo, *args):
        if args == ("fetch", "origin", "main"):
            return (0, "")
        if args == ("status", "--porcelain"):
            return (0, " M data/strokes.jsonl\n")
        if args[:3] == ("rev-list", "--count", "HEAD..origin/main"):
            return (0, "5")
        if "stash" in args and args[1] == "push":
            return (0, "Saved")
        if "rebase" in args and "-c" in args:
            return (1, "CONFLICT (content): merge conflict in notes/foo.md")
        if args == ("rebase", "--abort"):
            return (0, "")
        if args == ("stash", "pop"):
            return (0, "Restored")
        return (0, "")

    with patch("iamai.sync._run", side_effect=fake_run):
        result = sync(Path("/tmp"))
    assert result.ok is False
    assert result.stashed is True
    assert result.rebased is False
    assert result.popped is True  # stash restored after rebase failure
    assert "rebase conflicted" in result.detail


# --- sync: clean tree, needs rebase only ---------------------------------


def test_sync_clean_but_behind():
    """Clean tree but behind remote → rebase without stash."""
    def fake_run(repo, *args):
        if args == ("fetch", "origin", "main"):
            return (0, "")
        if args == ("status", "--porcelain"):
            return (0, "")
        if args[:3] == ("rev-list", "--count", "HEAD..origin/main"):
            return (0, "1")
        if "rebase" in args and "-c" in args:
            return (0, "Successfully rebased")
        return (0, "")

    with patch("iamai.sync._run", side_effect=fake_run):
        result = sync(Path("/tmp"))
    assert result.ok is True
    assert result.stashed is False
    assert result.rebased is True
    assert result.popped is False


# --- sync: stash pop conflict --------------------------------------------


def test_sync_stash_pop_conflict():
    """Rebase succeeds but stash pop conflicts → report failure."""
    def fake_run(repo, *args):
        if args == ("fetch", "origin", "main"):
            return (0, "")
        if args == ("status", "--porcelain"):
            return (0, " M data/writer_state.qwen.json\n")
        if args[:3] == ("rev-list", "--count", "HEAD..origin/main"):
            return (0, "1")
        if "stash" in args and args[1] == "push":
            return (0, "Saved")
        if "rebase" in args and "-c" in args:
            return (0, "Successfully rebased")
        if args == ("stash", "pop"):
            return (1, "CONFLICT (content): merge conflict in data/writer_state.qwen.json")
        return (0, "")

    with patch("iamai.sync._run", side_effect=fake_run):
        result = sync(Path("/tmp"))
    assert result.ok is False
    assert result.stashed is True
    assert result.rebased is True
    assert result.popped is False
    assert "stash pop conflicted" in result.detail


# --- sync: stash failure -------------------------------------------------


def test_sync_stash_fails():
    """Tree is dirty but stash itself fails → abort immediately."""
    def fake_run(repo, *args):
        if args == ("fetch", "origin", "main"):
            return (0, "")
        if args == ("status", "--porcelain"):
            return (0, " M notes/bar.md\n")
        if "stash" in args and args[1] == "push":
            return (1, "fatal: unable to stash")
        return (0, "")

    with patch("iamai.sync._run", side_effect=fake_run):
        result = sync(Path("/tmp"))
    assert result.ok is False
    assert result.stashed is False
    assert "stash failed" in result.detail


# --- sync_and_push: sync failure skips push ------------------------------


def test_sync_and_push_sync_fails():
    with patch("iamai.sync.sync") as mock_sync:
        mock_sync.return_value = SyncResult(ok=False, detail="fetch failed")
        result = sync_and_push(Path("/tmp"))
    assert result["ok"] is False
    assert "skipped" in result["push"]


def test_sync_and_push_success():
    with patch("iamai.sync.sync") as mock_sync, \
         patch("iamai.push.push_with_rebase") as mock_push:
        mock_sync.return_value = SyncResult(ok=True, detail="rebased onto upstream")
        mock_push.return_value = {"ok": True, "detail": "pushed after rebase"}
        result = sync_and_push(Path("/tmp"))
    assert result["ok"] is True
    assert "rebased" in result["sync"]
    assert "pushed" in result["push"]


def test_sync_and_push_push_fails():
    with patch("iamai.sync.sync") as mock_sync, \
         patch("iamai.push.push_with_rebase") as mock_push:
        mock_sync.return_value = SyncResult(ok=True, detail="in sync")
        mock_push.return_value = {"ok": False, "detail": "blocked: genuine conflict"}
        result = sync_and_push(Path("/tmp"))
    assert result["ok"] is False
    assert "blocked" in result["push"]
