#!/usr/bin/env python3
"""Tests for tools/stroke_gap_monitor.py — writer silence detector."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from stroke_gap_monitor import (
    GapReport,
    analyze,
    as_markdown,
    load_history,
    parse_iso,
    state_path,
    DEFAULT_MAX_GAP,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_history() -> list[dict]:
    """A realistic 5-stroke history spanning ~2 minutes."""
    base = "2026-10-09T13:00:00+00:00"
    base_ts = parse_iso(base)
    kinds = ["devlog", "garden", "note", "metrics", "snippet"]
    return [
        {
            "at": f"2026-10-09T13:{i:02d}:00+00:00",
            "kind": kinds[i],
            "path": f"docs/{kinds[i].upper()}.md",
            "seq": 12660 + i,
        }
        for i in range(5)
    ]


@pytest.fixture
def state_file(tmp_path: Path, sample_history: list[dict]) -> Path:
    """Write a temporary writer state file and patch state_path to use it."""
    state_dir = tmp_path / "data"
    state_dir.mkdir()
    sf = state_dir / "writer_state.qwen.json"
    sf.write_text(json.dumps({"history": sample_history, "seq": 12665}))

    def _patched(writer_id: str) -> Path:
        return state_dir / f"writer_state.{writer_id}.json"

    with patch("stroke_gap_monitor.state_path", side_effect=_patched):
        yield sf


@pytest.fixture
def empty_state(tmp_path: Path) -> Path:
    """Writer state with an empty history list."""
    state_dir = tmp_path / "data"
    state_dir.mkdir()
    sf = state_dir / "writer_state.qwen.json"
    sf.write_text(json.dumps({"history": [], "seq": 0}))

    def _patched(writer_id: str) -> Path:
        return state_dir / f"writer_state.{writer_id}.json"

    with patch("stroke_gap_monitor.state_path", side_effect=_patched):
        yield sf


@pytest.fixture
def missing_state(tmp_path: Path) -> Path:
    """Redirect state_path to a nonexistent directory."""
    state_dir = tmp_path / "data"
    state_dir.mkdir()

    def _patched(writer_id: str) -> Path:
        return state_dir / f"writer_state.{writer_id}.json"

    with patch("stroke_gap_monitor.state_path", side_effect=_patched):
        yield state_dir


# ---------------------------------------------------------------------------
# parse_iso
# ---------------------------------------------------------------------------

class TestParseIso:
    def test_utc_offset(self):
        ts = parse_iso("2026-10-09T13:00:00+00:00")
        assert isinstance(ts, float)
        assert ts > 1_700_000_000

    def test_z_suffix(self):
        ts = parse_iso("2026-10-09T13:00:00Z")
        assert isinstance(ts, float)

    def test_naive_assumed_utc(self):
        ts = parse_iso("2026-10-09T13:00:00")
        assert isinstance(ts, float)

    def test_positive_offset(self):
        ts = parse_iso("2026-10-09T21:00:00+08:00")
        assert isinstance(ts, float)

    def test_consistency(self):
        """All three formats of the same instant should parse to the same value."""
        a = parse_iso("2026-10-09T13:00:00+00:00")
        b = parse_iso("2026-10-09T13:00:00Z")
        c = parse_iso("2026-10-09T13:00:00")
        assert abs(a - b) < 1
        assert abs(a - c) < 1


# ---------------------------------------------------------------------------
# load_history
# ---------------------------------------------------------------------------

class TestLoadHistory:
    def test_loads_valid_state(self, state_file: Path):
        history = load_history("qwen")
        assert len(history) == 5
        assert history[0]["kind"] == "devlog"

    def test_missing_file_raises(self, missing_state: Path):
        with pytest.raises(FileNotFoundError):
            load_history("qwen")

    def test_invalid_json(self, tmp_path: Path):
        state_dir = tmp_path / "data"
        state_dir.mkdir()
        sf = state_dir / "writer_state.qwen.json"
        sf.write_text("not json at all")

        def _patched(writer_id: str) -> Path:
            return state_dir / f"writer_state.{writer_id}.json"

        with patch("stroke_gap_monitor.state_path", side_effect=_patched):
            with pytest.raises(json.JSONDecodeError):
                load_history("qwen")

    def test_history_not_list(self, tmp_path: Path):
        state_dir = tmp_path / "data"
        state_dir.mkdir()
        sf = state_dir / "writer_state.qwen.json"
        sf.write_text(json.dumps({"history": "wrong type"}))

        def _patched(writer_id: str) -> Path:
            return state_dir / f"writer_state.{writer_id}.json"

        with patch("stroke_gap_monitor.state_path", side_effect=_patched):
            with pytest.raises(ValueError, match="not a list"):
                load_history("qwen")


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_active_writer(self, state_file: Path, sample_history: list[dict]):
        """Writer that just wrote should not be stalled."""
        last_at = parse_iso(sample_history[-1]["at"])
        report = analyze(writer_id="qwen", max_gap=600, now=last_at + 30)
        assert not report.stalled
        assert report.gap_seconds == pytest.approx(30, abs=1)
        assert report.history_len == 5
        assert report.last_kind == "snippet"

    def test_stalled_writer(self, state_file: Path, sample_history: list[dict]):
        """Writer silent for 20 minutes should be stalled with 600s threshold."""
        last_at = parse_iso(sample_history[-1]["at"])
        report = analyze(writer_id="qwen", max_gap=600, now=last_at + 1200)
        assert report.stalled
        assert report.gap_seconds == pytest.approx(1200, abs=1)

    def test_empty_history(self, empty_state: Path):
        """Empty history should report stalled with no gap."""
        report = analyze(writer_id="qwen", max_gap=600, now=time.time())
        assert report.stalled
        assert report.last_stroke_at is None
        assert report.history_len == 0

    def test_missing_state(self, missing_state: Path):
        """Missing state file should report stalled."""
        report = analyze(writer_id="qwen", max_gap=600, now=time.time())
        assert report.stalled
        assert report.last_stroke_at is None

    def test_custom_max_gap(self, state_file: Path, sample_history: list[dict]):
        """A very large max_gap should prevent stall detection."""
        last_at = parse_iso(sample_history[-1]["at"])
        report = analyze(writer_id="qwen", max_gap=99999, now=last_at + 1200)
        assert not report.stalled

    def test_boundary_exact(self, state_file: Path, sample_history: list[dict]):
        """Gap exactly at max_gap should not stall (not strictly greater)."""
        last_at = parse_iso(sample_history[-1]["at"])
        report = analyze(writer_id="qwen", max_gap=600, now=last_at + 600)
        assert not report.stalled

    def test_boundary_one_over(self, state_file: Path, sample_history: list[dict]):
        """Gap one second over max_gap should stall."""
        last_at = parse_iso(sample_history[-1]["at"])
        report = analyze(writer_id="qwen", max_gap=600, now=last_at + 601)
        assert report.stalled

    def test_writer_id_preserved(self, state_file: Path, sample_history: list[dict]):
        last_at = parse_iso(sample_history[-1]["at"])
        report = analyze(writer_id="qwen", max_gap=600, now=last_at + 30)
        assert report.writer_id == "qwen"


# ---------------------------------------------------------------------------
# as_markdown
# ---------------------------------------------------------------------------

class TestAsMarkdown:
    def test_ok_seconds(self):
        report = GapReport(
            writer_id="qwen",
            last_stroke_at=time.time() - 30,
            last_stroke_iso="2026-10-09T13:00:00+00:00",
            now=time.time(),
            gap_seconds=30.0,
            max_gap=600,
            history_len=100,
            stalled=False,
            last_kind="note",
        )
        md = as_markdown(report)
        assert "OK" in md
        assert "note" in md
        assert "qwen" in md

    def test_stall_minutes(self):
        report = GapReport(
            writer_id="qwen",
            last_stroke_at=time.time() - 900,
            last_stroke_iso="2026-10-09T12:45:00+00:00",
            now=time.time(),
            gap_seconds=900.0,
            max_gap=600,
            history_len=100,
            stalled=True,
            last_kind="devlog",
        )
        md = as_markdown(report)
        assert "STALL" in md
        assert "m" in md  # minutes unit

    def test_stall_hours(self):
        report = GapReport(
            writer_id="qwen",
            last_stroke_at=time.time() - 7200,
            last_stroke_iso="2026-10-09T11:00:00+00:00",
            now=time.time(),
            gap_seconds=7200.0,
            max_gap=600,
            history_len=100,
            stalled=True,
            last_kind="garden",
        )
        md = as_markdown(report)
        assert "STALL" in md
        assert "h" in md  # hours unit

    def test_no_history(self):
        report = GapReport(
            writer_id="qwen",
            last_stroke_at=None,
            last_stroke_iso=None,
            now=time.time(),
            gap_seconds=None,
            max_gap=600,
            history_len=0,
            stalled=True,
            last_kind=None,
        )
        md = as_markdown(report)
        assert "NO HISTORY" in md

    def test_unknown_kind(self):
        report = GapReport(
            writer_id="qwen",
            last_stroke_at=time.time() - 30,
            last_stroke_iso="2026-10-09T13:00:00+00:00",
            now=time.time(),
            gap_seconds=30.0,
            max_gap=600,
            history_len=100,
            stalled=False,
            last_kind=None,
        )
        md = as_markdown(report)
        assert "?" in md


# ---------------------------------------------------------------------------
# state_path
# ---------------------------------------------------------------------------

class TestStatePath:
    def test_default_writer(self):
        p = state_path("qwen")
        assert p.name == "writer_state.qwen.json"
        assert "data" in str(p)

    def test_custom_writer(self):
        p = state_path("kimi")
        assert p.name == "writer_state.kimi.json"


# ---------------------------------------------------------------------------
# Integration: full round-trip
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_cycle(self, state_file: Path, sample_history: list[dict]):
        """End-to-end: write state, analyze, check result."""
        last_at = parse_iso(sample_history[-1]["at"])

        # Active
        report = analyze(writer_id="qwen", max_gap=300, now=last_at + 60)
        assert not report.stalled
        md = as_markdown(report)
        assert "OK" in md

        # Stalled
        report = analyze(writer_id="qwen", max_gap=300, now=last_at + 600)
        assert report.stalled
        md = as_markdown(report)
        assert "STALL" in md
