#!/usr/bin/env python3
"""Tests for tools/writer_silence_detector.py — writer silence detection."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from writer_silence_detector import (
    exit_code,
    format_text,
    is_stalled,
    last_stroke_time,
    silence_gap,
    status,
)


@pytest.fixture
def strokes_file(tmp_path: Path) -> Path:
    """Create a temporary strokes.jsonl with controlled timestamps."""
    path = tmp_path / "strokes.jsonl"
    return path


def _write_strokes(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class TestLastStrokeTime:
    def test_returns_none_when_file_missing(self, tmp_path: Path):
        assert last_stroke_time(tmp_path / "nonexistent.jsonl") is None

    def test_returns_none_when_empty(self, strokes_file: Path):
        strokes_file.write_text("")
        assert last_stroke_time(strokes_file) is None

    def test_returns_last_timestamp(self, strokes_file: Path):
        now = time.time()
        _write_strokes(strokes_file, [
            {"seq": 1, "at": _iso(now - 3600), "kind": "thought", "text": "old"},
            {"seq": 2, "at": _iso(now - 100), "kind": "note", "text": "recent"},
        ])
        result = last_stroke_time(strokes_file)
        assert result is not None
        assert abs(result - (now - 100)) < 1

    def test_handles_blank_lines(self, strokes_file: Path):
        now = time.time()
        with open(strokes_file, "w") as f:
            f.write(f'{{"seq":1,"at":"{_iso(now - 50)}","kind":"t","text":"x"}}\n')
            f.write("\n")
            f.write("  \n")
        result = last_stroke_time(strokes_file)
        assert result is not None
        assert abs(result - (now - 50)) < 1

    def test_returns_none_for_malformed_json(self, strokes_file: Path):
        strokes_file.write_text("not json at all\n")
        assert last_stroke_time(strokes_file) is None


class TestSilenceGap:
    def test_returns_none_when_no_strokes(self, tmp_path: Path):
        assert silence_gap(path=tmp_path / "missing.jsonl") is None

    def test_computes_gap(self, strokes_file: Path):
        now = time.time()
        _write_strokes(strokes_file, [
            {"seq": 1, "at": _iso(now - 300), "kind": "t", "text": "x"},
        ])
        gap = silence_gap(now=now, path=strokes_file)
        assert gap is not None
        assert 299 <= gap <= 301


class TestIsStalled:
    def test_none_gap_is_stalled(self):
        assert is_stalled(None) is True

    def test_within_threshold(self):
        assert is_stalled(1000, cadence=900, multiplier=2.0) is False

    def test_exceeds_threshold(self):
        assert is_stalled(2000, cadence=900, multiplier=2.0) is True

    def test_exact_threshold(self):
        assert is_stalled(1800, cadence=900, multiplier=2.0) is False


class TestStatus:
    def test_stalled_when_no_file(self, tmp_path: Path):
        info = status(path=tmp_path / "nope.jsonl")
        assert info["stalled"] is True
        assert info["gap_seconds"] is None

    def test_active_writer(self, strokes_file: Path):
        now = time.time()
        _write_strokes(strokes_file, [
            {"seq": 1, "at": _iso(now - 60), "kind": "t", "text": "x"},
        ])
        info = status(now=now, path=strokes_file, cadence=900, multiplier=2.0)
        assert info["stalled"] is False
        assert info["gap_seconds"] is not None
        assert info["gap_seconds"] < 120

    def test_stalled_writer(self, strokes_file: Path):
        now = time.time()
        _write_strokes(strokes_file, [
            {"seq": 1, "at": _iso(now - 5000), "kind": "t", "text": "x"},
        ])
        info = status(now=now, path=strokes_file, cadence=900, multiplier=2.0)
        assert info["stalled"] is True


class TestFormatText:
    def test_no_data(self):
        text = format_text({"gap_seconds": None, "stalled": True, "threshold": 1800})
        assert "no strokes" in text.lower()

    def test_stalled(self):
        text = format_text({"gap_seconds": 3600, "stalled": True, "threshold": 1800})
        assert "STALL" in text
        assert "3600" in text

    def test_active(self):
        text = format_text({"gap_seconds": 120, "stalled": False, "threshold": 1800})
        assert "OK" in text
        assert "120" in text


class TestExitCode:
    def test_stalled_returns_1(self):
        assert exit_code({"stalled": True}) == 1

    def test_active_returns_0(self):
        assert exit_code({"stalled": False}) == 0
