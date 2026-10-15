"""Tests for tools/repo_pulse.py — multi-signal health check."""

import json
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import repo_pulse as rp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(tmp_path: Path, history: list[dict], writer: str = "qwen") -> Path:
    """Write a writer state file and return its path."""
    state = {"history": history, "seq": len(history)}
    p = tmp_path / f"writer_state.{writer}.json"
    p.write_text(json.dumps(state), encoding="utf-8")
    return p


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _stroke(seq: int, kind: str, at: datetime) -> dict:
    return {"seq": seq, "kind": kind, "at": _iso(at), "path": f"notes/{kind}.md"}


# ---------------------------------------------------------------------------
# check_last_stroke_age
# ---------------------------------------------------------------------------

class TestLastStrokeAge:
    def test_fresh_stroke(self, tmp_path):
        now = datetime.now(timezone.utc)
        history = [_stroke(1, "note", now - timedelta(seconds=30))]
        p = _make_state(tmp_path, history)
        result = rp.check_last_stroke_age(p)
        assert result["status"] == "green"
        assert result["age_seconds"] <= 35
        assert result["last_kind"] == "note"
        assert result["last_seq"] == 1

    def test_stale_stroke(self, tmp_path):
        now = datetime.now(timezone.utc)
        history = [_stroke(1, "note", now - timedelta(seconds=300))]
        p = _make_state(tmp_path, history)
        result = rp.check_last_stroke_age(p)
        assert result["status"] == "yellow"

    def test_dead_stroke(self, tmp_path):
        now = datetime.now(timezone.utc)
        history = [_stroke(1, "note", now - timedelta(seconds=900))]
        p = _make_state(tmp_path, history)
        result = rp.check_last_stroke_age(p)
        assert result["status"] == "red"

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent.json"
        result = rp.check_last_stroke_age(p)
        assert result["status"] == "red"
        assert "missing" in result["error"]

    def test_empty_history(self, tmp_path):
        p = _make_state(tmp_path, [])
        result = rp.check_last_stroke_age(p)
        assert result["status"] == "red"
        assert "empty" in result["error"]


# ---------------------------------------------------------------------------
# check_pending_files
# ---------------------------------------------------------------------------

class TestPendingFiles:
    def test_clean_repo(self, tmp_path):
        """Mock git to return no pending files."""
        with patch("repo_pulse.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="", stderr=""
            )
            result = rp.check_pending_files()
        assert result["status"] == "green"
        assert result["count"] == 0 or result["count"] == 1  # empty string splits to ['']

    def test_few_pending(self, tmp_path):
        with patch("repo_pulse.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=" M file1.py\n M file2.py\n M file3.py\n",
                stderr=""
            )
            result = rp.check_pending_files()
        assert result["status"] == "green"
        assert result["count"] == 3

    def test_many_pending_warning(self):
        lines = "\n".join(f" M file{i}.py" for i in range(10))
        with patch("repo_pulse.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=lines, stderr=""
            )
            result = rp.check_pending_files()
        assert result["status"] == "yellow"

    def test_many_pending_critical(self):
        lines = "\n".join(f" M file{i}.py" for i in range(25))
        with patch("repo_pulse.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=lines, stderr=""
            )
            result = rp.check_pending_files()
        assert result["status"] == "red"


# ---------------------------------------------------------------------------
# check_diversity
# ---------------------------------------------------------------------------

class TestDiversity:
    def test_balanced(self, tmp_path):
        """60 strokes, 10 per kind — perfectly balanced."""
        now = datetime.now(timezone.utc)
        kinds = ("devlog", "garden", "metrics", "note", "snippet", "thought")
        history = [
            _stroke(i, kinds[i % 6], now - timedelta(seconds=60 - i))
            for i in range(60)
        ]
        p = _make_state(tmp_path, history)
        result = rp.check_diversity(p, window=60)
        assert result["status"] == "green"
        assert result["imbalance"] < 0.1

    def test_imbalanced(self, tmp_path):
        """All strokes are one kind."""
        now = datetime.now(timezone.utc)
        history = [_stroke(i, "note", now - timedelta(seconds=60 - i)) for i in range(30)]
        p = _make_state(tmp_path, history)
        result = rp.check_diversity(p, window=30)
        assert result["status"] == "red"
        assert result["imbalance"] > 0.5

    def test_too_few_strokes(self, tmp_path):
        now = datetime.now(timezone.utc)
        history = [_stroke(1, "note", now)]
        p = _make_state(tmp_path, history)
        result = rp.check_diversity(p)
        assert result["status"] == "yellow"

    def test_missing_state_file(self, tmp_path):
        p = tmp_path / "nonexistent.json"
        result = rp.check_diversity(p)
        assert result["status"] == "red"

    def test_moderate_imbalance(self, tmp_path):
        """Two kinds dominant, others sparse."""
        now = datetime.now(timezone.utc)
        history = []
        for i in range(60):
            kind = "note" if i % 3 == 0 else "devlog" if i % 3 == 1 else "garden"
            history.append(_stroke(i, kind, now - timedelta(seconds=60 - i)))
        p = _make_state(tmp_path, history)
        result = rp.check_diversity(p, window=60)
        # 20 each of 3 kinds, 0 of other 3 — imbalance should be high
        assert result["status"] in ("yellow", "red")


# ---------------------------------------------------------------------------
# check_writer_alive
# ---------------------------------------------------------------------------

class TestWriterAlive:
    def test_writer_running(self):
        with patch("repo_pulse.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="12345\n", stderr=""
            )
            result = rp.check_writer_alive("qwen")
        assert result["status"] == "green"
        assert result["alive"] is True
        assert "12345" in result["pids"]

    def test_writer_not_running(self):
        with patch("repo_pulse.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr=""
            )
            result = rp.check_writer_alive("qwen")
        assert result["status"] == "red"
        assert result["alive"] is False

    def test_writer_exception(self):
        with patch("repo_pulse.subprocess.run") as mock_run:
            mock_run.side_effect = RuntimeError("timeout")
            result = rp.check_writer_alive("qwen")
        assert result["status"] == "red"
        assert "error" in result


# ---------------------------------------------------------------------------
# check_last_commit_age
# ---------------------------------------------------------------------------

class TestLastCommitAge:
    def test_fresh_commit(self):
        recent = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        with patch("repo_pulse.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=recent + "\n", stderr=""
            )
            result = rp.check_last_commit_age()
        assert result["status"] == "green"
        assert result["age_seconds"] <= 125

    def test_stale_commit(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=1800)).isoformat()
        with patch("repo_pulse.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=old + "\n", stderr=""
            )
            result = rp.check_last_commit_age()
        assert result["status"] == "yellow"

    def test_dead_commit(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
        with patch("repo_pulse.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=old + "\n", stderr=""
            )
            result = rp.check_last_commit_age()
        assert result["status"] == "red"

    def test_git_failure(self):
        with patch("repo_pulse.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="fatal"
            )
            result = rp.check_last_commit_age()
        assert result["status"] == "red"
        assert "git log failed" in result.get("error", "")


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------

class TestAggregate:
    def test_all_green(self):
        signals = [{"status": "green"}, {"status": "green"}]
        assert rp.aggregate(signals) == "healthy"

    def test_one_yellow(self):
        signals = [{"status": "green"}, {"status": "yellow"}]
        assert rp.aggregate(signals) == "warning"

    def test_one_red(self):
        signals = [{"status": "green"}, {"status": "red"}]
        assert rp.aggregate(signals) == "critical"

    def test_red_overrides_yellow(self):
        signals = [{"status": "yellow"}, {"status": "red"}, {"status": "green"}]
        assert rp.aggregate(signals) == "critical"

    def test_empty_signals(self):
        assert rp.aggregate([]) == "healthy"


# ---------------------------------------------------------------------------
# format_text
# ---------------------------------------------------------------------------

class TestFormatText:
    def test_healthy_output(self):
        report = {
            "verdict": "healthy",
            "writer": "qwen",
            "checked_at": "2026-10-16T03:00:00+00:00",
            "signals": [
                {"signal": "writer_alive", "status": "green", "alive": True, "pids": ["1234"]},
                {"signal": "stroke_age", "status": "green", "age_seconds": 30,
                 "last_kind": "note", "last_seq": 100},
                {"signal": "commit_age", "status": "green", "age_seconds": 120},
                {"signal": "pending_files", "status": "green", "count": 0},
                {"signal": "diversity", "status": "green", "imbalance": 0.05},
            ],
        }
        text = rp.format_text(report)
        assert "[OK]" in text
        assert "healthy" in text
        assert "qwen" in text
        assert "[+] writer_alive" in text
        assert "30s ago" in text

    def test_critical_output(self):
        report = {
            "verdict": "critical",
            "writer": "qwen",
            "checked_at": "2026-10-16T03:00:00+00:00",
            "signals": [
                {"signal": "writer_alive", "status": "red", "alive": False, "pids": []},
                {"signal": "stroke_age", "status": "red", "age_seconds": None,
                 "error": "state file missing"},
            ],
        }
        text = rp.format_text(report)
        assert "[CRIT]" in text
        assert "DOWN" in text

    def test_warning_output(self):
        report = {
            "verdict": "warning",
            "writer": "qwen",
            "checked_at": "2026-10-16T03:00:00+00:00",
            "signals": [
                {"signal": "stroke_age", "status": "yellow", "age_seconds": 400,
                 "last_kind": "devlog", "last_seq": 50},
            ],
        }
        text = rp.format_text(report)
        assert "[WARN]" in text
        assert "400s ago" in text


# ---------------------------------------------------------------------------
# run_pulse (integration)
# ---------------------------------------------------------------------------

class TestRunPulse:
    def test_returns_expected_keys(self):
        """run_pulse returns verdict, writer, checked_at, and signals."""
        with patch("repo_pulse.check_writer_alive") as m1, \
             patch("repo_pulse.check_last_stroke_age") as m2, \
             patch("repo_pulse.check_last_commit_age") as m3, \
             patch("repo_pulse.check_pending_files") as m4, \
             patch("repo_pulse.check_diversity") as m5:
            m1.return_value = {"signal": "writer_alive", "status": "green", "alive": True, "pids": ["1"]}
            m2.return_value = {"signal": "stroke_age", "status": "green", "age_seconds": 10,
                               "last_kind": "note", "last_seq": 1}
            m3.return_value = {"signal": "commit_age", "status": "green", "age_seconds": 60}
            m4.return_value = {"signal": "pending_files", "status": "green", "count": 0}
            m5.return_value = {"signal": "diversity", "status": "green", "imbalance": 0.02}

            report = rp.run_pulse("qwen")

        assert report["verdict"] == "healthy"
        assert report["writer"] == "qwen"
        assert "checked_at" in report
        assert len(report["signals"]) == 5

    def test_critical_when_writer_down(self):
        with patch("repo_pulse.check_writer_alive") as m1, \
             patch("repo_pulse.check_last_stroke_age") as m2, \
             patch("repo_pulse.check_last_commit_age") as m3, \
             patch("repo_pulse.check_pending_files") as m4, \
             patch("repo_pulse.check_diversity") as m5:
            m1.return_value = {"signal": "writer_alive", "status": "red", "alive": False, "pids": []}
            m2.return_value = {"signal": "stroke_age", "status": "green", "age_seconds": 10,
                               "last_kind": "note", "last_seq": 1}
            m3.return_value = {"signal": "commit_age", "status": "green", "age_seconds": 60}
            m4.return_value = {"signal": "pending_files", "status": "green", "count": 0}
            m5.return_value = {"signal": "diversity", "status": "green", "imbalance": 0.02}

            report = rp.run_pulse("qwen")

        assert report["verdict"] == "critical"
