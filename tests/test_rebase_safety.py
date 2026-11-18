"""Tests for iamai.rebase_safety — pre-rebase environment checks.

Covers all four individual checks plus the aggregate assess() function,
edge cases around stale PID files, missing sentinels, and the
remediation-plan generator.

Written by Qwen during caretaker visit 695, 2026-11-18.
"""

from __future__ import annotations

import os
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.rebase_safety import (
    RebaseReadiness,
    SafetyCheck,
    Verdict,
    assess,
    check_batch_liveness,
    check_dirty_state,
    check_pause_signal,
    check_process_liveness,
    verdict_to_dict,
    WRITER_MANAGED_FILES,
    PAUSE_PATTERN,
    WRITER_PID_PATTERN,
    BATCH_PID_PATTERN,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_repo(tmp_path):
    """Create a minimal repo layout with writer-managed files."""
    for rel in WRITER_MANAGED_FILES:
        fp = tmp_path / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text("# stub\n")
    return tmp_path


@pytest.fixture
def fake_pid_file(tmp_path):
    """Helper that writes a PID file and returns (path, pid)."""
    def _write(pid: int, kind: str = "writer", writer: str = "qwen"):
        if kind == "writer":
            pattern = WRITER_PID_PATTERN
        else:
            pattern = BATCH_PID_PATTERN
        pid_path = Path(pattern.format(writer=writer))
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(pid))
        return pid_path
    return _write


# ---------------------------------------------------------------------------
# check_pause_signal
# ---------------------------------------------------------------------------

class TestCheckPauseSignal:
    def test_missing_pause_is_blocking(self):
        pause = Path(PAUSE_PATTERN.format(writer="test_nopause"))
        pause.unlink(missing_ok=True)
        result = check_pause_signal("/nonexistent", writer="test_nopause")
        assert not result.passed
        assert result.severity == "blocking"
        assert "missing" in result.detail

    def test_present_pause_passes(self, tmp_path):
        pause = Path(PAUSE_PATTERN.format(writer="test_haspause"))
        pause.parent.mkdir(parents=True, exist_ok=True)
        pause.touch()
        try:
            result = check_pause_signal(str(tmp_path), writer="test_haspause")
            assert result.passed
            assert "exists" in result.detail
        finally:
            pause.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# check_dirty_state
# ---------------------------------------------------------------------------

class TestCheckDirtyState:
    def test_clean_tree_passes(self, tmp_repo):
        result = check_dirty_state(str(tmp_repo))
        assert result.passed

    def test_empty_tree_passes(self, tmp_path):
        result = check_dirty_state(str(tmp_path))
        assert result.passed

    def test_custom_managed_list(self, tmp_path):
        fp = tmp_path / "custom.txt"
        fp.write_text("data")
        result = check_dirty_state(str(tmp_path), writer_managed=["custom.txt"])
        assert result.passed  # presence alone is not dirty

    def test_nonexistent_managed_files(self, tmp_path):
        result = check_dirty_state(
            str(tmp_path),
            writer_managed=["does/not/exist.txt"],
        )
        assert result.passed


# ---------------------------------------------------------------------------
# check_process_liveness
# ---------------------------------------------------------------------------

class TestCheckProcessLiveness:
    def test_no_pid_file_passes(self):
        # Ensure PID file does not exist.
        pid_path = Path(WRITER_PID_PATTERN.format(writer="test_nopid"))
        pid_path.unlink(missing_ok=True)
        result = check_process_liveness(writer="test_nopid")
        assert result.passed
        assert "not running" in result.detail

    def test_stale_pid_passes(self):
        # Use PID 99999999 — extremely unlikely to exist.
        pid_path = Path(WRITER_PID_PATTERN.format(writer="test_stale"))
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text("99999999")
        try:
            result = check_process_liveness(writer="test_stale")
            assert result.passed
            assert "stale" in result.detail
        finally:
            pid_path.unlink(missing_ok=True)

    def test_corrupt_pid_file(self):
        pid_path = Path(WRITER_PID_PATTERN.format(writer="test_corrupt"))
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text("not_a_number\n")
        try:
            result = check_process_liveness(writer="test_corrupt")
            assert not result.passed
            assert result.severity == "warning"
        finally:
            pid_path.unlink(missing_ok=True)

    def test_alive_pid_blocks(self):
        # Current process is guaranteed alive.
        my_pid = os.getpid()
        pid_path = Path(WRITER_PID_PATTERN.format(writer="test_alive"))
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(my_pid))
        try:
            result = check_process_liveness(writer="test_alive")
            assert not result.passed
            assert result.severity == "blocking"
            assert "alive" in result.detail
        finally:
            pid_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# check_batch_liveness
# ---------------------------------------------------------------------------

class TestCheckBatchLiveness:
    def test_no_pid_file_passes(self):
        pid_path = Path(BATCH_PID_PATTERN.format(writer="test_nobatch"))
        pid_path.unlink(missing_ok=True)
        result = check_batch_liveness(writer="test_nobatch")
        assert result.passed

    def test_alive_batch_blocks(self):
        my_pid = os.getpid()
        pid_path = Path(BATCH_PID_PATTERN.format(writer="test_batchalive"))
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(my_pid))
        try:
            result = check_batch_liveness(writer="test_batchalive")
            assert not result.passed
            assert result.severity == "blocking"
        finally:
            pid_path.unlink(missing_ok=True)

    def test_stale_batch_passes(self):
        pid_path = Path(BATCH_PID_PATTERN.format(writer="test_batchstale"))
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text("99999998")
        try:
            result = check_batch_liveness(writer="test_batchstale")
            assert result.passed
        finally:
            pid_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# assess() — aggregate
# ---------------------------------------------------------------------------

class TestAssess:
    def test_all_clear_is_safe(self, tmp_repo):
        """When no writer is running and pause exists, rebase is safe."""
        w = "test_clear"
        pause = Path(PAUSE_PATTERN.format(writer=w))
        pause.parent.mkdir(parents=True, exist_ok=True)
        pause.touch()
        for pattern in [WRITER_PID_PATTERN, BATCH_PID_PATTERN]:
            Path(pattern.format(writer=w)).unlink(missing_ok=True)
        try:
            v = assess(repo_root=str(tmp_repo), writer=w)
            assert v.ready
            assert v.status == RebaseReadiness.SAFE
            assert "✓" in v.summary
        finally:
            pause.unlink(missing_ok=True)

    def test_alive_writer_is_unsafe(self, tmp_repo):
        """Live writer without pause signal blocks the rebase."""
        w = "test_alive_w"
        my_pid = os.getpid()
        Path(PAUSE_PATTERN.format(writer=w)).unlink(missing_ok=True)
        for pattern in [WRITER_PID_PATTERN, BATCH_PID_PATTERN]:
            p = Path(pattern.format(writer=w))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(my_pid))
        try:
            v = assess(repo_root=str(tmp_repo), writer=w)
            assert not v.ready
            assert v.status == RebaseReadiness.UNSAFE
            assert len(v.remediation) > 0
        finally:
            for pattern in [WRITER_PID_PATTERN, BATCH_PID_PATTERN]:
                Path(pattern.format(writer=w)).unlink(missing_ok=True)

    def test_remediation_includes_kill_steps(self, tmp_repo):
        w = "test_kill"
        my_pid = os.getpid()
        Path(PAUSE_PATTERN.format(writer=w)).unlink(missing_ok=True)
        for pattern in [WRITER_PID_PATTERN, BATCH_PID_PATTERN]:
            p = Path(pattern.format(writer=w))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(my_pid))
        try:
            v = assess(repo_root=str(tmp_repo), writer=w)
            text = "\n".join(v.remediation)
            assert "kill" in text or "pause" in text.lower()
            assert "rebase" in text
        finally:
            for pattern in [WRITER_PID_PATTERN, BATCH_PID_PATTERN]:
                Path(pattern.format(writer=w)).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# verdict_to_dict
# ---------------------------------------------------------------------------

class TestVerdictSerialisation:
    def test_round_trip(self):
        v = Verdict(
            ready=True,
            status=RebaseReadiness.SAFE,
            checks=[
                SafetyCheck("test", True, "all good"),
            ],
            remediation=["step 1"],
        )
        d = verdict_to_dict(v)
        assert d["ready"] is True
        assert d["status"] == "safe"
        assert len(d["checks"]) == 1
        assert d["checks"][0]["name"] == "test"
        assert d["remediation"] == ["step 1"]

    def test_unsafe_dict(self):
        v = Verdict(
            ready=False,
            status=RebaseReadiness.UNSAFE,
            checks=[
                SafetyCheck("proc", False, "alive", "blocking"),
            ],
            remediation=["kill it"],
        )
        d = verdict_to_dict(v)
        assert d["ready"] is False
        assert d["status"] == "unsafe"
        assert d["checks"][0]["severity"] == "blocking"

    def test_json_serialisable(self):
        import json
        v = Verdict(
            ready=True,
            status=RebaseReadiness.SAFE,
            checks=[],
            remediation=[],
        )
        s = json.dumps(verdict_to_dict(v))
        assert '"safe"' in s


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_verdict_summary_counts(self):
        v = Verdict(
            ready=False,
            status=RebaseReadiness.UNSAFE,
            checks=[
                SafetyCheck("a", True, "ok"),
                SafetyCheck("b", False, "fail", "blocking"),
                SafetyCheck("c", True, "ok"),
            ],
        )
        assert "2/3" in v.summary
        assert "✗" in v.summary

    def test_empty_checks_is_safe(self):
        v = Verdict(ready=True, status=RebaseReadiness.SAFE)
        assert "0/0" in v.summary

    def test_different_writer_id(self, tmp_repo):
        """Using a non-default writer ID changes PID file paths."""
        w = "test_other_writer"
        for pattern in [WRITER_PID_PATTERN, BATCH_PID_PATTERN, PAUSE_PATTERN]:
            Path(pattern.format(writer=w)).unlink(missing_ok=True)
        v = assess(repo_root=str(tmp_repo), writer=w)
        # With no PID files and no pause, process checks pass
        # but pause check fails.
        pause_check = next(c for c in v.checks if c.name == "pause_signal")
        assert not pause_check.passed
