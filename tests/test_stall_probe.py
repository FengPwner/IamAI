"""Tests for iamai.stall_probe — multi-signal health probe."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.stall_probe import (
    _last_stroke_age,
    _pid_alive,
    _uncommitted_count,
    probe,
    probe_report,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, strokes: list[dict] | None = None) -> Path:
    """Create a fake repo with data/ and a minimal git status."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    if strokes is not None:
        with open(data_dir / "strokes.jsonl", "w", encoding="utf-8") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
    return tmp_path


def _stroke(seconds_ago: float, kind: str = "thought") -> dict:
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return {"seq": 1, "at": ts.isoformat(), "kind": kind, "text": "test"}


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


# ---------------------------------------------------------------------------
# _pid_alive
# ---------------------------------------------------------------------------

class TestPidAlive:
    def test_missing_file(self, tmp_path: Path):
        assert _pid_alive(tmp_path / "nonexistent.pid") is False

    def test_stale_pid(self, tmp_path: Path):
        # PID 99999999 is almost certainly not running
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("99999999", encoding="utf-8")
        assert _pid_alive(pid_file) is False

    def test_self_pid(self, tmp_path: Path):
        # Our own PID is definitely alive
        pid_file = tmp_path / "self.pid"
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        assert _pid_alive(pid_file) is True

    def test_invalid_pid_content(self, tmp_path: Path):
        pid_file = tmp_path / "bad.pid"
        pid_file.write_text("not_a_number", encoding="utf-8")
        assert _pid_alive(pid_file) is False

    def test_empty_pid_file(self, tmp_path: Path):
        pid_file = tmp_path / "empty.pid"
        pid_file.write_text("", encoding="utf-8")
        assert _pid_alive(pid_file) is False


# ---------------------------------------------------------------------------
# _last_stroke_age
# ---------------------------------------------------------------------------

class TestLastStrokeAge:
    def test_missing_file(self, tmp_path: Path):
        assert _last_stroke_age(tmp_path / "nope.jsonl") == float("inf")

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("", encoding="utf-8")
        assert _last_stroke_age(p) == float("inf")

    def test_recent_stroke(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        stroke = _stroke(seconds_ago=10)
        p.write_text(json.dumps(stroke) + "\n", encoding="utf-8")
        age = _last_stroke_age(p)
        assert 9 <= age <= 15

    def test_old_stroke(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        stroke = _stroke(seconds_ago=3600)
        p.write_text(json.dumps(stroke) + "\n", encoding="utf-8")
        age = _last_stroke_age(p)
        assert 3599 <= age <= 3605

    def test_multiple_strokes_reads_last(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        old = _stroke(seconds_ago=3600)
        new = _stroke(seconds_ago=5)
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(old) + "\n")
            f.write(json.dumps(new) + "\n")
        age = _last_stroke_age(p)
        assert 4 <= age <= 10

    def test_corrupt_json(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("not json\n", encoding="utf-8")
        assert _last_stroke_age(p) == float("inf")

    def test_missing_at_field(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(json.dumps({"seq": 1, "text": "oops"}) + "\n", encoding="utf-8")
        assert _last_stroke_age(p) == float("inf")

    def test_naive_timestamp_treated_as_utc(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        ts = datetime.now(timezone.utc) - timedelta(seconds=30)
        # strip tzinfo to simulate a naive timestamp
        naive_ts = ts.replace(tzinfo=None)
        entry = {"seq": 1, "at": naive_ts.isoformat(), "kind": "thought", "text": "x"}
        p.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        age = _last_stroke_age(p)
        assert 29 <= age <= 35


# ---------------------------------------------------------------------------
# _uncommitted_count
# ---------------------------------------------------------------------------

class TestUncommittedCount:
    def test_non_git_dir(self, tmp_path: Path):
        # Without a .git directory, git status will fail
        count = _uncommitted_count(tmp_path)
        # Should return -1 (unknown) for non-git dirs
        assert count == -1

    def test_real_repo(self, tmp_path: Path):
        """If run inside the actual IamAI repo, should return >= 0."""
        real_repo = Path(__file__).resolve().parent.parent
        count = _uncommitted_count(real_repo)
        assert count >= 0


# ---------------------------------------------------------------------------
# probe (composite)
# ---------------------------------------------------------------------------

class TestProbe:
    def test_all_green_healthy(self, tmp_path: Path):
        """When all signals are good, verdict is healthy."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=10)])
        # Create PID files with our own (alive) PID
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        # Mock git status to show clean tree
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="qwen", cadence_seconds=15.0)
        assert result["verdict"] == "healthy"
        assert result["green_count"] == 4
        assert all(result["signals"].values())

    def test_writer_dead_degraded(self, tmp_path: Path):
        """When writer PID is gone but everything else is fine: degraded."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=10)])
        _write_pid(tmp_path / "data" / "writer-qwen.pid", 99999999)  # dead
        _write_pid(tmp_path / "data" / "batch-qwen.pid", os.getpid())
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="qwen")
        assert result["verdict"] == "degraded"
        assert result["signals"]["writer_alive"] is False
        assert result["signals"]["batch_alive"] is True

    def test_everything_dead_stalled(self, tmp_path: Path):
        """When all signals are bad, verdict is stalled."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=3600)])
        _write_pid(tmp_path / "data" / "writer-qwen.pid", 99999999)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", 99999999)
        with patch("iamai.stall_probe._uncommitted_count", return_value=50):
            result = probe(repo, writer_id="qwen")
        assert result["verdict"] == "stalled"
        assert result["green_count"] == 0

    def test_backlog_high(self, tmp_path: Path):
        """High uncommitted count turns backlog_low signal red."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=10)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        with patch("iamai.stall_probe._uncommitted_count", return_value=30):
            result = probe(repo, writer_id="qwen", backlog_threshold=20)
        assert result["signals"]["backlog_low"] is False

    def test_stale_strokes(self, tmp_path: Path):
        """Old strokes cause stroke_fresh to go red."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=600)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="qwen", cadence_seconds=15, fresh_threshold=5)
        assert result["signals"]["stroke_fresh"] is False

    def test_no_strokes_file(self, tmp_path: Path):
        """Missing strokes.jsonl means stroke_fresh is red."""
        repo = _make_repo(tmp_path, strokes=None)
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="qwen")
        assert result["signals"]["stroke_fresh"] is False

    def test_no_pid_files(self, tmp_path: Path):
        """Missing PID files means both process signals go red."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=10)])
        # Also mock /tmp fallback
        with patch("iamai.stall_probe._pid_alive", return_value=False), \
             patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="nonexistent_writer")
        assert result["signals"]["writer_alive"] is False
        assert result["signals"]["batch_alive"] is False

    def test_custom_thresholds(self, tmp_path: Path):
        """Custom thresholds change when signals flip."""
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=200)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        # With a generous threshold (20× cadence), 200s age is fine
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo, writer_id="qwen",
                          cadence_seconds=15, fresh_threshold=20)
        assert result["signals"]["stroke_fresh"] is True

    def test_verdict_structure(self, tmp_path: Path):
        """Result dict has the expected keys."""
        repo = _make_repo(tmp_path)
        with patch("iamai.stall_probe._pid_alive", return_value=False), \
             patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo)
        assert "verdict" in result
        assert "signals" in result
        assert "details" in result
        assert "green_count" in result
        assert "total_signals" in result
        assert result["total_signals"] == 4
        assert result["verdict"] in ("healthy", "degraded", "stalled")

    def test_details_stroke_age_negative_for_missing(self, tmp_path: Path):
        """When strokes.jsonl is missing, stroke_age_seconds is -1."""
        repo = _make_repo(tmp_path)
        with patch("iamai.stall_probe._pid_alive", return_value=False), \
             patch("iamai.stall_probe._uncommitted_count", return_value=0):
            result = probe(repo)
        assert result["details"]["stroke_age_seconds"] == -1


# ---------------------------------------------------------------------------
# probe_report
# ---------------------------------------------------------------------------

class TestProbeReport:
    def test_healthy_report(self, tmp_path: Path):
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=10)])
        my_pid = os.getpid()
        _write_pid(tmp_path / "data" / "writer-qwen.pid", my_pid)
        _write_pid(tmp_path / "data" / "batch-qwen.pid", my_pid)
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            report = probe_report(repo, writer_id="qwen")
        assert report.startswith("healthy")
        assert "4/4" in report
        assert "✓" in report

    def test_stalled_report(self, tmp_path: Path):
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=7200)])
        with patch("iamai.stall_probe._pid_alive", return_value=False), \
             patch("iamai.stall_probe._uncommitted_count", return_value=99):
            report = probe_report(repo, writer_id="qwen")
        assert report.startswith("stalled")
        assert "0/4" in report
        assert "✗" in report

    def test_degraded_contains_mixed_signals(self, tmp_path: Path):
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=10)])
        _write_pid(tmp_path / "data" / "writer-qwen.pid", os.getpid())
        # batch dead
        _write_pid(tmp_path / "data" / "batch-qwen.pid", 99999999)
        with patch("iamai.stall_probe._uncommitted_count", return_value=0):
            report = probe_report(repo, writer_id="qwen")
        assert "degraded" in report
        assert "3/4" in report
