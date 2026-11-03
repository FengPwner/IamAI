"""Tests for iamai.push_reconcile — safe pull while writer is active."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

from iamai.push_reconcile import (
    ReconcileResult,
    _count_remote_commits,
    _has_uncommitted_changes,
    _is_clean_ahead,
    _is_state_file,
    _local_head,
    _parse_conflict_files,
    _pause_writer,
    _remote_head,
    _resume_writer,
    _wait_for_writer_quiet,
    reconcile_before_push,
    reconcile_summary,
    STATE_FILE_PATTERNS,
    TIMEOUTS,
)


# ---------------------------------------------------------------------------
# _is_state_file
# ---------------------------------------------------------------------------

class TestIsStateFile:
    def test_exact_match(self):
        assert _is_state_file("data/strokes.jsonl") is True

    def test_wildcard_match(self):
        assert _is_state_file("data/writer_state.qwen.json") is True
        assert _is_state_file("data/writer_state.guoban.json") is True

    def test_non_state_file(self):
        assert _is_state_file("notes/conventions.md") is False
        assert _is_state_file("iamai/watchdog.py") is False

    def test_partial_match_rejected(self):
        assert _is_state_file("data/other.jsonl") is False
        assert _is_state_file("notes/writer_state.qwen.json") is False

    def test_metrics_jsonl(self):
        assert _is_state_file("data/metrics.jsonl") is True


# ---------------------------------------------------------------------------
# _pause_writer / _resume_writer
# ---------------------------------------------------------------------------

class TestPauseResume:
    def test_pause_creates_file(self, tmp_path):
        with mock.patch("iamai.push_reconcile.Path") as mock_path:
            # Can't easily mock Path constructor, so test the real thing
            pass

    def test_pause_and_resume_roundtrip(self):
        writer_id = f"test-{int(time.time())}"
        pause_file = _pause_writer(writer_id)
        try:
            assert pause_file.exists()
            assert pause_file.name == f"iamai-writer-pause-{writer_id}"
        finally:
            _resume_writer(pause_file)
        assert not pause_file.exists()

    def test_resume_nonexistent_file(self):
        fake = Path("/tmp/iamai-writer-pause-nonexistent-test")
        # Should not raise.
        _resume_writer(fake)


# ---------------------------------------------------------------------------
# _parse_conflict_files
# ---------------------------------------------------------------------------

class TestParseConflictFiles:
    def test_single_conflict(self):
        output = "CONFLICT (content): Merge conflict in notes/foo.md\n"
        assert _parse_conflict_files(output) == ["notes/foo.md"]

    def test_multiple_conflicts(self):
        output = (
            "CONFLICT (content): Merge conflict in notes/foo.md\n"
            "CONFLICT (modify/delete): Merge conflict in data/bar.jsonl\n"
        )
        result = _parse_conflict_files(output)
        assert len(result) == 2
        assert "notes/foo.md" in result
        assert "data/bar.jsonl" in result

    def test_no_conflicts(self):
        output = "Auto-merging notes/foo.md\nFast-forward\n"
        assert _parse_conflict_files(output) == []

    def test_empty_output(self):
        assert _parse_conflict_files("") == []


# ---------------------------------------------------------------------------
# ReconcileResult
# ---------------------------------------------------------------------------

class TestReconcileResult:
    def test_to_dict(self):
        r = ReconcileResult(
            ok=True,
            strategy="rebase",
            remote_commits=3,
            stash_applied=True,
            conflict_files=["notes/foo.md"],
            duration_ms=1234,
            summary="pulled 3 commits",
        )
        d = r.to_dict()
        assert d["ok"] is True
        assert d["strategy"] == "rebase"
        assert d["remote_commits"] == 3
        assert d["stash_applied"] is True
        assert d["conflict_files"] == ["notes/foo.md"]
        assert d["duration_ms"] == 1234
        assert d["summary"] == "pulled 3 commits"

    def test_empty_conflict_files(self):
        r = ReconcileResult(
            ok=True,
            strategy="noop",
            remote_commits=0,
            stash_applied=False,
            conflict_files=[],
            duration_ms=50,
            summary="up to date",
        )
        assert r.conflict_files == []


# ---------------------------------------------------------------------------
# reconcile_summary
# ---------------------------------------------------------------------------

class TestReconcileSummary:
    def test_ok_summary(self):
        r = ReconcileResult(
            ok=True,
            strategy="rebase",
            remote_commits=1,
            stash_applied=False,
            conflict_files=[],
            duration_ms=500,
            summary="pulled 1 remote commit(s) via rebase",
        )
        s = reconcile_summary(r)
        assert "[OK]" in s
        assert "rebase" in s
        assert "1 remote" in s

    def test_fail_summary(self):
        r = ReconcileResult(
            ok=False,
            strategy="rebase",
            remote_commits=0,
            stash_applied=False,
            conflict_files=[],
            duration_ms=30000,
            summary="fetch failed: timeout",
        )
        s = reconcile_summary(r)
        assert "[FAIL]" in s
        assert "timeout" in s

    def test_summary_with_stash(self):
        r = ReconcileResult(
            ok=True,
            strategy="rebase",
            remote_commits=2,
            stash_applied=True,
            conflict_files=[],
            duration_ms=800,
            summary="pulled 2 via rebase, stash popped",
        )
        s = reconcile_summary(r)
        assert "stash" in s

    def test_summary_with_conflicts(self):
        r = ReconcileResult(
            ok=True,
            strategy="merge",
            remote_commits=1,
            stash_applied=True,
            conflict_files=["notes/foo.md"],
            duration_ms=1200,
            summary="1 conflict(s)",
        )
        s = reconcile_summary(r)
        assert "1 conflict" in s


# ---------------------------------------------------------------------------
# TIMEOUTS constant
# ---------------------------------------------------------------------------

class TestTimeouts:
    def test_all_phases_have_timeouts(self):
        expected = {"wait_writer", "stash", "pull", "pop"}
        assert set(TIMEOUTS.keys()) == expected

    def test_pull_timeout_is_longest(self):
        assert TIMEOUTS["pull"] > TIMEOUTS["stash"]
        assert TIMEOUTS["pull"] > TIMEOUTS["pop"]
        assert TIMEOUTS["pull"] > TIMEOUTS["wait_writer"]

    def test_all_timeouts_positive(self):
        for name, value in TIMEOUTS.items():
            assert value > 0, f"timeout {name} must be positive"


# ---------------------------------------------------------------------------
# STATE_FILE_PATTERNS
# ---------------------------------------------------------------------------

class TestStateFilePatterns:
    def test_patterns_nonempty(self):
        assert len(STATE_FILE_PATTERNS) > 0

    def test_strokes_jsonl_included(self):
        assert "data/strokes.jsonl" in STATE_FILE_PATTERNS
