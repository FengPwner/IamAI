"""Tests for tools/deadman_switch.py — heartbeat write and freshness check."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

# Ensure tools/ is importable.
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import deadman_switch  # noqa: E402


@pytest.fixture()
def clean_deadman(tmp_path, monkeypatch):
    """Redirect deadman files to a temp directory so tests don't pollute /tmp."""

    def _path(writer: str) -> Path:
        return tmp_path / f"iamai-deadman-{writer}.json"

    monkeypatch.setattr(deadman_switch, "deadman_path", _path)
    return tmp_path


class TestWriteHeartbeat:
    def test_creates_file(self, clean_deadman):
        path = deadman_switch.write_heartbeat("test-writer")
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["writer"] == "test-writer"
        assert "timestamp" in data
        assert "iso" in data
        assert "pid" in data
        assert data["pid"] == os.getpid()

    def test_overwrites_on_second_call(self, clean_deadman):
        deadman_switch.write_heartbeat("test-writer")
        time.sleep(0.05)
        deadman_switch.write_heartbeat("test-writer")
        path = deadman_switch.deadman_path("test-writer")
        data = json.loads(path.read_text())
        assert data["writer"] == "test-writer"

    def test_extra_fields_merged(self, clean_deadman):
        deadman_switch.write_heartbeat("test-writer", extra={"seq": 42})
        path = deadman_switch.deadman_path("test-writer")
        data = json.loads(path.read_text())
        assert data["seq"] == 42
        # Original fields still present.
        assert data["writer"] == "test-writer"

    def test_no_temp_file_left_behind(self, clean_deadman):
        deadman_switch.write_heartbeat("test-writer")
        leftovers = list(clean_deadman.glob("*.tmp"))
        assert leftovers == []


class TestCheckHeartbeat:
    def test_fresh_heartbeat_returns_zero(self, clean_deadman):
        deadman_switch.write_heartbeat("test-writer")
        rc = deadman_switch.check_heartbeat("test-writer", max_age_seconds=60)
        assert rc == 0

    def test_stale_heartbeat_returns_one(self, clean_deadman, monkeypatch):
        deadman_switch.write_heartbeat("test-writer")
        # Fake time advancing by 600 seconds.
        real_time = time.time
        monkeypatch.setattr(
            deadman_switch.time, "time", lambda: real_time() + 600
        )
        rc = deadman_switch.check_heartbeat("test-writer", max_age_seconds=300)
        assert rc == 1

    def test_missing_file_returns_two(self, clean_deadman):
        rc = deadman_switch.check_heartbeat("nonexistent", max_age_seconds=300)
        assert rc == 2

    def test_corrupt_file_returns_two(self, clean_deadman):
        path = deadman_switch.deadman_path("test-writer")
        path.write_text("not json{{{")
        rc = deadman_switch.check_heartbeat("test-writer", max_age_seconds=300)
        assert rc == 2

    def test_zero_timestamp_is_stale(self, clean_deadman):
        """A heartbeat with timestamp=0 should always be stale."""
        path = deadman_switch.deadman_path("test-writer")
        path.write_text(json.dumps({"writer": "test-writer", "timestamp": 0, "iso": "x"}))
        rc = deadman_switch.check_heartbeat("test-writer", max_age_seconds=300)
        assert rc == 1
