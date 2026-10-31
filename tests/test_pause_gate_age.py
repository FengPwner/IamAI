"""Tests for tools/pause_gate_age.py — the stale pause-gate monitor."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.pause_gate_age import classify, pause_age, main  # noqa: E402


# ---------------------------------------------------------------------------
# classify()
# ---------------------------------------------------------------------------

class TestClassify:
    """classify() maps age + threshold to a status word."""

    def test_none_age_is_open(self):
        assert classify(None, 600) == "open"

    def test_zero_age_is_paused(self):
        assert classify(0.0, 600) == "paused"

    def test_age_below_threshold_is_paused(self):
        assert classify(300.0, 600) == "paused"

    def test_age_at_threshold_is_stale(self):
        # At exactly threshold, age > threshold is False → paused
        assert classify(600.0, 600) == "paused"

    def test_age_above_threshold_is_stale(self):
        assert classify(601.0, 600) == "stale"

    def test_large_age_is_stale(self):
        assert classify(99999.0, 600) == "stale"

    def test_zero_threshold_makes_any_age_stale(self):
        assert classify(0.1, 0) == "stale"

    def test_zero_threshold_zero_age_is_paused(self):
        # 0 > 0 is False, so paused
        assert classify(0.0, 0) == "paused"


# ---------------------------------------------------------------------------
# pause_age()
# ---------------------------------------------------------------------------

class TestPauseAge:
    """pause_age() reads the mtime of the pause file."""

    def test_returns_none_when_no_file(self, tmp_path, monkeypatch):
        """If the pause file doesn't exist, return None."""
        fake_pause = tmp_path / "nonexistent_pause"
        monkeypatch.setattr(
            "tools.pause_gate_age.writer.pause_file",
            lambda wid=None: fake_pause,
        )
        assert pause_age("test_writer") is None

    def test_returns_age_when_file_exists(self, tmp_path, monkeypatch):
        """If the pause file exists, return a positive age."""
        pf = tmp_path / "pause_test"
        pf.write_text("paused\n")
        monkeypatch.setattr(
            "tools.pause_gate_age.writer.pause_file",
            lambda wid=None: pf,
        )
        age = pause_age("test_writer")
        assert age is not None
        assert age >= 0
        assert age < 5  # should be very fresh

    def test_stale_file_has_large_age(self, tmp_path, monkeypatch):
        """A file touched long ago returns a large age."""
        pf = tmp_path / "pause_old"
        pf.write_text("paused\n")
        old_time = time.time() - 1200  # 20 minutes ago
        os.utime(pf, (old_time, old_time))
        monkeypatch.setattr(
            "tools.pause_gate_age.writer.pause_file",
            lambda wid=None: pf,
        )
        age = pause_age("test_writer")
        assert age is not None
        assert age > 1100


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

class TestMain:
    """main() exit codes and output."""

    def test_open_gate_exits_zero(self, tmp_path, monkeypatch, capsys):
        fake_pause = tmp_path / "no_pause"
        monkeypatch.setattr(
            "tools.pause_gate_age.writer.pause_file",
            lambda wid=None: fake_pause,
        )
        rc = main(["--writer", "test_writer"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "open" in out

    def test_stale_gate_exits_one(self, tmp_path, monkeypatch, capsys):
        pf = tmp_path / "pause_stale"
        pf.write_text("paused\n")
        old_time = time.time() - 1200
        os.utime(pf, (old_time, old_time))
        monkeypatch.setattr(
            "tools.pause_gate_age.writer.pause_file",
            lambda wid=None: pf,
        )
        rc = main(["--writer", "test_writer", "--threshold", "600"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "STALE" in out

    def test_json_output(self, tmp_path, monkeypatch, capsys):
        import json
        fake_pause = tmp_path / "no_pause_json"
        monkeypatch.setattr(
            "tools.pause_gate_age.writer.pause_file",
            lambda wid=None: fake_pause,
        )
        rc = main(["--writer", "test_writer", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["gate"] == "open"
        assert data["age_seconds"] is None

    def test_json_stale_output(self, tmp_path, monkeypatch, capsys):
        import json
        pf = tmp_path / "pause_stale_json"
        pf.write_text("paused\n")
        old_time = time.time() - 900
        os.utime(pf, (old_time, old_time))
        monkeypatch.setattr(
            "tools.pause_gate_age.writer.pause_file",
            lambda wid=None: pf,
        )
        rc = main(["--writer", "test_writer", "--threshold", "600", "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["gate"] == "stale"
        assert data["age_seconds"] is not None
        assert data["age_seconds"] > 800

    def test_paused_within_threshold_exits_zero(self, tmp_path, monkeypatch, capsys):
        pf = tmp_path / "pause_fresh"
        pf.write_text("paused\n")
        monkeypatch.setattr(
            "tools.pause_gate_age.writer.pause_file",
            lambda wid=None: pf,
        )
        rc = main(["--writer", "test_writer", "--threshold", "600"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "closed" in out
