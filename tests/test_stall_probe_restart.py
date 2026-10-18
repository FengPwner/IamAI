"""Tests for stall_probe in post-restart verification scenarios.

When a caretaker restarts dead processes, the probe must distinguish:
  - process alive + strokes flowing → healthy (restart succeeded)
  - process alive + no new strokes → degraded (warmup or silent stall)
  - process alive + stale strokes → degraded (writer not recovered)

These tests cover the timing-sensitive state between "just restarted"
and "fully healthy", which is where most false-positive alerts come from.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.stall_probe import probe, probe_report


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, strokes: list[dict] | None = None) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    if strokes is not None:
        with open(data_dir / "strokes.jsonl", "w", encoding="utf-8") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
    return tmp_path


def _stroke(seconds_ago: float, kind: str = "thought") -> dict:
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return {"seq": 1, "at": ts.isoformat(), "kind": kind, "text": "post-restart test"}


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


# ---------------------------------------------------------------------------
# Post-restart: alive but not yet producing
# ---------------------------------------------------------------------------

class TestPostRestartImmediate:
    """Probe right after restart — process alive, strokes may be stale."""

    def test_alive_with_fresh_stroke_is_healthy(self, tmp_path: Path):
        """Best case: writer restarted and already produced a new stroke."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=5)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="qwen", cadence_seconds=15.0)
        assert result["verdict"] == "healthy"
        assert result["green_count"] == 4

    def test_alive_with_stale_stroke_is_degraded(self, tmp_path: Path):
        """Writer restarted but hasn't produced yet — strokes are old."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=600)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="qwen", cadence_seconds=15.0, fresh_threshold=5.0)
        assert result["verdict"] == "degraded"
        assert result["signals"]["stroke_fresh"] is False
        assert result["signals"]["writer_alive"] is True

    def test_alive_with_no_strokes_file_is_degraded(self, tmp_path: Path):
        """Fresh repo, no strokes.jsonl yet — stroke_fresh must be red."""
        repo = _make_repo(tmp_path, strokes=None)
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="qwen")
        assert result["signals"]["stroke_fresh"] is False
        # writer + batch alive + backlog ok = 3/4 → degraded
        assert result["verdict"] == "degraded"

    def test_alive_stroke_just_within_threshold(self, tmp_path: Path):
        """Stroke age exactly at the boundary — should still be fresh."""
        # fresh_threshold=5 × cadence=15 = 75s. Use 70s to be safely inside.
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=70)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="qwen", cadence_seconds=15.0, fresh_threshold=5.0)
        assert result["signals"]["stroke_fresh"] is True


# ---------------------------------------------------------------------------
# Signal combinations after restart
# ---------------------------------------------------------------------------

class TestPostRestartSignalCombos:
    """Various signal states a caretaker might see after triggering restart."""

    def test_writer_alive_batch_dead_fresh_stroke(self, tmp_path: Path):
        """Writer recovered but batch committer didn't — degraded."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=10)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", 99999999)  # dead
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="qwen")
        assert result["signals"]["writer_alive"] is True
        assert result["signals"]["batch_alive"] is False
        assert result["verdict"] == "degraded"

    def test_both_alive_stale_stroke_high_backlog(self, tmp_path: Path):
        """Processes running but pipeline stalled — stale + backlog high."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=1800)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        with patch("iamai.stall_probe._uncommitted_count", return_value=50):
            result = probe(repo, writer_id="qwen", cadence_seconds=15.0, fresh_threshold=5.0)
        # stroke_fresh=False, backlog_low=False → 2/4 → degraded (not stalled)
        # because writer_alive and batch_alive are both True
        assert result["signals"]["stroke_fresh"] is False
        assert result["signals"]["backlog_low"] is False
        assert result["green_count"] == 2
        assert result["verdict"] == "degraded"

    def test_writer_dead_batch_alive_normal_backlog(self, tmp_path: Path):
        """Writer died again right after restart — batch still running."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=30)])
        _write_pid(tmp_path / "data" / "writer-qwen.pid", 99999999)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", os.getpid())
        with patch("iamai.stall_probe._uncommitted_count", return_value=2):
            result = probe(repo, writer_id="qwen")
        assert result["signals"]["writer_alive"] is False
        assert result["signals"]["batch_alive"] is True
        assert result["verdict"] == "degraded"

    def test_all_signals_red_is_stalled(self, tmp_path: Path):
        """Worst case: nothing works after restart attempt."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=7200)])
        _write_pid(tmp_path / "data" / "writer-qwen.pid", 99999999)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", 99999999)
        with patch("iamai.stall_probe._uncommitted_count", return_value=100):
            result = probe(repo, writer_id="qwen", cadence_seconds=15.0, fresh_threshold=5.0)
        assert result["green_count"] == 0
        assert result["verdict"] == "stalled"


# ---------------------------------------------------------------------------
# Edge cases and boundary conditions
# ---------------------------------------------------------------------------

class TestPostRestartEdgeCases:
    """Boundary conditions that trip up caretakers reading probe output."""

    def test_missing_pid_files_safe(self, tmp_path: Path):
        """No PID files at all — probe doesn't crash, signals go red."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=10)])
        with patch("iamai.stall_probe._pid_alive", return_value=False), \
             patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="totally_nonexistent_writer_xyz")
        assert result["signals"]["writer_alive"] is False
        assert result["signals"]["batch_alive"] is False

    def test_zero_fresh_threshold_always_stale(self, tmp_path: Path):
        """fresh_threshold=0 means even a 0-second-old stroke is stale."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=0.001)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="qwen", cadence_seconds=15.0, fresh_threshold=0.0)
        # 0 × 15 = 0s threshold; any age > 0 is stale
        assert result["signals"]["stroke_fresh"] is False

    def test_zero_backlog_threshold_any_change_triggers(self, tmp_path: Path):
        """backlog_threshold=0 means even 1 uncommitted file is too many."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=5)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        with patch("iamai.stall_probe._uncommitted_count", return_value=1):
            result = probe(repo, writer_id="qwen", backlog_threshold=0)
        assert result["signals"]["backlog_low"] is False

    def test_degraded_report_shows_correct_count(self, tmp_path: Path):
        """probe_report for degraded state shows 2/4 or 3/4."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=600)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        # stroke stale + backlog high = 2/4 → degraded
        with patch("iamai.stall_probe._uncommitted_count", return_value=50):
            report = probe_report(repo, writer_id="qwen", cadence_seconds=15.0,
                                  fresh_threshold=5.0, backlog_threshold=20)
        assert "degraded" in report
        assert "2/4" in report

    def test_one_signal_off_is_degraded(self, tmp_path: Path):
        """3/4 green (one signal off) is still degraded, not healthy."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=10)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        # Only backlog is bad
        with patch("iamai.stall_probe._uncommitted_count", return_value=25):
            result = probe(repo, writer_id="qwen", backlog_threshold=20)
        assert result["green_count"] == 3
        assert result["verdict"] == "degraded"

    def test_all_green_after_recovery(self, tmp_path: Path):
        """Simulate full recovery: writer caught up, batch committed, fresh."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=3)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="qwen", cadence_seconds=15.0)
            report = probe_report(repo, writer_id="qwen", cadence_seconds=15.0)
        assert result["verdict"] == "healthy"
        assert "healthy" in report
        assert "4/4" in report
