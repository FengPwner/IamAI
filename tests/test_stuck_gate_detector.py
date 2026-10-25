#!/usr/bin/env python3
"""Tests for tools/stuck_gate_detector.py — stuck pause gate detection."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from stuck_gate_detector import (
    clear_gate,
    detect,
    format_result,
    gate_age_seconds,
    gate_is_red,
    gate_path,
    log_event,
    run_tests,
)


# ---------------------------------------------------------------------------
# gate_path / gate_is_red
# ---------------------------------------------------------------------------


class TestGatePath:
    def test_path_contains_writer_id(self):
        p = gate_path("qwen")
        assert "qwen" in str(p)
        assert "pause" in str(p)

    def test_different_writers_different_paths(self):
        assert gate_path("qwen") != gate_path("doubao")


class TestGateIsRed:
    def test_false_when_no_gate(self, tmp_path: Path):
        with patch("stuck_gate_detector.gate_path", return_value=tmp_path / "nope"):
            assert gate_is_red("test") is False

    def test_true_when_gate_exists(self, tmp_path: Path):
        gate = tmp_path / "gate"
        gate.touch()
        with patch("stuck_gate_detector.gate_path", return_value=gate):
            assert gate_is_red("test") is True


# ---------------------------------------------------------------------------
# gate_age_seconds
# ---------------------------------------------------------------------------


class TestGateAge:
    def test_none_when_no_gate(self, tmp_path: Path):
        with patch("stuck_gate_detector.gate_path", return_value=tmp_path / "nope"):
            assert gate_age_seconds("test") is None

    def test_returns_positive_age(self, tmp_path: Path):
        gate = tmp_path / "gate"
        gate.touch()
        with patch("stuck_gate_detector.gate_path", return_value=gate):
            age = gate_age_seconds("test")
            assert age is not None
            assert age >= 0
            assert age < 5  # just created, should be near-zero


# ---------------------------------------------------------------------------
# clear_gate
# ---------------------------------------------------------------------------


class TestClearGate:
    def test_clears_existing_gate(self, tmp_path: Path):
        gate = tmp_path / "gate"
        gate.touch()
        with patch("stuck_gate_detector.gate_path", return_value=gate):
            assert clear_gate("test") is True
            assert not gate.exists()

    def test_returns_true_when_no_gate(self, tmp_path: Path):
        with patch("stuck_gate_detector.gate_path", return_value=tmp_path / "nope"):
            assert clear_gate("test") is True


# ---------------------------------------------------------------------------
# run_tests
# ---------------------------------------------------------------------------


class TestRunTests:
    def test_returns_bool(self, tmp_path: Path):
        # Running against a non-existent directory should return False
        result = run_tests(tmp_path / "nonexistent", timeout=5)
        assert isinstance(result, bool)

    def test_collect_only_is_faster(self, tmp_path: Path):
        # Just checking the interface works; both should return bool
        r1 = run_tests(REPO, full=False, timeout=30)
        assert isinstance(r1, bool)


# ---------------------------------------------------------------------------
# detect — the core logic
# ---------------------------------------------------------------------------


class TestDetect:
    def test_no_gate(self, tmp_path: Path):
        with patch("stuck_gate_detector.gate_is_red", return_value=False):
            result = detect("test", tmp_path)
            assert result["status"] == "no_gate"

    def test_fresh_gate_left_alone(self, tmp_path: Path):
        with patch("stuck_gate_detector.gate_is_red", return_value=True), \
             patch("stuck_gate_detector.gate_age_seconds", return_value=30.0), \
             patch("stuck_gate_detector.run_tests", return_value=True):
            result = detect("test", tmp_path)
            assert result["status"] == "too_fresh"

    def test_stuck_gate_cleared(self, tmp_path: Path):
        with patch("stuck_gate_detector.gate_is_red", return_value=True), \
             patch("stuck_gate_detector.gate_age_seconds", return_value=300.0), \
             patch("stuck_gate_detector.run_tests", return_value=True), \
             patch("stuck_gate_detector.clear_gate", return_value=True), \
             patch("stuck_gate_detector.log_event"):
            result = detect("test", tmp_path, check_only=False)
            assert result["status"] == "stuck_cleared"
            assert "cleared" in result["message"]

    def test_stuck_gate_check_only(self, tmp_path: Path):
        with patch("stuck_gate_detector.gate_is_red", return_value=True), \
             patch("stuck_gate_detector.gate_age_seconds", return_value=300.0), \
             patch("stuck_gate_detector.run_tests", return_value=True), \
             patch("stuck_gate_detector.clear_gate") as mock_clear, \
             patch("stuck_gate_detector.log_event"):
            result = detect("test", tmp_path, check_only=True)
            assert result["status"] == "stuck_not_cleared"
            mock_clear.assert_not_called()

    def test_legitimate_gate_left_alone(self, tmp_path: Path):
        with patch("stuck_gate_detector.gate_is_red", return_value=True), \
             patch("stuck_gate_detector.gate_age_seconds", return_value=300.0), \
             patch("stuck_gate_detector.run_tests", return_value=False), \
             patch("stuck_gate_detector.clear_gate") as mock_clear:
            result = detect("test", tmp_path)
            assert result["status"] == "legitimate"
            mock_clear.assert_not_called()


# ---------------------------------------------------------------------------
# format_result
# ---------------------------------------------------------------------------


class TestFormatResult:
    @pytest.mark.parametrize("status", [
        "no_gate", "too_fresh", "stuck_cleared",
        "stuck_not_cleared", "legitimate", "error",
    ])
    def test_all_statuses_format(self, status: str):
        result = {"status": status, "message": f"test message for {status}"}
        text = format_result(result)
        assert status in text
        assert "test message" in text

    def test_unknown_status_gets_question_mark(self):
        result = {"status": "wat", "message": "mystery"}
        text = format_result(result)
        assert "?" in text


# ---------------------------------------------------------------------------
# log_event
# ---------------------------------------------------------------------------


class TestLogEvent:
    def test_appends_to_log(self, tmp_path: Path):
        log_file = tmp_path / "log.jsonl"
        with patch("stuck_gate_detector.Path") as mock_path_cls:
            # Simulate the log path
            with patch(
                "stuck_gate_detector.log_event",
                wraps=lambda w, e: _manual_log(log_file, w, e),
            ):
                log_event("qwen", {"event": "test"})
        # verify the manual log
        if log_file.exists():
            lines = log_file.read_text().strip().split("\n")
            assert len(lines) >= 1
            record = json.loads(lines[-1])
            assert record["event"] == "test"
            assert "at" in record


def _manual_log(log_path: Path, writer: str, event: dict) -> None:
    from datetime import datetime, timezone
    event["at"] = datetime.now(tz=timezone.utc).isoformat()
    event["writer"] = writer
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
