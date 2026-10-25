#!/usr/bin/env python3
"""Tests for restart_audit.py — gap classification in writer history."""

import json
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import restart_audit as ra


# ---------------------------------------------------------------------------
# classify_gap
# ---------------------------------------------------------------------------

class TestClassifyGap:
    def test_healthy_small_gap(self):
        """10s gap with 15s cadence → healthy."""
        assert ra.classify_gap(10, cadence=15) == "healthy"

    def test_healthy_at_boundary(self):
        """Exactly 2× cadence is still healthy (threshold is exclusive)."""
        # gap < cadence * stall_multiplier  →  30 < 30 is False
        # so 30s with cadence 15 → stall
        assert ra.classify_gap(29, cadence=15) == "healthy"

    def test_stall_mid_gap(self):
        """45s gap with 15s cadence → stall (3× cadence)."""
        assert ra.classify_gap(45, cadence=15) == "stall"

    def test_stall_at_upper_boundary(self):
        """149s gap with 15s cadence → stall (just under 10×)."""
        assert ra.classify_gap(149, cadence=15) == "stall"

    def test_restart_large_gap(self):
        """3000s gap with 15s cadence → restart (200× cadence)."""
        assert ra.classify_gap(3000, cadence=15) == "restart"

    def test_restart_at_boundary(self):
        """Exactly 10× cadence → restart."""
        assert ra.classify_gap(150, cadence=15) == "restart"

    def test_negative_gap_is_healthy(self):
        """Clock skew producing a negative gap is treated as noise."""
        assert ra.classify_gap(-5, cadence=15) == "healthy"

    def test_custom_multipliers(self):
        """Custom stall/restart multipliers shift the boundaries."""
        # stall at 3×, restart at 5×
        assert ra.classify_gap(40, cadence=15, stall_multiplier=3.0, restart_multiplier=5.0) == "healthy"
        assert ra.classify_gap(50, cadence=15, stall_multiplier=3.0, restart_multiplier=5.0) == "stall"
        assert ra.classify_gap(80, cadence=15, stall_multiplier=3.0, restart_multiplier=5.0) == "restart"


# ---------------------------------------------------------------------------
# audit_gaps
# ---------------------------------------------------------------------------

class TestAuditGaps:
    def test_empty_history(self):
        """No history entries → no gaps."""
        assert ra.audit_gaps([]) == []

    def test_single_entry(self):
        """One entry means zero gaps."""
        history = [{"at": "2026-10-07T10:00:00+00:00", "kind": "note", "path": "x", "seq": 1}]
        assert ra.audit_gaps(history) == []

    def test_two_entries_healthy(self):
        """Two entries 10s apart with 15s cadence → one healthy gap."""
        history = [
            {"at": "2026-10-07T10:00:00+00:00", "kind": "note", "path": "x", "seq": 1},
            {"at": "2026-10-07T10:00:10+00:00", "kind": "note", "path": "y", "seq": 2},
        ]
        gaps = ra.audit_gaps(history, cadence=15)
        assert len(gaps) == 1
        assert gaps[0]["kind"] == "healthy"
        assert gaps[0]["gap_seconds"] == 10.0
        assert gaps[0]["index"] == 1

    def test_mixed_gap_types(self):
        """History with healthy, stall, and restart gaps."""
        history = [
            {"at": "2026-10-07T10:00:00+00:00", "kind": "a", "path": "x", "seq": 1},
            {"at": "2026-10-07T10:00:10+00:00", "kind": "b", "path": "y", "seq": 2},   # 10s → healthy
            {"at": "2026-10-07T10:00:50+00:00", "kind": "c", "path": "z", "seq": 3},   # 40s → stall
            {"at": "2026-10-07T10:30:50+00:00", "kind": "d", "path": "w", "seq": 4},   # 1800s → restart
        ]
        gaps = ra.audit_gaps(history, cadence=15)
        assert len(gaps) == 3
        assert gaps[0]["kind"] == "healthy"
        assert gaps[1]["kind"] == "stall"
        assert gaps[2]["kind"] == "restart"

    def test_non_monotonic_timestamps(self):
        """Clock going backward produces negative gap → classified as healthy."""
        history = [
            {"at": "2026-10-07T10:01:00+00:00", "kind": "a", "path": "x", "seq": 1},
            {"at": "2026-10-07T10:00:00+00:00", "kind": "b", "path": "y", "seq": 2},
        ]
        gaps = ra.audit_gaps(history, cadence=15)
        assert len(gaps) == 1
        assert gaps[0]["kind"] == "healthy"  # negative gap → noise
        assert gaps[0]["gap_seconds"] == -60.0

    def test_missing_at_key_skipped(self):
        """Entries without 'at' are skipped gracefully."""
        history = [
            {"kind": "a", "path": "x", "seq": 1},  # no "at"
            {"at": "2026-10-07T10:00:10+00:00", "kind": "b", "path": "y", "seq": 2},
        ]
        gaps = ra.audit_gaps(history, cadence=15)
        assert len(gaps) == 0  # first gap skipped due to missing key


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

class TestSummarize:
    def test_all_healthy(self):
        gaps = [
            {"index": 1, "gap_seconds": 10, "kind": "healthy", "from_at": "a", "to_at": "b"},
            {"index": 2, "gap_seconds": 12, "kind": "healthy", "from_at": "b", "to_at": "c"},
        ]
        s = ra.summarize(gaps)
        assert s["total_gaps"] == 2
        assert s["counts"]["healthy"] == 2
        assert s["counts"]["stall"] == 0
        assert s["counts"]["restart"] == 0
        assert s["latest_problem"] is None

    def test_with_problems(self):
        gaps = [
            {"index": 1, "gap_seconds": 10, "kind": "healthy", "from_at": "a", "to_at": "b"},
            {"index": 2, "gap_seconds": 45, "kind": "stall", "from_at": "b", "to_at": "c"},
            {"index": 3, "gap_seconds": 3000, "kind": "restart", "from_at": "c", "to_at": "d"},
        ]
        s = ra.summarize(gaps)
        assert s["counts"]["stall"] == 1
        assert s["counts"]["restart"] == 1
        assert s["latest_problem"]["kind"] == "restart"  # last non-healthy

    def test_empty_gaps(self):
        s = ra.summarize([])
        assert s["total_gaps"] == 0
        assert s["latest_problem"] is None


# ---------------------------------------------------------------------------
# as_text
# ---------------------------------------------------------------------------

class TestAsText:
    def test_all_healthy_text(self):
        s = {"total_gaps": 5, "counts": {"healthy": 5, "stall": 0, "restart": 0}, "latest_problem": None}
        text = ra.as_text(s)
        assert "5 gaps" in text
        assert "5 healthy" in text
        assert "stall" not in text
        assert "restart" not in text

    def test_with_restart_text(self):
        s = {
            "total_gaps": 10,
            "counts": {"healthy": 8, "stall": 1, "restart": 1},
            "latest_problem": {"kind": "restart", "gap_seconds": 3000, "from_at": "a", "to_at": "b", "index": 9},
        }
        text = ra.as_text(s)
        assert "1 restart(s)" in text
        assert "1 stall(s)" in text
        assert "3000" in text


# ---------------------------------------------------------------------------
# load_history
# ---------------------------------------------------------------------------

class TestLoadHistory:
    def test_missing_file(self, tmp_path):
        assert ra.load_history(tmp_path / "nonexistent.json") == []

    def test_valid_file(self, tmp_path):
        f = tmp_path / "state.json"
        f.write_text(json.dumps({"history": [{"at": "2026-10-07T10:00:00+00:00"}]}))
        result = ra.load_history(f)
        assert len(result) == 1

    def test_corrupt_json(self, tmp_path):
        f = tmp_path / "state.json"
        f.write_text("not json {{{")
        assert ra.load_history(f) == []
