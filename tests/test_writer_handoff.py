#!/usr/bin/env python3
"""Tests for iamai/writer_handoff.py — writer context preservation across restarts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_handoff import (
    HandoffManager,
    DEFAULT_MAX_STROKES,
    DEFAULT_STALE_S,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handoff_dir(tmp_path: Path) -> Path:
    """Provide a temp directory for handoff files."""
    return tmp_path


@pytest.fixture
def mgr(handoff_dir: Path) -> HandoffManager:
    """Fresh manager with default thresholds, fixed clock."""
    return HandoffManager(
        path=handoff_dir / "handoff.json",
        now=1_000_000.0,
    )


@pytest.fixture
def tight_mgr(handoff_dir: Path) -> HandoffManager:
    """Manager with tight staleness for boundary testing."""
    return HandoffManager(
        path=handoff_dir / "tight_handoff.json",
        stale_s=60.0,
        now=1_000_000.0,
    )


# ---------------------------------------------------------------------------
# initial state — no handoff file
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_restore_returns_none(self, mgr: HandoffManager) -> None:
        assert mgr.restore() is None

    def test_status_not_available(self, mgr: HandoffManager) -> None:
        s = mgr.status()
        assert s["available"] is False
        assert "no handoff file" in s["detail"]

    def test_clear_returns_false(self, mgr: HandoffManager) -> None:
        assert mgr.clear() is False


# ---------------------------------------------------------------------------
# snapshot — basic write
# ---------------------------------------------------------------------------


class TestSnapshotBasic:
    def test_snapshot_creates_file(self, mgr: HandoffManager) -> None:
        path = mgr.snapshot(seq=100, topic="testing", now=1_000_000.0)
        assert path.exists()

    def test_snapshot_is_valid_json(self, mgr: HandoffManager) -> None:
        path = mgr.snapshot(seq=100, now=1_000_000.0)
        with open(path) as f:
            data = json.load(f)
        assert data["seq"] == 100

    def test_snapshot_stores_topic(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, topic="caretaker automation", now=1_000_000.0)
        data = mgr.restore(now=1_000_000.0)
        assert data is not None
        assert data["topic"] == "caretaker automation"

    def test_snapshot_stores_clean_flag(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, clean=True, now=1_000_000.0)
        data = mgr.restore(now=1_000_000.0)
        assert data is not None
        assert data["clean"] is True

    def test_snapshot_stores_clean_false(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, clean=False, now=1_000_000.0)
        data = mgr.restore(now=1_000_000.0)
        assert data is not None
        assert data["clean"] is False

    def test_snapshot_stores_writer(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, writer="doubao", now=1_000_000.0)
        data = mgr.restore(now=1_000_000.0)
        assert data is not None
        assert data["writer"] == "doubao"

    def test_snapshot_default_writer_is_qwen(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, now=1_000_000.0)
        data = mgr.restore(now=1_000_000.0)
        assert data is not None
        assert data["writer"] == "qwen"

    def test_snapshot_stores_epoch(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, now=1_000_000.0)
        data = mgr.restore(now=1_000_000.0)
        assert data is not None
        assert data["at_epoch"] == 1_000_000.0

    def test_snapshot_stores_iso_timestamp(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, now=1_000_000.0)
        data = mgr.restore(now=1_000_000.0)
        assert data is not None
        assert "1970-01-12" in data["at"]  # epoch 1_000_000


# ---------------------------------------------------------------------------
# snapshot — stroke history
# ---------------------------------------------------------------------------


class TestSnapshotStrokes:
    def test_stores_last_strokes(self, mgr: HandoffManager) -> None:
        strokes = [
            {"seq": 99, "kind": "note", "text": "hello"},
            {"seq": 100, "kind": "thought", "text": "world"},
        ]
        mgr.snapshot(seq=100, last_strokes=strokes, now=1_000_000.0)
        data = mgr.restore(now=1_000_000.0)
        assert data is not None
        assert len(data["last_strokes"]) == 2
        assert data["last_strokes"][0]["seq"] == 99

    def test_empty_strokes_when_none_given(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, now=1_000_000.0)
        data = mgr.restore(now=1_000_000.0)
        assert data is not None
        assert data["last_strokes"] == []

    def test_trims_to_max_strokes(self, mgr: HandoffManager) -> None:
        strokes = [{"seq": i, "kind": "note", "text": f"s{i}"} for i in range(50)]
        mgr.snapshot(seq=49, last_strokes=strokes, now=1_000_000.0)
        data = mgr.restore(now=1_000_000.0)
        assert data is not None
        assert len(data["last_strokes"]) == DEFAULT_MAX_STROKES
        # Should keep the most recent.
        assert data["last_strokes"][0]["seq"] == 50 - DEFAULT_MAX_STROKES
        assert data["last_strokes"][-1]["seq"] == 49

    def test_stroke_count_equals_seq(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=42, now=1_000_000.0)
        data = mgr.restore(now=1_000_000.0)
        assert data is not None
        assert data["stroke_count"] == 42


# ---------------------------------------------------------------------------
# snapshot — overwrite
# ---------------------------------------------------------------------------


class TestSnapshotOverwrite:
    def test_overwrites_previous(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, topic="first", now=1_000_000.0)
        mgr.snapshot(seq=200, topic="second", now=1_000_050.0)
        data = mgr.restore(now=1_000_050.0)
        assert data is not None
        assert data["seq"] == 200
        assert data["topic"] == "second"

    def test_no_temp_file_left(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, now=1_000_000.0)
        parent = mgr._path.parent
        temps = list(parent.glob(".handoff_*.tmp"))
        assert len(temps) == 0


# ---------------------------------------------------------------------------
# restore — gap calculation
# ---------------------------------------------------------------------------


class TestRestoreGap:
    def test_gap_is_zero_at_snapshot_time(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, now=1_000_000.0)
        data = mgr.restore(now=1_000_000.0)
        assert data is not None
        assert data["gap_s"] == 0.0

    def test_gap_increases_with_time(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, now=1_000_000.0)
        data = mgr.restore(now=1_000_300.0)
        assert data is not None
        assert data["gap_s"] == 300.0

    def test_gap_rounded_to_one_decimal(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, now=1_000_000.0)
        data = mgr.restore(now=1_000_000.333)
        assert data is not None
        assert data["gap_s"] == 0.3


# ---------------------------------------------------------------------------
# restore — staleness
# ---------------------------------------------------------------------------


class TestRestoreStaleness:
    def test_fresh_snapshot_restores(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, now=1_000_000.0)
        # Just under 1 hour.
        data = mgr.restore(now=1_000_000.0 + DEFAULT_STALE_S - 1)
        assert data is not None

    def test_stale_snapshot_returns_none(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, now=1_000_000.0)
        # Just over 1 hour.
        data = mgr.restore(now=1_000_000.0 + DEFAULT_STALE_S + 1)
        assert data is None

    def test_exact_boundary_is_not_stale(self, tight_mgr: HandoffManager) -> None:
        tight_mgr.snapshot(seq=100, now=1_000_000.0)
        # Exactly at stale_s boundary — still fresh (strict >).
        data = tight_mgr.restore(now=1_000_000.0 + 60.0)
        assert data is not None

    def test_just_over_boundary_is_stale(self, tight_mgr: HandoffManager) -> None:
        tight_mgr.snapshot(seq=100, now=1_000_000.0)
        data = tight_mgr.restore(now=1_000_000.0 + 60.1)
        assert data is None

    def test_just_under_boundary_restores(self, tight_mgr: HandoffManager) -> None:
        tight_mgr.snapshot(seq=100, now=1_000_000.0)
        data = tight_mgr.restore(now=1_000_000.0 + 59.9)
        assert data is not None

    def test_missing_epoch_returns_none(self, mgr: HandoffManager) -> None:
        # Write a legacy snapshot without at_epoch.
        mgr._path.parent.mkdir(parents=True, exist_ok=True)
        with open(mgr._path, "w") as f:
            json.dump({"seq": 100, "topic": "legacy"}, f)
        data = mgr.restore(now=1_000_000.0)
        assert data is None


# ---------------------------------------------------------------------------
# restore — corrupt file
# ---------------------------------------------------------------------------


class TestRestoreCorrupt:
    def test_corrupt_json_returns_none(self, mgr: HandoffManager) -> None:
        mgr._path.parent.mkdir(parents=True, exist_ok=True)
        mgr._path.write_text("not json at all{{{")
        assert mgr.restore() is None

    def test_empty_file_returns_none(self, mgr: HandoffManager) -> None:
        mgr._path.parent.mkdir(parents=True, exist_ok=True)
        mgr._path.write_text("")
        assert mgr.restore() is None


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_removes_file(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, now=1_000_000.0)
        assert mgr.clear() is True
        assert not mgr._path.exists()

    def test_clear_then_restore_is_none(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, now=1_000_000.0)
        mgr.clear()
        assert mgr.restore() is None

    def test_clear_nonexistent_returns_false(self, mgr: HandoffManager) -> None:
        assert mgr.clear() is False


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_no_file(self, mgr: HandoffManager) -> None:
        s = mgr.status()
        assert s["available"] is False

    def test_status_fresh_snapshot(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, topic="test", now=1_000_000.0)
        s = mgr.status(now=1_000_100.0)
        assert s["available"] is True
        assert s["stale"] is False
        assert s["seq"] == 100
        assert s["topic"] == "test"
        assert s["gap_s"] == 100.0

    def test_status_stale_snapshot(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, now=1_000_000.0)
        s = mgr.status(now=1_000_000.0 + DEFAULT_STALE_S + 100)
        assert s["available"] is False
        assert s["stale"] is True
        assert "stale" in s["detail"]

    def test_status_corrupt_file(self, mgr: HandoffManager) -> None:
        mgr._path.parent.mkdir(parents=True, exist_ok=True)
        mgr._path.write_text("broken")
        s = mgr.status()
        assert s["available"] is False
        assert "corrupt" in s["detail"]

    def test_status_clean_flag(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, clean=False, now=1_000_000.0)
        s = mgr.status(now=1_000_010.0)
        assert s["clean"] is False

    def test_status_writer_field(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, writer="doubao", now=1_000_000.0)
        s = mgr.status(now=1_000_010.0)
        assert s["writer"] == "doubao"

    def test_status_detail_includes_writer(self, mgr: HandoffManager) -> None:
        mgr.snapshot(seq=100, writer="qwen", now=1_000_000.0)
        s = mgr.status(now=1_000_010.0)
        assert "qwen" in s["detail"]

    def test_status_legacy_format(self, mgr: HandoffManager) -> None:
        mgr._path.parent.mkdir(parents=True, exist_ok=True)
        with open(mgr._path, "w") as f:
            json.dump({"seq": 100}, f)
        s = mgr.status(now=1_000_000.0)
        assert s["available"] is False
        assert s["stale"] is True
        assert "legacy" in s["detail"]


# ---------------------------------------------------------------------------
# atomic write — crash safety
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_snapshot_is_atomic(self, mgr: HandoffManager) -> None:
        """After snapshot, the file should be valid and complete."""
        mgr.snapshot(
            seq=500,
            last_strokes=[{"seq": 500, "kind": "note", "text": "atomic test"}],
            topic="atomicity",
            now=1_000_000.0,
        )
        # File should be parseable.
        with open(mgr._path) as f:
            data = json.load(f)
        assert data["seq"] == 500
        assert data["last_strokes"][0]["text"] == "atomic test"

    def test_snapshot_creates_parent_dirs(self, handoff_dir: Path) -> None:
        deep_path = handoff_dir / "a" / "b" / "c" / "handoff.json"
        mgr = HandoffManager(path=deep_path, now=1_000_000.0)
        mgr.snapshot(seq=1, now=1_000_000.0)
        assert deep_path.exists()


# ---------------------------------------------------------------------------
# integration — snapshot + restore round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_full_cycle(self, mgr: HandoffManager) -> None:
        strokes = [
            {"seq": i, "kind": "note", "text": f"stroke {i}"}
            for i in range(6700, 6712)
        ]
        mgr.snapshot(
            seq=6711,
            last_strokes=strokes,
            topic="writer handoff module",
            clean=True,
            writer="qwen",
            now=1_000_000.0,
        )
        data = mgr.restore(now=1_000_120.0)
        assert data is not None
        assert data["seq"] == 6711
        assert data["topic"] == "writer handoff module"
        assert data["clean"] is True
        assert data["writer"] == "qwen"
        assert data["gap_s"] == 120.0
        assert len(data["last_strokes"]) == 12
        assert data["last_strokes"][0]["seq"] == 6700
        assert data["last_strokes"][-1]["seq"] == 6711

    def test_crash_recovery_cycle(self, mgr: HandoffManager) -> None:
        """Simulate crash → restart → restore."""
        # Writer crashes — snapshot with clean=False.
        mgr.snapshot(
            seq=5000,
            last_strokes=[{"seq": 5000, "kind": "thought", "text": "last thought"}],
            topic="crash recovery test",
            clean=False,
            now=1_000_000.0,
        )
        # New writer starts 30s later.
        data = mgr.restore(now=1_000_030.0)
        assert data is not None
        assert data["clean"] is False
        assert data["gap_s"] == 30.0
        assert data["seq"] == 5000
        # New writer knows where to resume.
        assert data["last_strokes"][-1]["text"] == "last thought"
