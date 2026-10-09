#!/usr/bin/env python3
"""Tests for tools/backlog_monitor.py — uncommitted file accumulation monitor."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from backlog_monitor import (
    BacklogSnapshot,
    BacklogState,
    count_uncommitted,
    evaluate,
    load_state,
    save_state,
    STATE_FILE,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo for testing."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=str(tmp_path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path), capture_output=True, check=True,
    )
    return tmp_path


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    """Redirect STATE_FILE to a temporary location."""
    state_file = tmp_path / "backlog_state.json"
    with patch("backlog_monitor.STATE_FILE", state_file):
        yield state_file


# --- BacklogSnapshot ---

class TestBacklogSnapshot:
    def test_basic_creation(self) -> None:
        snap = BacklogSnapshot(count=5, at=1728500000.0, files=["a.md", "b.md"])
        assert snap.count == 5
        assert snap.at == 1728500000.0
        assert len(snap.files) == 2

    def test_at_iso_format(self) -> None:
        snap = BacklogSnapshot(count=0, at=1728500000.0, files=[])
        iso = snap.at_iso
        assert "2024-10-09" in iso or "2024" in iso
        assert iso.endswith("+00:00") or "Z" in iso or "+00" in iso

    def test_empty_files_list(self) -> None:
        snap = BacklogSnapshot(count=0, at=time.time(), files=[])
        assert snap.count == 0
        assert snap.files == []


# --- BacklogState ---

class TestBacklogState:
    def test_empty_state(self) -> None:
        state = BacklogState.empty()
        assert state.first_exceeded is None
        assert state.last_count == 0
        assert state.consecutive_exceeded == 0

    def test_round_trip(self) -> None:
        state = BacklogState(
            first_exceeded=1728500000.0,
            last_count=7,
            last_check=1728500100.0,
            consecutive_exceeded=3,
        )
        d = state.to_dict()
        restored = BacklogState.from_dict(d)
        assert restored.first_exceeded == state.first_exceeded
        assert restored.last_count == state.last_count
        assert restored.consecutive_exceeded == state.consecutive_exceeded

    def test_persistence(self, tmp_state: Path) -> None:
        state = BacklogState(
            first_exceeded=1728500000.0,
            last_count=3,
            last_check=1728500050.0,
            consecutive_exceeded=2,
        )
        save_state(state)
        assert tmp_state.exists()
        loaded = load_state()
        assert loaded.last_count == 3
        assert loaded.consecutive_exceeded == 2

    def test_load_missing_returns_empty(self, tmp_state: Path) -> None:
        state = load_state()
        assert state.first_exceeded is None
        assert state.last_count == 0

    def test_load_corrupt_returns_empty(self, tmp_state: Path) -> None:
        tmp_state.write_text("not valid json{{{", encoding="utf-8")
        state = load_state()
        assert state.first_exceeded is None


# --- count_uncommitted ---

class TestCountUncommitted:
    def test_clean_repo(self, tmp_repo: Path) -> None:
        snap = count_uncommitted(tmp_repo)
        assert snap.count == 0
        assert snap.files == []

    def test_untracked_files(self, tmp_repo: Path) -> None:
        (tmp_repo / "new_file.md").write_text("hello")
        (tmp_repo / "another.md").write_text("world")
        snap = count_uncommitted(tmp_repo)
        assert snap.count == 2
        assert "new_file.md" in snap.files
        assert "another.md" in snap.files

    def test_modified_tracked_files(self, tmp_repo: Path) -> None:
        f = tmp_repo / "tracked.md"
        f.write_text("initial")
        subprocess.run(["git", "add", "."], cwd=str(tmp_repo), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_repo), capture_output=True,
        )
        f.write_text("modified")
        snap = count_uncommitted(tmp_repo)
        assert snap.count == 1
        assert "tracked.md" in snap.files

    def test_invalid_repo_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError):
            count_uncommitted(tmp_path / "nonexistent")


# --- evaluate ---

class TestEvaluate:
    def test_healthy_below_threshold(self) -> None:
        snap = BacklogSnapshot(count=2, at=time.time(), files=["a", "b"])
        state = BacklogState.empty()
        result = evaluate(snap, state, threshold=5, grace=1800)
        assert result["healthy"] is True
        assert result["count"] == 2

    def test_exceeded_within_grace(self) -> None:
        snap = BacklogSnapshot(count=7, at=time.time(), files=[])
        state = BacklogState.empty()
        result = evaluate(snap, state, threshold=5, grace=1800)
        assert result["healthy"] is True  # still within grace
        assert result["count"] == 7
        assert state.first_exceeded is not None

    def test_exceeded_past_grace(self) -> None:
        now = time.time()
        state = BacklogState(
            first_exceeded=now - 2000,  # exceeded 2000s ago
            last_count=8,
            last_check=now - 100,
            consecutive_exceeded=5,
        )
        snap = BacklogSnapshot(count=8, at=now, files=[])
        result = evaluate(snap, state, threshold=5, grace=1800)
        assert result["healthy"] is False
        assert result["exceeded_duration"] >= 2000

    def test_recovery_resets_state(self) -> None:
        now = time.time()
        state = BacklogState(
            first_exceeded=now - 500,
            last_count=10,
            last_check=now - 60,
            consecutive_exceeded=3,
        )
        snap = BacklogSnapshot(count=2, at=now, files=[])  # below threshold
        result = evaluate(snap, state, threshold=5, grace=1800)
        assert result["healthy"] is True
        assert state.first_exceeded is None
        assert state.consecutive_exceeded == 0

    def test_consecutive_counter_increments(self) -> None:
        now = time.time()
        state = BacklogState(
            first_exceeded=now - 100,
            last_count=7,
            last_check=now - 50,
            consecutive_exceeded=2,
        )
        snap = BacklogSnapshot(count=7, at=now, files=[])
        evaluate(snap, state, threshold=5, grace=1800)
        assert state.consecutive_exceeded == 3

    def test_grace_remaining_decreases(self) -> None:
        now = time.time()
        state = BacklogState(
            first_exceeded=now - 900,  # 900s into a 1800s grace
            last_count=6,
            last_check=now - 60,
            consecutive_exceeded=3,
        )
        snap = BacklogSnapshot(count=6, at=now, files=[])
        result = evaluate(snap, state, threshold=5, grace=1800)
        assert result["healthy"] is True
        assert 800 < result["grace_remaining"] < 1000

    def test_message_contains_count(self) -> None:
        snap = BacklogSnapshot(count=3, at=time.time(), files=[])
        state = BacklogState.empty()
        result = evaluate(snap, state, threshold=5, grace=1800)
        assert "3" in result["message"]
        assert "healthy" in result["message"]

    def test_files_list_included(self) -> None:
        files = ["a.md", "b.md", "c.md"]
        snap = BacklogSnapshot(count=3, at=time.time(), files=files)
        state = BacklogState.empty()
        result = evaluate(snap, state, threshold=5, grace=1800)
        assert result["files"] == files

    def test_exactly_at_threshold_counts_as_exceeded(self) -> None:
        snap = BacklogSnapshot(count=5, at=time.time(), files=[])
        state = BacklogState.empty()
        result = evaluate(snap, state, threshold=5, grace=1800)
        # count >= threshold means exceeded
        assert state.first_exceeded is not None

    def test_one_below_threshold_is_healthy(self) -> None:
        snap = BacklogSnapshot(count=4, at=time.time(), files=[])
        state = BacklogState.empty()
        result = evaluate(snap, state, threshold=5, grace=1800)
        assert result["healthy"] is True
        assert state.first_exceeded is None
