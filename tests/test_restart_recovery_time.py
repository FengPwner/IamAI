"""Tests for tools/restart_recovery_time.py — measure writer recovery after restart."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from restart_recovery_time import (  # noqa: E402
    _parse_iso,
    compute_recovery_times,
    load_strokes,
    summarize,
)


# ── _parse_iso ───────────────────────────────────────────────────────────────


class TestParseIso:
    def test_standard_iso(self):
        dt = _parse_iso("2026-10-29T12:00:00+00:00")
        assert dt.year == 2026
        assert dt.month == 10
        assert dt.hour == 12

    def test_z_suffix(self):
        dt = _parse_iso("2026-10-29T12:00:00Z")
        assert dt.tzinfo is not None

    def test_whitespace_stripped(self):
        dt = _parse_iso("  2026-10-29T12:00:00+00:00  ")
        assert dt.year == 2026


# ── load_strokes ─────────────────────────────────────────────────────────────


class TestLoadStrokes:
    def test_empty_state(self, tmp_path):
        state = tmp_path / "empty.json"
        state.write_text('{"history": []}')
        result = load_strokes(state)
        assert result == []

    def test_missing_file(self, tmp_path):
        result = load_strokes(tmp_path / "nope.json")
        assert result == []

    def test_parses_entries(self, tmp_path):
        state = tmp_path / "state.json"
        state.write_text(json.dumps({
            "history": [
                {"at": "2026-10-29T10:00:00+00:00", "seq": 1, "kind": "thought"},
                {"at": "2026-10-29T10:05:00+00:00", "seq": 2, "kind": "devlog"},
            ]
        }))
        result = load_strokes(state)
        assert len(result) == 2
        assert result[0]["seq"] == 1
        assert result[1]["kind"] == "devlog"

    def test_sorted_by_time(self, tmp_path):
        state = tmp_path / "state.json"
        state.write_text(json.dumps({
            "history": [
                {"at": "2026-10-29T12:00:00+00:00", "seq": 2, "kind": "devlog"},
                {"at": "2026-10-29T10:00:00+00:00", "seq": 1, "kind": "thought"},
            ]
        }))
        result = load_strokes(state)
        assert result[0]["seq"] == 1
        assert result[1]["seq"] == 2

    def test_skips_entries_without_at(self, tmp_path):
        state = tmp_path / "state.json"
        state.write_text(json.dumps({
            "history": [
                {"seq": 1, "kind": "thought"},
                {"at": "2026-10-29T10:00:00+00:00", "seq": 2, "kind": "devlog"},
            ]
        }))
        result = load_strokes(state)
        assert len(result) == 1
        assert result[0]["seq"] == 2


# ── compute_recovery_times ───────────────────────────────────────────────────


class TestComputeRecoveryTimes:
    def test_basic_recovery(self):
        restarts = [{"at": datetime(2026, 10, 29, 10, 0, 0, tzinfo=timezone.utc), "source": "test"}]
        strokes = [
            {"at": datetime(2026, 10, 29, 9, 55, 0, tzinfo=timezone.utc), "seq": 1, "kind": "thought"},
            {"at": datetime(2026, 10, 29, 10, 0, 30, tzinfo=timezone.utc), "seq": 2, "kind": "thought"},
        ]
        result = compute_recovery_times(restarts, strokes)
        assert len(result) == 1
        assert result[0]["recovery_seconds"] == 30.0

    def test_no_stroke_after_restart(self):
        restarts = [{"at": datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc), "source": "test"}]
        strokes = [
            {"at": datetime(2026, 10, 29, 10, 0, 0, tzinfo=timezone.utc), "seq": 1, "kind": "thought"},
        ]
        result = compute_recovery_times(restarts, strokes)
        assert len(result) == 0

    def test_multiple_restarts(self):
        base = datetime(2026, 10, 29, 10, 0, 0, tzinfo=timezone.utc)
        restarts = [
            {"at": base, "source": "r1"},
            {"at": datetime(2026, 10, 29, 11, 0, 0, tzinfo=timezone.utc), "source": "r2"},
        ]
        strokes = [
            {"at": datetime(2026, 10, 29, 10, 0, 45, tzinfo=timezone.utc), "seq": 1, "kind": "thought"},
            {"at": datetime(2026, 10, 29, 11, 2, 0, tzinfo=timezone.utc), "seq": 2, "kind": "thought"},
        ]
        result = compute_recovery_times(restarts, strokes)
        assert len(result) == 2
        assert result[0]["recovery_seconds"] == 45.0
        assert result[1]["recovery_seconds"] == 120.0

    def test_stroke_exactly_at_restart(self):
        """a stroke at the exact restart time should NOT count (must be strictly after)."""
        t = datetime(2026, 10, 29, 10, 0, 0, tzinfo=timezone.utc)
        restarts = [{"at": t, "source": "test"}]
        strokes = [{"at": t, "seq": 1, "kind": "thought"}]
        result = compute_recovery_times(restarts, strokes)
        assert len(result) == 0

    def test_negative_recovery_ignored(self):
        """a stroke before the restart is not a recovery."""
        restarts = [{"at": datetime(2026, 10, 29, 10, 0, 0, tzinfo=timezone.utc), "source": "test"}]
        strokes = [{"at": datetime(2026, 10, 29, 9, 0, 0, tzinfo=timezone.utc), "seq": 1, "kind": "thought"}]
        result = compute_recovery_times(restarts, strokes)
        assert len(result) == 0

    def test_empty_inputs(self):
        assert compute_recovery_times([], []) == []
        assert compute_recovery_times([], [{"at": datetime.now(timezone.utc), "seq": 1, "kind": "x"}]) == []


# ── summarize ────────────────────────────────────────────────────────────────


class TestSummarize:
    def test_empty(self):
        assert summarize([]) == {"count": 0}

    def test_single_entry(self):
        result = summarize([{"recovery_seconds": 30.0}])
        assert result["count"] == 1
        assert result["min_seconds"] == 30.0

    def test_basic_stats(self):
        recoveries = [
            {"recovery_seconds": 10.0},
            {"recovery_seconds": 20.0},
            {"recovery_seconds": 30.0},
            {"recovery_seconds": 40.0},
            {"recovery_seconds": 50.0},
        ]
        result = summarize(recoveries)
        assert result["count"] == 5
        assert result["min_seconds"] == 10.0
        assert result["max_seconds"] == 50.0
        assert result["median_seconds"] == 30.0

    def test_trend_stable(self):
        # first and second half medians are close → stable
        recoveries = [{"recovery_seconds": v} for v in [10.0, 10.0, 11.0, 11.0, 10.0, 10.0, 11.0, 11.0, 10.0, 11.0]]
        result = summarize(recoveries)
        assert result["trend"] == "stable"

    def test_trend_degrading(self):
        """second half significantly slower than first half."""
        first = [{"recovery_seconds": 10.0}] * 5
        second = [{"recovery_seconds": 50.0}] * 5
        result = summarize(first + second)
        assert result["trend"] == "degrading"

    def test_trend_improving(self):
        """second half significantly faster than first half."""
        first = [{"recovery_seconds": 50.0}] * 5
        second = [{"recovery_seconds": 10.0}] * 5
        result = summarize(first + second)
        assert result["trend"] == "improving"

    def test_p95_calculation(self):
        recoveries = [{"recovery_seconds": float(i)} for i in range(1, 21)]
        result = summarize(recoveries)
        assert result["p95_seconds"] == 20.0  # int(20*0.95)=19 → index 19 → value 20

    def test_count_preserved(self):
        n = 15
        recoveries = [{"recovery_seconds": float(i)} for i in range(n)]
        assert summarize(recoveries)["count"] == n
